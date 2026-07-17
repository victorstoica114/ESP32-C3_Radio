from __future__ import annotations

import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import analyze_capture
from .models import Profile, TestCase
from .planning import build_cases, parameter_commands
from .ppk import Ppk2Sampler, SAMPLE_RATE_HZ
from .results import ResultWriter
from .serial_radio import RadioCommandError, SerialRadio, TransmissionResult


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _output_directory(root: Path, profile_id: str, measurement_direction: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "" if measurement_direction == "tx" else "_rx"
    return root / f"{stamp}_{profile_id.lower()}{suffix}"


def _received_all_frames(expected_payloads: tuple[bytes, ...], lines: tuple[str, ...]) -> bool:
    remaining = list(lines)
    for payload in expected_payloads:
        expected = payload.decode("ascii")
        match = next((index for index, line in enumerate(remaining) if expected in line), None)
        if match is None:
            return False
        remaining.pop(match)
    return True


def _execute_receive_transfer(
    receiver: SerialRadio,
    transmitter: SerialRadio,
    profile: Profile,
    case: TestCase,
) -> tuple[TransmissionResult, tuple[str, ...]]:
    """Measure one bounded RX window and return all receiver output."""
    receiver.configure(profile.receiver_enable_commands)
    try:
        wait_for_completion = profile.transmit.mode == "burst_command"
        transmission = transmitter.send_packet(
            profile,
            case.payload_bytes,
            wait_for_completion=wait_for_completion,
            completion_timeout_s=max(2.0, case.capture_after_trigger_s),
            inter_frame_gap_ms=profile.receive.inter_frame_gap_ms,
        )
        if not wait_for_completion:
            receive_time_s = max(
                0.0,
                case.estimated_event_s - profile.receive.post_receive_s,
            )
            time.sleep(receive_time_s)
        receiver_lines = receiver.drain(wait_s=profile.receive.post_receive_s)
        return transmission, receiver_lines
    finally:
        receiver.configure(profile.post_config_commands)


def run_profile(
    profile: Profile,
    *,
    radio_port: str,
    receiver_port: str | None,
    measurement_direction: str = "tx",
    transmitter_port: str | None = None,
    ppk_port: str,
    voltage_mv: int,
    output_root: Path,
    save_raw: bool,
    keep_power_on: bool,
    boot_wait_s: float,
) -> Path:
    if measurement_direction not in {"tx", "rx"}:
        raise ValueError("Measurement direction must be 'tx' or 'rx'")
    if measurement_direction == "rx":
        if receiver_port:
            raise ValueError("--receiver-port is only valid for TX measurements")
        if not transmitter_port:
            raise ValueError("RX measurements require --transmitter-port")
        if not profile.receiver_enable_commands:
            raise ValueError(
                f"Profile {profile.profile_id} does not define controlled RX commands"
            )
        peer_port = transmitter_port
    else:
        if transmitter_port:
            raise ValueError("--transmitter-port is only valid for RX measurements")
        peer_port = receiver_port
    if peer_port and peer_port.upper() == radio_port.upper():
        raise ValueError("Measured radio and peer ports must be different")

    cases = build_cases(profile, measurement_direction)
    output_dir = _output_directory(
        output_root,
        profile.profile_id,
        measurement_direction,
    )
    metadata: dict[str, Any] = {
        "created_utc": _timestamp(),
        "profile": dataclasses.asdict(profile),
        "measurement_direction": measurement_direction,
        "measured_port": radio_port,
        "radio_port": radio_port,
        "transmitter_port": (
            radio_port if measurement_direction == "tx" else transmitter_port
        ),
        "receiver_port": (
            receiver_port if measurement_direction == "tx" else radio_port
        ),
        "peer_port": peer_port,
        "ppk_port": ppk_port,
        "ppk_mode": "ampere",
        "voltage_mv": voltage_mv,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "save_raw": save_raw,
        "test_count": len(cases),
    }

    sampler: Ppk2Sampler | None = None
    radio: SerialRadio | None = None
    peer: SerialRadio | None = None
    writer: ResultWriter | None = None
    previous_parameters: dict[str, Any] | None = None
    try:
        sampler = Ppk2Sampler(ppk_port, voltage_mv=voltage_mv)
        sampler.power_on()
        time.sleep(boot_wait_s)
        radio = SerialRadio(radio_port, profile.baudrate)
        measured_role = "transmitter" if measurement_direction == "tx" else "receiver"
        print(
            f"Configuring measured {measured_role} "
            f"({profile.display_name}) on {radio_port} ..."
        )
        radio.configure(profile.setup_commands)
        if peer_port:
            if measurement_direction == "tx" and not profile.receiver_enable_commands:
                raise ValueError(
                    f"Profile {profile.profile_id} does not define receiver-enable commands"
                )
            peer = SerialRadio(peer_port, profile.baudrate)
            peer_role = "receiver" if measurement_direction == "tx" else "transmitter"
            print(f"Configuring peer {peer_role} on {peer_port} ...")
            peer.configure(profile.setup_commands)
            peer.configure(
                profile.receiver_enable_commands
                if measurement_direction == "tx"
                else profile.post_config_commands
            )
        writer = ResultWriter(output_dir, metadata)

        for case in cases:
            if case.parameters != previous_parameters:
                radio.configure(parameter_commands(profile, case.parameters))
                radio.configure(profile.post_config_commands)
                if peer is not None:
                    peer.configure(parameter_commands(profile, case.parameters))
                    peer.configure(
                        profile.receiver_enable_commands
                        if measurement_direction == "tx"
                        else profile.post_config_commands
                    )
                previous_parameters = dict(case.parameters)
                time.sleep(0.10)

            radio.drain(wait_s=0.03)
            if peer is not None:
                peer.drain(wait_s=0.03)
            transmission = None
            receiver_lines_during_trigger: tuple[str, ...] = ()

            def trigger() -> None:
                nonlocal transmission, receiver_lines_during_trigger
                if measurement_direction == "tx":
                    transmission = radio.send_packet(
                        profile,
                        case.payload_bytes,
                        inter_frame_gap_ms=profile.receive.inter_frame_gap_ms,
                    )
                else:
                    if peer is None:
                        raise RuntimeError("RX measurement has no transmitter")
                    transmission, receiver_lines_during_trigger = _execute_receive_transfer(
                        radio,
                        peer,
                        profile,
                        case,
                    )

            capture = sampler.capture(
                pre_s=profile.capture.pre_s,
                after_trigger_s=case.capture_after_trigger_s,
                trigger=trigger,
            )
            measured_lines = radio.drain(wait_s=0.08)
            peer_lines = peer.drain(wait_s=0.15) if peer is not None else ()
            if measurement_direction == "tx":
                response_lines = measured_lines
                transmitter_lines = measured_lines
                receiver_lines = peer_lines
            else:
                receiver_lines = receiver_lines_during_trigger + measured_lines
                transmitter_lines = (
                    (transmission.response_lines if transmission is not None else ())
                    + peer_lines
                )
                response_lines = receiver_lines
            response = " | ".join(response_lines)
            transmitter_response = " | ".join(transmitter_lines)
            receiver_response = " | ".join(receiver_lines)
            if transmission is None:
                raise RuntimeError("Radio transmission did not return transfer metadata")
            packet_received = (
                _received_all_frames(transmission.expected_payloads, receiver_lines)
                if measurement_direction == "rx" or peer is not None
                else None
            )
            radio_error = next(
                (line for line in transmitter_lines if line.upper().startswith("#ERROR")),
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
            elif packet_received is not None and not packet_received:
                status = "rx_missing"
            else:
                status = "ok"
            row = {
                "run_id": run_id,
                "timestamp_utc": _timestamp(),
                "profile_id": profile.profile_id,
                "module": profile.display_name,
                "firmware_selection": profile.firmware_selection,
                "measurement_direction": measurement_direction,
                "measured_port": radio_port,
                "peer_port": peer_port or "",
                "transmitter_port": (
                    radio_port if measurement_direction == "tx" else transmitter_port or ""
                ),
                "repetition": case.repetition,
                "payload_bytes": case.payload_bytes,
                "frame_count": len(transmission.frame_payload_bytes),
                "max_frame_payload_bytes": max(transmission.frame_payload_bytes),
                "serial_content_bytes": transmission.content_bytes,
                "parameters_json": json.dumps(case.parameters, sort_keys=True),
                "ppk_mode": "ampere",
                "voltage_mv": voltage_mv,
                "estimated_airtime_ms": case.estimated_airtime_s * 1000.0,
                "estimated_event_ms": case.estimated_event_s * 1000.0,
                "captured_samples": len(capture.samples_uA),
                "sample_loss_percent": capture.sample_loss_percent,
                "event_detected": metrics.event_detected,
                "baseline_median_uA": metrics.baseline_median_uA,
                "threshold_uA": metrics.threshold_uA,
                "event_start_ms": metrics.event_start_ms,
                "event_duration_ms": metrics.event_duration_ms,
                "tx_mean_uA": metrics.tx_mean_uA,
                "tx_peak_uA": metrics.tx_peak_uA,
                "rx_mean_uA": (
                    metrics.tx_mean_uA if measurement_direction == "rx" else ""
                ),
                "rx_peak_uA": (
                    metrics.tx_peak_uA if measurement_direction == "rx" else ""
                ),
                "event_mean_uA": metrics.tx_mean_uA,
                "event_peak_uA": metrics.tx_peak_uA,
                "charge_total_uC": metrics.charge_total_uC,
                "charge_excess_uC": metrics.charge_excess_uC,
                "energy_total_uJ": metrics.energy_total_uJ,
                "energy_excess_uJ": metrics.energy_excess_uJ,
                "radio_response": response,
                "transmitter_response": transmitter_response,
                "receiver_port": (
                    receiver_port if measurement_direction == "tx" else radio_port
                ) or "",
                "receiver_response": receiver_response,
                "packet_received": packet_received if packet_received is not None else "",
                "packet_lost": (
                    not packet_received if packet_received is not None else ""
                ),
                "status": status,
            }
            writer.add(row)
            if save_raw:
                writer.save_raw(run_id, capture)
            print(
                f"[{case.case_index:>4}/{len(cases)}] {measurement_direction.upper()} "
                f"{case.payload_bytes:>4} B, "
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
        if peer is not None:
            peer.close()
        if sampler is not None:
            sampler.close(keep_power_on=keep_power_on)
