from __future__ import annotations

import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import analyze_capture
from .models import Profile, TestCase
from .planning import build_cases, estimate_airtime_s, parameter_commands
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
        match = next(
            (
                index
                for index, line in enumerate(remaining)
                if SerialRadio.line_contains_payload(line, payload)
            ),
            None,
        )
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
    """Send one bounded RX stimulus and return all receiver output."""
    wait_for_completion = (
        profile.transmit.mode == "burst_command"
        or profile.transmit.wait_for_ok
    )
    frame_count = len(profile.transmit.frame_sizes(case.payload_bytes))
    pacing_ms = profile.receive.inter_frame_gap_ms
    if profile.transmit.mode == "text_line" and frame_count > 1:
        pacing_ms += max(
            estimate_airtime_s(profile, frame_size, case.parameters)
            for frame_size in profile.transmit.frame_sizes(case.payload_bytes)
        ) * 1000.0
    transmission = transmitter.send_packet(
        profile,
        case.payload_bytes,
        wait_for_completion=wait_for_completion,
        completion_timeout_s=max(2.0, case.capture_after_trigger_s),
        inter_frame_gap_ms=pacing_ms,
    )
    if not wait_for_completion:
        host_pacing_s = (
            (frame_count - 1) * pacing_ms / 1000.0
            if profile.transmit.mode == "text_line"
            else 0.0
        )
        receive_time_s = max(
            0.0,
            case.estimated_event_s
            - profile.receive.post_receive_s
            - host_pacing_s,
        )
        time.sleep(receive_time_s)
    receiver_lines = receiver.drain(wait_s=profile.receive.post_receive_s)
    return transmission, receiver_lines


def _warm_up_radio_path(
    radio: SerialRadio,
    peer: SerialRadio | None,
    profile: Profile,
    case: TestCase,
    measurement_direction: str,
) -> None:
    """Prime stateful RF firmware without including initialization in captures."""
    if profile.warmup_transfers <= 0:
        return
    if measurement_direction == "rx" and peer is None:
        raise ValueError("RX warm-up requires a peer transmitter")

    print(
        f"Warming up RF path with {profile.warmup_transfers} "
        "unmeasured verified transfer(s) ..."
    )
    for warmup_index in range(profile.warmup_transfers):
        radio.drain(wait_s=0.03)
        if peer is not None:
            peer.drain(wait_s=0.03)

        if measurement_direction == "tx":
            frame_count = len(profile.transmit.frame_sizes(case.payload_bytes))
            pacing_ms = profile.receive.inter_frame_gap_ms
            if profile.transmit.mode == "text_line" and frame_count > 1:
                pacing_ms += max(
                    estimate_airtime_s(profile, frame_size, case.parameters)
                    for frame_size in profile.transmit.frame_sizes(case.payload_bytes)
                ) * 1000.0
            transmission = radio.send_packet(
                profile,
                case.payload_bytes,
                inter_frame_gap_ms=pacing_ms,
                completion_timeout_s=max(2.0, case.capture_after_trigger_s),
            )
            receiver_lines = (
                peer.drain(wait_s=profile.receive.post_receive_s)
                if peer is not None
                else ()
            )
        else:
            assert peer is not None
            radio.configure(profile.receiver_enable_commands)
            transmission, receiver_lines = _execute_receive_transfer(
                radio,
                peer,
                profile,
                case,
            )

        if peer is not None and not _received_all_frames(
            transmission.expected_payloads,
            receiver_lines,
        ):
            raise RadioCommandError(
                f"RF warm-up {warmup_index + 1}/{profile.warmup_transfers} "
                "was not received by the peer"
            )
        time.sleep(0.05)


def _should_reset_between_runs(profile: Profile, case: TestCase) -> bool:
    """Return whether this case needs the profile's queue-clearing reset."""
    if not profile.inter_run_commands:
        return False
    if not profile.power_cycle_between_runs:
        return True
    return case.estimated_airtime_s >= profile.power_cycle_min_airtime_s


def _restore_after_reset(
    radio: SerialRadio,
    profile: Profile,
    parameters: dict[str, Any],
    role_commands: tuple[str, ...],
) -> None:
    """Reapply the complete modem configuration after a reset."""
    # The caller has already sent ``inter_run_commands``.  A reset command may
    # also be part of the normal process-start setup, but repeating it here
    # would reset the modem twice between every measured packet.
    inter_run_resets = {
        command.strip().upper()
        for command in profile.inter_run_commands
        if "RESET" in command.upper()
    }
    setup_commands = tuple(
        command
        for command in profile.setup_commands
        if command.strip().upper() not in inter_run_resets
    )
    radio.configure(setup_commands)
    radio.configure_profile_parameters(profile, parameters)
    radio.configure(role_commands)


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
                radio.configure_profile_parameters(
                    profile,
                    case.parameters,
                    previous_parameters=previous_parameters,
                )
                radio.configure(profile.post_config_commands)
                if peer is not None:
                    peer.configure_profile_parameters(
                        profile,
                        case.parameters,
                        previous_parameters=previous_parameters,
                    )
                    peer.configure(
                        profile.receiver_enable_commands
                        if measurement_direction == "tx"
                        else profile.post_config_commands
                    )
                previous_parameters = dict(case.parameters)
                time.sleep(max(0.10, profile.cooldown_s))
                _warm_up_radio_path(
                    radio,
                    peer,
                    profile,
                    case,
                    measurement_direction,
                )

            radio.drain(wait_s=0.03)
            if peer is not None:
                peer.drain(wait_s=0.03)
            transmission = None
            receiver_lines_during_trigger: tuple[str, ...] = ()

            def trigger() -> None:
                nonlocal transmission, receiver_lines_during_trigger
                if measurement_direction == "tx":
                    frame_count = len(
                        profile.transmit.frame_sizes(case.payload_bytes)
                    )
                    pacing_ms = profile.receive.inter_frame_gap_ms
                    if profile.transmit.mode == "text_line" and frame_count > 1:
                        pacing_ms += max(
                            estimate_airtime_s(profile, frame_size, case.parameters)
                            for frame_size in profile.transmit.frame_sizes(
                                case.payload_bytes
                            )
                        ) * 1000.0
                    transmission = radio.send_packet(
                        profile,
                        case.payload_bytes,
                        inter_frame_gap_ms=pacing_ms,
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

            if measurement_direction == "rx":
                radio.configure(profile.receiver_enable_commands)
                time.sleep(0.05)

            capture = sampler.capture(
                pre_s=profile.capture.pre_s,
                after_trigger_s=case.capture_after_trigger_s,
                trigger=trigger,
            )
            measured_lines = radio.drain(wait_s=0.08)
            peer_lines = (
                peer.drain(wait_s=profile.receive.post_receive_s)
                if peer is not None
                else ()
            )
            if measurement_direction == "rx" and profile.restore_after_receive:
                radio.configure(profile.post_config_commands)
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
                expected_event_count=len(transmission.frame_payload_bytes),
                search_window_s=min(
                    case.capture_after_trigger_s,
                    case.estimated_event_s * 1.5
                    + profile.capture.search_window_margin_s,
                ),
                fallback_window_s=(
                    max(
                        0.001,
                        case.estimated_event_s - profile.receive.post_receive_s,
                    )
                    if measurement_direction == "rx" and packet_received
                    else None
                ),
                # RX current is nearly flat while the radio listens, so tiny
                # noise spikes can otherwise win threshold-based event
                # selection. Integrate one deterministic on-air window for RX;
                # TX continues to use measured event boundaries.
                integration_window_s=(
                    case.estimated_airtime_s
                    if (
                        measurement_direction == "rx"
                        or profile.capture.align_tx_airtime_window
                    )
                    else None
                ),
                align_integration_window=(
                    measurement_direction == "tx"
                    and profile.capture.align_tx_airtime_window
                ),
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
            if case.case_index < len(cases):
                time.sleep(profile.cooldown_s)
                if _should_reset_between_runs(profile, case):
                    if profile.power_cycle_between_runs:
                        sampler.power_off()
                        time.sleep(profile.power_cycle_off_s)
                        sampler.power_on()
                        time.sleep(boot_wait_s)
                        radio.drain(wait_s=0.25)
                    else:
                        radio.configure(profile.inter_run_commands)
                    _restore_after_reset(
                        radio,
                        profile,
                        case.parameters,
                        profile.post_config_commands,
                    )
                    if peer is not None:
                        peer.configure(profile.inter_run_commands)
                        _restore_after_reset(
                            peer,
                            profile,
                            case.parameters,
                            (
                                profile.receiver_enable_commands
                                if measurement_direction == "tx"
                                else profile.post_config_commands
                            ),
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
