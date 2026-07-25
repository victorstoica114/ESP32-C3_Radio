from __future__ import annotations

import csv
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


STUDY_DIR = Path(__file__).resolve().parent
PROFILER_DIR = STUDY_DIR.parent
COMPARISONS_DIR = PROFILER_DIR / "comparisons"
TOOLS_DIR = PROFILER_DIR / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from render_lora_campaign_plots import (  # noqa: E402
    BLACK,
    BLUE,
    GREEN,
    GRID,
    ORANGE,
    RED,
    PdfCanvas,
    _map,
)


PURPLE = (0.44, 0.23, 0.62)
CYAN = (0.05, 0.56, 0.62)
GRAY = (0.42, 0.45, 0.49)
YELLOW = (0.88, 0.66, 0.04)
PALETTE = (BLUE, RED, GREEN, ORANGE, PURPLE, CYAN, YELLOW, GRAY)
TICK_FONT_SIZE = 24.0
LEGEND_FONT_SIZE = 24.0
AXIS_FONT_SIZE = 26.0
DATA_LABEL_FONT_SIZE = 21.0
SUBTITLE_FONT_SIZE = 23.0
NOTE_FONT_SIZE = 22.0


@dataclass(frozen=True)
class ModuleSpec:
    slug: str
    code: str
    label: str
    chip: str
    band: str
    interface: str
    modulation: str
    configured_rates: str
    tested_powers: str
    family: str
    validation: str = "Validated"


MODULES = (
    ModuleSpec("cc1101_v1_433", "CC1101 V1 433 MHz (CC1101)", "CC1101 V1 433 MHz (CC1101)", "CC1101", "433 MHz", "SPI", "2-FSK", "1.2/38.4/250 kbps", "-30/0/10 dBm", "Narrowband FSK"),
    ModuleSpec("cc1101_v2_868", "CC1101 V2 868 MHz (CC1101)", "CC1101 V2 868 MHz (CC1101)", "CC1101", "868 MHz", "SPI", "2-FSK", "1.2/38.4/250 kbps", "-30/0/10 dBm", "Narrowband FSK"),
    ModuleSpec("ebyte_e07_400m10s", "Ebyte E07-400M10S (CC1101)", "Ebyte E07-400M10S (CC1101)", "CC1101", "410--450 MHz", "SPI", "GFSK", "1.2/38.4/250 kbps", "-30/0/10 dBm", "CC1101 module"),
    ModuleSpec("ebyte_e07_433m20s", "Ebyte E07-433M20S (CC1101 + PA/LNA)", "Ebyte E07-433M20S (CC1101 + PA/LNA)", "CC1101 + PA/LNA", "425--450.5 MHz", "SPI", "GFSK", "1.2/38.4/250 kbps", "-30/0/10 dBm drive", "CC1101 module"),
    ModuleSpec("ebyte_e07_900mm10s", "Ebyte E07-900MM10S (CC1101)", "Ebyte E07-900MM10S (CC1101)", "CC1101", "855--925 MHz", "SPI", "GFSK", "1.2/38.4/250 kbps", "-30/0/10 dBm", "CC1101 module"),
    ModuleSpec("e28_sx1280", "Ebyte E28 (SX1280)", "Ebyte E28 (SX1280)", "SX1280", "2.4 GHz", "SPI", "LoRa, CR 4/6", "SF5/8/12, BW 812.5 kHz", "-18/0/13 dBm", "LoRa 2.4 GHz"),
    ModuleSpec("e280", "Ebyte E280-2G4T12S (SX1280)", "Ebyte E280-2G4T12S (SX1280)", "SX1280", "2.4 GHz", "UART", "Vendor transparent PHY", "1/100/2000 kbps presets", "4/7/12 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e22_400m30s", "Ebyte E22-400M30S (SX1268 + PA)", "Ebyte E22-400M30S (SX1268 + PA)", "SX1268 + PA", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-9/10/18 dBm front stage", "LoRa sub-GHz"),
    ModuleSpec("ebyte_e32_433t20d", "Ebyte E32-433T20D (SX1278)", "Ebyte E32-433T20D (SX1278)", "SX1278", "433 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "10/14/20 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e32_433t33d", "Ebyte E32-433T33D (SX1278 + PA)", "Ebyte E32-433T33D (SX1278 + PA)", "SX1278 + PA", "433 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "24/27/30 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e32_868t20d", "Ebyte E32-868T20D (SX1276)", "Ebyte E32-868T20D (SX1276)", "SX1276", "868 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "10/14/20 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e32_868t30d", "Ebyte E32-868T30D (SX1276 + PA)", "Ebyte E32-868T30D (SX1276 + PA)", "SX1276 + PA", "868 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "21/27/30 dBm", "Transparent UART", "Legacy accepted"),
    ModuleSpec("ebyte_e79_400dm2005s", "Ebyte E79-400DM2005S via ESP32 (CC1352P)", "Ebyte E79-400DM2005S via ESP32 (CC1352P)", "CC1352P", "433 MHz", "UART AT via ESP32", "2-GFSK, OOK, SLR, 802.15.4g", "2.5--200 kbps (7 PHYs)", "-20/0/13 dBm", "Multi-PHY sub-GHz"),
    ModuleSpec("ebyte_e79_ch9340", "Ebyte E79-400DM2005S via CH9340C (CC1352P)", "Ebyte E79-400DM2005S via CH9340C (CC1352P)", "CC1352P", "433 MHz", "UART AT via CH9340C", "2-GFSK, OOK, SLR, 802.15.4g", "2.5--200 kbps (7 PHYs)", "-20/0/13 dBm", "Multi-PHY sub-GHz"),
    ModuleSpec("hc12", "HC-12 (Si4463)", "HC-12 (Si4463)", "Si4463", "433 MHz", "UART", "Transparent (G)FSK", "0.5/15/250 kbps presets", "-1/8/20 dBm", "Transparent UART"),
    ModuleSpec("nrf24l01", "NRF24L01 (nRF24L01+)", "NRF24L01 (nRF24L01+)", "nRF24L01+", "2.4 GHz", "SPI", "GFSK, ESB framing", "250/1000/2000 kbps", "-18/-6/0 dBm", "2.4 GHz GFSK"),
    ModuleSpec("nrf24l01_pa", "NRF24L01 PA/LNA (nRF24L01+)", "NRF24L01 PA/LNA (nRF24L01+)", "nRF24L01+", "2.4 GHz", "SPI", "GFSK, ESB framing", "250/1000/2000 kbps", "-18/-6/0 dBm drive", "2.4 GHz GFSK"),
    ModuleSpec("ra01h_sx1276", "Ai-Thinker RA-01H (SX1276)", "Ai-Thinker RA-01H (SX1276)", "SX1276", "868 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "2/10/20 dBm", "LoRa sub-GHz"),
    ModuleSpec("ra01sh_sx1262", "Ai-Thinker RA-01SH (SX1262)", "Ai-Thinker RA-01SH (SX1262)", "SX1262", "868 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-9/10/22 dBm", "LoRa sub-GHz"),
    ModuleSpec("ra02_sx1278", "Ai-Thinker RA-02 (SX1278)", "Ai-Thinker RA-02 (SX1278)", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("ra02_sx1278_2cap", "Ai-Thinker RA-02 with 2 Cap (SX1278)", "Ai-Thinker RA-02 with 2 Cap (SX1278)", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("ra08_asr6601", "Ai-Thinker RA-08 (ASR6601)", "Ai-Thinker RA-08 (ASR6601)", "ASR6601", "433 MHz", "UART AT", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "2/12/22 dBm", "LoRa SoC modem"),
    ModuleSpec("ra09_stm32wle5", "Ai-Thinker RA-09 (STM32WLE5)", "Ai-Thinker RA-09 (STM32WLE5)", "STM32WLE5", "433 MHz", "UART AT", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-9/10/22 dBm", "LoRa SoC modem"),
    ModuleSpec("sx1278_adafruit_level_shifter", "Adafruit board with level shifter (SX1278)", "Adafruit board with level shifter (SX1278)", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant", "Accepted; no validation memo"),
    ModuleSpec("sx1278_naked", "Unshielded radio module (SX1278)", "Unshielded radio module (SX1278)", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("sx1278_pcb_2cap", "Carrier PCB with 2 Cap (SX1278)", "Carrier PCB with 2 Cap (SX1278)", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("sx1278_shielded", "Shielded radio module (SX1278)", "Shielded radio module (SX1278)", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("xl1276_d01_sx1276", "XL1276-D01 (SX1276)", "XL1276-D01 (SX1276)", "SX1276", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "LoRa sub-GHz"),
)

MODULE_BY_SLUG = {spec.slug: spec for spec in MODULES}


def module_name(slug: str) -> str:
    return MODULE_BY_SLUG[slug].code


PACKET_SOURCES = {
    "ebyte_e07_400m10s": (
        "ebyte_e07_400m10s_20260724/e07_400m10s_tx.csv",
        "ebyte_e07_400m10s_20260724/e07_400m10s_rx.csv",
    ),
    "ebyte_e07_433m20s": (
        "ebyte_e07_433m20s_20260725/e07_433m20s_tx.csv",
        "ebyte_e07_433m20s_20260725/e07_433m20s_rx.csv",
    ),
    "ebyte_e07_900mm10s": (
        "ebyte_e07_900mm10s_20260725/e07_900mm10s_tx.csv",
        "ebyte_e07_900mm10s_20260725/e07_900mm10s_rx.csv",
    ),
    "ebyte_e79_ch9340": (
        "ebyte_e79_400dm2005s_20260724/e79_tx.csv",
        "ebyte_e79_400dm2005s_20260724/e79_rx.csv",
    ),
    "ra09_stm32wle5": (
        "ai_thinker_ra09_20260725/ra09_tx.csv",
        "ai_thinker_ra09_20260725/ra09_rx.csv",
    ),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def load_packet_rows(spec: ModuleSpec) -> list[dict[str, str]]:
    sources = PACKET_SOURCES.get(
        spec.slug,
        (f"{spec.slug}/{spec.slug}_data.csv",),
    )
    return [
        row
        for source in sources
        for row in read_csv(COMPARISONS_DIR / source)
    ]


def load_continuous_rows(spec: ModuleSpec) -> list[dict[str, str]]:
    path = COMPARISONS_DIR / spec.slug / f"{spec.slug}_continuous.csv"
    return read_csv(path) if path.exists() else []


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def field_rate(row: dict[str, str]) -> float:
    for key in ("data_rate_kbps", "bit_rate_kbps"):
        value = number(row, key)
        if value > 0:
            return value
    profile = row.get("rf_profile", "")
    profile_rates = {
        "GFSK4K8": 4.8,
        "GFSK50": 50.0,
        "GFSK200": 200.0,
        "SLR2K5": 2.5,
        "SLR5": 5.0,
        "OOK4K8": 4.8,
        "IEEE154G50": 50.0,
    }
    if profile in profile_rates:
        return profile_rates[profile]
    air_rate = row.get("air_rate", "")
    return {"1K": 1.0, "100K": 100.0, "2M": 2000.0}.get(air_rate, 0.0)


def lora_gross_rate(row: dict[str, str], coding_denominator: int = 5) -> float:
    sf = number(row, "spreading_factor")
    bw_khz = number(row, "bandwidth_khz") or number(row, "bandwidth_hz") / 1000.0
    if sf <= 0 or bw_khz <= 0:
        return 0.0
    return bw_khz / (2.0**sf) * sf * 4.0 / coding_denominator


def configured_rate(row: dict[str, str], spec: ModuleSpec) -> float:
    direct = field_rate(row)
    if direct > 0:
        return direct
    coding_denominator = 6 if spec.slug == "e28_sx1280" else 5
    return lora_gross_rate(row, coding_denominator)


def mode_rank(row: dict[str, str], spec: ModuleSpec) -> float:
    return configured_rate(row, spec)


def choose_packet(rows: Sequence[dict[str, str]], spec: ModuleSpec, direction: str) -> dict[str, str]:
    candidates = [
        row
        for row in rows
        if row.get("measurement_direction") == direction
        and abs(number(row, "payload_bytes") - 32.0) < 0.01
    ]
    if not candidates:
        raise ValueError(f"No 32-byte {direction} row for {spec.slug}")
    return max(candidates, key=lambda row: (mode_rank(row, spec), number(row, "tx_power_dbm")))


def packet_mode_label(row: dict[str, str]) -> str:
    if row.get("rf_profile"):
        return row["rf_profile"]
    if number(row, "spreading_factor"):
        return f"SF{number(row, 'spreading_factor'):g}"
    if row.get("module", "").startswith("Ai-Thinker RA-09"):
        rate = field_rate(row)
        for candidate, sf in ((0.29296875, 12), (1.7578125, 9), (5.46875, 7)):
            if math.isclose(rate, candidate, rel_tol=0.0, abs_tol=1e-6):
                return f"SF{sf}"
    if row.get("air_rate"):
        return row["air_rate"]
    return f"{field_rate(row):g} kbps"


def packet_lora_sf(row: dict[str, str]) -> int:
    direct = round(number(row, "spreading_factor"))
    if direct:
        return direct
    if row.get("module", "").startswith("Ai-Thinker RA-09"):
        rate = field_rate(row)
        for candidate, sf in ((0.29296875, 12), (1.7578125, 9), (5.46875, 7)):
            if math.isclose(rate, candidate, rel_tol=0.0, abs_tol=1e-6):
                return sf
    return 0


def packet_delivery_percent(row: dict[str, str]) -> float | str:
    attempted = round(number(row, "packets_attempted")) or round(number(row, "runs"))
    received_value = row.get("packets_received", "")
    if not attempted or received_value in ("", None):
        return ""
    if not row.get("packets_attempted") and number(row, "packets_received") == 0:
        return ""
    return 100.0 * number(row, "packets_received") / attempted


def normalize_packet_point(
    row: dict[str, str],
    spec: ModuleSpec,
    series: str,
    comparison: str,
) -> dict[str, object]:
    return {
        "comparison": comparison,
        "slug": spec.slug,
        "series": series,
        "direction": row.get("measurement_direction", ""),
        "payload_bytes": round(number(row, "payload_bytes")),
        "rate_kbps": configured_rate(row, spec),
        "spreading_factor": packet_lora_sf(row),
        "profile": row.get("rf_profile", ""),
        "power_dbm": number(row, "tx_power_dbm"),
        "energy_mJ": number(row, "energy_total_mJ_mean"),
        "duration_ms": number(row, "event_duration_ms_mean"),
        "delivery_percent": packet_delivery_percent(row),
        "runs": round(number(row, "runs")),
    }


def build_payload_summary(
    packet_data: dict[str, list[dict[str, str]]]
) -> tuple[list[dict[str, object]], list[int]]:
    rows: list[dict[str, object]] = []
    payload_sizes: set[int] = set()
    for spec in MODULES:
        packets = packet_data[spec.slug]
        module_payloads = sorted(
            {
                round(number(row, "payload_bytes"))
                for row in packets
                if number(row, "payload_bytes") > 0
            }
        )
        payload_sizes.update(module_payloads)
        for payload_bytes in module_payloads:
            selected: dict[str, dict[str, str]] = {}
            for direction in ("tx", "rx"):
                candidates = [
                    row
                    for row in packets
                    if row.get("measurement_direction") == direction
                    and round(number(row, "payload_bytes")) == payload_bytes
                ]
                if not candidates:
                    continue
                selected[direction] = max(
                    candidates,
                    key=lambda row: (mode_rank(row, spec), number(row, "tx_power_dbm")),
                )

            if set(selected) != {"tx", "rx"}:
                raise ValueError(f"Missing TX/RX pair for {spec.slug} at {payload_bytes} bytes")
            tx = selected["tx"]
            rx = selected["rx"]
            if packet_mode_label(tx) != packet_mode_label(rx) or number(
                tx, "tx_power_dbm"
            ) != number(rx, "tx_power_dbm"):
                raise ValueError(f"TX/RX configuration mismatch for {spec.slug} at {payload_bytes} bytes")

            for direction, row in selected.items():
                energy = number(row, "energy_total_mJ_mean")
                rows.append(
                    {
                        "slug": spec.slug,
                        "code": spec.code,
                        "label": spec.label,
                        "direction": direction,
                        "payload_bytes": payload_bytes,
                        "mode": packet_mode_label(row),
                        "rate_kbps": configured_rate(row, spec),
                        "power_dbm": number(row, "tx_power_dbm"),
                        "energy_mJ": energy,
                        "energy_per_bit_uJ": energy * 1000.0 / (payload_bytes * 8.0),
                        "duration_ms": number(row, "event_duration_ms_mean"),
                        "runs": round(number(row, "runs")),
                        "packets_received": round(number(row, "packets_received")),
                    }
                )
    return rows, sorted(payload_sizes)


def build_cc1101_comparison(
    packet_data: dict[str, list[dict[str, str]]]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    modules = (
        ("cc1101_v1_433", module_name("cc1101_v1_433")),
        ("cc1101_v2_868", module_name("cc1101_v2_868")),
    )
    empty_metric = {
        "energy_mJ": "",
        "total_power_mW": "",
        "excess_power_mW": "",
        "delivery_percent": "",
    }
    for slug, code in modules:
        packets = packet_data[slug]
        for comparison, candidates in (
            (
                "payload",
                [
                    row
                    for row in packets
                    if abs(field_rate(row) - 250.0) < 0.01
                    and abs(number(row, "tx_power_dbm") - 10.0) < 0.01
                ],
            ),
            (
                "rate",
                [
                    row
                    for row in packets
                    if round(number(row, "payload_bytes")) == 32
                    and abs(number(row, "tx_power_dbm") - 10.0) < 0.01
                ],
            ),
        ):
            for row in candidates:
                rows.append(
                    {
                        "comparison": comparison,
                        "slug": slug,
                        "code": code,
                        "direction": row.get("measurement_direction", ""),
                        "payload_bytes": round(number(row, "payload_bytes")),
                        "rate_kbps": field_rate(row),
                        "power_dbm": number(row, "tx_power_dbm"),
                        **empty_metric,
                        "energy_mJ": number(row, "energy_total_mJ_mean"),
                    }
                )

        continuous = read_csv(COMPARISONS_DIR / slug / f"{slug}_continuous.csv")
        for row in continuous:
            loss = number(row, "frame_loss_percent")
            rows.append(
                {
                    "comparison": "continuous",
                    "slug": slug,
                    "code": code,
                    "direction": row.get("measurement_direction", ""),
                    "payload_bytes": round(number(row, "content_bytes_per_frame")),
                    "rate_kbps": field_rate(row),
                    "power_dbm": number(row, "tx_power_dbm"),
                    **empty_metric,
                    "total_power_mW": number(row, "mean_power_mW"),
                    "excess_power_mW": number(row, "mean_excess_power_mW"),
                    "delivery_percent": 100.0 - loss if row.get("measurement_direction") == "rx" else "",
                }
            )
    return rows


def build_e07_comparison(
    packet_data: dict[str, list[dict[str, str]]]
) -> list[dict[str, object]]:
    specs = {
        spec.slug: spec
        for spec in MODULES
        if spec.slug in {
            "ebyte_e07_400m10s",
            "ebyte_e07_433m20s",
            "ebyte_e07_900mm10s",
        }
    }
    labels = {slug: module_name(slug) for slug in specs}
    output: list[dict[str, object]] = []
    for slug, spec in specs.items():
        for row in packet_data[slug]:
            at_common_power = math.isclose(number(row, "tx_power_dbm"), -30.0)
            if (
                at_common_power
                and math.isclose(field_rate(row), 38.4)
            ):
                output.append(
                    normalize_packet_point(row, spec, labels[slug], "payload")
                )
            if (
                at_common_power
                and round(number(row, "payload_bytes")) == 32
            ):
                output.append(
                    normalize_packet_point(row, spec, labels[slug], "rate")
                )
    return output


def build_cc1101_family_comparison(
    packet_data: dict[str, list[dict[str, str]]]
) -> list[dict[str, object]]:
    labels = {
        slug: module_name(slug)
        for slug in (
            "cc1101_v1_433",
            "cc1101_v2_868",
            "ebyte_e07_400m10s",
            "ebyte_e07_433m20s",
            "ebyte_e07_900mm10s",
        )
    }
    specs = {spec.slug: spec for spec in MODULES}
    output: list[dict[str, object]] = []
    for slug, label in labels.items():
        spec = specs[slug]
        for row in packet_data[slug]:
            if (
                round(number(row, "payload_bytes")) == 32
                and math.isclose(field_rate(row), 38.4)
            ):
                output.append(
                    normalize_packet_point(row, spec, label, "power")
                )
    return output


def build_e79_interface_comparison(
    packet_data: dict[str, list[dict[str, str]]]
) -> list[dict[str, object]]:
    specs = {spec.slug: spec for spec in MODULES}
    labels = {
        "ebyte_e79_400dm2005s": "ESP32 bridge",
        "ebyte_e79_ch9340": "CH9340C",
    }
    output: list[dict[str, object]] = []
    for slug, label in labels.items():
        spec = specs[slug]
        for row in packet_data[slug]:
            output.append(
                normalize_packet_point(row, spec, label, "interface")
            )
    return output


def build_ra_modem_comparison(
    packet_data: dict[str, list[dict[str, str]]]
) -> list[dict[str, object]]:
    specs = {spec.slug: spec for spec in MODULES}
    labels = {
        "ra08_asr6601": module_name("ra08_asr6601"),
        "ra09_stm32wle5": module_name("ra09_stm32wle5"),
    }
    output: list[dict[str, object]] = []
    for slug, label in labels.items():
        spec = specs[slug]
        for row in packet_data[slug]:
            if not math.isclose(number(row, "tx_power_dbm"), 22.0):
                continue
            sf = packet_lora_sf(row)
            if sf == 7:
                output.append(
                    normalize_packet_point(row, spec, label, "payload")
                )
            if round(number(row, "payload_bytes")) == 32:
                output.append(
                    normalize_packet_point(row, spec, label, "spreading_factor")
                )
    return output


def choose_continuous(rows: Sequence[dict[str, str]], spec: ModuleSpec, direction: str) -> dict[str, str]:
    candidates = [row for row in rows if row.get("measurement_direction") == direction]
    if not candidates:
        raise ValueError(f"No continuous {direction} row for {spec.slug}")
    return max(candidates, key=lambda row: (mode_rank(row, spec), number(row, "tx_power_dbm")))


def matching_continuous_rx(
    rows: Sequence[dict[str, str]], spec: ModuleSpec, tx_row: dict[str, str]
) -> dict[str, str]:
    candidates = [row for row in rows if row.get("measurement_direction") == "rx"]
    if not candidates:
        raise ValueError(f"No continuous rx row for {spec.slug}")

    def mismatch(row: dict[str, str]) -> tuple[float, float]:
        mode_error = abs(configured_rate(row, spec) - configured_rate(tx_row, spec))
        power_error = abs(number(row, "tx_power_dbm") - number(tx_row, "tx_power_dbm"))
        return mode_error, power_error

    return min(candidates, key=mismatch)


def packet_delivery(rows: Sequence[dict[str, str]]) -> tuple[int, int, float, str]:
    evaluated = list(rows)
    has_attempt_schema = any("packets_attempted" in row for row in rows)
    tx_rows = [row for row in rows if row.get("measurement_direction") == "tx"]
    rx_rows = [row for row in rows if row.get("measurement_direction") == "rx"]
    scope = "bidirectional"
    if (
        not has_attempt_schema
        and tx_rows
        and rx_rows
        and sum(number(row, "packets_received") for row in tx_rows) == 0
        and sum(number(row, "packets_received") for row in rx_rows) > 0
    ):
        evaluated = rx_rows
        scope = "rx-only legacy telemetry"
    received = sum(round(number(row, "packets_received")) for row in evaluated)
    attempted = sum(
        round(number(row, "packets_attempted")) or round(number(row, "runs"))
        for row in evaluated
    )
    return received, attempted, 100.0 * received / attempted if attempted else 0.0, scope


def continuous_delivery(rows: Sequence[dict[str, str]]) -> tuple[int, int, float]:
    received = sum(round(number(row, "frames_received")) for row in rows if row.get("measurement_direction") == "rx")
    attempted = sum(round(number(row, "frames_transmitted")) for row in rows if row.get("measurement_direction") == "rx")
    return received, attempted, 100.0 * received / attempted if attempted else 0.0


def goodput_kbps(row: dict[str, str]) -> float:
    seconds = number(row, "active_window_s") or number(row, "actual_tx_duration_ms") / 1000.0
    content = number(row, "content_bytes_per_frame") or number(row, "frame_bytes")
    return number(row, "frames_received") * content * 8.0 / seconds / 1000.0 if seconds else 0.0


def load_summary() -> tuple[list[dict[str, object]], dict[str, list[dict[str, str]]]]:
    summary: list[dict[str, object]] = []
    packet_data: dict[str, list[dict[str, str]]] = {}
    for spec in MODULES:
        packets = load_packet_rows(spec)
        continuous = load_continuous_rows(spec)
        packet_data[spec.slug] = packets
        tx = choose_packet(packets, spec, "tx")
        rx = choose_packet(packets, spec, "rx")
        received, attempted, packet_percent, packet_scope = packet_delivery(packets)
        payload = number(tx, "payload_bytes")
        tx_energy = number(tx, "energy_total_mJ_mean")
        rx_energy = number(rx, "energy_total_mJ_mean")
        result: dict[str, object] = {
            **asdict(spec),
            "packet_payload_bytes": payload,
            "canonical_rate_kbps": configured_rate(tx, spec),
            "canonical_mode": packet_mode_label(tx),
            "canonical_power_dbm": number(tx, "tx_power_dbm"),
            "tx_energy_mJ": tx_energy,
            "rx_energy_mJ": rx_energy,
            "tx_energy_per_bit_uJ": tx_energy * 1000.0 / (payload * 8.0),
            "rx_energy_per_bit_uJ": rx_energy * 1000.0 / (payload * 8.0),
            "tx_duration_ms": number(tx, "event_duration_ms_mean"),
            "rx_duration_ms": number(rx, "event_duration_ms_mean"),
            "packet_received": received,
            "packet_attempted": attempted,
            "packet_campaign_runs": sum(round(number(row, "runs")) for row in packets),
            "packet_points": len(packets),
            "packet_delivery_scope": packet_scope,
            "packet_delivery_percent": packet_percent,
            "continuous_available": bool(continuous),
            "continuous_rate_kbps": "",
            "continuous_mode": "",
            "continuous_power_dbm": "",
            "continuous_tx_power_mW": "",
            "continuous_rx_power_mW": "",
            "continuous_goodput_kbps": "",
            "continuous_received": 0,
            "continuous_attempted": 0,
            "continuous_delivery_percent": "",
            "continuous_non_ok": 0,
            "continuous_windows": 0,
        }
        if continuous:
            ctx = choose_continuous(continuous, spec, "tx")
            crx = matching_continuous_rx(continuous, spec, ctx)
            c_received, c_attempted, continuous_percent = continuous_delivery(continuous)
            result.update(
                {
                    "continuous_rate_kbps": configured_rate(ctx, spec),
                    "continuous_mode": ctx.get("rf_profile")
                    or (
                        f"SF{number(ctx, 'spreading_factor'):g}"
                        if number(ctx, "spreading_factor")
                        else f"{field_rate(ctx):g} kbps"
                    ),
                    "continuous_power_dbm": number(ctx, "tx_power_dbm"),
                    "continuous_tx_power_mW": number(ctx, "mean_power_mW"),
                    "continuous_rx_power_mW": number(crx, "mean_power_mW"),
                    "continuous_goodput_kbps": goodput_kbps(crx),
                    "continuous_received": c_received,
                    "continuous_attempted": c_attempted,
                    "continuous_delivery_percent": continuous_percent,
                    "continuous_non_ok": sum(
                        1 for row in continuous if row.get("status") != "ok"
                    ),
                    "continuous_windows": len(continuous),
                }
            )
        summary.append(result)
    return summary, packet_data


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def latex_escape(value: object) -> str:
    text = str(value)
    for source, replacement in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
    ):
        text = text.replace(source, replacement)
    return text


def fmt(value: object, digits: int = 3) -> str:
    number_value = float(value)
    if number_value == 0:
        return "0"
    if abs(number_value) >= 100:
        return f"{number_value:.1f}"
    if abs(number_value) >= 10:
        return f"{number_value:.2f}"
    if abs(number_value) >= 1:
        return f"{number_value:.3f}"
    return f"{number_value:.{digits}g}"


def write_tables(
    summary: Sequence[dict[str, object]],
    payload_rows: Sequence[dict[str, object]],
    payload_sizes: Sequence[int],
) -> None:
    tables = STUDY_DIR / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    catalog_lines = [
        r"\begingroup",
        r"\captionsetup{justification=raggedright,singlelinecheck=false}",
        r"\setlength{\LTleft}{0pt}",
        r"\setlength{\LTright}{\fill}",
        r"\begin{longtable}{@{}>{\raggedright\arraybackslash}p{0.24\linewidth}>{\raggedright\arraybackslash}p{0.11\linewidth}>{\raggedright\arraybackslash}p{0.07\linewidth}>{\raggedright\arraybackslash}p{0.08\linewidth}>{\raggedright\arraybackslash}p{0.15\linewidth}>{\raggedright\arraybackslash}p{0.13\linewidth}>{\raggedright\arraybackslash}p{0.13\linewidth}@{}}",
        r"\caption{Measured module and hardware-variant catalog. Rates and powers are the settings exercised in this campaign, not the full capabilities of each chipset.}\label{tab:catalog}\\",
        r"\toprule",
        r"Module/variant & Radio IC & Band & I/F & Tested PHY/modulation & Tested rates & Tested power \\ \midrule",
        r"\endfirsthead",
        r"\toprule Module/variant & Radio IC & Band & I/F & Tested PHY/modulation & Tested rates & Tested power \\ \midrule",
        r"\endhead",
    ]
    for row in summary:
        catalog_name = str(row["label"]).rsplit(" (", 1)[0]
        catalog_lines.append(
            " & ".join(
                latex_escape(value)
                for value in (
                    catalog_name,
                    row["chip"],
                    row["band"],
                    row["interface"],
                    row["modulation"],
                    row["configured_rates"],
                    row["tested_powers"],
                )
            )
            + r" \\"
        )
    catalog_lines.extend((r"\bottomrule", r"\end{longtable}", r"\endgroup"))
    (tables / "module_catalog.tex").write_text("\n".join(catalog_lines) + "\n", encoding="utf-8")

    matrix = {
        (str(row["slug"]), str(row["direction"]), int(row["payload_bytes"])): row
        for row in payload_rows
    }
    for direction, filename, label in (
        ("tx", "tx_packet_energy_by_payload.tex", "tab:packet-tx-matrix"),
        ("rx", "rx_packet_energy_by_payload.tex", "tab:packet-rx-matrix"),
    ):
        direction_name = direction.upper()
        include_radio_ic = direction == "rx"
        if include_radio_ic:
            column_spec = (
                r"@{}>{\raggedright\arraybackslash}p{0.17\linewidth}"
                r">{\raggedright\arraybackslash}p{0.10\linewidth}"
                r">{\raggedright\arraybackslash}p{0.09\linewidth}"
                r">{\raggedright\arraybackslash}p{0.08\linewidth}"
                + "l" * len(payload_sizes)
                + "@{}"
            )
            header = (
                r"Module/\newline variant & Radio IC & Mode & Configured & "
                rf"\multicolumn{{{len(payload_sizes)}}}{{l}}{{Logical payload size [bytes]}} \\"
            )
            payload_header = r" & & & power & " + " & ".join(str(size) for size in payload_sizes) + r" \\"
            units = r" & & & [dBm] & " + " & ".join("[mJ]" for _ in payload_sizes) + r" \\ \midrule"
        else:
            column_spec = "@{}" + "l" * (3 + len(payload_sizes)) + "@{}"
            header = (
                r"Module/variant & Mode & Configured & "
                rf"\multicolumn{{{len(payload_sizes)}}}{{l}}{{Logical payload size [bytes]}} \\"
            )
            payload_header = r" & & power & " + " & ".join(str(size) for size in payload_sizes) + r" \\"
            units = r" & & [dBm] & " + " & ".join("[mJ]" for _ in payload_sizes) + r" \\ \midrule"
        caption_text = (
            f"Measured {direction_name} energy per logical packet at each module's fastest tested "
            "mode and highest tested configured power. Payload columns are bytes; a dash means "
            "that payload size was not measured."
        )
        if include_radio_ic:
            matrix_lines = [
                r"\begingroup",
                r"\captionsetup{justification=raggedright,singlelinecheck=false}",
                r"\setlength{\LTleft}{0pt}",
                r"\setlength{\LTright}{\fill}",
                rf"\begin{{longtable}}{{{column_spec}}}",
                rf"\caption{{{caption_text}}}\label{{{label}}}\\",
                r"\toprule",
                header,
                payload_header,
                units,
                r"\endfirsthead",
                r"\toprule",
                header,
                payload_header,
                units,
                r"\endhead",
            ]
        else:
            matrix_lines = [
                r"\captionsetup{justification=raggedright,singlelinecheck=false}",
                r"\begin{table}[p]",
                r"\centering",
                rf"\caption{{{caption_text}}}",
                rf"\label{{{label}}}",
                r"\resizebox{\textwidth}{!}{%",
                rf"\begin{{tabular}}{{{column_spec}}}",
                r"\toprule",
                header,
                payload_header,
                units,
            ]
        for module in summary:
            values = []
            for payload_bytes in payload_sizes:
                point = matrix.get((str(module["slug"]), direction, payload_bytes))
                values.append(f"{float(point['energy_mJ']):.2f}" if point else r"\textemdash")
            if include_radio_ic:
                module_name = str(module["code"]).rsplit(" (", 1)[0]
                module_cell = latex_escape(module_name)
                row_prefix = (
                    f"{module_cell} & {latex_escape(module['chip'])} & "
                    f"{latex_escape(module['canonical_mode'])} & "
                    f"{float(module['canonical_power_dbm']):.0f} & "
                )
            else:
                row_prefix = (
                    f"{latex_escape(module['code'])} & {latex_escape(module['canonical_mode'])} & "
                    f"{float(module['canonical_power_dbm']):.0f} & "
                )
            matrix_lines.append(row_prefix + " & ".join(values) + r" \\")
        if include_radio_ic:
            matrix_lines.extend((r"\bottomrule", r"\end{longtable}", r"\endgroup"))
        else:
            matrix_lines.extend((r"\bottomrule", r"\end{tabular}", r"}", r"\end{table}"))
        (tables / filename).write_text("\n".join(matrix_lines) + "\n", encoding="utf-8")

    benchmark_lines = [
        r"\begin{longtable}{@{}>{\raggedright\arraybackslash}p{0.30\linewidth}>{\raggedright\arraybackslash}p{0.10\linewidth}rrrrrrr@{}}",
        r"\caption{Sustained-traffic and delivery benchmark. Continuous values use the fastest mode available in each 60-second campaign. PDR and CDR aggregate the complete packet and continuous matrices, respectively; a dash denotes that no continuous campaign was measured.}\label{tab:benchmark}\\",
        r"\toprule",
        r"Module/variant & Mode & Rate & dBm & $P_{TX}$ & $P_{RX}$ & Goodput & PDR & CDR \\",
        r" & & [kbps] & & [mW] & [mW] & [kbps] & [\%] & [\%] \\ \midrule",
        r"\endfirsthead",
        r"\toprule Module/variant & Mode & Rate & dBm & $P_{TX}$ & $P_{RX}$ & Goodput & PDR & CDR \\ \midrule",
        r"\endhead",
    ]
    for row in summary:
        if row["continuous_available"]:
            continuous_cells = (
                latex_escape(row["continuous_mode"]),
                fmt(row["continuous_rate_kbps"]),
                fmt(row["continuous_power_dbm"]),
                fmt(row["continuous_tx_power_mW"]),
                fmt(row["continuous_rx_power_mW"]),
                fmt(row["continuous_goodput_kbps"]),
                f"{float(row['continuous_delivery_percent']):.1f}",
            )
        else:
            continuous_cells = (r"\textemdash",) * 7
        benchmark_lines.append(
            f"{latex_escape(row['code'])} & {continuous_cells[0]} & {continuous_cells[1]} & "
            f"{continuous_cells[2]} & {continuous_cells[3]} & {continuous_cells[4]} & "
            f"{continuous_cells[5]} & "
            f"{float(row['packet_delivery_percent']):.1f} & {continuous_cells[6]} \\\\"
        )
    benchmark_lines.extend((r"\bottomrule", r"\end{longtable}"))
    (tables / "benchmark_summary.tex").write_text("\n".join(benchmark_lines) + "\n", encoding="utf-8")


def title(
    canvas: PdfCanvas,
    value: str,
    subtitle: str = "",
    subtitle_font_size: float | None = None,
) -> None:
    size = fitted_font_size(canvas, value, 28.0, canvas.width - 60.0)
    canvas.centered_text(canvas.height - 35, value, size=size, bold=True)
    if subtitle:
        sub_size = fitted_font_size(
            canvas,
            subtitle,
            subtitle_font_size or SUBTITLE_FONT_SIZE,
            canvas.width - 80.0,
        )
        canvas.centered_text(
            canvas.height - 60,
            subtitle,
            size=sub_size,
            color=GRAY,
            italic=True,
        )


def fitted_font_size(
    canvas: PdfCanvas,
    value: str,
    preferred_size: float,
    available_width: float,
    minimum_size: float = 16.0,
) -> float:
    measured_width = canvas.text_width(value, preferred_size)
    if measured_width <= available_width:
        return preferred_size
    return max(minimum_size, preferred_size * available_width / measured_width)


def gray_note(canvas: PdfCanvas, value: str, y: float) -> None:
    size = fitted_font_size(
        canvas,
        value,
        NOTE_FONT_SIZE,
        canvas.width - 80.0,
        minimum_size=17.0,
    )
    canvas.centered_text(
        y,
        value,
        size=size,
        italic=True,
        color=GRAY,
    )


def centered_axis_label(
    canvas: PdfCanvas,
    y: float,
    value: str,
    *,
    left: float,
    width: float,
    size: float = AXIS_FONT_SIZE,
) -> None:
    canvas.centered_text(
        y,
        value,
        size=size,
        bold=True,
        left=left,
        width=width,
    )


def compact_plot_label(value: str) -> str:
    compact = value.rsplit(" (", 1)[0] if value.endswith(")") else value
    aliases = {
        "Adafruit board with level shifter": "Adafruit level-shifter board",
        "Ai-Thinker RA-02 with 2 Cap": "RA-02 + 2 capacitors",
        "Carrier PCB with 2 Cap": "Carrier PCB + 2 capacitors",
        "Ebyte E32-433T20D": "E32-433T20D",
        "Ebyte E32-868T20D": "E32-868T20D",
        "Ebyte E79-400DM2005S via CH9340C": "E79 via CH9340C",
        "Ebyte E79-400DM2005S via ESP32": "E79 via ESP32",
    }
    return aliases.get(compact, compact)


def wrap_plot_label(value: str, max_chars: int = 28) -> tuple[str, ...]:
    words = value.split()
    if len(value) <= max_chars or len(words) == 1:
        return (value,)
    lines = ["", ""]
    for word in words:
        target = 0 if len(lines[0]) + len(word) + bool(lines[0]) <= max_chars else 1
        lines[target] = f"{lines[target]} {word}".strip()
    return tuple(line for line in lines if line)


def log_ticks(low: float, high: float) -> list[float]:
    lo_exp = math.floor(math.log10(low))
    hi_exp = math.ceil(math.log10(high))
    values: list[float] = []
    for exponent in range(lo_exp, hi_exp + 1):
        for multiplier in (1.0, 2.0, 5.0):
            value = multiplier * 10.0**exponent
            if low <= value <= high:
                values.append(value)
    return values


def fmt_tick(value: float) -> str:
    if value >= 1000:
        if math.isclose(value, 1024.0):
            return "1k"
        return f"{value / 1000:g}k"
    if value >= 1:
        return f"{value:g}"
    return f"{value:.2g}"


def linear_ticks(high: float, target_count: int = 5) -> tuple[float, list[float]]:
    raw_step = high / max(1, target_count)
    exponent = math.floor(math.log10(raw_step)) if raw_step > 0 else 0
    scale = 10.0**exponent
    fraction = raw_step / scale
    nice_fraction = next(value for value in (1.0, 2.0, 2.5, 5.0, 10.0) if value >= fraction)
    step = nice_fraction * scale
    upper = math.ceil(high / step) * step
    return upper, [index * step for index in range(round(upper / step) + 1)]


def dot_comparison(
    path: Path,
    rows: Sequence[dict[str, object]],
    left_key: str,
    right_key: str,
    left_label: str,
    right_label: str,
    heading: str,
    unit: str,
    subtitle: str,
    log_x: bool = True,
    radio_ic_column: bool = False,
    expanded_layout: bool = False,
    expanded_plot_left: float = 540.0,
    expanded_plot_height: float = 985.0,
    subtitle_font_size: float | None = None,
) -> None:
    ordered = sorted(rows, key=lambda row: max(float(row[left_key]), float(row[right_key])))
    canvas = PdfCanvas(
        1360,
        expanded_plot_height + 225.0 if expanded_layout else 760,
    )
    title(canvas, heading, subtitle, subtitle_font_size)
    if expanded_layout:
        box = (
            expanded_plot_left,
            100.0,
            1300.0 - expanded_plot_left,
            expanded_plot_height,
        )
    else:
        box = (500.0, 75.0, 800.0, 585.0) if radio_ic_column else (430.0, 75.0, 870.0, 585.0)
    values = [float(row[key]) for row in ordered for key in (left_key, right_key) if float(row[key]) > 0]
    low = min(values) * (0.72 if log_x else 0.0)
    high = max(values) * 1.28
    if not log_x:
        low = 0.0
        if unit.endswith("[%]"):
            high = 100.0
    ticks = log_ticks(low, high) if log_x else [high * index / 5.0 for index in range(6)]
    expanded_labels: list[tuple[str, ...]] = []
    if expanded_layout:
        for row in ordered:
            label = str(row["code"])
            if len(label) > 34 and " (" in label and label.endswith(")"):
                module_name, radio_ic = label.rsplit(" (", 1)
                expanded_labels.append((module_name, f"({radio_ic}"))
            else:
                expanded_labels.append((label,))
        row_weights = [1.35 if len(lines) == 2 else 1.0 for lines in expanded_labels]
        row_height = box[3] / sum(row_weights)
        row_centers: list[float] = []
        row_cursor = box[1]
        for weight in row_weights:
            band_height = row_height * weight
            row_centers.append(row_cursor + band_height / 2.0)
            row_cursor += band_height
    else:
        row_centers = [
            box[1] + (index + 0.5) * box[3] / len(ordered)
            for index in range(len(ordered))
        ]
    for tick in ticks:
        px = _map(tick, low, high, box[0], box[2], log_x)
        canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.7)
        tick_offset = 31.0 if expanded_layout else 28.0
        canvas.text(px - 18, box[1] - tick_offset, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    for index, row in enumerate(ordered):
        py = row_centers[index]
        label = str(row["code"])
        if radio_ic_column:
            variant = label.rsplit(" (", 1)[0] if label.endswith(")") else label
            chip = str(row["chip"])
            variant_size = min(
                TICK_FONT_SIZE,
                310.0 / max(1.0, len(variant) * 0.68),
            )
            chip_size = min(
                TICK_FONT_SIZE,
                130.0 / max(1.0, len(chip) * 0.68),
            )
            canvas.text(20, py - 6, variant, size=variant_size, bold=True)
            canvas.text(350, py - 6, chip, size=chip_size, bold=True)
        elif expanded_layout:
            label_lines = expanded_labels[index]
            label_size = TICK_FONT_SIZE
            if len(label_lines) == 2:
                canvas.text(40, py + 7, label_lines[0], size=label_size, bold=True)
                canvas.text(40, py - 18, label_lines[1], size=label_size, bold=True)
            else:
                canvas.text(40, py - 6, label_lines[0], size=label_size, bold=True)
        else:
            plot_label = compact_plot_label(label)
            label_lines = wrap_plot_label(plot_label)
            if len(label_lines) == 2:
                canvas.text(20, py + 7, label_lines[0], size=TICK_FONT_SIZE, bold=True)
                canvas.text(20, py - 18, label_lines[1], size=TICK_FONT_SIZE, bold=True)
            else:
                canvas.text(20, py - 6, label_lines[0], size=TICK_FONT_SIZE, bold=True)
        first = _map(float(row[left_key]), low, high, box[0], box[2], log_x)
        second = _map(float(row[right_key]), low, high, box[0], box[2], log_x)
        canvas.line(first, py, second, py, color=GRAY, width=1.2)
        canvas.marker(first, py, color=BLUE, kind=2, radius=4)
        canvas.marker(second, py, color=RED, kind=0, radius=4)
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    axis_label_y = 25.0 if expanded_layout else 27.0
    canvas.centered_text(
        axis_label_y,
        unit,
        size=AXIS_FONT_SIZE,
        bold=True,
        left=box[0],
        width=box[2],
    )
    legend_y = box[1] + box[3] + 18.0
    left_legend_x = 700.0 if radio_ic_column or expanded_layout else 620.0
    right_legend_x = 930.0 if radio_ic_column or expanded_layout else 875.0
    if radio_ic_column:
        canvas.text(20, legend_y - 8, "Module/variant", size=LEGEND_FONT_SIZE, bold=True)
        canvas.text(350, legend_y - 8, "Radio IC", size=LEGEND_FONT_SIZE, bold=True)
    canvas.marker(left_legend_x, legend_y, color=BLUE, kind=2, radius=5)
    canvas.text(left_legend_x + 14, legend_y - 8, left_label, size=LEGEND_FONT_SIZE, bold=True)
    canvas.marker(right_legend_x, legend_y, color=RED, kind=0, radius=5)
    canvas.text(right_legend_x + 14, legend_y - 8, right_label, size=LEGEND_FONT_SIZE, bold=True)
    canvas.save(path)


def scatter_rate_energy(path: Path, rows: Sequence[dict[str, object]]) -> None:
    canvas = PdfCanvas(1400, 1570)
    title(canvas, "Packet energy versus rate design space", "")
    box = (110.0, 650.0, 1190.0, 760.0)
    xs = [float(row["canonical_rate_kbps"]) for row in rows]
    ys = [float(row["tx_energy_mJ"]) for row in rows]
    x_range = (min(xs) * 0.65, max(xs) * 1.55)
    y_range = (min(ys) * 0.55, max(ys) * 2.1)
    for tick in log_ticks(*x_range):
        px = _map(tick, *x_range, box[0], box[2], True)
        canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.7)
        canvas.text(px - 18, box[1] - 28, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    for tick in log_ticks(*y_range):
        py = _map(tick, *y_range, box[1], box[3], True)
        canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.7)
        canvas.text(box[0] - 62, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    families = {family: index for index, family in enumerate(sorted({str(row["family"]) for row in rows}))}
    indexed_rows = sorted(
        rows,
        key=lambda row: (
            float(row["canonical_rate_kbps"]),
            -float(row["tx_energy_mJ"]),
            str(row["code"]),
        ),
    )
    plotted: list[tuple[int, dict[str, object], float, float, tuple[float, float, float]]] = []
    for number, row in enumerate(indexed_rows, start=1):
        px = _map(float(row["canonical_rate_kbps"]), *x_range, box[0], box[2], True)
        py = _map(float(row["tx_energy_mJ"]), *y_range, box[1], box[3], True)
        color = PALETTE[families[str(row["family"])] % len(PALETTE)]
        canvas.marker(px, py, color=color, kind=number - 1, radius=5)
        plotted.append((number, row, px, py, color))

    number_size = 22.0
    number_gap = 30.0
    x_group_gap = 32.0
    label_bottom = box[1] + 8.0
    label_top = box[1] + box[3] - number_size
    x_groups: list[list[tuple[int, dict[str, object], float, float, tuple[float, float, float]]]] = []
    for point in sorted(plotted, key=lambda item: item[2]):
        if not x_groups or point[2] - x_groups[-1][-1][2] > x_group_gap:
            x_groups.append([point])
        else:
            x_groups[-1].append(point)

    label_y_by_number: dict[int, float] = {}
    for group in x_groups:
        vertical_points = sorted(group, key=lambda point: point[3])
        label_positions: list[float] = []
        for _, _, _, py, _ in vertical_points:
            preferred = max(label_bottom, py - number_size * 0.35)
            if label_positions:
                preferred = max(preferred, label_positions[-1] + number_gap)
            label_positions.append(preferred)
        if label_positions[-1] > label_top:
            label_positions[-1] = label_top
            for index in range(len(label_positions) - 2, -1, -1):
                label_positions[index] = min(
                    label_positions[index],
                    label_positions[index + 1] - number_gap,
                )
        for point, label_y in zip(vertical_points, label_positions):
            label_y_by_number[point[0]] = label_y

    compact_label_slugs = {
        "ebyte_e32_433t20d",
        "ebyte_e32_433t33d",
        "ebyte_e32_868t20d",
        "ebyte_e32_868t30d",
    }
    for number, row, px, py, color in plotted:
        label_y = label_y_by_number[number]
        label_offset = (
            18.0
            if str(row["slug"]) in compact_label_slugs
            else 60.0 if float(row["canonical_rate_kbps"]) <= 20.0 else 18.0
        )
        if px < box[0] + box[2] - label_offset - 27.0:
            label_x = px + label_offset
            leader_x = label_x - 5.0
        else:
            label_x = px - 25.0
            leader_x = label_x + 20.0
        if abs(label_y + 5.0 - py) > 5.0:
            canvas.line(px, py, leader_x, label_y + 5.0, color=color, width=0.7)
        canvas.text(label_x, label_y, str(number), size=number_size, color=BLACK, bold=True)

    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.2)
    canvas.text(515, 582, "Configured gross rate [kbps]", size=AXIS_FONT_SIZE, bold=True)
    canvas.text(box[0], box[1] + box[3] + 15.0, "32-byte TX energy [mJ]", size=AXIS_FONT_SIZE, bold=True)

    canvas.text(60, 532, "Module index", size=26.0, bold=True)
    key_columns = 2
    rows_per_column = math.ceil(len(plotted) / key_columns)
    key_top = 490.0
    key_line_height = 32.0
    key_font_size = 24.0
    key_column_x = (60.0, 700.0)
    for index, (number, row, _, _, color) in enumerate(plotted):
        column = index // rows_per_column
        row_index = index % rows_per_column
        key_y = key_top - row_index * key_line_height
        key_x = key_column_x[column]
        canvas.marker(key_x, key_y + 6.0, color=color, kind=number - 1, radius=5)
        canvas.text(
            key_x + 14.0,
            key_y - 2.0,
            f"{number}. {row['code']}",
            size=key_font_size,
            color=BLACK,
            bold=True,
        )
    canvas.save(path)


def payload_energy_figure(
    path: Path,
    payload_rows: Sequence[dict[str, object]],
    payload_sizes: Sequence[int],
    direction: str,
) -> None:
    groups = (
        (
            "CC1101 boards and E07 modules",
            {"cc1101_v1_433", "cc1101_v2_868", "ebyte_e07_400m10s", "ebyte_e07_433m20s", "ebyte_e07_900mm10s"},
        ),
        (
            "FSK and transparent high-rate modules",
            {"e280", "ebyte_e79_400dm2005s", "ebyte_e79_ch9340", "hc12", "nrf24l01", "nrf24l01_pa"},
        ),
        (
            "Direct LoRa and modem implementations",
            {"e28_sx1280", "ebyte_e22_400m30s", "ra01h_sx1276", "ra01sh_sx1262", "ra08_asr6601", "ra09_stm32wle5", "xl1276_d01_sx1276"},
        ),
        (
            "SX1278 physical variants",
            {"ra02_sx1278", "ra02_sx1278_2cap", "sx1278_adafruit_level_shifter", "sx1278_naked", "sx1278_pcb_2cap", "sx1278_shielded"},
        ),
        (
            "E32 transparent UART modules",
            {"ebyte_e32_433t20d", "ebyte_e32_433t33d", "ebyte_e32_868t20d", "ebyte_e32_868t30d"},
        ),
    )
    selected_rows = [row for row in payload_rows if row["direction"] == direction]
    direction_name = direction.upper()
    payload_index = {payload: index for index, payload in enumerate(payload_sizes)}

    sheets = [groups[index:index + 2] for index in range(0, len(groups), 2)]
    for sheet_index, sheet_groups in enumerate(sheets):
        single_panel_sheet = len(sheet_groups) == 1
        canvas = PdfCanvas(1120, 740 if single_panel_sheet else 1260)
        continuation = " (continued)" if sheet_index else ""
        title(
            canvas,
            f"{direction_name} energy versus measured logical payload size{continuation}",
            "Fastest tested mode and highest tested configured power per module; logarithmic energy axis",
        )
        panel_origins = (
            ((105.0, 105.0),)
            if single_panel_sheet
            else ((105.0, 690.0), (105.0, 100.0))
        )
        plot_width = 910.0
        plot_height = 310.0

        for local_index, ((panel_title, slugs), (left, bottom)) in enumerate(zip(sheet_groups, panel_origins)):
            panel_index = sheet_index * 2 + local_index
            panel_rows = [row for row in selected_rows if row["slug"] in slugs]
            energies = [float(row["energy_mJ"]) for row in panel_rows]
            y_range = (min(energies) * 0.65, max(energies) * 1.65)
            canvas.centered_text(
                bottom + plot_height + 163,
                panel_title,
                size=23,
                bold=True,
                left=left,
                width=plot_width,
            )
            canvas.centered_text(
                bottom + plot_height + 5,
                f"{direction_name} packet energy [mJ]",
                size=AXIS_FONT_SIZE,
                bold=True,
                left=left,
                width=plot_width,
            )

            module_codes = sorted({str(row["code"]) for row in panel_rows})
            code_style = {
                code: (PALETTE[index % len(PALETTE)], index)
                for index, code in enumerate(module_codes)
            }
            for index, code in enumerate(module_codes):
                color, marker = code_style[code]
                legend_column = index % 2
                legend_row = index // 2
                lx = left + legend_column * 455
                ly = bottom + plot_height + 128 - legend_row * 30
                plot_code = compact_plot_label(code)
                canvas.line(lx, ly + 4, lx + 20, ly + 4, color=color, width=1.6)
                canvas.marker(lx + 10, ly + 4, color=color, kind=marker, radius=4.0)
                canvas.text(
                    lx + 27,
                    ly - 3,
                    plot_code,
                    size=LEGEND_FONT_SIZE,
                    color=color,
                    bold=True,
                )

            for tick in log_ticks(*y_range):
                py = _map(tick, *y_range, bottom, plot_height, True)
                canvas.line(left, py, left + plot_width, py, color=GRID, width=0.65)
                canvas.text(left - 64, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
            for payload in payload_sizes:
                index = payload_index[payload]
                px = left + index * plot_width / max(1, len(payload_sizes) - 1)
                canvas.line(px, bottom, px, bottom + plot_height, color=GRID, width=0.5)
                canvas.text(px - (14 if payload < 100 else 24), bottom - 28, str(payload), size=TICK_FONT_SIZE, bold=True)

            for code in module_codes:
                series = sorted(
                    (row for row in panel_rows if row["code"] == code),
                    key=lambda row: int(row["payload_bytes"]),
                )
                color, marker = code_style[code]
                mapped = [
                    (
                        left + payload_index[int(row["payload_bytes"])] * plot_width / max(1, len(payload_sizes) - 1),
                        _map(float(row["energy_mJ"]), *y_range, bottom, plot_height, True),
                    )
                    for row in series
                ]
                canvas.polyline(mapped, color=color, width=1.7)
                for px, py in mapped:
                    canvas.marker(px, py, color=color, kind=marker, radius=4.0)

            canvas.line(left, bottom, left + plot_width, bottom, width=1.1)
            canvas.line(left, bottom, left, bottom + plot_height, width=1.1)
            canvas.centered_text(
                bottom - 52,
                "Logical payload [bytes]",
                size=AXIS_FONT_SIZE,
                bold=True,
                left=left,
                width=plot_width,
            )
            canvas.text(left + plot_width - 22, bottom + plot_height + 5, chr(ord("A") + panel_index), size=20, bold=True)

        if sheet_index == 0:
            output_path = path
        elif sheet_index == 1:
            output_path = path.with_name(f"{path.stem}_continued{path.suffix}")
        else:
            output_path = path.with_name(
                f"{path.stem}_continued_{sheet_index}{path.suffix}"
            )
        canvas.save(output_path)


def linear_axis(maximum: float, divisions: int = 4) -> tuple[float, list[float]]:
    target = maximum * 1.12 / divisions
    magnitude = 10.0 ** math.floor(math.log10(target))
    step = next(
        candidate * magnitude
        for candidate in (1.0, 2.0, 5.0, 10.0)
        if candidate * magnitude >= target
    )
    high = math.ceil(maximum * 1.08 / step) * step
    return high, [index * step for index in range(round(high / step) + 1)]


def two_board_panel(
    canvas: PdfCanvas,
    rows: Sequence[dict[str, object]],
    left: float,
    bottom: float,
    width: float,
    height: float,
    panel_title: str,
    letter: str,
    x_key: str,
    y_key: str,
    x_ticks: Sequence[float],
    x_label: str,
    y_label: str,
    x_log: bool,
    y_log: bool,
) -> None:
    values = [float(row[y_key]) for row in rows]
    if y_log:
        y_range = (min(values) * 0.68, max(values) * 1.4)
        y_ticks = log_ticks(*y_range)
    else:
        high, y_ticks = linear_axis(max(values))
        y_range = (0.0, high)
    x_low = min(x_ticks) * (0.78 if x_log else 1.0)
    x_high = max(x_ticks) * (1.28 if x_log else 1.0)
    if not x_log:
        margin = max(1.0, (x_high - x_low) * 0.08)
        x_low -= margin
        x_high += margin

    canvas.centered_text(
        bottom + height + 43,
        panel_title,
        size=22,
        bold=True,
        left=left,
        width=width,
    )
    canvas.centered_text(
        bottom + height + 19,
        y_label,
        size=AXIS_FONT_SIZE,
        bold=True,
        left=left,
        width=width,
    )
    canvas.text(left + width - 16, bottom + height + 7, letter, size=20, bold=True)
    for tick in y_ticks:
        py = _map(tick, *y_range, bottom, height, y_log)
        canvas.line(left, py, left + width, py, color=GRID, width=0.55)
        canvas.text(left - 58, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    for tick in x_ticks:
        px = _map(tick, x_low, x_high, left, width, x_log)
        canvas.line(px, bottom, px, bottom + height, color=GRID, width=0.45)
        label = fmt_tick(tick)
        canvas.text(px - len(label) * 4.8, bottom - 27, label, size=TICK_FONT_SIZE, bold=True)

    styles = {
        module_name("cc1101_v1_433"): (BLUE, 2),
        module_name("cc1101_v2_868"): (RED, 0),
    }
    for code, (color, marker) in styles.items():
        series = sorted((row for row in rows if row["code"] == code), key=lambda row: float(row[x_key]))
        mapped = [
            (
                _map(float(row[x_key]), x_low, x_high, left, width, x_log),
                _map(float(row[y_key]), *y_range, bottom, height, y_log),
            )
            for row in series
        ]
        canvas.polyline(mapped, color=color, width=1.8)
        for px, py in mapped:
            canvas.marker(px, py, color=color, kind=marker, radius=4)

    canvas.line(left, bottom, left + width, bottom, width=1.0)
    canvas.line(left, bottom, left, bottom + height, width=1.0)
    centered_axis_label(
        canvas,
        bottom - 51,
        x_label,
        left=left,
        width=width,
    )


def stacked_packet_series_figure(
    path: Path,
    rows: Sequence[dict[str, object]],
    heading: str,
    subtitle: str,
    series_order: Sequence[str],
    x_key: str,
    x_ticks: Sequence[float],
    x_labels: Sequence[str],
    x_label: str,
    x_log: bool,
) -> None:
    canvas = PdfCanvas(1080, 820)
    title(canvas, heading, subtitle)
    legend_columns = 2
    for index, label in enumerate(series_order):
        column = index % legend_columns
        row_index = index // legend_columns
        left = 105.0 + column * 455.0
        y = 718.0 - row_index * 30.0
        color = PALETTE[index % len(PALETTE)]
        plot_label = compact_plot_label(label)
        canvas.line(left, y, left + 28, y, color=color, width=2.0)
        canvas.marker(left + 14, y, color=color, kind=index, radius=4.5)
        canvas.text(
            left + 38,
            y - 7,
            plot_label,
            size=LEGEND_FONT_SIZE,
            color=color,
            bold=True,
        )

    panels = (("tx", "TX packet energy", "A"), ("rx", "RX packet energy", "B"))
    boxes = ((110.0, 405.0, 880.0, 190.0), (110.0, 95.0, 880.0, 190.0))
    x_min = min(x_ticks)
    x_max = max(x_ticks)
    if x_log:
        x_range = (x_min * 0.78, x_max * 1.28)
    else:
        margin = max(0.5, (x_max - x_min) * 0.08)
        x_range = (x_min - margin, x_max + margin)

    has_delivery_warning = False
    for panel_index, ((direction, panel_title, panel_code), box) in enumerate(zip(panels, boxes)):
        panel_rows = [
            row
            for row in rows
            if row["direction"] == direction and float(row["energy_mJ"]) > 0
        ]
        values = [float(row["energy_mJ"]) for row in panel_rows]
        y_range = (min(values) * 0.70, max(values) * 1.45)
        y_ticks = log_ticks(*y_range)
        canvas.centered_text(
            box[1] + box[3] + 16,
            f"{panel_title} [mJ]",
            size=AXIS_FONT_SIZE,
            bold=True,
            left=box[0],
            width=box[2],
        )
        canvas.text(box[0] + box[2] - 18, box[1] + box[3] + 24, panel_code, size=20, bold=True)

        for tick in y_ticks:
            py = _map(tick, *y_range, box[1], box[3], True)
            canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.6)
            canvas.text(box[0] - 68, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
        x_tick_font_size = min(TICK_FONT_SIZE, 22.0)
        for tick, label in zip(x_ticks, x_labels):
            px = _map(tick, *x_range, box[0], box[2], x_log)
            canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.5)
            canvas.text(
                px - max(14.0, len(label) * x_tick_font_size * 0.30),
                box[1] - 29,
                label,
                size=x_tick_font_size,
                bold=True,
            )

        for series_index, series_label in enumerate(series_order):
            series = sorted(
                (row for row in panel_rows if row["series"] == series_label),
                key=lambda row: float(row[x_key]),
            )
            color = PALETTE[series_index % len(PALETTE)]
            points = [
                (
                    _map(float(row[x_key]), *x_range, box[0], box[2], x_log),
                    _map(float(row["energy_mJ"]), *y_range, box[1], box[3], True),
                )
                for row in series
            ]
            canvas.polyline(points, color=color, width=2.0)
            for row, (px, py) in zip(series, points):
                canvas.marker(px, py, color=color, kind=series_index, radius=4.7)
                delivery = row["delivery_percent"]
                if delivery != "" and float(delivery) < 99.999:
                    has_delivery_warning = True
                    canvas.line(px - 7, py - 7, px + 7, py + 7, color=BLACK, width=1.6)
                    canvas.line(px - 7, py + 7, px + 7, py - 7, color=BLACK, width=1.6)

        canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.1)
        canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.1)
        if panel_index == len(panels) - 1:
            centered_axis_label(
                canvas,
                box[1] - 57,
                x_label,
                left=box[0],
                width=box[2],
            )

    if has_delivery_warning:
        gray_note(
            canvas,
            "Black cross: at least one of five packets was not delivered at this point.",
            14,
        )
    canvas.save(path)


def cc1101_legend(canvas: PdfCanvas, y: float) -> None:
    panel_centers = (75.0 + 425.0 / 2.0, 620.0 + 425.0 / 2.0)
    for index, (label, color, marker) in enumerate(
        (
            (module_name("cc1101_v1_433"), BLUE, 2),
            (module_name("cc1101_v2_868"), RED, 0),
        )
    ):
        plot_label = compact_plot_label(label)
        item_width = 32.0 + canvas.text_width(plot_label, LEGEND_FONT_SIZE)
        left = panel_centers[index] - item_width / 2.0
        canvas.line(left, y, left + 24, y, color=color, width=1.8)
        canvas.marker(left + 12, y, color=color, kind=marker, radius=4)
        canvas.text(
            left + 32,
            y - 8,
            plot_label,
            size=LEGEND_FONT_SIZE,
            color=color,
            bold=True,
        )


def cc1101_continuous_figure(path: Path, rows: Sequence[dict[str, object]]) -> None:
    continuous = [row for row in rows if row["comparison"] == "continuous"]
    canvas = PdfCanvas(1120, 800)
    title(
        canvas,
        "CC1101 V1/V2 continuous-power comparison",
        "60 s windows, 32-byte frames, 38.4 kbps, 15 ms host gap, 3.3 V",
    )
    panels = (
        ("Total TX power", "tx", "total_power_mW", "Mean power [mW]"),
        ("Total RX power", "rx", "total_power_mW", "Mean power [mW]"),
        ("TX power above standby", "tx", "excess_power_mW", "Excess power [mW]"),
        ("RX power above standby", "rx", "excess_power_mW", "Excess power [mW]"),
    )
    origins = ((75.0, 410.0), (620.0, 410.0), (75.0, 65.0), (620.0, 65.0))
    for index, ((panel_title, direction, y_key, y_label), (left, bottom)) in enumerate(zip(panels, origins)):
        two_board_panel(
            canvas,
            [row for row in continuous if row["direction"] == direction],
            left,
            bottom,
            425.0,
            220.0,
            panel_title,
            chr(ord("A") + index),
            "power_dbm",
            y_key,
            (-30.0, 0.0, 10.0),
            "Configured peer TX power [dBm]" if direction == "rx" else "Configured TX power [dBm]",
            y_label,
            False,
            False,
        )
    cc1101_legend(canvas, 704)
    canvas.save(path)


def cc1101_packet_figure(path: Path, rows: Sequence[dict[str, object]]) -> None:
    canvas = PdfCanvas(1120, 800)
    title(
        canvas,
        "CC1101 V1/V2 packet-energy comparison",
        "Total measured event energy; identical application workload on each comparison axis",
    )
    panels = (
        ("TX energy versus payload", "payload", "tx", "payload_bytes", (8.0, 32.0, 64.0, 128.0, 512.0, 1024.0), "Logical payload [bytes]"),
        ("RX energy versus payload", "payload", "rx", "payload_bytes", (8.0, 32.0, 64.0, 128.0, 512.0, 1024.0), "Logical payload [bytes]"),
        ("TX energy versus rate", "rate", "tx", "rate_kbps", (1.2, 38.4, 250.0), "Configured rate [kbps]"),
        ("RX energy versus rate", "rate", "rx", "rate_kbps", (1.2, 38.4, 250.0), "Configured rate [kbps]"),
    )
    origins = ((75.0, 410.0), (620.0, 410.0), (75.0, 65.0), (620.0, 65.0))
    for index, ((panel_title, comparison, direction, x_key, x_ticks, x_label), (left, bottom)) in enumerate(zip(panels, origins)):
        two_board_panel(
            canvas,
            [
                row
                for row in rows
                if row["comparison"] == comparison and row["direction"] == direction
            ],
            left,
            bottom,
            425.0,
            220.0,
            panel_title,
            chr(ord("A") + index),
            x_key,
            "energy_mJ",
            x_ticks,
            x_label,
            "Packet energy [mJ]",
            True,
            True,
        )
    cc1101_legend(canvas, 704)
    canvas.save(path)


def continuous_power_pair_figure(
    path: Path,
    comparison_id: str,
    heading: str,
    subtitle: str,
    variants: Sequence[tuple[str, str]],
    mode_field: str,
    mode_value: float,
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for variant_index, (slug, variant_label) in enumerate(variants):
        source = read_csv(COMPARISONS_DIR / slug / f"{slug}_continuous.csv")
        selected = [
            row
            for row in source
            if row.get("status") == "ok"
            and row.get("measurement_direction") in {"tx", "rx"}
            and abs(number(row, mode_field) - mode_value) < 0.001
        ]
        if len(selected) != 6:
            raise ValueError(
                f"Expected 6 matched continuous rows for {slug} at {mode_field}={mode_value}, got {len(selected)}"
            )
        for row in selected:
            normalized.append(
                {
                    "comparison": comparison_id,
                    "slug": slug,
                    "variant": variant_label,
                    "variant_index": variant_index,
                    "direction": row["measurement_direction"],
                    "mode_field": mode_field,
                    "mode_value": mode_value,
                    "power_dbm": number(row, "tx_power_dbm"),
                    "mean_power_mW": number(row, "mean_power_mW"),
                    "mean_excess_power_mW": number(row, "mean_excess_power_mW"),
                    "baseline_mean_uA": number(row, "baseline_mean_uA"),
                    "frames_transmitted": round(number(row, "frames_transmitted")),
                    "frames_received": round(number(row, "frames_received")),
                    "status": row.get("status", ""),
                }
            )

    canvas = PdfCanvas(1080, 720)
    title(canvas, heading, subtitle)
    panels = (
        ("mean_power_mW", "Total average power", "A"),
        ("mean_excess_power_mW", "Mean power above standby", "B"),
    )
    boxes = ((82.0, 145.0, 420.0, 315.0), (578.0, 145.0, 420.0, 315.0))
    powers = sorted({float(row["power_dbm"]) for row in normalized})
    power_span = max(powers) - min(powers)
    x_range = (min(powers) - power_span * 0.08, max(powers) + power_span * 0.08)

    for (metric, panel_title, panel_code), box in zip(panels, boxes):
        upper, ticks = linear_ticks(max(float(row[metric]) for row in normalized) * 1.05)
        canvas.centered_text(
            536,
            panel_title,
            size=22,
            bold=True,
            left=box[0],
            width=box[2],
        )
        canvas.text(box[0] + box[2] - 16, 516, panel_code, size=20, bold=True)
        for tick in ticks:
            py = _map(tick, 0.0, upper, box[1], box[3], False)
            canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.6)
            canvas.text(box[0] - 62, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
        for power in powers:
            px = _map(power, *x_range, box[0], box[2], False)
            canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.5)
            canvas.text(px - 16, box[1] - 29, f"{power:g}", size=TICK_FONT_SIZE, bold=True)

        for variant_index, _ in enumerate(variants):
            for direction in ("tx", "rx"):
                color = BLUE if direction == "tx" else RED
                dash = "[] 0" if variant_index == 0 else "[6 4] 0"
                rows = sorted(
                    (
                        row
                        for row in normalized
                        if int(row["variant_index"]) == variant_index and row["direction"] == direction
                    ),
                    key=lambda row: float(row["power_dbm"]),
                )
                points = [
                    (
                        _map(float(row["power_dbm"]), *x_range, box[0], box[2], False),
                        _map(float(row[metric]), 0.0, upper, box[1], box[3], False),
                    )
                    for row in rows
                ]
                canvas.polyline(points, color=color, width=1.8, dash=dash)
                for px, py in points:
                    canvas.marker(px, py, color=color, kind=variant_index, radius=4.2)

        canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.1)
        canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.1)
        centered_axis_label(
            canvas,
            84,
            "Configured RF power [dBm]",
            left=box[0],
            width=box[2],
        )
        canvas.centered_text(
            471,
            "Power [mW]",
            size=AXIS_FONT_SIZE,
            bold=True,
            left=box[0],
            width=box[2],
        )

    legend_items = [
        (variant_label, direction.upper(), BLUE if direction == "tx" else RED, variant_index)
        for variant_index, (_, variant_label) in enumerate(variants)
        for direction in ("tx", "rx")
    ]
    for index, (variant_label, direction, color, marker) in enumerate(legend_items):
        row_index, column_index = divmod(index, 2)
        lx = 90 + column_index * 500
        ly = 605 - row_index * 28
        dash = "[] 0" if marker == 0 else "[6 4] 0"
        label = f"{compact_plot_label(variant_label)} {direction}"
        canvas.line(lx, ly, lx + 24, ly, color=color, width=1.8, dash=dash)
        canvas.marker(lx + 12, ly, color=color, kind=marker, radius=3.5)
        canvas.text(
            lx + 31,
            ly - 7,
            label,
            size=LEGEND_FONT_SIZE,
            color=color,
            bold=True,
        )

    note_lines = (
        "Negative excess values are clipped to zero by the campaign pipeline.",
        "Each point is a 60 s mean at 3.3 V.",
    )
    for note_index, note_line in enumerate(note_lines):
        gray_note(canvas, note_line, 18 + note_index * 25)
    canvas.save(path)
    return normalized


def continuous_power_family_figure(
    path: Path,
    continued_path: Path,
    comparison_id: str,
    heading: str,
    subtitle: str,
    variants: Sequence[tuple[str, str]],
    mode_field: str,
    mode_value: float,
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    accepted_statuses = {"ok", "no_rx_data"}
    for variant_index, (slug, variant_label) in enumerate(variants):
        source = read_csv(COMPARISONS_DIR / slug / f"{slug}_continuous.csv")
        selected = [
            row
            for row in source
            if row.get("status") in accepted_statuses
            and row.get("measurement_direction") in {"tx", "rx"}
            and abs(number(row, mode_field) - mode_value) < 0.001
        ]
        if len(selected) != 6:
            raise ValueError(
                f"Expected 6 continuous rows for {slug} at {mode_field}={mode_value}, got {len(selected)}"
            )
        for row in selected:
            normalized.append(
                {
                    "comparison": comparison_id,
                    "slug": slug,
                    "variant": variant_label,
                    "variant_index": variant_index,
                    "direction": row["measurement_direction"],
                    "mode_field": mode_field,
                    "mode_value": mode_value,
                    "power_dbm": number(row, "tx_power_dbm"),
                    "mean_power_mW": number(row, "mean_power_mW"),
                    "mean_excess_power_mW": number(row, "mean_excess_power_mW"),
                    "baseline_mean_uA": number(row, "baseline_mean_uA"),
                    "frames_transmitted": round(number(row, "frames_transmitted")),
                    "frames_received": round(number(row, "frames_received")),
                    "status": row.get("status", ""),
                }
            )

    powers = sorted({float(row["power_dbm"]) for row in normalized})
    power_span = max(powers) - min(powers)
    x_range = (min(powers) - power_span * 0.08, max(powers) + power_span * 0.08)

    def render_sheet(
        output_path: Path,
        sheet_heading: str,
        panels: Sequence[tuple[str, str, str, str]],
    ) -> None:
        canvas = PdfCanvas(1080, 760)
        title(canvas, sheet_heading, subtitle)
        for variant_index, (_, variant_label) in enumerate(variants):
            row_index, column_index = divmod(variant_index, 2)
            lx = 78 + column_index * 500
            ly = 656 - row_index * 30
            color = PALETTE[variant_index % len(PALETTE)]
            plot_label = compact_plot_label(variant_label)
            canvas.line(lx, ly, lx + 28, ly, color=color, width=2.0)
            canvas.marker(lx + 14, ly, color=color, kind=variant_index, radius=4.3)
            canvas.text(
                lx + 38,
                ly - 7,
                plot_label,
                size=LEGEND_FONT_SIZE,
                color=color,
                bold=True,
            )

        boxes = ((120.0, 355.0, 880.0, 185.0), (120.0, 78.0, 880.0, 185.0))
        for panel_index, ((direction, metric, panel_title, panel_code), box) in enumerate(zip(panels, boxes)):
            panel_rows = [row for row in normalized if row["direction"] == direction]
            upper, ticks = linear_ticks(max(float(row[metric]) for row in panel_rows) * 1.05)
            canvas.centered_text(
                box[1] + box[3] + 12,
                f"{panel_title} [mW]",
                size=AXIS_FONT_SIZE,
                bold=True,
                left=box[0],
                width=box[2],
            )
            canvas.text(box[0] + box[2] - 18, box[1] + box[3] + 17, panel_code, size=20, bold=True)
            for tick in ticks:
                py = _map(tick, 0.0, upper, box[1], box[3], False)
                canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.6)
                canvas.text(box[0] - 66, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
            for power in powers:
                px = _map(power, *x_range, box[0], box[2], False)
                canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.5)
                canvas.text(px - 17, box[1] - 29, f"{power:g}", size=TICK_FONT_SIZE, bold=True)

            for variant_index, _ in enumerate(variants):
                rows = sorted(
                    (
                        row
                        for row in panel_rows
                        if int(row["variant_index"]) == variant_index
                    ),
                    key=lambda row: float(row["power_dbm"]),
                )
                color = PALETTE[variant_index % len(PALETTE)]
                points = [
                    (
                        _map(float(row["power_dbm"]), *x_range, box[0], box[2], False),
                        _map(float(row[metric]), 0.0, upper, box[1], box[3], False),
                    )
                    for row in rows
                ]
                canvas.polyline(points, color=color, width=2.0)
                for row, (px, py) in zip(rows, points):
                    canvas.marker(px, py, color=color, kind=variant_index, radius=4.5)
                    if row["status"] != "ok":
                        canvas.line(px - 7, py - 7, px + 7, py + 7, color=BLACK, width=1.6)
                        canvas.line(px - 7, py + 7, px + 7, py - 7, color=BLACK, width=1.6)

            canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.1)
            canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.1)
            if panel_index == len(panels) - 1:
                centered_axis_label(
                    canvas,
                    box[1] - 62,
                    "Configured RF power [dBm]",
                    left=box[0],
                    width=box[2],
                )

        canvas.save(output_path)

    render_sheet(
        path,
        heading,
        (
            ("tx", "mean_power_mW", "TX total average power", "A"),
            ("rx", "mean_power_mW", "RX total average power", "B"),
        ),
    )
    render_sheet(
        continued_path,
        f"{heading} (continued)",
        (
            ("tx", "mean_excess_power_mW", "TX mean power above standby", "C"),
            ("rx", "mean_excess_power_mW", "RX mean power above standby", "D"),
        ),
    )
    return normalized


def packet_continuous_delivery(path: Path, rows: Sequence[dict[str, object]]) -> None:
    dot_comparison(
        path,
        rows,
        "packet_delivery_percent",
        "continuous_delivery_percent",
        "Packet campaign",
        "60 s continuous",
        "Delivery ratio across campaigns",
        "Delivered frames [%]",
        "",
        log_x=False,
        expanded_layout=True,
    )


def variant_figure(path: Path, rows: Sequence[dict[str, object]]) -> None:
    slugs = {
        "ra02_sx1278",
        "ra02_sx1278_2cap",
        "sx1278_adafruit_level_shifter",
        "sx1278_naked",
        "sx1278_pcb_2cap",
        "sx1278_shielded",
    }
    selected = [row for row in rows if row["slug"] in slugs]
    dot_comparison(
        path,
        selected,
        "tx_energy_mJ",
        "rx_energy_mJ",
        "TX",
        "RX",
        "SX1278 physical-implementation comparison",
        "Packet energy [mJ]",
        "Identical 32 B, SF7/BW125/CR4/5, +20 dBm configuration",
        subtitle_font_size=23.0,
    )


def sx1276_variant_figure(path: Path, rows: Sequence[dict[str, object]]) -> None:
    expected_slugs = {spec.slug for spec in MODULES if spec.chip.startswith("SX1276")}
    selected = [row for row in rows if str(row["chip"]).startswith("SX1276")]
    selected_slugs = {str(row["slug"]) for row in selected}
    if selected_slugs != expected_slugs:
        raise ValueError(
            "SX1276 figure/catalog mismatch: "
            f"expected {sorted(expected_slugs)}, selected {sorted(selected_slugs)}"
        )
    dot_comparison(
        path,
        selected,
        "tx_energy_mJ",
        "rx_energy_mJ",
        "TX",
        "RX",
        "SX1276-based module comparison",
        "Packet energy [mJ]",
        "32 B canonical points; direct-SPI pair is matched, E32 modules use transparent UART/FEC",
    )


def nrf_figure(path: Path, packet_data: dict[str, list[dict[str, str]]]) -> None:
    canvas = PdfCanvas(1080, 600)
    title(canvas, "NRF24L01 module versus PA/LNA variant", "32-byte TX packet at 0 dBm radio drive; auto-ack disabled")
    box = (120.0, 105.0, 850.0, 400.0)
    rates = (250.0, 1000.0, 2000.0)
    all_values: list[float] = []
    series: list[tuple[str, list[tuple[float, float]], tuple[float, float, float], int]] = []
    for index, (slug, label, color) in enumerate(
        (
            ("nrf24l01", module_name("nrf24l01"), BLUE),
            ("nrf24l01_pa", module_name("nrf24l01_pa"), RED),
        )
    ):
        points = []
        for rate in rates:
            row = next(
                item
                for item in packet_data[slug]
                if item.get("measurement_direction") == "tx"
                and number(item, "payload_bytes") == 32
                and number(item, "tx_power_dbm") == 0
                and field_rate(item) == rate
            )
            energy = number(row, "energy_total_mJ_mean")
            all_values.append(energy)
            points.append((rate, energy))
        series.append((label, points, color, index))
    x_range = (200.0, 2500.0)
    y_range = (min(all_values) * 0.65, max(all_values) * 1.55)
    for tick in rates:
        px = _map(tick, *x_range, box[0], box[2], True)
        canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.7)
        canvas.text(px - 28, box[1] - 30, f"{tick:g}", size=TICK_FONT_SIZE, bold=True)
    for tick in log_ticks(*y_range):
        py = _map(tick, *y_range, box[1], box[3], True)
        canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.7)
        canvas.text(box[0] - 64, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    for label, points, color, marker in series:
        mapped = [(_map(x, *x_range, box[0], box[2], True), _map(y, *y_range, box[1], box[3], True)) for x, y in points]
        canvas.polyline(mapped, color=color, width=2)
        for px, py in mapped:
            canvas.marker(px, py, color=color, kind=marker, radius=5)
        legend_x = 220 + marker * 440
        canvas.line(legend_x, 516, legend_x + 28, 516, color=color, width=2)
        canvas.marker(legend_x + 14, 516, color=color, kind=marker, radius=4)
        plot_label = compact_plot_label(label)
        canvas.text(
            legend_x + 35,
            508,
            plot_label,
            size=LEGEND_FONT_SIZE,
            bold=True,
        )
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.2)
    canvas.centered_text(
        42,
        "Configured rate [kbps]",
        size=AXIS_FONT_SIZE,
        bold=True,
        left=box[0],
        width=box[2],
    )
    canvas.centered_text(
        505,
        "TX energy [mJ]",
        size=AXIS_FONT_SIZE,
        bold=True,
        left=box[0],
        width=box[2],
    )
    canvas.save(path)


def e79_figure(path: Path, packet_data: dict[str, list[dict[str, str]]]) -> list[dict[str, object]]:
    rows = [
        row
        for row in packet_data["ebyte_e79_400dm2005s"]
        if row.get("measurement_direction") == "tx"
        and number(row, "payload_bytes") == 32
        and number(row, "tx_power_dbm") == 13
    ]
    profiles = []
    for row in rows:
        energy = number(row, "energy_total_mJ_mean")
        profiles.append(
            {
                "profile": row.get("rf_profile", ""),
                "rate_kbps": field_rate(row),
                "tx_energy_mJ": energy,
                "energy_per_bit_uJ": energy * 1000.0 / 256.0,
                "duration_ms": number(row, "event_duration_ms_mean"),
                "packet_delivery": number(row, "packets_received") / max(1.0, number(row, "runs")) * 100.0,
            }
        )
    profiles.sort(key=lambda row: (float(row["rate_kbps"]), str(row["profile"])))
    canvas = PdfCanvas(1080, 610)
    title(canvas, "E79 multi-PHY energy frontier", "32-byte TX packet at +13 dBm; same module, firmware and supply")
    box = (110.0, 100.0, 850.0, 420.0)
    xs = [float(row["rate_kbps"]) for row in profiles]
    ys = [float(row["tx_energy_mJ"]) for row in profiles]
    x_range = (min(xs) * 0.7, max(xs) * 1.4)
    y_range = (min(ys) * 0.7, max(ys) * 1.5)
    for tick in log_ticks(*x_range):
        px = _map(tick, *x_range, box[0], box[2], True)
        canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.7)
        canvas.text(px - 18, box[1] - 30, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    for tick in log_ticks(*y_range):
        py = _map(tick, *y_range, box[1], box[3], True)
        canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.7)
        canvas.text(box[0] - 64, py - 6, fmt_tick(tick), size=TICK_FONT_SIZE, bold=True)
    plotted = []
    for index, row in enumerate(profiles):
        px = _map(float(row["rate_kbps"]), *x_range, box[0], box[2], True)
        py = _map(float(row["tx_energy_mJ"]), *y_range, box[1], box[3], True)
        color = PALETTE[index % len(PALETTE)]
        canvas.marker(px, py, color=color, kind=index, radius=6)
        plotted.append((index, row, px, py, color))
    profile_offsets = {
        "SLR2K5": (8.0, -22.0),
        "OOK4K8": (-108.0, -22.0),
        "GFSK4K8": (10.0, 18.0),
        "SLR5": (18.0, -28.0),
        "GFSK50": (-108.0, -22.0),
        "IEEE154G50": (10.0, 12.0),
        "GFSK200": (-112.0, -22.0),
    }
    for _, row, px, py, color in plotted:
        dx, dy = profile_offsets[str(row["profile"])]
        canvas.text(px + dx, py + dy, str(row["profile"]), size=LEGEND_FONT_SIZE, bold=True, color=color)
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.2)
    canvas.text(325, 39, "Configured PHY rate [kbps]", size=AXIS_FONT_SIZE, bold=True)
    canvas.text(110, 522, "32-byte TX energy [mJ]", size=AXIS_FONT_SIZE, bold=True)
    canvas.save(path)
    return profiles


def e79_interface_figure(
    path: Path,
    rows: Sequence[dict[str, object]],
) -> None:
    profile_order = (
        "SLR2K5",
        "GFSK4K8",
        "OOK4K8",
        "SLR5",
        "GFSK50",
        "IEEE154G50",
        "GFSK200",
    )
    profile_index = {profile: index for index, profile in enumerate(profile_order)}
    selected = []
    for row in rows:
        if (
            int(row["payload_bytes"]) == 32
            and math.isclose(float(row["power_dbm"]), 13.0)
        ):
            selected.append({**row, "profile_index": profile_index[str(row["profile"])]})
    stacked_packet_series_figure(
        path,
        selected,
        "E79 interface-context comparison",
        "Same CC1352P matrix point: 32-byte packet, +13 dBm; converter power is outside the PPK2 boundary",
        ("ESP32 bridge", "CH9340C"),
        "profile_index",
        tuple(float(index) for index in range(len(profile_order))),
        profile_order,
        "RF profile",
        False,
    )


def e07_figures(
    payload_path: Path,
    rate_path: Path,
    rows: Sequence[dict[str, object]],
) -> None:
    series = tuple(
        module_name(slug)
        for slug in (
            "ebyte_e07_400m10s",
            "ebyte_e07_433m20s",
            "ebyte_e07_900mm10s",
        )
    )
    stacked_packet_series_figure(
        payload_path,
        [row for row in rows if row["comparison"] == "payload"],
        "E07 family: packet energy versus payload",
        "Controlled GFSK point: 38.4 kbps, -30 dBm; all measured packets delivered",
        series,
        "payload_bytes",
        (8.0, 32.0, 64.0),
        ("8", "32", "64"),
        "Logical payload [bytes]",
        True,
    )
    stacked_packet_series_figure(
        rate_path,
        [row for row in rows if row["comparison"] == "rate"],
        "E07 family: packet energy versus rate",
        "Controlled 32-byte point at -30 dBm; all measured packets delivered",
        series,
        "rate_kbps",
        (1.2, 38.4, 250.0),
        ("1.2", "38.4", "250"),
        "Configured rate [kbps]",
        True,
    )


def cc1101_family_figure(
    path: Path,
    rows: Sequence[dict[str, object]],
) -> None:
    stacked_packet_series_figure(
        path,
        rows,
        "CC1101 and E07 module-boundary comparison",
        "Common point: 32-byte packet, 38.4 kbps; E07-433 includes its external PA/LNA",
        (
            module_name("cc1101_v1_433"),
            module_name("cc1101_v2_868"),
            module_name("ebyte_e07_400m10s"),
            module_name("ebyte_e07_433m20s"),
            module_name("ebyte_e07_900mm10s"),
        ),
        "power_dbm",
        (-30.0, 0.0, 10.0),
        ("-30", "0", "+10"),
        "Configured CC1101 drive [dBm]",
        False,
    )


def ra_modem_figures(
    payload_path: Path,
    sf_path: Path,
    rows: Sequence[dict[str, object]],
) -> None:
    series = (module_name("ra08_asr6601"), module_name("ra09_stm32wle5"))
    stacked_packet_series_figure(
        payload_path,
        [row for row in rows if row["comparison"] == "payload"],
        "Ai-Thinker RA-08 (ASR6601) versus Ai-Thinker RA-09 (STM32WLE5): energy versus payload",
        "Matched LoRa point: SF7/BW125/CR4/5 and +22 dBm",
        series,
        "payload_bytes",
        (8.0, 32.0, 128.0),
        ("8", "32", "128"),
        "Logical payload [bytes]",
        True,
    )
    stacked_packet_series_figure(
        sf_path,
        [row for row in rows if row["comparison"] == "spreading_factor"],
        "Ai-Thinker RA-08 (ASR6601) versus Ai-Thinker RA-09 (STM32WLE5): energy versus SF",
        "Matched 32-byte LoRa point at BW125/CR4/5 and +22 dBm",
        series,
        "spreading_factor",
        (7.0, 9.0, 12.0),
        ("SF7", "SF9", "SF12"),
        "LoRa spreading factor",
        False,
    )


def write_findings(
    summary: Sequence[dict[str, object]],
    e79_profiles: Sequence[dict[str, object]],
    e79_interface_rows: Sequence[dict[str, object]],
    e07_rows: Sequence[dict[str, object]],
    ra_rows: Sequence[dict[str, object]],
) -> None:
    by_energy = sorted(summary, key=lambda row: float(row["tx_energy_mJ"]))
    continuous_summary = [row for row in summary if row["continuous_available"]]
    by_rx = sorted(continuous_summary, key=lambda row: float(row["continuous_rx_power_mW"]))
    by_tx_power = sorted(continuous_summary, key=lambda row: float(row["continuous_tx_power_mW"]))
    by_goodput = sorted(continuous_summary, key=lambda row: float(row["continuous_goodput_kbps"]), reverse=True)
    best_e79 = min(e79_profiles, key=lambda row: float(row["tx_energy_mJ"]))
    slow_e79 = next(row for row in e79_profiles if row["profile"] == "SLR2K5")
    fast_e79 = next(row for row in e79_profiles if row["profile"] == "GFSK200")

    interface_matrix = {
        (
            str(row["series"]),
            str(row["direction"]),
            int(row["payload_bytes"]),
            str(row["profile"]),
            float(row["power_dbm"]),
        ): row
        for row in e79_interface_rows
    }
    interface_ratios: dict[str, list[float]] = {"tx": [], "rx": []}
    for key, old_row in interface_matrix.items():
        setup, direction, payload, profile, power = key
        if setup != "ESP32 bridge":
            continue
        new_row = interface_matrix.get(
            ("CH9340C", direction, payload, profile, power)
        )
        if new_row:
            interface_ratios[direction].append(
                float(new_row["energy_mJ"]) / float(old_row["energy_mJ"])
            )

    def selected_value(
        rows: Sequence[dict[str, object]],
        *,
        series: str,
        comparison: str,
        direction: str,
        payload: int,
        power: float,
        rate: float | None = None,
        sf: int | None = None,
    ) -> float:
        return float(
            next(
                row["energy_mJ"]
                for row in rows
                if row["series"] == series
                and row["comparison"] == comparison
                and row["direction"] == direction
                and int(row["payload_bytes"]) == payload
                and math.isclose(float(row["power_dbm"]), power)
                and (rate is None or math.isclose(float(row["rate_kbps"]), rate))
                and (sf is None or int(row["spreading_factor"]) == sf)
            )
        )

    e07_values = {
        (series, direction): selected_value(
            e07_rows,
            series=series,
            comparison="rate",
            direction=direction,
            payload=32,
            power=-30.0,
            rate=38.4,
        )
        for series in (
            module_name("ebyte_e07_400m10s"),
            module_name("ebyte_e07_433m20s"),
            module_name("ebyte_e07_900mm10s"),
        )
        for direction in ("tx", "rx")
    }
    ra_values = {
        (series, direction): selected_value(
            ra_rows,
            series=series,
            comparison="spreading_factor",
            direction=direction,
            payload=32,
            power=22.0,
            sf=7,
        )
        for series in (module_name("ra08_asr6601"), module_name("ra09_stm32wle5"))
        for direction in ("tx", "rx")
    }
    macro_lines = [
        "% Generated by generate_study.py; do not edit by hand.",
        f"\\newcommand{{\\TotalModules}}{{{len(summary)}}}",
        f"\\newcommand{{\\TotalContinuousModules}}{{{len(continuous_summary)}}}",
        f"\\newcommand{{\\BestPacketEnergyModule}}{{{latex_escape(by_energy[0]['label'])}}}",
        f"\\newcommand{{\\BestPacketEnergy}}{{{fmt(by_energy[0]['tx_energy_mJ'])}}}",
        f"\\newcommand{{\\WorstPacketEnergyModule}}{{{latex_escape(by_energy[-1]['label'])}}}",
        f"\\newcommand{{\\WorstPacketEnergy}}{{{fmt(by_energy[-1]['tx_energy_mJ'])}}}",
        f"\\newcommand{{\\LowestRxModule}}{{{latex_escape(by_rx[0]['label'])}}}",
        f"\\newcommand{{\\LowestRxPower}}{{{fmt(by_rx[0]['continuous_rx_power_mW'])}}}",
        f"\\newcommand{{\\LowestTxModule}}{{{latex_escape(by_tx_power[0]['label'])}}}",
        f"\\newcommand{{\\LowestTxPower}}{{{fmt(by_tx_power[0]['continuous_tx_power_mW'])}}}",
        f"\\newcommand{{\\HighestGoodputModule}}{{{latex_escape(by_goodput[0]['label'])}}}",
        f"\\newcommand{{\\HighestGoodput}}{{{fmt(by_goodput[0]['continuous_goodput_kbps'])}}}",
        f"\\newcommand{{\\BestESeventyNineProfile}}{{{latex_escape(best_e79['profile'])}}}",
        f"\\newcommand{{\\BestESeventyNineEnergy}}{{{fmt(best_e79['tx_energy_mJ'])}}}",
        f"\\newcommand{{\\ESeventyNineSlowEnergy}}{{{fmt(slow_e79['tx_energy_mJ'])}}}",
        f"\\newcommand{{\\ESeventyNineFastEnergy}}{{{fmt(fast_e79['tx_energy_mJ'])}}}",
        f"\\newcommand{{\\ESeventyNineImprovement}}{{{float(slow_e79['tx_energy_mJ']) / float(fast_e79['tx_energy_mJ']):.1f}}}",
        f"\\newcommand{{\\ESeventyNineInterfaceTxRatio}}{{{statistics.median(interface_ratios['tx']):.3f}}}",
        f"\\newcommand{{\\ESeventyNineInterfaceRxRatio}}{{{statistics.median(interface_ratios['rx']):.3f}}}",
        f"\\newcommand{{\\ESevenFourTx}}{{{fmt(e07_values[(module_name('ebyte_e07_400m10s'), 'tx')])}}}",
        f"\\newcommand{{\\ESevenFourRx}}{{{fmt(e07_values[(module_name('ebyte_e07_400m10s'), 'rx')])}}}",
        f"\\newcommand{{\\ESevenFourThreeTx}}{{{fmt(e07_values[(module_name('ebyte_e07_433m20s'), 'tx')])}}}",
        f"\\newcommand{{\\ESevenFourThreeRx}}{{{fmt(e07_values[(module_name('ebyte_e07_433m20s'), 'rx')])}}}",
        f"\\newcommand{{\\ESevenNineTx}}{{{fmt(e07_values[(module_name('ebyte_e07_900mm10s'), 'tx')])}}}",
        f"\\newcommand{{\\ESevenNineRx}}{{{fmt(e07_values[(module_name('ebyte_e07_900mm10s'), 'rx')])}}}",
        f"\\newcommand{{\\RAEightTx}}{{{fmt(ra_values[(module_name('ra08_asr6601'), 'tx')])}}}",
        f"\\newcommand{{\\RAEightRx}}{{{fmt(ra_values[(module_name('ra08_asr6601'), 'rx')])}}}",
        f"\\newcommand{{\\RANineTx}}{{{fmt(ra_values[(module_name('ra09_stm32wle5'), 'tx')])}}}",
        f"\\newcommand{{\\RANineRx}}{{{fmt(ra_values[(module_name('ra09_stm32wle5'), 'rx')])}}}",
        f"\\newcommand{{\\TotalPacketRuns}}{{{sum(int(row['packet_campaign_runs']) for row in summary)}}}",
        f"\\newcommand{{\\TotalPacketEvaluated}}{{{sum(int(row['packet_attempted']) for row in summary)}}}",
        f"\\newcommand{{\\TotalPacketPoints}}{{{sum(int(row['packet_points']) for row in summary)}}}",
        f"\\newcommand{{\\TotalPacketReceived}}{{{sum(int(row['packet_received']) for row in summary)}}}",
        f"\\newcommand{{\\TotalContinuousWindows}}{{{sum(int(row['continuous_windows']) for row in summary)}}}",
        f"\\newcommand{{\\TotalContinuousSent}}{{{sum(int(row['continuous_attempted']) for row in summary)}}}",
        f"\\newcommand{{\\TotalContinuousReceived}}{{{sum(int(row['continuous_received']) for row in summary)}}}",
    ]
    (STUDY_DIR / "generated_findings.tex").write_text("\n".join(macro_lines) + "\n", encoding="utf-8")


def main() -> int:
    for folder in (STUDY_DIR / "data", STUDY_DIR / "figures", STUDY_DIR / "tables"):
        folder.mkdir(parents=True, exist_ok=True)
    summary, packet_data = load_summary()
    continuous_summary = [row for row in summary if row["continuous_available"]]
    payload_rows, payload_sizes = build_payload_summary(packet_data)
    cc1101_rows = build_cc1101_comparison(packet_data)
    e07_rows = build_e07_comparison(packet_data)
    cc1101_family_rows = build_cc1101_family_comparison(packet_data)
    e79_interface_rows = build_e79_interface_comparison(packet_data)
    ra_modem_rows = build_ra_modem_comparison(packet_data)
    write_csv(STUDY_DIR / "data" / "module_catalog.csv", [asdict(spec) for spec in MODULES])
    write_csv(STUDY_DIR / "data" / "module_summary.csv", summary)
    write_csv(STUDY_DIR / "data" / "payload_energy_summary.csv", payload_rows)
    write_csv(STUDY_DIR / "data" / "cc1101_controlled_summary.csv", cc1101_rows)
    write_csv(STUDY_DIR / "data" / "e07_controlled_summary.csv", e07_rows)
    write_csv(STUDY_DIR / "data" / "cc1101_family_summary.csv", cc1101_family_rows)
    write_csv(STUDY_DIR / "data" / "e79_interface_summary.csv", e79_interface_rows)
    write_csv(STUDY_DIR / "data" / "ra08_ra09_summary.csv", ra_modem_rows)
    write_tables(summary, payload_rows, payload_sizes)
    figures = STUDY_DIR / "figures"
    dot_comparison(
        figures / "packet_energy_comparison.pdf",
        summary,
        "tx_energy_mJ",
        "rx_energy_mJ",
        "TX",
        "RX",
        "Packet energy across all measured modules",
        "Energy for one 32-byte payload [mJ]",
        "",
        expanded_layout=True,
        expanded_plot_height=1220.0,
    )
    dot_comparison(
        figures / "continuous_power_comparison.pdf",
        continuous_summary,
        "continuous_tx_power_mW",
        "continuous_rx_power_mW",
        "TX",
        "RX",
        "Continuous average power",
        "Average module power at 3.3 V [mW]",
        "",
        expanded_layout=True,
        expanded_plot_left=470.0,
    )
    scatter_rate_energy(figures / "rate_energy_design_space.pdf", summary)
    payload_energy_figure(figures / "tx_energy_by_payload.pdf", payload_rows, payload_sizes, "tx")
    payload_energy_figure(figures / "rx_energy_by_payload.pdf", payload_rows, payload_sizes, "rx")
    packet_continuous_delivery(figures / "delivery_comparison.pdf", continuous_summary)
    variant_figure(figures / "sx1278_variant_comparison.pdf", summary)
    sx1276_variant_figure(figures / "sx1276_variant_comparison.pdf", summary)
    nrf_figure(figures / "nrf24_pa_comparison.pdf", packet_data)
    e79_profiles = e79_figure(figures / "e79_profile_frontier.pdf", packet_data)
    e79_interface_figure(
        figures / "e79_interface_comparison.pdf",
        e79_interface_rows,
    )
    e07_figures(
        figures / "e07_payload_comparison.pdf",
        figures / "e07_rate_comparison.pdf",
        e07_rows,
    )
    cc1101_family_figure(
        figures / "cc1101_e07_power_comparison.pdf",
        cc1101_family_rows,
    )
    ra_modem_figures(
        figures / "ra08_ra09_payload_comparison.pdf",
        figures / "ra08_ra09_sf_comparison.pdf",
        ra_modem_rows,
    )
    cc1101_continuous_figure(figures / "cc1101_continuous_power_comparison.pdf", cc1101_rows)
    cc1101_packet_figure(figures / "cc1101_packet_comparison.pdf", cc1101_rows)
    matched_continuous_rows: list[dict[str, object]] = []
    matched_continuous_rows.extend(
        continuous_power_pair_figure(
            figures / "e32_band_continuous_power_comparison.pdf",
            "e32_band",
            "Ebyte E32-433T20D versus Ebyte E32-868T20D",
            "Matched 60 s workload: 58-byte frames, 4.8 kbps, 15 ms host gap, 3.3 V",
            (
                ("ebyte_e32_433t20d", module_name("ebyte_e32_433t20d")),
                ("ebyte_e32_868t20d", module_name("ebyte_e32_868t20d")),
            ),
            "bit_rate_kbps",
            4.8,
        )
    )
    matched_continuous_rows.extend(
        continuous_power_pair_figure(
            figures / "nrf24_pa_continuous_power_comparison.pdf",
            "nrf24_pa",
            "NRF24L01 versus NRF24L01 PA/LNA",
            "Matched 60 s workload: 32-byte frames, 1 Mbps, 15 ms host gap, 3.3 V",
            (
                ("nrf24l01", module_name("nrf24l01")),
                ("nrf24l01_pa", module_name("nrf24l01_pa")),
            ),
            "bit_rate_kbps",
            1000.0,
        )
    )
    matched_continuous_rows.extend(
        continuous_power_family_figure(
            figures / "sx1278_continuous_power_comparison.pdf",
            figures / "sx1278_continuous_power_comparison_continued.pdf",
            "sx1278_implementations",
            "SX1278 physical-implementation comparison",
            "Matched 60 s workload: 32-byte frames, SF9/BW125, 15 ms host gap, 3.3 V",
            (
                ("ra02_sx1278", module_name("ra02_sx1278")),
                ("ra02_sx1278_2cap", module_name("ra02_sx1278_2cap")),
                (
                    "sx1278_adafruit_level_shifter",
                    module_name("sx1278_adafruit_level_shifter"),
                ),
                ("sx1278_naked", module_name("sx1278_naked")),
                ("sx1278_pcb_2cap", module_name("sx1278_pcb_2cap")),
                ("sx1278_shielded", module_name("sx1278_shielded")),
            ),
            "spreading_factor",
            9.0,
        )
    )
    matched_continuous_rows.extend(
        continuous_power_pair_figure(
            figures / "sx1276_continuous_power_comparison.pdf",
            "sx1276_implementations",
            "SX1276 direct-SPI continuous comparison",
            "SF9/BW125, 32-byte frames, 15 ms host gap; low-power endpoints differ",
            (
                ("ra01h_sx1276", module_name("ra01h_sx1276")),
                ("xl1276_d01_sx1276", module_name("xl1276_d01_sx1276")),
            ),
            "spreading_factor",
            9.0,
        )
    )
    write_csv(STUDY_DIR / "data" / "e79_profile_summary.csv", e79_profiles)
    write_csv(STUDY_DIR / "data" / "matched_continuous_power_summary.csv", matched_continuous_rows)
    write_findings(
        summary,
        e79_profiles,
        e79_interface_rows,
        e07_rows,
        ra_modem_rows,
    )
    print(
        f"Generated {len(summary)} module summaries, {len(payload_rows)} payload-energy rows, "
        f"{len(cc1101_rows)} controlled CC1101 points, {len(matched_continuous_rows)} matched "
        f"continuous-power points, and 22 numbered figures across 27 plot sheets in {STUDY_DIR}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
