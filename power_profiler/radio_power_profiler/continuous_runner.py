from __future__ import annotations

import csv
import json
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Profile
from .planning import parameter_commands
from .ppk import Capture, Ppk2Sampler, SAMPLE_RATE_HZ
from .serial_radio import ContinuousTransmissionResult, SerialRadio


CONTINUOUS_FIELDS = [
    "run_id",
    "timestamp_utc",
    "profile_id",
    "module",
    "measurement_direction",
    "measured_port",
    "peer_port",
    "ppk_port",
    "voltage_mv",
    "tx_power_dbm",
    "bit_rate_kbps",
    "frame_bytes",
    "content_bytes_per_frame",
    "inter_frame_gap_ms",
    "requested_duration_s",
    "actual_tx_duration_ms",
    "frames_transmitted",
    "bytes_transmitted",
    "frames_received",
    "frame_loss_percent",
    "captured_samples",
    "active_samples",
    "active_window_s",
    "sample_loss_percent",
    "baseline_mean_uA",
    "baseline_median_uA",
    "mean_current_uA",
    "stdev_current_uA",
    "peak_current_uA",
    "mean_excess_current_uA",
    "mean_power_mW",
    "stdev_power_mW",
    "peak_power_mW",
    "mean_excess_power_mW",
    "energy_60s_mJ",
    "transmitter_response",
    "status",
]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _output_directory(root: Path, profile_id: str, direction: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / f"{stamp}_{profile_id.lower()}_continuous_{direction}"


def _measurement_stats(
    capture: Capture,
    *,
    duration_s: float,
    voltage_mv: int,
) -> dict[str, float | int]:
    active_start = capture.trigger_index
    requested_samples = int(round(duration_s * SAMPLE_RATE_HZ))
    active_stop = min(len(capture.samples_uA), active_start + requested_samples)
    active = capture.samples_uA[active_start:active_stop]
    if len(active) < requested_samples * 0.90:
        raise RuntimeError(
            f"Continuous capture contains only {len(active)} of "
            f"{requested_samples} requested active samples"
        )

    baseline_start = max(0, active_start - int(0.10 * SAMPLE_RATE_HZ))
    baseline = capture.samples_uA[baseline_start:active_start]
    if not baseline:
        raise RuntimeError("Continuous capture has no pre-trigger baseline")

    mean_current = statistics.fmean(active)
    stdev_current = statistics.pstdev(active)
    peak_current = max(active)
    baseline_mean = statistics.fmean(baseline)
    baseline_median = statistics.median(baseline)
    mean_excess = max(0.0, mean_current - baseline_mean)
    power_scale = voltage_mv / 1_000_000.0
    mean_power = mean_current * power_scale
    return {
        "captured_samples": len(capture.samples_uA),
        "active_samples": len(active),
        "active_window_s": len(active) / SAMPLE_RATE_HZ,
        "sample_loss_percent": capture.sample_loss_percent,
        "baseline_mean_uA": baseline_mean,
        "baseline_median_uA": baseline_median,
        "mean_current_uA": mean_current,
        "stdev_current_uA": stdev_current,
        "peak_current_uA": peak_current,
        "mean_excess_current_uA": mean_excess,
        "mean_power_mW": mean_power,
        "stdev_power_mW": stdev_current * power_scale,
        "peak_power_mW": peak_current * power_scale,
        "mean_excess_power_mW": mean_excess * power_scale,
        "energy_60s_mJ": mean_power * duration_s,
    }


def _receive_continuous(
    receiver: SerialRadio,
    transmitter: SerialRadio,
    *,
    duration_ms: int,
    frame_bytes: int,
    inter_frame_gap_ms: int,
) -> tuple[ContinuousTransmissionResult, tuple[str, ...]]:
    receiver.command("AT+RX=ON", drain_before=False)
    result_holder: list[ContinuousTransmissionResult] = []
    errors: list[BaseException] = []

    def send() -> None:
        try:
            result_holder.append(
                transmitter.send_continuous(
                    duration_ms=duration_ms,
                    frame_bytes=frame_bytes,
                    inter_frame_gap_ms=inter_frame_gap_ms,
                    drain_before=False,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    sender = threading.Thread(target=send, daemon=True)
    receiver_lines: list[str] = []
    sender.start()
    try:
        while sender.is_alive():
            receiver_lines.extend(receiver.drain(wait_s=0.02))
        sender.join(timeout=1.0)
        receiver_lines.extend(receiver.drain(wait_s=0.15))
        if sender.is_alive():
            raise RuntimeError("Continuous transmitter did not stop")
        if errors:
            raise errors[0]
        if not result_holder:
            raise RuntimeError("Continuous transmitter returned no result")
        return result_holder[0], tuple(receiver_lines)
    finally:
        receiver.command("AT+RX=OFF", drain_before=False)


def run_continuous_profile(
    profile: Profile,
    *,
    measurement_direction: str,
    powers_dbm: tuple[float, ...],
    bit_rate_kbps: float,
    duration_s: float,
    frame_bytes: int,
    inter_frame_gap_ms: int,
    radio_port: str,
    transmitter_port: str | None,
    ppk_port: str,
    voltage_mv: int,
    output_root: Path,
    boot_wait_s: float,
) -> Path:
    if measurement_direction not in {"tx", "rx"}:
        raise ValueError("Continuous measurement direction must be 'tx' or 'rx'")
    if measurement_direction == "rx" and not transmitter_port:
        raise ValueError("Continuous RX measurement requires a transmitter port")
    if transmitter_port and transmitter_port.upper() == radio_port.upper():
        raise ValueError("Measured radio and continuous transmitter must be different")
    if not 1.0 <= duration_s <= 600.0:
        raise ValueError("Continuous duration must be between 1 and 600 seconds")
    if not 3 <= frame_bytes <= 32:
        raise ValueError("Continuous CC1101 frames must be between 3 and 32 bytes")
    if not 0 <= inter_frame_gap_ms <= 1000:
        raise ValueError("Continuous inter-frame gap must be between 0 and 1000 ms")
    if not powers_dbm:
        raise ValueError("At least one TX power is required")

    axis_names = {axis.name for axis in profile.axes}
    required_axes = {"tx_power_dbm", "bit_rate_kbps"}
    if not required_axes.issubset(axis_names):
        raise ValueError(
            f"Profile {profile.profile_id} does not expose the CC1101 power/rate axes"
        )

    duration_ms = int(round(duration_s * 1000.0))
    output_dir = _output_directory(
        output_root,
        profile.profile_id,
        measurement_direction,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    metadata: dict[str, Any] = {
        "created_utc": _timestamp(),
        "test_type": "continuous_average_power",
        "profile_id": profile.profile_id,
        "module": profile.display_name,
        "firmware_selection": profile.firmware_selection,
        "measurement_direction": measurement_direction,
        "measured_port": radio_port,
        "peer_port": transmitter_port if measurement_direction == "rx" else "",
        "ppk_port": ppk_port,
        "ppk_mode": "ampere",
        "voltage_mv": voltage_mv,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "powers_dbm": powers_dbm,
        "bit_rate_kbps": bit_rate_kbps,
        "frame_bytes": frame_bytes,
        "content_bytes_per_frame": frame_bytes - 2,
        "inter_frame_gap_ms": inter_frame_gap_ms,
        "requested_duration_s": duration_s,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    summary_path = output_dir / "summary.csv"
    sampler: Ppk2Sampler | None = None
    radio: SerialRadio | None = None
    peer: SerialRadio | None = None
    stream = summary_path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(stream, fieldnames=CONTINUOUS_FIELDS)
    writer.writeheader()
    stream.flush()
    try:
        sampler = Ppk2Sampler(ppk_port, voltage_mv=voltage_mv)
        sampler.power_on()
        time.sleep(boot_wait_s)
        radio = SerialRadio(radio_port, profile.baudrate)
        radio.configure(profile.setup_commands)
        radio.configure(profile.post_config_commands)
        if measurement_direction == "rx":
            peer = SerialRadio(str(transmitter_port), profile.baudrate)
            peer.configure(profile.setup_commands)
            peer.configure(profile.post_config_commands)

        for index, power_dbm in enumerate(powers_dbm, start=1):
            power_value: float | int = (
                int(power_dbm) if float(power_dbm).is_integer() else power_dbm
            )
            parameters = {
                "tx_power_dbm": power_value,
                "bit_rate_kbps": bit_rate_kbps,
            }
            commands = parameter_commands(profile, parameters)
            radio.configure(commands)
            radio.configure(profile.post_config_commands)
            if peer is not None:
                peer.configure(commands)
                peer.configure(profile.post_config_commands)
            time.sleep(0.10)
            radio.drain(wait_s=0.05)
            if peer is not None:
                peer.drain(wait_s=0.05)

            transmission: ContinuousTransmissionResult | None = None
            receiver_lines: tuple[str, ...] = ()

            def trigger() -> None:
                nonlocal transmission, receiver_lines
                if measurement_direction == "tx":
                    transmission = radio.send_continuous(
                        duration_ms=duration_ms,
                        frame_bytes=frame_bytes,
                        inter_frame_gap_ms=inter_frame_gap_ms,
                        drain_before=False,
                    )
                else:
                    if peer is None:
                        raise RuntimeError("Continuous RX measurement has no transmitter")
                    transmission, receiver_lines = _receive_continuous(
                        radio,
                        peer,
                        duration_ms=duration_ms,
                        frame_bytes=frame_bytes,
                        inter_frame_gap_ms=inter_frame_gap_ms,
                    )

            capture = sampler.capture(
                pre_s=0.20,
                after_trigger_s=duration_s + 0.75,
                trigger=trigger,
            )
            if transmission is None:
                raise RuntimeError("Continuous transmission returned no metadata")
            metrics = _measurement_stats(
                capture,
                duration_s=duration_s,
                voltage_mv=voltage_mv,
            )
            expected_payload = SerialRadio.make_payload(frame_bytes - 2).decode("ascii")
            frames_received: int | str = ""
            frame_loss_percent: float | str = ""
            status = "ok"
            if measurement_direction == "rx":
                frames_received = sum(line == expected_payload for line in receiver_lines)
                frame_loss_percent = (
                    100.0
                    * max(0, transmission.frames - frames_received)
                    / transmission.frames
                    if transmission.frames
                    else 100.0
                )
                if frames_received == 0:
                    status = "no_rx_data"

            row = {
                "run_id": f"continuous_{index:03d}",
                "timestamp_utc": _timestamp(),
                "profile_id": profile.profile_id,
                "module": profile.display_name,
                "measurement_direction": measurement_direction,
                "measured_port": radio_port,
                "peer_port": transmitter_port if measurement_direction == "rx" else "",
                "ppk_port": ppk_port,
                "voltage_mv": voltage_mv,
                "tx_power_dbm": power_dbm,
                "bit_rate_kbps": bit_rate_kbps,
                "frame_bytes": frame_bytes,
                "content_bytes_per_frame": frame_bytes - 2,
                "inter_frame_gap_ms": inter_frame_gap_ms,
                "requested_duration_s": duration_s,
                "actual_tx_duration_ms": transmission.elapsed_ms,
                "frames_transmitted": transmission.frames,
                "bytes_transmitted": transmission.payload_bytes,
                "frames_received": frames_received,
                "frame_loss_percent": frame_loss_percent,
                **metrics,
                "transmitter_response": " | ".join(transmission.response_lines),
                "status": status,
            }
            writer.writerow({field: row.get(field, "") for field in CONTINUOUS_FIELDS})
            stream.flush()
            print(
                f"[{index}/{len(powers_dbm)}] {measurement_direction.upper()} "
                f"{power_dbm:g} dBm: mean={metrics['mean_current_uA'] / 1000.0:.3f} mA, "
                f"power={metrics['mean_power_mW']:.3f} mW, status={status}"
            )
            time.sleep(0.50)
    finally:
        stream.close()
        if peer is not None:
            peer.close()
        if radio is not None:
            radio.close()
        if sampler is not None:
            sampler.close()
    return output_dir
