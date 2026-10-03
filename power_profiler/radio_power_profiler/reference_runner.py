"""Five whole paired transfers at the agreed 5 V module reference point.

RX is a modeled listening window, not an independently detected RF interval.
No hardware is opened at import. Power stays on when serial ports are released.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import re
import shutil
import statistics
import struct
import time
import uuid
from pathlib import Path

from .analysis import analyze_capture
from .paired_ppk import ContinuousDrain, capture_pair
from .planning import estimate_airtime_s
from .ppk import Ppk2Sampler, SAMPLE_RATE_HZ
from .profiles import load_profile
from .results import save_raw_capture
from .serial_radio import SerialRadio

PROFILE_ID = "RADIO_EBYTE_E22_SX1268"
PARAMETERS = {"tx_power_dbm": 18, "spreading_factor": 7, "bandwidth_khz": 125}
REFERENCE_POINTS = {
    "RADIO_SX1278_ADAFRUIT_LEVEL_SHIFTER": {
        "label": "SX1278-Adafruit", "manufacturer_prefix": "",
        "parameters": {"tx_power_dbm": 20, "spreading_factor": 7, "bandwidth_khz": 125},
        "frequency_mhz": 433, "description": "level shifter, SF7/BW125/CR4/5, +20 dBm",
        "help_identity": "AT commands for SX1278 (RadioLib)", "content_bytes": 32,
        "control_low": "AT+RX=OFF", "control_high": "AT+RX=ON", "control_settle_s": .15,
        "tx_after_mapping": "AT+RX=OFF", "coding_rate_denominator": 5, "preamble_symbols": 8,
        "setup": ["AT+RX=OFF", "AT+RESET", "AT+DEBUG=OFF",
                  "AT+SET=433,125,7,5,0x14,20,0,8,1,ON",
                  "AT+HEADER=EXPLICIT", "AT+IQ=OFF", "AT+FHSS=0"],
        "expected": {"FREQ": "433.000 MHz", "BW": "125.0 kHz", "SF": "7", "CR": "5",
                     "SYNC": "0x14", "PWR": "20 dBm", "CURR": "0.0 mA (0=skip)",
                     "PREAMBLE": "8", "GAIN": "1", "CRC": "ON", "HEADER": "EXPLICIT",
                     "IQ": "NORMAL", "FHSS": "0", "SLEEP": "NO"},
        "expected_by_role": {"tx": {"RX": "OFF", "DEBUG": "ON"},
                             "rx": {"RX": "ON", "DEBUG": "OFF"}},
        "tx_success_line": "[SX1278] TX OK",
    },
    "RADIO_HC12": {
        "label": "HC-12", "manufacturer_prefix": "",
        "parameters": {"tx_power_dbm": 20, "bit_rate_kbps": 250},
        "frequency_mhz": 437.0, "description": "FU1 (250 kbps preset), +20 dBm, channel 10",
        "help_identity": "AT commands for HC-12", "content_bytes": 30,
        "control_low": "AT+SLEEP", "control_high": "AT+WAKE", "control_settle_s": 1.0,
        "control_after_trigger_s": 2.0,
        "setup": ["AT+WAKE", "AT+DEBUG=OFF", "AT+BRIDGE=ON", "AT+FU=1",
                  "AT+BAUD=9600", "AT+CHAN=10", "AT+UART=8N1", "AT+POWER=8"],
        "expected": {"USB_BAUD": "115200", "HC_BAUD": "9600", "CHANNEL": "10",
                     "POWER": "8", "FU": "1", "UART": "8N1", "BRIDGE": "ON", "SLEEP": "NO"},
        "physical_queries": {"AT+RAW=AT+RB": "OK+B9600", "AT+RAW=AT+RF": "OK+FU1",
                             "AT+RAW=AT+RP": "OK+RP:+20dBm", "AT+RAW=AT+RC": "OK+RC010"},
        "tx_success_line": None,
    },
    PROFILE_ID: {
        "label": "E22", "parameters": PARAMETERS, "frequency_mhz": 433,
        "description": "SF7/BW125/CR4/5, +18 dBm before PA",
        "help_identity": "Ebyte E22 SX1268", "content_bytes": 32,
        "tx_after_mapping": "AT+RX=OFF", "coding_rate_denominator": 5, "preamble_symbols": 8,
        "expected_by_role": {"tx": {"RX": "OFF"}, "rx": {"RX": "ON"}},
        "control_low": "AT+RX=OFF", "control_high": "AT+RX=ON", "control_settle_s": .15,
        "setup": ["AT+RX=OFF", "AT+RESET", "AT+DEBUG=OFF", "AT+FREQ=433", "AT+SF=7",
                  "AT+BW=125", "AT+CR=5", "AT+PREAMBLE=8", "AT+PWR=18", "AT+CRC=ON",
                  "AT+HEADER=EXPLICIT", "AT+SYNC=0x14", "AT+IQ=OFF", "AT+LDRO=OFF"],
        "expected": {"FREQ": "433.000 MHz", "BW": "125.0 kHz", "SF": "7", "CR": "5",
                     "PWR": "18 dBm", "PREAMBLE": "8", "CRC": "ON", "HEADER": "EXPLICIT", "SLEEP": "NO",
                     "SYNC": "0x14", "IQ": "NORMAL", "LDRO": "AUTO/OFF"},
        "tx_success_line": "[SX1268] TX OK",
    },
    "RADIO_EBYTE_E280_SX1280": {
        "label": "E280", "parameters": {"tx_power_dbm": 12, "air_rate": "2M"}, "frequency_mhz": 2450,
        "description": "2 Mbps preset, +12 dBm", "help_identity": "Ebyte E280-2G4T12S",
        "content_bytes": 30, "control_low": "AT+SLEEP", "control_high": "AT+WAKE", "control_settle_s": .3,
        "setup": ["AT+DEBUG=OFF", "AT+RESET", "AT+MODE=TRANSMISSION", "AT+BRIDGE=ON",
                  "AT+ADDR=0", "AT+CHAN=10", "AT+FIXED=OFF", "AT+AIR=2M", "AT+POWER=12",
                  "AT+FHSS=OFF", "AT+LBT=OFF"],
        "expected": {"ADDR": "0x0000", "CHAN": "10", "AIR": "2M_FSK", "POWER": "12 dBm",
                     "FIXED": "OFF", "FHSS": "OFF", "LBT": "OFF", "MODE": "TRANSMISSION",
                     "BRIDGE": "ON", "SLEEP": "NO", "BAUD": "9600", "PARITY": "8N1"},
        "tx_success_line": None,
    },
    "RADIO_EBYTE_E32_433T20D": {
        "label": "E32-433T20D", "parameters": {"tx_power_dbm": 20, "bit_rate_kbps": 19.2},
        "frequency_mhz": 433, "description": "19.2 kbps, +20 dBm",
        "help_identity": "Ebyte E32 (generic", "content_bytes": 30,
        "control_low": "AT+SLEEP", "control_high": "AT+WAKE", "control_settle_s": .3,
        "setup": ["AT+WAKE", "AT+DEBUG=OFF", "AT+BRIDGE=ON",
                  "AT+SETRADIO=0,0,23,8,1,6,1,1,1,0,PP"],
        "expected": {"ADDH": "0", "ADDL": "0", "CHAN": "23", "UART Baud": "115200bps",
                     "UART Parity": "8N1", "Air Data Rate": "19.2kbps", "FEC": "Enable",
                     "Fixed Transmission": "Transparent", "TX Power": "code 0 (20 dBm)",
                     "Runtime mode": "NORMAL", "Bridge": "ON", "HEAD": "C3", "Freq": "32", "Feat": "14"},
        "tx_success_line": None,
    },
    "RADIO_EBYTE_E32_433T33D": {
        "label": "E32-433T33D", "parameters": {"tx_power_dbm": 30, "bit_rate_kbps": 19.2},
        "frequency_mhz": 433, "description": "19.2 kbps, +30 dBm",
        "help_identity": "Ebyte E32 (generic", "content_bytes": 30,
        "control_low": "AT+SLEEP", "control_high": "AT+WAKE", "control_settle_s": 1.0,
        "control_after_trigger_s": 1.0,
        "setup": ["AT+WAKE", "AT+DEBUG=OFF", "AT+BRIDGE=ON",
                  "AT+SETRADIO=0,0,23,8,1,6,2,1,1,0,PP"],
        "expected": {"ADDH": "0", "ADDL": "0", "CHAN": "23", "UART Baud": "115200bps",
                     "UART Parity": "8N1", "Air Data Rate": "19.2kbps", "FEC": "Enable",
                     "Fixed Transmission": "Transparent", "TX Power": "code 1 (30 dBm)",
                     "Runtime mode": "NORMAL", "Bridge": "ON", "HEAD": "C3", "Freq": "32", "Feat": "21"},
        "tx_success_line": None,
    },
    "RADIO_EBYTE_E32_868T20D": {
        "label": "E32-868T20D", "parameters": {"tx_power_dbm": 20, "bit_rate_kbps": 19.2},
        "frequency_mhz": 868, "description": "19.2 kbps, +20 dBm, channel 6",
        "help_identity": "Ebyte E32 (generic", "content_bytes": 30,
        "control_low": "AT+SLEEP", "control_high": "AT+WAKE", "control_settle_s": 1.0,
        "control_after_trigger_s": 1.0,
        "setup": ["AT+WAKE", "AT+DEBUG=OFF", "AT+BRIDGE=ON",
                  "AT+SETRADIO=0,0,6,8,1,6,1,1,1,0,PP"],
        "expected": {"ADDH": "0", "ADDL": "0", "CHAN": "6", "UART Baud": "115200bps",
                     "UART Parity": "8N1", "Air Data Rate": "19.2kbps", "FEC": "Enable",
                     "Fixed Transmission": "Transparent", "TX Power": "code 0 (20 dBm)",
                     "Runtime mode": "NORMAL", "Bridge": "ON", "HEAD": "C3", "Freq": "45", "Feat": "14"},
        "tx_success_line": None,
    },
    "RADIO_EBYTE_E32_868T30D": {
        "label": "E32-868T30D", "parameters": {"tx_power_dbm": 30, "bit_rate_kbps": 19.2},
        "frequency_mhz": 868, "description": "19.2 kbps, +30 dBm, channel 6",
        "help_identity": "Ebyte E32 (generic", "content_bytes": 30,
        "control_low": "AT+SLEEP", "control_high": "AT+WAKE", "control_settle_s": 1.0,
        "control_after_trigger_s": 1.0,
        "setup": ["AT+WAKE", "AT+DEBUG=OFF", "AT+BRIDGE=ON",
                  "AT+SETRADIO=0,0,6,8,1,6,1,1,1,0,PP"],
        "expected": {"ADDH": "0", "ADDL": "0", "CHAN": "6", "UART Baud": "115200bps",
                     "UART Parity": "8N1", "Air Data Rate": "19.2kbps", "FEC": "Enable",
                     "Fixed Transmission": "Transparent", "TX Power": "code 0 (30 dBm)",
                     "Runtime mode": "NORMAL", "Bridge": "ON", "HEAD": "C3", "Freq": "45", "Feat": "1E"},
        "tx_success_line": None,
    },
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def fingerprint(path, root):
    return {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def infer_power_mapping(controls):
    mapping = {}
    for radio, changes in controls.items():
        ordered = sorted(changes, key=changes.get, reverse=True)
        high, low = ordered
        if changes[high] < 1000 or abs(changes[low]) > max(500, changes[high] * .25):
            raise ValueError(f"Ambiguous PPK-to-radio mapping for {radio}: {changes}")
        mapping[radio] = high
    if len(mapping) != 2 or len(set(mapping.values())) != 2:
        raise ValueError("The two radios must map to different PPK current paths")
    return mapping


def readback_fields(lines):
    fields = {}
    for line in lines:
        match = re.match(r"^([^=:]+?)\s*[:=]\s*(.+)$", line)
        if match:
            key, value = (part.strip() for part in match.groups())
            if key in fields:
                raise ValueError(f"Duplicate configuration field: {key}")
            fields[key] = value
    return fields


def verify_physical_readbacks(radio, specification):
    """Require module replies, not merely the bridge's final OK or cached CFG."""
    transcripts = {}
    for command, expected in specification.get("physical_queries", {}).items():
        lines = list(radio.command(command).lines)
        if lines.count(expected) != 1:
            raise ValueError(f"Physical module readback mismatch for {command}: {lines}")
        transcripts[command] = lines
    return transcripts


def configure_reference_roles(radios, specification):
    radios["tx"].command("AT+DEBUG=ON" if specification["tx_success_line"] else "AT+DEBUG=OFF")
    for role, radio in radios.items():
        radio.command(specification.get("tx_after_mapping", specification["control_high"])
                      if role == "tx" else specification["control_high"])


def wire_qa(capture, path, calibration):
    from tools.audit_filter_marker_totals import normalize, replay

    raw = path.read_bytes()
    if len(raw) != 4 * len(capture.samples_uA) or not raw:
        raise ValueError("WIRE/current sample count mismatch")
    words = [word for (word,) in struct.iter_unpack("<I", raw)]
    discontinuities = [i for i in range(1, len(words))
                       if (words[i] >> 18) & 63 != (((words[i - 1] >> 18) & 63) + 1) % 64]
    invalid = [i for i, word in enumerate(words) if ((word >> 14) & 7) > 4 or word & (1 << 17)]
    if discontinuities or invalid:
        raise ValueError(f"WIRE integrity: {len(discontinuities)} counter gaps, {len(invalid)} invalid words")
    coefficients, voltage = normalize(calibration, 5000)
    decoded, _ = replay(words, coefficients, voltage)
    difference = max(abs(actual - expected) for actual, expected in zip(capture.samples_uA, decoded))
    if difference > 1e-6 or len(capture.logic_bits) != len(words) or any(
            logic != word >> 24 for logic, word in zip(capture.logic_bits, words)):
        raise ValueError("Independent WIRE replay differs from captured current/logic")
    if capture.sample_loss_percent > 5 or not all(math.isfinite(value) for value in decoded):
        raise ValueError("Incomplete or nonfinite current capture")
    return {"valid": True, "sample_count": len(words), "counter_discontinuities": 0,
            "invalid_words": 0, "replay_max_difference_uA": difference,
            "limitation": "Modulo-64 continuity cannot detect losses of multiples of 64 samples."}


def validate_reference_result(root, expected_profile_id=None):
    errors = []
    report = json.loads((root / "reference.json").read_text(encoding="utf-8"))
    batch = report.get("accepted_batch")
    specification = REFERENCE_POINTS.get(report.get("profile_id"), {})
    if (report.get("status") != "complete" or not specification
            or (expected_profile_id is not None and report.get("profile_id") != expected_profile_id)
            or report.get("voltage_mv") != 5000 or report.get("parameters") != specification.get("parameters")):
        errors.append("Reference batch configuration/status is invalid")
    if not batch or len(batch.get("pairs", [])) != 5 or len(report.get("aggregates", [])) != 2:
        errors.append("Expected five complete TX/RX pairs and two aggregates")
    if {pair.get("run_id") for pair in (batch or {}).get("pairs", [])} != {f"run_{i:05d}" for i in range(1, 6)}:
        errors.append("Expected five distinct trial identifiers")
    for pair in (batch or {}).get("pairs", []):
        if not pair.get("valid") or not pair.get("packet_received") or set(pair.get("roles", {})) != {"tx", "rx"}:
            errors.append("Incomplete or invalid paired transfer")
        for role in pair.get("roles", {}).values():
            if not role.get("qa", {}).get("valid") or not role.get("metrics", {}).get("event_detected"):
                errors.append("Missing numeric or WIRE validation")
            for key in ("raw", "wire"):
                evidence = role.get(key, {})
                path = (root / evidence.get("path", "")).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    errors.append("Missing or out-of-root capture file")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != evidence.get("sha256"):
                    errors.append("Capture fingerprint changed")
    return {"valid": not errors, "errors": errors,
            "warnings": ["RX measures modeled listening; no exclusive RF reception energy claim."]}


def run_batch(args):
    from serial.tools.list_ports import comports

    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    samplers, radios, drain = {}, {}, None
    specification = REFERENCE_POINTS[args.profile_id]
    label = specification["label"]
    profile = load_profile(args.profile_id)
    airtime = estimate_airtime_s(profile, 32, specification["parameters"])
    report = {"profile_id": args.profile_id, "voltage_mv": 5000, "parameters": specification["parameters"],
              "payload_bytes": 32, "serial_content_bytes": specification["content_bytes"],
              "line_overhead_bytes": profile.transmit.line_overhead_bytes,
              "coding_rate_denominator": specification.get("coding_rate_denominator"),
              "preamble_symbols": specification.get("preamble_symbols"),
              "frequency_mhz": specification["frequency_mhz"], "status": "starting", "accepted_batch": None,
              "voltage_provenance": args.voltage_provenance, "physical_voltage_measured": False,
              "measured_rail": f"{label} only; ESP32 excluded", "ppk_mode": "ampere",
              "tx_confirmation": "Modem success report and exact RX payload" if specification["tx_success_line"]
                                 else "UART write/flush and exact RX payload; transparent modem has no per-packet TX acknowledgment",
              "synchronization": "host coordinated, independent PPK clocks",
              "rx_scope": "Fixed modeled listening interval starting at host trigger; not exclusive RF reception",
              "tx_scope": "Current-threshold TX event", "estimated_airtime_s": airtime,
              "calibrations": {}, "controls": {}, "attempts": [], "errors": []}
    write_json(root / "reference.json", report)
    try:
        usb = {p.device: p for p in comports()}
        report["usb"] = {port: {"serial": usb[port].serial_number, "vid": usb[port].vid, "pid": usb[port].pid}
                         for port in (args.tx_radio_port, args.rx_radio_port, args.ppk_a_port, args.ppk_b_port)}
        detected = dict(Ppk2Sampler.list_devices())
        for role, port in (("tx", args.ppk_a_port), ("rx", args.ppk_b_port)):
            if port not in detected:
                raise ValueError(f"{port} is not a PPK2 data port")
            samplers[role] = Ppk2Sampler(port, voltage_mv=5000)
            samplers[role].start_continuous()
        drain = ContinuousDrain(samplers)
        drain.start()
        report["control_calibrations_by_port"] = {
            sampler.api.ser.port: sampler.api.modifiers for sampler in samplers.values()}
        time.sleep(1)
        setup = specification["setup"]
        report["setup_commands"] = setup
        for role, port in (("tx", args.tx_radio_port), ("rx", args.rx_radio_port)):
            radio = radios[role] = SerialRadio(port, profile.baudrate, command_timeout_s=30, dtr=False, rts=False)
            help_lines = radio.command("AT+HELP", timeout_s=30).lines
            if not any(specification["help_identity"] in line for line in help_lines):
                raise ValueError(f"{port}: wrong module firmware")
            radio.configure(setup)
        changes = {}
        for role, radio in radios.items():
            for item in radios.values():
                item.command(specification["control_low"])
            time.sleep(specification["control_settle_s"])
            drain.pause()
            control = capture_pair(samplers, pre_s=.2,
                                   after_trigger_s=specification.get("control_after_trigger_s", .35),
                                   trigger=lambda radio=radio: radio.command(specification["control_high"]),
                                   wire_directory=root / "controls" / role)
            if control.errors or set(control.captures) != {"tx", "rx"}:
                raise ValueError(f"Power mapping capture failed: {control.errors}")
            changes[role] = {ppk: statistics.median(cap.samples_uA[-10000:])
                            - statistics.median(cap.samples_uA[1000:cap.trigger_index - 500])
                            for ppk, cap in control.captures.items()}
            report["controls"][role] = {"current_change_uA": changes[role], "timing": control.timing}
            drain.start()
        mapping = infer_power_mapping(changes)
        drain.pause()
        samplers = {role: samplers[ppk] for role, ppk in mapping.items()}
        drain = ContinuousDrain(samplers)
        drain.start()
        report["endpoints"] = {role: {"radio_port": radio.port, "ppk_port": samplers[role].api.ser.port}
                               for role, radio in radios.items()}
        report["calibrations"] = {role: sampler.api.modifiers for role, sampler in samplers.items()}
        configure_reference_roles(radios, specification)
        expected = specification["expected"]
        for role, radio in radios.items():
            lines = radio.command("AT+CFG?").lines
            config = readback_fields(lines)
            role_expected = {**expected, **specification.get("expected_by_role", {}).get(role, {})}
            if any(config.get(key) != value for key, value in role_expected.items()):
                raise ValueError(f"{role}: reference configuration readback mismatch: {config}")
            report["endpoints"][role]["config_readback"] = list(lines)
            physical = verify_physical_readbacks(radio, specification)
            if physical:
                report["endpoints"][role]["physical_readbacks"] = physical
        print(label + " configured and PPK mapping verified: " + json.dumps(report["endpoints"]), flush=True)
        token = uuid.uuid4().hex[:8]
        for attempt in range(1, 4):
            batch = {"attempt": attempt, "pairs": [], "status": "running"}
            report["attempts"].append(batch)
            report["status"] = "running"
            directory = root / f"attempt_{attempt:03d}"
            directory.mkdir()
            try:
                for index in range(1, 6):
                    drain.check()
                    time.sleep(1)
                    for radio in radios.values():
                        radio.drain_bounded(duration_s=.03)
                    payload = f"{label}_{token}_{attempt}_{index}_".ljust(specification["content_bytes"], "X")
                    transcript = {}

                    def trigger():
                        radios["tx"]._write_line(payload)
                        transcript["tx"] = list(radios["tx"].drain_bounded(duration_s=.4))
                        transcript["rx"] = list(radios["rx"].drain_bounded(duration_s=.3))

                    drain.pause()
                    paired = capture_pair(samplers, pre_s=.2, after_trigger_s=.8, trigger=trigger,
                                          wire_directory=directory / "wire" / f"run_{index:05d}")
                    pair = {"run_id": f"run_{index:05d}", "payload": payload, "transcript": transcript,
                            "timing": paired.timing, "errors": paired.errors, "roles": {}, "valid": False,
                            "packet_received": transcript.get("rx", []).count(payload) == 1}
                    batch["pairs"].append(pair)
                    if paired.errors or set(paired.captures) != {"tx", "rx"}:
                        raise ValueError(f"Paired capture failed: {paired.errors}")
                    for role, capture in paired.captures.items():
                        raw_path = save_raw_capture(directory / "raw" / role / (pair["run_id"] + ".csv.gz"), capture)
                        wire_path = Path(paired.wire_paths[role])
                        qa = wire_qa(capture, wire_path, report["calibrations"][role])
                        metrics = analyze_capture(capture.samples_uA, trigger_index=capture.trigger_index,
                            sample_rate_hz=SAMPLE_RATE_HZ, voltage_mv=5000, capture_spec=profile.capture,
                            search_window_s=.8, fallback_window_s=airtime if role == "rx" else None,
                            integration_window_s=airtime if role == "rx" else None)
                        if not metrics.event_detected or metrics.analysis_error:
                            raise ValueError(f"{role}: event analysis failed: {metrics.analysis_error}")
                        pair["roles"][role] = {"raw": fingerprint(raw_path, root), "wire": fingerprint(wire_path, root),
                                               "qa": qa, "metrics": dataclasses.asdict(metrics)}
                    success = specification["tx_success_line"]
                    tx_error = any("failed" in line.lower() or line.upper().startswith(("#ERROR", "ERROR"))
                                   for line in transcript.get("tx", []))
                    if not pair["packet_received"] or tx_error or (success is not None and transcript.get("tx", []).count(success) != 1):
                        raise ValueError("Expected one confirmed TX and one exact RX payload")
                    pair["valid"] = True
                    write_json(root / "reference.json", report)
                    print(f"{label} attempt {attempt}: {index}/5 complete pairs", flush=True)
                    drain.start()
                batch["status"] = "complete"
                report["accepted_batch"] = batch
                break
            except ValueError as exc:
                batch.update(status="failed", error=str(exc), captures_retained=False)
                if any(key in paired.errors for key in ("reader_cleanup", "trigger_cleanup")):
                    raise RuntimeError("Acquisition cleanup uncertain; automatic retry prohibited")
                # Delete only this worker's failed capture data inside its new session.
                for name in ("raw", "wire"):
                    target = (directory / name).resolve()
                    if not target.is_relative_to(root) or target == root:
                        raise ValueError("Capture cleanup escaped its session")
                    if target.exists():
                        shutil.rmtree(target)
                print(f"{label} attempt {attempt} failed: {exc}; restarting the whole batch", flush=True)
                drain.start()
                write_json(root / "reference.json", report)
        if report["accepted_batch"] is None:
            raise ValueError("Three complete-batch attempts exhausted")
        report["aggregates"] = []
        for role in ("tx", "rx"):
            rows = [pair["roles"][role]["metrics"] for pair in report["accepted_batch"]["pairs"]]
            aggregate = {"role": role, "trial_count": 5, "scope": report[role + "_scope"]}
            for field in ("energy_total_uJ", "energy_excess_uJ", "charge_total_uC", "event_duration_ms", "tx_mean_uA"):
                values = [row[field] for row in rows]
                aggregate[field + "_mean"] = statistics.fmean(values)
                aggregate[field + "_sd"] = statistics.stdev(values)
            report["aggregates"].append(aggregate)
        report["status"] = "complete"
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(report["errors"][-1], flush=True)
    finally:
        if drain is not None:
            try:
                drain.pause()
            except Exception as exc:
                report["status"] = "failed"
                report["errors"].append(f"Reader cleanup: {exc}")
        for role, radio in radios.items():
            try:
                radio.close()
            except Exception as exc:
                report["status"] = "failed"
                report["errors"].append(f"UART cleanup {role}: {exc}")
        for role, sampler in samplers.items():
            try:
                sampler.close(keep_power_on=True)
            except Exception as exc:
                report["status"] = "failed"
                report["errors"].append(f"PPK cleanup {role}: {exc}")
        write_json(root / "reference.json", report)
        print(f"Results: {root}", flush=True)
    return 0 if report["status"] == "complete" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", choices=tuple(REFERENCE_POINTS), default=PROFILE_ID)
    for flag in ("tx-radio-port", "rx-radio-port", "ppk-a-port", "ppk-b-port", "voltage-provenance"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ports = (args.tx_radio_port, args.rx_radio_port, args.ppk_a_port, args.ppk_b_port)
    if len(set(ports)) != 4:
        parser.error("Four distinct ports required")
    return run_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
