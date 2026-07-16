from __future__ import annotations

import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import analyze_capture
from .models import Profile
from .planning import build_cases, parameter_commands
from .ppk import Ppk2Sampler, SAMPLE_RATE_HZ
from .results import ResultWriter
from .serial_radio import RadioCommandError, SerialRadio


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _output_directory(root: Path, profile_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / f"{stamp}_{profile_id.lower()}"


def run_profile(
    profile: Profile,
    *,
    radio_port: str,
    receiver_port: str | None,
    ppk_port: str,
    voltage_mv: int,
    output_root: Path,
    save_raw: bool,
    keep_power_on: bool,
    boot_wait_s: float,
) -> Path:
    cases = build_cases(profile)
    output_dir = _output_directory(output_root, profile.profile_id)
    metadata: dict[str, Any] = {
        "created_utc": _timestamp(),
        "profile": dataclasses.asdict(profile),
        "radio_port": radio_port,
        "receiver_port": receiver_port,
        "ppk_port": ppk_port,
        "ppk_mode": "ampere",
        "voltage_mv": voltage_mv,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "save_raw": save_raw,
        "test_count": len(cases),
    }

    sampler: Ppk2Sampler | None = None
    radio: SerialRadio | None = None
    receiver: SerialRadio | None = None
    writer: ResultWriter | None = None
    previous_parameters: dict[str, Any] | None = None
    try:
        sampler = Ppk2Sampler(ppk_port, voltage_mv=voltage_mv)
        sampler.power_on()
        time.sleep(boot_wait_s)
        radio = SerialRadio(radio_port, profile.baudrate)
        print(f"Configuring {profile.display_name} on {radio_port} ...")
        radio.configure(profile.setup_commands)
        if receiver_port:
            if receiver_port.upper() == radio_port.upper():
                raise ValueError("Transmitter and receiver ports must be different")
            if not profile.receiver_enable_commands:
                raise ValueError(
                    f"Profile {profile.profile_id} does not define receiver-enable commands"
                )
            receiver = SerialRadio(receiver_port, profile.baudrate)
            print(f"Configuring receiver on {receiver_port} ...")
            receiver.configure(profile.setup_commands)
            receiver.configure(profile.receiver_enable_commands)
        writer = ResultWriter(output_dir, metadata)

        for case in cases:
            if case.parameters != previous_parameters:
                radio.configure(parameter_commands(profile, case.parameters))
                radio.configure(profile.post_config_commands)
                if receiver is not None:
                    receiver.configure(parameter_commands(profile, case.parameters))
                    receiver.configure(profile.receiver_enable_commands)
                previous_parameters = dict(case.parameters)
                time.sleep(0.10)

            radio.drain(wait_s=0.03)
            if receiver is not None:
                receiver.drain(wait_s=0.03)
            content_bytes = 0

            def trigger() -> None:
                nonlocal content_bytes
                content_bytes = radio.send_packet(profile, case.payload_bytes)

            capture = sampler.capture(
                pre_s=profile.capture.pre_s,
                after_trigger_s=case.capture_after_trigger_s,
                trigger=trigger,
            )
            response_lines = radio.drain(wait_s=0.08)
            response = " | ".join(response_lines)
            receiver_lines = receiver.drain(wait_s=0.15) if receiver is not None else ()
            receiver_response = " | ".join(receiver_lines)
            expected_payload = SerialRadio.make_payload(content_bytes).decode("ascii")
            packet_received = (
                any(expected_payload in line for line in receiver_lines)
                if receiver is not None
                else None
            )
            radio_error = next(
                (line for line in response_lines if line.upper().startswith("#ERROR")),
                "",
            )
            metrics = analyze_capture(
                capture.samples_uA,
                trigger_index=capture.trigger_index,
                sample_rate_hz=SAMPLE_RATE_HZ,
                voltage_mv=voltage_mv,
                capture_spec=profile.capture,
            )
            run_id = f"run_{case.case_index:05d}"
            if radio_error:
                status = "radio_error"
            elif not metrics.event_detected:
                status = "no_event_detected"
            elif receiver is not None and not packet_received:
                status = "rx_missing"
            else:
                status = "ok"
            row = {
                "run_id": run_id,
                "timestamp_utc": _timestamp(),
                "profile_id": profile.profile_id,
                "module": profile.display_name,
                "firmware_selection": profile.firmware_selection,
                "repetition": case.repetition,
                "payload_bytes": case.payload_bytes,
                "serial_content_bytes": content_bytes,
                "parameters_json": json.dumps(case.parameters, sort_keys=True),
                "ppk_mode": "ampere",
                "voltage_mv": voltage_mv,
                "estimated_airtime_ms": case.estimated_airtime_s * 1000.0,
                "captured_samples": len(capture.samples_uA),
                "sample_loss_percent": capture.sample_loss_percent,
                "event_detected": metrics.event_detected,
                "baseline_median_uA": metrics.baseline_median_uA,
                "threshold_uA": metrics.threshold_uA,
                "event_start_ms": metrics.event_start_ms,
                "event_duration_ms": metrics.event_duration_ms,
                "tx_mean_uA": metrics.tx_mean_uA,
                "tx_peak_uA": metrics.tx_peak_uA,
                "charge_total_uC": metrics.charge_total_uC,
                "charge_excess_uC": metrics.charge_excess_uC,
                "energy_total_uJ": metrics.energy_total_uJ,
                "energy_excess_uJ": metrics.energy_excess_uJ,
                "radio_response": response,
                "receiver_port": receiver_port or "",
                "receiver_response": receiver_response,
                "packet_received": packet_received if packet_received is not None else "",
                "status": status,
            }
            writer.add(row)
            if save_raw:
                writer.save_raw(run_id, capture)
            print(
                f"[{case.case_index:>4}/{len(cases)}] {case.payload_bytes:>3} B, "
                f"{case.parameters}, rep {case.repetition}: {status}, "
                f"peak={metrics.tx_peak_uA or 0:.1f} uA, "
                f"energy={metrics.energy_total_uJ or 0:.3f} uJ"
            )
            time.sleep(profile.cooldown_s)

        writer.write_aggregates()
        return output_dir
    except RadioCommandError:
        raise
    finally:
        if writer is not None:
            writer.close()
        if radio is not None:
            radio.close()
        if receiver is not None:
            receiver.close()
        if sampler is not None:
            sampler.close(keep_power_on=keep_power_on)
