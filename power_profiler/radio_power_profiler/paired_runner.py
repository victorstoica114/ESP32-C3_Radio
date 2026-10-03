"""Bounded E79 five-transfer batch, with two PPK2 records per transfer.

Defaults preserve the 32-byte/GFSK200/+13 dBm pilot. Campaign orchestration
selects one catalog condition per invocation. Explicit fragmented mode proves
every physical frame of a 128/512/1024-byte transfer independently.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .analysis import analyze_capture
from .marker_analysis import (
    analyze_tx_marker_pair, INTEGRATION_METHOD as MARKER_METHOD,
    MARKER_SOURCE, MEASUREMENT_SCOPE as MARKER_SCOPE, EXCESS_DEFINITION,
    analyze_radio_marker_pair, RADIO_INTEGRATION_METHOD, RADIO_MARKER_SOURCE,
    RADIO_MARKER_SOURCES, RADIO_MEASUREMENT_SCOPE, RADIO_ROLE_SCOPES,
    RADIO_TOTALS_INTEGRATION_METHOD, TOTAL_ONLY_ENERGY_POLICY, TOTAL_ONLY_EXCESS_DEFINITION,
    FILTER_RADIO_TOTALS_INTEGRATION_METHOD, FILTER_TOTAL_ONLY_ENERGY_POLICY,
    ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD, ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY,
)
from .models import Metrics
from .fragment_marker_analysis import (
    analyze_fragmented_radio_marker_pair, FRAGMENT_TOTALS_INTEGRATION_METHOD,
)
from .paired_ppk import capture_pair, ContinuousDrain
from .planning import build_cases, resolve_rate_bps
from .ppk import Ppk2Sampler, SAMPLE_RATE_HZ
from .profiles import load_profile, override_profile
from .results import ResultWriter
from .runner import _received_all_frames, _warm_up_radio_path
from .serial_radio import SerialRadio


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _port(port: str) -> str:
    normalized = port.strip().upper().removeprefix("\\\\.\\")
    if not re.fullmatch(r"COM[1-9][0-9]*", normalized):
        raise ValueError("Explicit Windows COM ports are required")
    return normalized


def _usb_metadata():
    from serial.tools.list_ports import comports
    return {item.device.upper(): {"device": item.device, "serial_number": item.serial_number,
                                  "vid": item.vid, "pid": item.pid, "hwid": item.hwid,
                                  "description": item.description}
            for item in comports()}


def _wait_for_usb_ports(ports, *, timeout_s=12.0, poll_interval_s=.5):
    """Wait for guard-close USB re-enumeration before opening any endpoint."""
    deadline = time.monotonic() + timeout_s
    waiting = False
    while True:
        usb = _usb_metadata()
        missing = [port for port in ports if port not in usb]
        if not missing:
            if waiting:
                print("All paired UART/PPK2 ports are enumerated", flush=True)
            return usb
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"USB enumeration timed out after {timeout_s:g}s; missing required ports: "
                + ", ".join(missing)
            )
        if not waiting:
            print("Waiting for paired USB ports to re-enumerate: " + ", ".join(missing), flush=True)
            waiting = True
        time.sleep(min(poll_interval_s, remaining))


def _configure_radio_marker(radio, role):
    """Set the firmware role outside capture, then require exact hardware-route readback."""
    command = "AT+MARKER=" + role.upper()
    set_lines = radio.command(command, drain_before=False).lines
    if "OK" not in set_lines or any(line.upper().startswith(("#ERROR", "ERROR")) for line in set_lines):
        raise ValueError(f"{role}: marker role configuration was not acknowledged: {set_lines!r}")
    marker_lines = radio.command("AT+MARKER?", drain_before=False).lines
    source = "RAT_GPO0" if role == "tx" else "RAT_GPO1"
    expected = f"+MARKER:ROLE={role.upper()},DIO=17,SOURCE={source},ACTIVE=HIGH"
    replies = [line for line in marker_lines if line.startswith("+MARKER:")]
    if replies != [expected] or "OK" not in marker_lines or any(line.upper().startswith(("#ERROR", "ERROR")) for line in marker_lines):
        raise ValueError(f"{role}: local marker configuration is missing or inconsistent: {marker_lines!r}")
    return {
        "marker_set_command": command, "marker_set_reply": list(set_lines),
        "marker_reply": list(marker_lines),
        "radio_marker": {"role": role.upper(), "dio": 17, "source": source,
                         "active": "HIGH", "ppk_input": "D0"},
    }


def _preflight(radio, role, integration_mode="modeled", *, rf_profile="GFSK200",
               tx_power_dbm=13, rate_bps=200000):
    version_lines = radio.command("AT+VERSION?", drain_before=False).lines
    versions = [match.group(1) for line in version_lines
                if (match := re.match(r"\+VERSION:E79_AT_MODEM,(0\.3\.[012])(?:,|$)", line))]
    if len(versions) != 1:
        raise ValueError(f"{role}: expected E79_AT_MODEM firmware 0.3.0, 0.3.1 or 0.3.2, got {version_lines!r}")
    result = {"firmware_version": versions[0], "version_reply": list(version_lines)}
    if integration_mode == "radio_markers":
        if versions[0] != "0.3.2":
            raise ValueError(f"{role}: independent radio markers require E79_AT_MODEM firmware 0.3.2")
        result.update(_configure_radio_marker(radio, role))
    elif integration_mode == "tx_marker" and role == "tx" and versions[0] == "0.3.2":
        result.update(_configure_radio_marker(radio, "tx"))
    # A role change can reopen RF, so read actual modem state after configuring it.
    config_lines = radio.command("AT+CFG?", drain_before=False).lines
    lines = [line for line in config_lines if line.startswith("+CFG:")]
    if len(lines) != 1:
        raise ValueError(f"{role}: missing or ambiguous AT+CFG? response")
    config = dict(part.split("=", 1) for part in lines[0][5:].split(",") if "=" in part)
    expected = {"PROFILE": rf_profile, "RATE": str(int(rate_bps)), "PWR": str(tx_power_dbm),
                "RX": "OFF" if role == "tx" else "ON", "SLEEP": "NO", "DEBUG": "OFF"}
    if integration_mode == "radio_markers":
        expected["MARKER"] = role.upper()
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{role}: actual modem configuration does not match the requested batch: {config}; expected {expected}")
    result.update(config_reply=list(config_lines), config=config)
    if integration_mode == "tx_marker" and role == "tx":
        if versions[0] not in {"0.3.1", "0.3.2"}:
            raise ValueError("TX hardware marker requires E79_AT_MODEM firmware 0.3.1 or 0.3.2")
        marker_lines = radio.command("AT+TXMARKER?", drain_before=False).lines
        expected_marker = "+TXMARKER:DIO=17,SOURCE=RAT_GPO0,ACTIVE=HIGH"
        replies = [line for line in marker_lines if line.startswith("+TXMARKER:")]
        if replies != [expected_marker] or "OK" not in marker_lines or any(line.startswith("#ERROR") for line in marker_lines):
            raise ValueError(f"TX marker configuration is missing or inconsistent: {marker_lines!r}")
        result["tx_marker_reply"] = list(marker_lines)
        result["tx_marker"] = {"dio": 17, "source": "RAT_GPO0", "active": "HIGH", "ppk_input": "D0"}
    return result


def _send_one_transfer(receiver, transmitter, profile, case):
    transmission = transmitter.send_packet(profile, case.payload_bytes, wait_for_completion=True,
                                            completion_timeout_s=2.0, inter_frame_gap_ms=0)
    return transmission, receiver.drain_bounded(duration_s=profile.receive.post_receive_s)


def _save_pairing(root: Path, manifest: dict) -> None:
    temporary = root / "pairing.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(root / "pairing.json")
    fields = ["run_id", "paired_transfer_id", "status", "tx_status", "rx_status", "packet_received"]
    with (root / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(manifest["rows"])


def _row(profile, case, role, endpoint, peer, metrics, capture, transmission, received, tx_lines, rx_lines, status, ppk_mode):
    row = dataclasses.asdict(metrics)
    row.pop("analysis_diagnostics", None)
    row.update(
        run_id=f"run_{case.case_index:05d}", timestamp_utc=_now(),
        profile_id=profile.profile_id, module=profile.display_name,
        firmware_selection=(profile.firmware_selection + "; observed " + role.upper() + " modem "
                            + endpoint.get("modem_preflight", {}).get("firmware_version", "unverified")),
        measurement_direction=role,
        measured_port=endpoint["radio_port"], peer_port=peer["radio_port"],
        transmitter_port=endpoint["radio_port"] if role == "tx" else peer["radio_port"],
        receiver_port=endpoint["radio_port"] if role == "rx" else peer["radio_port"],
        repetition=case.repetition, payload_bytes=case.payload_bytes,
        frame_count=len(transmission.frame_payload_bytes) if transmission else len(profile.transmit.frame_sizes(case.payload_bytes)),
        max_frame_payload_bytes=profile.transmit.frame_payload_bytes or profile.transmit.max_payload_bytes,
        serial_content_bytes=transmission.content_bytes if transmission else "",
        parameters_json=json.dumps(case.parameters, sort_keys=True), ppk_mode=ppk_mode,
        voltage_mv=endpoint["voltage_mv"], estimated_airtime_ms=case.estimated_airtime_s * 1000,
        estimated_event_ms=case.estimated_event_s * 1000,
        captured_samples=len(capture.samples_uA) if capture else 0,
        sample_loss_percent=capture.sample_loss_percent if capture else "",
        event_mean_uA=metrics.tx_mean_uA, event_peak_uA=metrics.tx_peak_uA,
        rx_mean_uA=metrics.tx_mean_uA if role == "rx" else "",
        rx_peak_uA=metrics.tx_peak_uA if role == "rx" else "",
        integration_windows_ms=json.dumps(metrics.integration_windows_ms),
        radio_response=" | ".join(tx_lines if role == "tx" else rx_lines),
        transmitter_response=" | ".join(tx_lines), receiver_response=" | ".join(rx_lines),
        packet_received=received if received is not None else "",
        packet_lost=not received if received is not None else "", status=status,
    )
    return row


def run_paired_pilot(
    *, tx_radio_port: str, rx_radio_port: str, tx_ppk_port: str, rx_ppk_port: str,
    tx_voltage_mv: int, rx_voltage_mv: int, output_root: Path, repetitions: int = 5,
    interface_label: str = "CH340", tx_identity: str = "", rx_identity: str = "",
    voltage_confirmed: bool = False, voltage_provenance: str = "",
    ppk_mode: str = "ampere", integration_mode: str = "modeled",
    payload_bytes: int = 32, rf_profile: str = "GFSK200", tx_power_dbm: int = 13,
    marker_totals_only: bool = False, fragmented: bool = False,
    filter_aware_totals: bool = False,
    filter_history_policy: str = "current_equivalence_v1",
) -> Path:
    ports = [_port(port) for port in (tx_radio_port, rx_radio_port, tx_ppk_port, rx_ppk_port)]
    if len(set(ports)) != 4:
        raise ValueError("All four UART/PPK2 ports must be distinct")
    if repetitions != 5:
        raise ValueError("This bounded batch requires exactly five measured transfers")
    if ppk_mode not in {"ampere", "source"}:
        raise ValueError("PPK mode must be explicitly ampere or source")
    if integration_mode not in {"modeled", "tx_marker", "radio_markers"}:
        raise ValueError("Integration mode must be modeled, tx_marker or radio_markers")
    if type(marker_totals_only) is not bool:
        raise ValueError("marker_totals_only must be an explicit boolean")
    if marker_totals_only and integration_mode != "radio_markers":
        raise ValueError("Marker totals only is supported only with independent radio_markers")
    if type(fragmented) is not bool:
        raise ValueError("fragmented must be an explicit boolean")
    if fragmented and (integration_mode != "radio_markers" or not marker_totals_only):
        raise ValueError("Fragmented batches require radio_markers with marker_totals_only")
    if type(filter_aware_totals) is not bool:
        raise ValueError("filter_aware_totals must be an explicit boolean")
    if filter_aware_totals and (not marker_totals_only or integration_mode != "radio_markers" or fragmented):
        raise ValueError("Filter-aware totals require nonfragmented radio_markers with marker_totals_only")
    if (not isinstance(filter_history_policy, str)
            or filter_history_policy not in {"current_equivalence_v1", "energy_relative_v2"}
            or (filter_history_policy != "current_equivalence_v1" and not filter_aware_totals)):
        raise ValueError("An explicit supported history policy requires filter-aware totals")
    energy_budget = filter_history_policy == "energy_relative_v2"
    energy_policy = (ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY if energy_budget else
                     FILTER_TOTAL_ONLY_ENERGY_POLICY if filter_aware_totals else TOTAL_ONLY_ENERGY_POLICY)
    hardware_markers = integration_mode != "modeled"
    independent_markers = integration_mode == "radio_markers"
    marker_method = (FRAGMENT_TOTALS_INTEGRATION_METHOD if fragmented else
                     ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD if energy_budget else
                     FILTER_RADIO_TOTALS_INTEGRATION_METHOD if filter_aware_totals else
                     RADIO_TOTALS_INTEGRATION_METHOD if marker_totals_only else
                     RADIO_INTEGRATION_METHOD if independent_markers else MARKER_METHOD)
    marker_source = RADIO_MARKER_SOURCE if independent_markers else MARKER_SOURCE
    marker_scope = RADIO_MEASUREMENT_SCOPE if independent_markers else MARKER_SCOPE
    if fragmented:
        marker_scope += " Sum all local frame intervals; exclude inter-frame gaps."
    if not voltage_confirmed or not voltage_provenance.strip():
        raise ValueError("Confirm both actual input voltages and record their provenance before running")
    if not all(isinstance(v, int) and not isinstance(v, bool) and 800 <= v <= 5000 for v in (tx_voltage_mv, rx_voltage_mv)):
        raise ValueError("Explicit actual input voltages in mV are required")
    if not tx_identity.strip() or not rx_identity.strip() or not interface_label.strip():
        raise ValueError("Record both physical radio identities and the interface context")
    catalog_profile = load_profile("RADIO_EBYTE_E79_CC1352P")
    axes = {axis.name: axis.values for axis in catalog_profile.axes}
    allowed_sizes = (128, 512, 1024) if fragmented else (8, 32, 64)
    if (not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool)
            or payload_bytes not in allowed_sizes or payload_bytes not in catalog_profile.payload_sizes):
        raise ValueError(f"Paired {'fragmented' if fragmented else 'single-packet'} batches support only catalog payloads {allowed_sizes}")
    frame_sizes = catalog_profile.transmit.frame_sizes(payload_bytes)
    if frame_sizes != ((64,) * (payload_bytes // 64) if fragmented else (payload_bytes,)):
        raise ValueError("Unexpected physical frame layout for this paired batch")
    if not isinstance(rf_profile, str) or rf_profile not in axes["rf_profile"]:
        raise ValueError(f"RF profile must be one of {axes['rf_profile']}")
    if (not isinstance(tx_power_dbm, int) or isinstance(tx_power_dbm, bool)
            or tx_power_dbm not in axes["tx_power_dbm"]):
        raise ValueError(f"TX power must be one of {axes['tx_power_dbm']} dBm")
    if fragmented and tx_power_dbm != 13:
        raise ValueError("The fragmented measurement matrix requires +13 dBm")
    profile = override_profile(catalog_profile, sizes=(payload_bytes,), repetitions=repetitions,
                               axis_overrides={"rf_profile": (rf_profile,), "tx_power_dbm": (tx_power_dbm,)})
    profile = dataclasses.replace(
        profile,
        firmware_selection=(profile.firmware_selection.split(";", 1)[0]
                            + "; modeled firmware 0.3.0/0.3.1/0.3.2; common TX marker requires TX 0.3.1/0.3.2"
                            + "; independent radio markers require both radios 0.3.2"),
        # This CH340 fixture needs a normal reset after the PPK power handoff.
        # SerialRadio pulses RTS once, before its initial AT synchronization.
        serial_reset_on_open=(interface_label.strip().upper() == "CH340"),
    )
    tx_cases, rx_cases = build_cases(profile, "tx"), build_cases(profile, "rx")
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_e79_paired_pilot"
    root = Path(output_root) / session_id
    root.mkdir(parents=True, exist_ok=False)
    endpoints = {
        "tx": {"radio_port": ports[0], "ppk_port": ports[2], "voltage_mv": tx_voltage_mv, "identity": tx_identity},
        "rx": {"radio_port": ports[1], "ppk_port": ports[3], "voltage_mv": rx_voltage_mv, "identity": rx_identity},
    }
    manifest = {
        "schema_version": 1, "session_id": session_id, "created_utc": _now(), "status": "running",
        "interface_label": interface_label, "endpoints": endpoints, "expected_rows": len(tx_cases),
        "profile_id": profile.profile_id, "payload_bytes": payload_bytes, "rf_profile": rf_profile, "tx_power_dbm": tx_power_dbm,
        "frame_count": len(frame_sizes), "max_frame_payload_bytes": profile.transmit.frame_payload_bytes,
        "fragmented": fragmented,
        "voltage_confirmed": voltage_confirmed, "voltage_provenance": voltage_provenance,
        "ppk_mode": ppk_mode, "serial_dtr": False, "serial_rts": False, "boot_wait_s": 6.0,
        "serial_reset_on_open": profile.serial_reset_on_open,
        "serial_reset_rts_pulse_ms": 100 if profile.serial_reset_on_open else 0,
        "serial_reset_scope": "once_per_radio_before_initial_AT_sync_and_preflight" if profile.serial_reset_on_open else "disabled",
        "integration_mode": integration_mode,
        "marker_totals_only": marker_totals_only,
        "ppk_sampling_policy": "stopped_during_postprocessing; resumed_between_valid_transfers_only",
        "ppk_postprocessing_power_policy": "DUT power remains ON; only sampling is stopped",
        "hardware_synchronized": False, "synchronization": "host_coordinated_independent_sample_clocks",
        "measurement_scope": marker_scope if hardware_markers else "TX modeled event window; RX modeled listening window, excluding full transaction claims",
        "rx_metric_definition": RADIO_ROLE_SCOPES["rx"] if independent_markers else "RX consumption during common TX hardware interval; not independently delimited RX energy" if hardware_markers else "Fixed listening window at host trigger; not a detected RX packet event. UART/command latency can precede RF activity.",
        "marker_contract": {"source": marker_source, "ppk_input": "D0", "marker_bit": 0,
                            "width_tolerance_samples": None if independent_markers else 2,
                            "minimum_pulse_samples": 3,
                            "energy_excess_definition": TOTAL_ONLY_EXCESS_DEFINITION if marker_totals_only else EXCESS_DEFINITION} if hardware_markers else None,
        "warmup": "Profile warm-up is unmeasured; only its bounded initialization retries are allowed",
        "sample_rate_hz": SAMPLE_RATE_HZ, "rows": [], "errors": [], "warnings": [],
    }
    if independent_markers:
        manifest.update(rx_arming_policy="continuous_across_warmup_and_five_transfers",
                        rx_rearm_between_transfers=False)
        manifest["marker_contract"].update(
            role_sources=RADIO_MARKER_SOURCES,
            width_comparison="not_applicable_independent_radio_intervals",
        )
    if marker_totals_only:
        manifest["energy_policy"] = energy_policy
        manifest["marker_contract"]["energy_policy"] = energy_policy
    if filter_aware_totals:
        manifest["filter_aware_totals"] = True
    if energy_budget:
        manifest["filter_history_policy"] = filter_history_policy
    if fragmented:
        manifest.update(integration_method=marker_method, frame_payload_bytes=list(frame_sizes))
        manifest["marker_contract"].update(expected_frame_count=len(frame_sizes),
                                           inter_frame_energy="excluded")
    _save_pairing(root, manifest)
    samplers, radios, writers = {}, {}, {}
    holding = None
    try:
        usb = _wait_for_usb_ports(ports)
        for role, endpoint in endpoints.items():
            for port_type in ("radio", "ppk"):
                port = endpoint[port_type + "_port"]
                if port not in usb:
                    raise RuntimeError(f"{role}: {port_type} port {port} is not currently enumerated")
                endpoint[port_type + "_usb"] = usb[port]
            if not endpoint["ppk_usb"]["serial_number"]:
                raise RuntimeError(f"{role}: cannot establish the PPK2 USB serial identity")
        for role, endpoint in endpoints.items():
            writers[role] = ResultWriter(root / role, {
                **manifest, "profile": dataclasses.asdict(profile), "measurement_direction": role,
                "radio_port": endpoint["radio_port"], "measured_port": endpoint["radio_port"],
                "peer_port": endpoints["rx" if role == "tx" else "tx"]["radio_port"],
                "transmitter_port": ports[0], "receiver_port": ports[1],
                "ppk_port": endpoint["ppk_port"], "voltage_mv": endpoint["voltage_mv"],
                "ppk_mode": ppk_mode, "save_raw": True, "test_count": len(tx_cases),
                "baseline_state": "rx_off" if role == "tx" else "rx_listening",
            })
            samplers[role] = Ppk2Sampler(endpoint["ppk_port"], voltage_mv=endpoint["voltage_mv"])
            modifiers = samplers[role].api.modifiers
            if modifiers.get("HW") is None or modifiers.get("Calibrated") is None:
                raise RuntimeError(f"{role}: missing PPK2 calibration/hardware metadata")
            endpoint["ppk_calibration_metadata"] = modifiers
            if ppk_mode == "source":
                samplers[role].api.use_source_meter()
                samplers[role].api.set_source_voltage(endpoint["voltage_mv"])
                samplers[role].mode = "source"
        # Both measurement paths are owned before enabling either DUT path.
        for sampler in samplers.values():
            sampler.start_continuous()
        holding = ContinuousDrain(samplers)
        holding.start()
        time.sleep(6.0)
        holding.check()
        for role, endpoint in endpoints.items():
            manifest["lifecycle"] = {"phase": "uart_open_and_initial_sync", "role": role,
                                     "port": endpoint["radio_port"]}
            radios[role] = SerialRadio(endpoint["radio_port"], profile.baudrate,
                                       dtr=False, rts=False,
                                       reset_on_open=profile.serial_reset_on_open)
            manifest["lifecycle"]["phase"] = "radio_setup_commands"
            radios[role].configure(profile.setup_commands)
            manifest["lifecycle"]["phase"] = "radio_profile_parameters"
            radios[role].configure_profile_parameters(profile, tx_cases[0].parameters)
            manifest["lifecycle"]["phase"] = "radio_role_commands"
            radios[role].configure(profile.post_config_commands if role == "tx" else profile.receiver_enable_commands)
            manifest["lifecycle"]["phase"] = "radio_preflight"
            endpoint["modem_preflight"] = _preflight(
                radios[role], role, integration_mode, rf_profile=rf_profile,
                tx_power_dbm=tx_power_dbm, rate_bps=resolve_rate_bps(profile, tx_cases[0].parameters),
            )
        manifest["lifecycle"] = {"phase": "endpoint_matching"}
        for key in ("FREQ", "SYNC"):
            tx_value = endpoints["tx"]["modem_preflight"]["config"].get(key)
            rx_value = endpoints["rx"]["modem_preflight"]["config"].get(key)
            if not tx_value or tx_value != rx_value:
                raise RuntimeError(f"The two E79 endpoints disagree on {key}")
        for role in endpoints:
            path = root / role / "metadata.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata["endpoints"] = endpoints
            metadata["observed_endpoint"] = endpoints[role]
            path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        _save_pairing(root, manifest)
        time.sleep(max(.1, profile.cooldown_s))
        manifest["lifecycle"] = {"phase": "unmeasured_warmup"}
        _warm_up_radio_path(radios["tx"], radios["rx"], profile, tx_cases[0], "tx")
        for tx_case, rx_case in zip(tx_cases, rx_cases):
            holding.check()
            run_id = f"run_{tx_case.case_index:05d}"
            manifest["lifecycle"] = {"phase": "paired_transfer", "run_id": run_id}
            pair = {"run_id": run_id, "paired_transfer_id": f"{session_id}:{run_id}", "status": "capturing"}
            manifest["rows"].append(pair)
            _save_pairing(root, manifest)
            radios["tx"].drain_bounded(duration_s=.03)
            radios["rx"].drain_bounded(duration_s=.03)
            # Leave the same RX command armed across all packets in local-marker
            # mode, including warm-up, to exercise the RF core's repeat behavior.
            if not independent_markers:
                radios["rx"].configure(profile.receiver_enable_commands)
            time.sleep(.05)
            transfer = {}

            def trigger():
                pair["radio_send_entry_host_ns"] = time.perf_counter_ns()
                transmission, lines = _send_one_transfer(radios["rx"], radios["tx"], profile, rx_case)
                transfer.update(transmission=transmission, rx_lines=lines)

            holding.pause()
            holding.check()
            after_s = max(tx_case.capture_after_trigger_s, rx_case.capture_after_trigger_s)
            if fragmented:
                # Include bounded UART command/acknowledgment gaps in the record,
                # never in marker energy. The capture also waits for the sender.
                after_s = max(after_s, tx_case.estimated_airtime_s + .06 * len(frame_sizes)
                              + profile.receive.post_receive_s + .25)
            captured = capture_pair(samplers, pre_s=profile.capture.pre_s,
                                    after_trigger_s=after_s,
                                    trigger=trigger, wire_directory=root / "wire" / run_id)
            # capture_pair stops and drains both PPKs before returning. Keep
            # sampling stopped through RAW compression, analysis and persistence;
            # neither AVERAGE_STOP nor this pause changes either DUT power path.
            pair["timing"] = captured.timing
            pair["capture_errors"] = captured.errors
            pair["wire_paths"] = {role: str(Path(path).relative_to(root)) for role, path in captured.wire_paths.items()}
            # Persist both decoded RAW files before analyzing either endpoint.
            raw_errors = {}
            for role, capture in captured.captures.items():
                try:
                    path = writers[role].save_raw(run_id, capture)
                    pair[role + "_raw"] = path.relative_to(root).as_posix()
                except Exception as exc:
                    raw_errors[role] = f"RAW save failed: {exc}"
            transmission = transfer.get("transmission")
            tx_lines = tuple(transmission.response_lines if transmission else ())
            rx_lines = tuple(transfer.get("rx_lines", ()))
            if not captured.errors:
                tx_lines += tuple(radios["tx"].drain_bounded(duration_s=.08))
                rx_lines += tuple(radios["rx"].drain_bounded(duration_s=profile.receive.post_receive_s))
            received = _received_all_frames(transmission.expected_payloads, rx_lines) if transmission else None
            pair["packet_received"] = received
            if fragmented and transmission is not None:
                pair["frame_payload_bytes"] = list(transmission.frame_payload_bytes)
            radio_error = any(line.upper().startswith("#ERROR") for line in (*tx_lines, *rx_lines))
            marker_metrics = {}
            if hardware_markers:
                try:
                    analyze_markers = analyze_radio_marker_pair if independent_markers else analyze_tx_marker_pair
                    total_options = ({"marker_totals_only": True,
                                      "calibrations": {role: endpoint["ppk_calibration_metadata"]
                                                       for role, endpoint in endpoints.items()}}
                                     if marker_totals_only else {})
                    if filter_aware_totals:
                        total_options["filter_aware_totals"] = True
                        total_options["filter_history_policy"] = filter_history_policy
                    if fragmented:
                        analyze_markers = analyze_fragmented_radio_marker_pair
                        total_options.pop("marker_totals_only")
                        total_options["expected_frame_count"] = len(frame_sizes)
                    marker_metrics, marker_diagnostics = analyze_markers(
                        captured.captures, sample_rate_hz=SAMPLE_RATE_HZ,
                        voltages_mv={role: endpoint["voltage_mv"] for role, endpoint in endpoints.items()},
                        wire_paths=captured.wire_paths,
                        **total_options,
                    )
                except Exception as exc:
                    marker_diagnostics = {"valid": False, "marker_bit": 0, "source": marker_source,
                        "roles": {}, "reasons": [f"Marker analysis failed: {type(exc).__name__}: {exc}"], "warnings": []}
                if marker_totals_only:
                    marker_diagnostics["energy_policy"] = energy_policy
                prerequisite_errors = []
                if raw_errors:
                    prerequisite_errors.append(f"RAW evidence incomplete: {raw_errors}")
                if captured.errors:
                    prerequisite_errors.append(f"Paired acquisition failed: {captured.errors}")
                if transmission is None:
                    prerequisite_errors.append("Radio transfer metadata missing")
                elif fragmented and (tuple(transmission.frame_payload_bytes) != frame_sizes
                                     or len(transmission.expected_payloads) != len(frame_sizes)
                                     or transmission.content_bytes != payload_bytes):
                    prerequisite_errors.append("Radio transfer frame layout differs from the planned fragments")
                if filter_aware_totals and received is not True:
                    prerequisite_errors.append("Filter-aware paired measurement requires confirmed packet delivery")
                marker_diagnostics["reasons"].extend(prerequisite_errors)
                if marker_diagnostics["reasons"]:
                    marker_diagnostics["valid"] = False
                    marker_metrics = {role: Metrics(False, None, None, integration_method=marker_method,
                        analysis_error="; ".join(marker_diagnostics["reasons"]),
                        analysis_diagnostics={"marker_diagnostics": marker_diagnostics,
                                              "excess_energy_definition": TOTAL_ONLY_EXCESS_DEFINITION if marker_totals_only else EXCESS_DEFINITION,
                                              **({"energy_policy": energy_policy} if marker_totals_only else {})}) for role in endpoints}
                pair["marker_diagnostics"] = marker_diagnostics
                manifest["warnings"].extend(f"{run_id}: {warning}" for warning in marker_diagnostics["warnings"])
            for role, case in (("tx", tx_case), ("rx", rx_case)):
                capture = captured.captures.get(role)
                relevant_errors = {key: value for key, value in captured.errors.items()
                                   if key in {role, role + "_decode", "coordinator", "trigger", "reader_cleanup", "trigger_cleanup", "hold_resume"}}
                error = raw_errors.get(role) or (str(relevant_errors) if relevant_errors else "")
                modeled_samples = int(case.estimated_airtime_s * SAMPLE_RATE_HZ)
                if integration_mode == "modeled" and capture and len(capture.samples_uA) - capture.trigger_index < modeled_samples:
                    error = error or "Posttrigger record does not cover the full modeled integration window"
                if capture and capture.sample_loss_percent > 1:
                    error = error or f"Acquisition sample loss {capture.sample_loss_percent:.3f}% exceeds 1%"
                if capture is None or transmission is None:
                    error = error or "Capture or radio transfer metadata missing"
                if error:
                    metrics = Metrics(False, None, None, analysis_error=error,
                                      integration_method=marker_method if hardware_markers else "",
                                      analysis_diagnostics={"marker_diagnostics": pair["marker_diagnostics"]} if hardware_markers else {})
                elif hardware_markers:
                    metrics = marker_metrics[role]
                else:
                    try:
                        metrics = analyze_capture(
                            capture.samples_uA, trigger_index=capture.trigger_index,
                            sample_rate_hz=SAMPLE_RATE_HZ, voltage_mv=endpoints[role]["voltage_mv"],
                            capture_spec=profile.capture, expected_event_count=1,
                            search_window_s=min(case.capture_after_trigger_s, case.estimated_event_s * 1.5 + profile.capture.search_window_margin_s),
                            integration_window_s=case.estimated_airtime_s,
                            align_integration_window=role == "tx", frame_airtimes_s=None,
                            fallback_window_s=max(.001, case.estimated_event_s - profile.receive.post_receive_s) if role == "rx" and received else None,
                        )
                        expected_ms = modeled_samples * 1000 / SAMPLE_RATE_HZ
                        if metrics.event_duration_ms is None or abs(metrics.event_duration_ms - expected_ms) > .005:
                            raise ValueError("Integrated window duration differs from the complete modeled duration")
                    except Exception as exc:
                        metrics = Metrics(False, None, None, analysis_error=f"{type(exc).__name__}: {exc}")
                status = ("analysis_review_required" if metrics.analysis_error else "radio_error" if radio_error
                          else "no_event_detected" if not metrics.event_detected else "rx_missing" if not received else "ok")
                writers[role].save_analysis(run_id, metrics)
                writers[role].add(_row(profile, case, role, endpoints[role], endpoints["rx" if role == "tx" else "tx"],
                                       metrics, capture, transmission, received, tx_lines, rx_lines, status, ppk_mode))
                pair[role + "_status"] = status
                if capture and capture.sample_loss_percent > 1:
                    manifest["warnings"].append(f"{run_id} {role}: sample_loss_percent={capture.sample_loss_percent:.3f}")
            accepted_statuses = {"ok"} if fragmented else {"ok", "rx_missing"}
            pair["status"] = "valid" if all(pair[role + "_status"] in accepted_statuses for role in endpoints) else "failed"
            _save_pairing(root, manifest)
            print(f"[{tx_case.case_index}/{len(tx_cases)}] paired {payload_bytes} B {rf_profile} {tx_power_dbm:+d} dBm: TX={pair['tx_status']}, RX={pair['rx_status']}", flush=True)
            if pair["status"] != "valid":
                raise RuntimeError(f"{run_id}: paired result requires review; no automatic retry")
            if tx_case.case_index < len(tx_cases):
                manifest["lifecycle"] = {"phase": "inter_capture_hold_resume", "run_id": run_id}
                try:
                    holding.start()
                    holding.check()
                except Exception as exc:
                    # A start can succeed on one PPK before failing on the other.
                    # Preserve the completed transfer and stop both instruments
                    # before final file handling; never send the next transfer.
                    pair["hold_resume_error"] = f"{type(exc).__name__}: {exc}"
                    try:
                        holding.pause()
                    except Exception as pause_exc:
                        manifest["errors"].append(f"Partial hold resume reader cleanup: {pause_exc}")
                    for role, sampler in samplers.items():
                        try:
                            sampler.api.stop_measuring()
                            sampler.api.ser.flush()
                        except Exception as stop_exc:
                            manifest["errors"].append(f"{role} partial hold resume stop: {stop_exc}")
                    raise RuntimeError(f"{run_id}: PPK hold resume failed after persisted transfer: {exc}") from exc
                time.sleep(profile.cooldown_s)
        manifest["status"] = "valid"
        manifest["lifecycle"] = {"phase": "measured_batch_completed"}
    except (Exception, KeyboardInterrupt) as exc:
        manifest["status"] = "failed"
        manifest["errors"].append(f"{type(exc).__name__}: {exc}")
        manifest["failure_context"] = dict(manifest.get("lifecycle", {"phase": "acquisition_setup"}))
        manifest["failure_traceback"] = traceback.format_exc()
        print(f"Paired batch failed: {manifest['failure_context']}: {type(exc).__name__}: {exc}", flush=True)
    finally:
        if holding is not None:
            try:
                holding.pause()
                holding.check()
            except Exception as exc:
                manifest["status"] = "failed"
                manifest["errors"].append(f"PPK continuous hold cleanup: {exc}")
        for role, writer in writers.items():
            try:
                writer.write_aggregates()
            except Exception as exc:
                manifest["status"] = "failed"
                manifest["errors"].append(f"{role} aggregates: {exc}")
            finally:
                try:
                    writer.close()
                except Exception as exc:
                    manifest["status"] = "failed"
                    manifest["errors"].append(f"{role} writer close: {exc}")
        for role, radio in radios.items():
            try:
                radio.close()
            except Exception as exc:
                manifest["status"] = "failed"
                manifest["errors"].append(f"{role} radio close: {exc}")
        for role, sampler in samplers.items():
            try:
                sampler.close(keep_power_on=True)
                endpoints[role]["ppk_closed_keep_power_on"] = True
            except Exception as exc:
                manifest["status"] = "failed"
                manifest["errors"].append(f"{role} PPK close: {exc}")
                try:
                    sampler.api.ser.close()
                except Exception as close_exc:
                    manifest["errors"].append(f"{role} PPK serial fallback close: {close_exc}")
        manifest["completed_utc"] = _now()
        _save_pairing(root, manifest)
    return root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("tx-radio-port", "rx-radio-port", "tx-ppk-port", "rx-ppk-port", "tx-identity", "rx-identity", "voltage-provenance"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--tx-voltage-mv", type=int, required=True)
    parser.add_argument("--rx-voltage-mv", type=int, required=True)
    parser.add_argument("--voltage-confirmed", action="store_true")
    parser.add_argument("--interface-label", default="CH340")
    parser.add_argument("--ppk-mode", choices=("ampere", "source"), default="ampere")
    parser.add_argument("--integration-mode", choices=("modeled", "tx_marker", "radio_markers"), default="modeled")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--payload-bytes", type=int, default=32)
    parser.add_argument("--rf-profile", default="GFSK200")
    parser.add_argument("--tx-power-dbm", type=int, default=13)
    parser.add_argument("--marker-totals-only", action="store_true",
                        help="For radio_markers only: prove local total energy from wire ADC; omit baseline/excess")
    parser.add_argument("--filter-aware-totals", action="store_true",
                        help="Opt into bounded PPK range-filter replay for nonfragmented radio marker totals")
    parser.add_argument("--filter-history-policy", default="current_equivalence_v1",
                        choices=("current_equivalence_v1", "energy_relative_v2"),
                        help="Separate 0.01 percent history energy allowance in v2; exact replay remains required")
    parser.add_argument("--fragmented", action="store_true",
                        help="Measure all 2/8/16 physical frames of 128/512/1024 B at +13 dBm")
    parser.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    args["output_root"] = args.pop("output")
    root = run_paired_pilot(**args)
    print(f"Results: {root.resolve()}", flush=True)
    return 0 if json.loads((root / "pairing.json").read_text(encoding="utf-8"))["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
