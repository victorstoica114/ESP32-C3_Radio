from __future__ import annotations

import csv
import math
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
    ModuleSpec("cc1101_v1_433", "C11-433", "CC1101 V1 433 MHz", "CC1101", "433 MHz", "SPI", "2-FSK", "1.2/38.4/250 kbps", "-30/0/10 dBm", "Narrowband FSK"),
    ModuleSpec("cc1101_v2_868", "C11-868", "CC1101 V2 868 MHz", "CC1101", "868 MHz", "SPI", "2-FSK", "1.2/38.4/250 kbps", "-30/0/10 dBm", "Narrowband FSK"),
    ModuleSpec("e28_sx1280", "E28", "E28 direct SPI", "SX1280", "2.4 GHz", "SPI", "LoRa, CR 4/6", "SF5/8/12, BW 812.5 kHz", "-18/0/13 dBm", "LoRa 2.4 GHz"),
    ModuleSpec("e280", "E280", "Ebyte E280-2G4T12S", "SX1280", "2.4 GHz", "UART", "Vendor transparent PHY", "1/100/2000 kbps presets", "4/7/12 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e22_400m30s", "E22", "Ebyte E22-400M30S", "SX1268 + PA", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-9/10/18 dBm front stage", "LoRa sub-GHz"),
    ModuleSpec("ebyte_e32_433t20d", "E32-43-20", "Ebyte E32-433T20D", "SX1278", "433 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "10/14/20 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e32_433t33d", "E32-43-33", "Ebyte E32-433T33D", "SX1278 + PA", "433 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "24/27/30 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e32_868t20d", "E32-86-20", "Ebyte E32-868T20D", "SX1276", "868 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "10/14/20 dBm", "Transparent UART"),
    ModuleSpec("ebyte_e32_868t30d", "E32-86-30", "Ebyte E32-868T30D", "SX1276 + PA", "868 MHz", "UART", "LoRa transparent, FEC", "0.3/4.8/19.2 kbps", "21/27/30 dBm", "Transparent UART", "Legacy accepted"),
    ModuleSpec("ebyte_e79_400dm2005s", "E79", "Ebyte E79-400DM2005S", "CC1352P", "433 MHz", "UART AT", "2-GFSK, OOK, SLR, 802.15.4g", "2.5--200 kbps (7 PHYs)", "-20/0/13 dBm", "Multi-PHY sub-GHz"),
    ModuleSpec("hc12", "HC-12", "HC-12", "Si4463", "433 MHz", "UART", "Transparent (G)FSK", "0.5/15/250 kbps presets", "-1/8/20 dBm", "Transparent UART"),
    ModuleSpec("nrf24l01", "NRF", "nRF24L01", "nRF24L01+", "2.4 GHz", "SPI", "GFSK, ESB framing", "250/1000/2000 kbps", "-18/-6/0 dBm", "2.4 GHz GFSK"),
    ModuleSpec("nrf24l01_pa", "NRF-PA", "nRF24L01+PA/LNA", "nRF24L01+ + PA/LNA", "2.4 GHz", "SPI", "GFSK, ESB framing", "250/1000/2000 kbps", "-18/-6/0 dBm drive", "2.4 GHz GFSK"),
    ModuleSpec("ra01h_sx1276", "RA-01H", "Ai-Thinker RA-01H", "SX1276", "868 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "2/10/20 dBm", "LoRa sub-GHz"),
    ModuleSpec("ra01sh_sx1262", "RA-01SH", "Ai-Thinker RA-01SH", "SX1262", "868 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-9/10/22 dBm", "LoRa sub-GHz"),
    ModuleSpec("ra02_sx1278", "RA-02", "Ai-Thinker RA-02", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("ra02_sx1278_2cap", "RA-02-2C", "Ai-Thinker RA-02 + 2 capacitors", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("ra08_asr6601", "RA-08", "Ai-Thinker RA-08", "ASR6601", "433 MHz", "UART AT", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "2/12/22 dBm", "LoRa SoC modem"),
    ModuleSpec("sx1278_adafruit_level_shifter", "S1278-LS", "SX1278 + level shifter", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant", "Accepted; no validation memo"),
    ModuleSpec("sx1278_naked", "S1278-N", "SX1278 naked board", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("sx1278_pcb_2cap", "S1278-2C", "SX1278 PCB + 2 capacitors", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("sx1278_shielded", "S1278-S", "SX1278 shielded board", "SX1278", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "SX1278 variant"),
    ModuleSpec("xl1276_d01_sx1276", "XL1276", "XL1276-D01", "SX1276", "433 MHz", "SPI", "LoRa, CR 4/5", "SF7/9/12, BW 125 kHz", "-4/10/20 dBm", "LoRa sub-GHz"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


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
    if row.get("air_rate"):
        return row["air_rate"]
    return f"{field_rate(row):g} kbps"


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
        ("cc1101_v1_433", "V1 433 MHz"),
        ("cc1101_v2_868", "V2 868 MHz"),
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
        folder = COMPARISONS_DIR / spec.slug
        packets = read_csv(folder / f"{spec.slug}_data.csv")
        continuous = read_csv(folder / f"{spec.slug}_continuous.csv")
        packet_data[spec.slug] = packets
        tx = choose_packet(packets, spec, "tx")
        rx = choose_packet(packets, spec, "rx")
        ctx = choose_continuous(continuous, spec, "tx")
        crx = matching_continuous_rx(continuous, spec, ctx)
        received, attempted, packet_percent, packet_scope = packet_delivery(packets)
        c_received, c_attempted, continuous_percent = continuous_delivery(continuous)
        payload = number(tx, "payload_bytes")
        tx_energy = number(tx, "energy_total_mJ_mean")
        rx_energy = number(rx, "energy_total_mJ_mean")
        summary.append(
            {
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
                "continuous_rate_kbps": configured_rate(ctx, spec),
                "continuous_mode": ctx.get("rf_profile") or (f"SF{number(ctx, 'spreading_factor'):g}" if number(ctx, "spreading_factor") else f"{field_rate(ctx):g} kbps"),
                "continuous_power_dbm": number(ctx, "tx_power_dbm"),
                "continuous_tx_power_mW": number(ctx, "mean_power_mW"),
                "continuous_rx_power_mW": number(crx, "mean_power_mW"),
                "continuous_goodput_kbps": goodput_kbps(crx),
                "packet_received": received,
                "packet_attempted": attempted,
                "packet_campaign_runs": sum(round(number(row, "runs")) for row in packets),
                "packet_points": len(packets),
                "packet_delivery_scope": packet_scope,
                "packet_delivery_percent": packet_percent,
                "continuous_received": c_received,
                "continuous_attempted": c_attempted,
                "continuous_delivery_percent": continuous_percent,
                "continuous_non_ok": sum(1 for row in continuous if row.get("status") != "ok"),
                "continuous_windows": len(continuous),
            }
        )
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
        r"\begin{longtable}{@{}p{0.065\linewidth}p{0.17\linewidth}p{0.105\linewidth}p{0.065\linewidth}p{0.065\linewidth}p{0.17\linewidth}p{0.14\linewidth}p{0.12\linewidth}@{}}",
        r"\caption{Measured module and hardware-variant catalog. Rates and powers are the settings exercised in this campaign, not the full capabilities of each chipset.}\label{tab:catalog}\\",
        r"\toprule",
        r"ID & Module/variant & Radio IC & Band & I/F & Tested PHY/modulation & Tested rates & Tested power \\ \midrule",
        r"\endfirsthead",
        r"\toprule ID & Module/variant & Radio IC & Band & I/F & Tested PHY/modulation & Tested rates & Tested power \\ \midrule",
        r"\endhead",
    ]
    for row in summary:
        catalog_lines.append(
            " & ".join(
                latex_escape(row[key])
                for key in ("code", "label", "chip", "band", "interface", "modulation", "configured_rates", "tested_powers")
            )
            + r" \\"
        )
    catalog_lines.extend((r"\bottomrule", r"\end{longtable}"))
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
        column_spec = "@{}llr" + "r" * len(payload_sizes) + "@{}"
        header = "ID & Mode & dBm & " + " & ".join(str(size) for size in payload_sizes) + r" \\"
        units = r" & & & " + " & ".join("[mJ]" for _ in payload_sizes) + r" \\ \midrule"
        matrix_lines = [
            rf"\begin{{longtable}}{{{column_spec}}}",
            rf"\caption{{Measured {direction_name} energy per logical packet at each module's fastest tested mode and highest tested configured power. Payload columns are bytes; a dash means that payload size was not measured.}}\label{{{label}}}\\",
            r"\toprule",
            header,
            units,
            r"\endfirsthead",
            r"\toprule",
            header + r" \midrule",
            r"\endhead",
        ]
        for module in summary:
            values = []
            for payload_bytes in payload_sizes:
                point = matrix.get((str(module["slug"]), direction, payload_bytes))
                values.append(fmt(point["energy_mJ"]) if point else r"\textemdash")
            matrix_lines.append(
                f"{latex_escape(module['code'])} & {latex_escape(module['canonical_mode'])} & "
                f"{fmt(module['canonical_power_dbm'])} & " + " & ".join(values) + r" \\"
            )
        matrix_lines.extend((r"\bottomrule", r"\end{longtable}"))
        (tables / filename).write_text("\n".join(matrix_lines) + "\n", encoding="utf-8")

    benchmark_lines = [
        r"\begin{longtable}{@{}llrrrrrrr@{}}",
        r"\caption{Sustained-traffic and delivery benchmark. Continuous values use the fastest mode available in each 60-second campaign. PDR and CDR aggregate the complete packet and continuous matrices, respectively.}\label{tab:benchmark}\\",
        r"\toprule",
        r"ID & Mode & Rate & dBm & $P_{TX}$ & $P_{RX}$ & Goodput & PDR & CDR \\",
        r" & & [kbps] & & [mW] & [mW] & [kbps] & [\%] & [\%] \\ \midrule",
        r"\endfirsthead",
        r"\toprule ID & Mode & Rate & dBm & $P_{TX}$ & $P_{RX}$ & Goodput & PDR & CDR \\ \midrule",
        r"\endhead",
    ]
    for row in summary:
        benchmark_lines.append(
            f"{latex_escape(row['code'])} & {latex_escape(row['continuous_mode'])} & {fmt(row['continuous_rate_kbps'])} & "
            f"{fmt(row['continuous_power_dbm'])} & {fmt(row['continuous_tx_power_mW'])} & "
            f"{fmt(row['continuous_rx_power_mW'])} & {fmt(row['continuous_goodput_kbps'])} & "
            f"{float(row['packet_delivery_percent']):.1f} & "
            f"{float(row['continuous_delivery_percent']):.1f} \\\\"
        )
    benchmark_lines.extend((r"\bottomrule", r"\end{longtable}"))
    (tables / "benchmark_summary.tex").write_text("\n".join(benchmark_lines) + "\n", encoding="utf-8")


def title(canvas: PdfCanvas, value: str, subtitle: str = "") -> None:
    size = min(17.0, (canvas.width - 50) / max(1.0, len(value) * 0.58))
    canvas.text(max(25.0, (canvas.width - len(value) * size * 0.58) / 2.0), canvas.height - 35, value, size=size, bold=True)
    if subtitle:
        sub_size = min(9.0, (canvas.width - 50) / max(1.0, len(subtitle) * 0.58))
        canvas.text(max(25.0, (canvas.width - len(subtitle) * sub_size * 0.58) / 2.0), canvas.height - 56, subtitle, size=sub_size, color=GRAY)


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
) -> None:
    ordered = sorted(rows, key=lambda row: max(float(row[left_key]), float(row[right_key])))
    canvas = PdfCanvas(1080, 760)
    title(canvas, heading, subtitle)
    box = (190.0, 75.0, 830.0, 585.0)
    values = [float(row[key]) for row in ordered for key in (left_key, right_key) if float(row[key]) > 0]
    low = min(values) * (0.72 if log_x else 0.0)
    high = max(values) * 1.28
    if not log_x:
        low = 0.0
        if unit.endswith("[%]"):
            high = 100.0
    ticks = log_ticks(low, high) if log_x else [high * index / 5.0 for index in range(6)]
    for tick in ticks:
        px = _map(tick, low, high, box[0], box[2], log_x)
        canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.7)
        canvas.text(px - 10, box[1] - 21, fmt_tick(tick), size=8)
    for index, row in enumerate(ordered):
        py = box[1] + (index + 0.5) * box[3] / len(ordered)
        canvas.text(20, py - 3, str(row["code"]), size=8, bold=True)
        first = _map(float(row[left_key]), low, high, box[0], box[2], log_x)
        second = _map(float(row[right_key]), low, high, box[0], box[2], log_x)
        canvas.line(first, py, second, py, color=GRAY, width=1.2)
        canvas.marker(first, py, color=BLUE, kind=2, radius=4)
        canvas.marker(second, py, color=RED, kind=0, radius=4)
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.text(460, 35, unit, size=9, bold=True)
    canvas.marker(420, 678, color=BLUE, kind=2, radius=4)
    canvas.text(430, 674, left_label, size=9)
    canvas.marker(620, 678, color=RED, kind=0, radius=4)
    canvas.text(630, 674, right_label, size=9)
    canvas.save(path)


def scatter_rate_energy(path: Path, rows: Sequence[dict[str, object]]) -> None:
    canvas = PdfCanvas(1080, 620)
    title(canvas, "Packet energy--rate design space", "Measured 32-byte TX packet; fastest tested mode; highest tested power")
    box = (100.0, 95.0, 900.0, 440.0)
    xs = [float(row["canonical_rate_kbps"]) for row in rows]
    ys = [float(row["tx_energy_mJ"]) for row in rows]
    x_range = (min(xs) * 0.65, max(xs) * 1.55)
    y_range = (min(ys) * 0.55, max(ys) * 2.1)
    for tick in log_ticks(*x_range):
        px = _map(tick, *x_range, box[0], box[2], True)
        canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.7)
        canvas.text(px - 12, box[1] - 20, fmt_tick(tick), size=8)
    for tick in log_ticks(*y_range):
        py = _map(tick, *y_range, box[1], box[3], True)
        canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.7)
        canvas.text(box[0] - 43, py - 3, fmt_tick(tick), size=8)
    families = {family: index for index, family in enumerate(sorted({str(row["family"]) for row in rows}))}
    plotted: list[tuple[int, dict[str, object], float, float, tuple[float, float, float]]] = []
    for index, row in enumerate(rows):
        px = _map(float(row["canonical_rate_kbps"]), *x_range, box[0], box[2], True)
        py = _map(float(row["tx_energy_mJ"]), *y_range, box[1], box[3], True)
        color = PALETTE[families[str(row["family"])] % len(PALETTE)]
        canvas.marker(px, py, color=color, kind=index, radius=5)
        plotted.append((index, row, px, py, color))
    groups: dict[float, list[tuple[int, dict[str, object], float, float, tuple[float, float, float]]]] = {}
    for point in plotted:
        groups.setdefault(round(float(point[1]["canonical_rate_kbps"]), 3), []).append(point)
    for points in groups.values():
        points.sort(key=lambda point: point[3])
        if len(points) > 2:
            center = sum(point[3] for point in points) / len(points)
            start = center - (len(points) - 1) * 5.5
            label_x = points[0][2] + 12 if points[0][2] < box[0] + box[2] * 0.55 else points[0][2] - 66
            for offset, (_, row, px, py, color) in enumerate(points):
                label_y = start + offset * 11
                canvas.line(px, py, label_x, label_y + 2, color=color, width=0.5)
                canvas.text(label_x, label_y, str(row["code"]), size=7, color=color, bold=True)
        else:
            for index, row, px, py, color in points:
                dx = 7 if px < box[0] + box[2] * 0.75 else -42
                dy = 8 if index % 2 == 0 else -13
                canvas.text(px + dx, py + dy, str(row["code"]), size=7, color=color, bold=True)
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.2)
    canvas.text(440, 48, "Configured gross rate [kbps]", size=9, bold=True)
    canvas.text(18, 558, "32-byte TX energy [mJ]", size=8, bold=True)
    canvas.save(path)


def payload_energy_figure(
    path: Path,
    payload_rows: Sequence[dict[str, object]],
    payload_sizes: Sequence[int],
    direction: str,
) -> None:
    groups = (
        (
            "FSK and transparent high-rate modules",
            {"cc1101_v1_433", "cc1101_v2_868", "e280", "ebyte_e79_400dm2005s", "hc12", "nrf24l01", "nrf24l01_pa"},
        ),
        (
            "Direct LoRa and modem implementations",
            {"e28_sx1280", "ebyte_e22_400m30s", "ra01h_sx1276", "ra01sh_sx1262", "ra08_asr6601", "xl1276_d01_sx1276"},
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
    canvas = PdfCanvas(1120, 820)
    direction_name = direction.upper()
    title(
        canvas,
        f"{direction_name} energy versus measured logical payload size",
        "Fastest tested mode and highest tested configured power per module; logarithmic energy axis",
    )
    panel_origins = ((65.0, 430.0), (615.0, 430.0), (65.0, 75.0), (615.0, 75.0))
    plot_width = 440.0
    plot_height = 225.0
    payload_index = {payload: index for index, payload in enumerate(payload_sizes)}

    for panel_index, ((panel_title, slugs), (left, bottom)) in enumerate(zip(groups, panel_origins)):
        panel_rows = [row for row in selected_rows if row["slug"] in slugs]
        energies = [float(row["energy_mJ"]) for row in panel_rows]
        y_range = (min(energies) * 0.65, max(energies) * 1.65)
        canvas.text(left, bottom + plot_height + 65, panel_title, size=10, bold=True)
        canvas.text(left, bottom + plot_height + 50, f"{direction_name} packet energy [mJ]", size=7, bold=True)

        module_codes = sorted({str(row["code"]) for row in panel_rows})
        code_style = {
            code: (PALETTE[index % len(PALETTE)], index)
            for index, code in enumerate(module_codes)
        }
        for index, code in enumerate(module_codes):
            color, marker = code_style[code]
            legend_column = index % 4
            legend_row = index // 4
            lx = left + legend_column * 108
            ly = bottom + plot_height + 34 - legend_row * 13
            canvas.line(lx, ly + 2, lx + 15, ly + 2, color=color, width=1.3)
            canvas.marker(lx + 7.5, ly + 2, color=color, kind=marker, radius=2.8)
            canvas.text(lx + 19, ly - 1, code, size=6.5, color=color, bold=True)

        for tick in log_ticks(*y_range):
            py = _map(tick, *y_range, bottom, plot_height, True)
            canvas.line(left, py, left + plot_width, py, color=GRID, width=0.55)
            canvas.text(left - 34, py - 3, fmt_tick(tick), size=6.5)
        for payload in payload_sizes:
            index = payload_index[payload]
            px = left + index * plot_width / max(1, len(payload_sizes) - 1)
            canvas.line(px, bottom, px, bottom + plot_height, color=GRID, width=0.4)
            canvas.text(px - (8 if payload < 100 else 12), bottom - 15, str(payload), size=6.5)

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
            canvas.polyline(mapped, color=color, width=1.4)
            for px, py in mapped:
                canvas.marker(px, py, color=color, kind=marker, radius=3.2)

        canvas.line(left, bottom, left + plot_width, bottom, width=1.0)
        canvas.line(left, bottom, left, bottom + plot_height, width=1.0)
        canvas.text(left + 178, bottom - 31, "Logical payload [bytes]", size=7, bold=True)
        canvas.text(left + plot_width - 35, bottom + plot_height + 3, chr(ord("A") + panel_index), size=9, bold=True)
    canvas.save(path)


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

    canvas.text(left, bottom + height + 32, panel_title, size=9.5, bold=True)
    canvas.text(left, bottom + height + 18, y_label, size=7, bold=True)
    canvas.text(left + width - 16, bottom + height + 7, letter, size=9, bold=True)
    for tick in y_ticks:
        py = _map(tick, *y_range, bottom, height, y_log)
        canvas.line(left, py, left + width, py, color=GRID, width=0.55)
        canvas.text(left - 34, py - 3, fmt_tick(tick), size=6.5)
    for tick in x_ticks:
        px = _map(tick, x_low, x_high, left, width, x_log)
        canvas.line(px, bottom, px, bottom + height, color=GRID, width=0.45)
        label = fmt_tick(tick)
        canvas.text(px - len(label) * 2.0, bottom - 15, label, size=6.5)

    styles = {
        "V1 433 MHz": (BLUE, 2),
        "V2 868 MHz": (RED, 0),
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
    canvas.text(left + width / 2.0 - len(x_label) * 2.1, bottom - 31, x_label, size=7, bold=True)


def cc1101_legend(canvas: PdfCanvas, y: float) -> None:
    for index, (label, color, marker) in enumerate(
        (("CC1101 V1 433 MHz", BLUE, 2), ("CC1101 V2 868 MHz", RED, 0))
    ):
        left = 345 + index * 245
        canvas.line(left, y, left + 24, y, color=color, width=1.8)
        canvas.marker(left + 12, y, color=color, kind=marker, radius=4)
        canvas.text(left + 32, y - 4, label, size=8, color=color, bold=True)


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
                }
            )

    canvas = PdfCanvas(1080, 620)
    title(canvas, heading, subtitle)
    panels = (
        ("mean_power_mW", "Total average power", "A"),
        ("mean_excess_power_mW", "Mean power above standby", "B"),
    )
    boxes = ((82.0, 100.0, 420.0, 340.0), (578.0, 100.0, 420.0, 340.0))
    powers = sorted({float(row["power_dbm"]) for row in normalized})
    power_span = max(powers) - min(powers)
    x_range = (min(powers) - power_span * 0.08, max(powers) + power_span * 0.08)

    for (metric, panel_title, panel_code), box in zip(panels, boxes):
        upper, ticks = linear_ticks(max(float(row[metric]) for row in normalized) * 1.05)
        canvas.text(box[0], 516, panel_title, size=11, bold=True)
        canvas.text(box[0] + box[2] - 12, 516, panel_code, size=10, bold=True)
        for tick in ticks:
            py = _map(tick, 0.0, upper, box[1], box[3], False)
            canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.6)
            canvas.text(box[0] - 38, py - 3, fmt_tick(tick), size=7)
        for power in powers:
            px = _map(power, *x_range, box[0], box[2], False)
            canvas.line(px, box[1], px, box[1] + box[3], color=GRID, width=0.5)
            canvas.text(px - 10, box[1] - 19, f"{power:g}", size=7)

        legend_items = []
        for variant_index, (_, variant_label) in enumerate(variants):
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
                legend_items.append((variant_label, direction.upper(), color, variant_index, dash))

        for index, (variant_label, direction, color, marker, dash) in enumerate(legend_items):
            column = index % 2
            row_index = index // 2
            lx = box[0] + column * 205
            ly = 490 - row_index * 17
            canvas.line(lx, ly, lx + 24, ly, color=color, width=1.8, dash=dash)
            canvas.marker(lx + 12, ly, color=color, kind=marker, radius=3.5)
            canvas.text(lx + 31, ly - 3, f"{variant_label} {direction}", size=7.5, color=color, bold=True)

        canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.1)
        canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.1)
        canvas.text(box[0] + 158, 55, "Configured RF power [dBm]", size=8, bold=True)
        canvas.text(box[0] - 8, 455, "Power [mW]", size=7.5, bold=True)
    canvas.text(
        250,
        24,
        "Each point is a 60 s mean at 3.3 V; the excess metric is clipped at zero by the campaign pipeline.",
        size=7.5,
        color=GRAY,
    )
    canvas.save(path)
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
        "Continuous loss includes bridge pacing and receiver re-arm behavior",
        log_x=False,
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
    )


def nrf_figure(path: Path, packet_data: dict[str, list[dict[str, str]]]) -> None:
    canvas = PdfCanvas(1080, 600)
    title(canvas, "nRF24L01 module versus PA/LNA variant", "32-byte TX packet at 0 dBm radio drive; auto-ack disabled")
    box = (120.0, 105.0, 850.0, 400.0)
    rates = (250.0, 1000.0, 2000.0)
    all_values: list[float] = []
    series: list[tuple[str, list[tuple[float, float]], tuple[float, float, float], int]] = []
    for index, (slug, label, color) in enumerate((("nrf24l01", "nRF24L01", BLUE), ("nrf24l01_pa", "nRF24L01+PA/LNA", RED))):
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
        canvas.text(px - 18, box[1] - 20, f"{tick:g}", size=8)
    for tick in log_ticks(*y_range):
        py = _map(tick, *y_range, box[1], box[3], True)
        canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.7)
        canvas.text(box[0] - 42, py - 3, fmt_tick(tick), size=8)
    for label, points, color, marker in series:
        mapped = [(_map(x, *x_range, box[0], box[2], True), _map(y, *y_range, box[1], box[3], True)) for x, y in points]
        canvas.polyline(mapped, color=color, width=2)
        for px, py in mapped:
            canvas.marker(px, py, color=color, kind=marker, radius=5)
        legend_x = 390 + marker * 190
        canvas.line(legend_x, 535, legend_x + 28, 535, color=color, width=2)
        canvas.marker(legend_x + 14, 535, color=color, kind=marker, radius=4)
        canvas.text(legend_x + 35, 531, label, size=9)
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.2)
    canvas.text(440, 56, "Configured rate [kbps]", size=9, bold=True)
    canvas.text(22, 525, "TX energy [mJ]", size=8, bold=True)
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
        canvas.text(px - 12, box[1] - 20, fmt_tick(tick), size=8)
    for tick in log_ticks(*y_range):
        py = _map(tick, *y_range, box[1], box[3], True)
        canvas.line(box[0], py, box[0] + box[2], py, color=GRID, width=0.7)
        canvas.text(box[0] - 40, py - 3, fmt_tick(tick), size=8)
    plotted = []
    for index, row in enumerate(profiles):
        px = _map(float(row["rate_kbps"]), *x_range, box[0], box[2], True)
        py = _map(float(row["tx_energy_mJ"]), *y_range, box[1], box[3], True)
        color = PALETTE[index % len(PALETTE)]
        canvas.marker(px, py, color=color, kind=index, radius=6)
        plotted.append((index, row, px, py, color))
    rate_groups: dict[float, list[tuple[int, dict[str, object], float, float, tuple[float, float, float]]]] = {}
    for point in plotted:
        rate_groups.setdefault(float(point[1]["rate_kbps"]), []).append(point)
    for points in rate_groups.values():
        points.sort(key=lambda point: point[3])
        for offset, (index, row, px, py, color) in enumerate(points):
            if len(points) > 1:
                label_y = py + (-15 if offset == 0 else 10)
                label_x = px + (-75 if offset == 0 else 10)
            else:
                label_x = px + (8 if px < box[0] + box[2] * 0.8 else -58)
                label_y = py + (10 if index % 2 else -16)
            canvas.text(label_x, label_y, str(row["profile"]), size=8, bold=True, color=color)
    canvas.line(box[0], box[1], box[0] + box[2], box[1], width=1.2)
    canvas.line(box[0], box[1], box[0], box[1] + box[3], width=1.2)
    canvas.text(420, 52, "Configured PHY rate [kbps]", size=9, bold=True)
    canvas.text(14, 542, "32-byte TX energy [mJ]", size=8, bold=True)
    canvas.save(path)
    return profiles


def write_findings(summary: Sequence[dict[str, object]], e79_profiles: Sequence[dict[str, object]]) -> None:
    by_energy = sorted(summary, key=lambda row: float(row["tx_energy_mJ"]))
    by_rx = sorted(summary, key=lambda row: float(row["continuous_rx_power_mW"]))
    by_tx_power = sorted(summary, key=lambda row: float(row["continuous_tx_power_mW"]))
    by_goodput = sorted(summary, key=lambda row: float(row["continuous_goodput_kbps"]), reverse=True)
    best_e79 = min(e79_profiles, key=lambda row: float(row["tx_energy_mJ"]))
    slow_e79 = next(row for row in e79_profiles if row["profile"] == "SLR2K5")
    fast_e79 = next(row for row in e79_profiles if row["profile"] == "GFSK200")
    macro_lines = [
        "% Generated by generate_study.py; do not edit by hand.",
        f"\\newcommand{{\\BestPacketEnergyModule}}{{{latex_escape(by_energy[0]['label'])}}}",
        f"\\newcommand{{\\BestPacketEnergy}}{{{fmt(by_energy[0]['tx_energy_mJ'])}}}",
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
    payload_rows, payload_sizes = build_payload_summary(packet_data)
    cc1101_rows = build_cc1101_comparison(packet_data)
    write_csv(STUDY_DIR / "data" / "module_catalog.csv", [asdict(spec) for spec in MODULES])
    write_csv(STUDY_DIR / "data" / "module_summary.csv", summary)
    write_csv(STUDY_DIR / "data" / "payload_energy_summary.csv", payload_rows)
    write_csv(STUDY_DIR / "data" / "cc1101_controlled_summary.csv", cc1101_rows)
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
        "Fastest tested mode and highest tested power per module; logarithmic scale",
    )
    dot_comparison(
        figures / "continuous_power_comparison.pdf",
        summary,
        "continuous_tx_power_mW",
        "continuous_rx_power_mW",
        "TX",
        "RX",
        "Continuous average power",
        "Average module power at 3.3 V [mW]",
        "Fastest mode present in each 60 s continuous campaign; logarithmic scale",
    )
    scatter_rate_energy(figures / "rate_energy_design_space.pdf", summary)
    payload_energy_figure(figures / "tx_energy_by_payload.pdf", payload_rows, payload_sizes, "tx")
    payload_energy_figure(figures / "rx_energy_by_payload.pdf", payload_rows, payload_sizes, "rx")
    packet_continuous_delivery(figures / "delivery_comparison.pdf", summary)
    variant_figure(figures / "sx1278_variant_comparison.pdf", summary)
    nrf_figure(figures / "nrf24_pa_comparison.pdf", packet_data)
    e79_profiles = e79_figure(figures / "e79_profile_frontier.pdf", packet_data)
    cc1101_continuous_figure(figures / "cc1101_continuous_power_comparison.pdf", cc1101_rows)
    cc1101_packet_figure(figures / "cc1101_packet_comparison.pdf", cc1101_rows)
    matched_continuous_rows: list[dict[str, object]] = []
    matched_continuous_rows.extend(
        continuous_power_pair_figure(
            figures / "e32_band_continuous_power_comparison.pdf",
            "e32_band",
            "E32-433T20D versus E32-868T20D",
            "Matched 60 s workload: 58-byte frames, 4.8 kbps, 15 ms host gap, 3.3 V",
            (("ebyte_e32_433t20d", "433T20D"), ("ebyte_e32_868t20d", "868T20D")),
            "bit_rate_kbps",
            4.8,
        )
    )
    matched_continuous_rows.extend(
        continuous_power_pair_figure(
            figures / "nrf24_pa_continuous_power_comparison.pdf",
            "nrf24_pa",
            "nRF24L01 versus PA/LNA module",
            "Matched 60 s workload: 32-byte frames, 1 Mbps, 15 ms host gap, 3.3 V",
            (("nrf24l01", "nRF24"), ("nrf24l01_pa", "nRF24+PA")),
            "bit_rate_kbps",
            1000.0,
        )
    )
    matched_continuous_rows.extend(
        continuous_power_pair_figure(
            figures / "ra02_capacitor_continuous_power_comparison.pdf",
            "ra02_capacitors",
            "RA-02 classic versus two-capacitor variant",
            "Matched 60 s workload: 32-byte frames, SF9/BW125, 15 ms host gap, 3.3 V",
            (("ra02_sx1278", "RA-02"), ("ra02_sx1278_2cap", "RA-02+2C")),
            "spreading_factor",
            9.0,
        )
    )
    write_csv(STUDY_DIR / "data" / "e79_profile_summary.csv", e79_profiles)
    write_csv(STUDY_DIR / "data" / "matched_continuous_power_summary.csv", matched_continuous_rows)
    write_findings(summary, e79_profiles)
    print(
        f"Generated {len(summary)} module summaries, {len(payload_rows)} payload-energy rows, "
        f"{len(cc1101_rows)} controlled CC1101 points, {len(matched_continuous_rows)} matched "
        f"continuous-power points, and 14 figures in {STUDY_DIR}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
