"""Independent offline audit of local PPK2 marker totals; never changes acceptance.

Uses only the standard library. The ADC conversion and three-sample range-change
filter dependency correspond to ppk2-api 0.9.2. No serial or production analysis
modules are imported. Example:

    python tools/audit_radio_marker_totals.py PATH_TO_PAIRED_RESULT

Optional --output creates a new JSON file exclusively; it cannot overwrite any
existing evidence. A mathematically proven total does not accept a failed pair.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_power_profiler.storage import resolve_measurement_path
import re
import struct
from typing import Any
import zlib


SAMPLE_RATE_HZ = 100_000
FILTER_GUARD_SAMPLES = 3
RUN_ID = re.compile(r"run_[0-9]+\Z")
COEFFICIENTS = ("R", "O", "GS", "GI", "S", "I", "UG")


def _evidence(path: Path, root: Path) -> tuple[bytes, dict]:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Evidence path escapes the paired result root")
    data = resolved.read_bytes()
    return data, {"path": path.relative_to(root).as_posix(), "bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest()}


def _calibration(endpoint: dict) -> tuple[dict, float]:
    voltage_mv = float(endpoint["voltage_mv"])
    if not math.isfinite(voltage_mv) or voltage_mv <= 0:
        raise ValueError("Endpoint voltage must be positive and finite")
    source = endpoint["ppk_calibration_metadata"]
    coefficients = {name: {str(i): float(source[name][str(i)]) for i in range(5)}
                    for name in COEFFICIENTS}
    if any(not math.isfinite(value) for values in coefficients.values() for value in values.values()):
        raise ValueError("Calibration coefficient is not finite")
    if any(value <= 0 for value in coefficients["R"].values()):
        raise ValueError("Calibration resistance must be positive")
    return coefficients, voltage_mv / 1000


def direct_current_uA(word: int, coefficients: dict, voltage_v: float) -> float:
    """Calibrated ADC without the stateful range-change filter; reject bad ranges."""
    range_code = (word >> 14) & 7
    if range_code > 4:
        raise ValueError("Wire range is outside 0..4; no clamping is permitted")
    key = str(range_code)
    adc = (word & 0x3FFF) * 4
    unscaled = ((adc - coefficients["O"][key])
                * ((1.8 / 163840) / coefficients["R"][key]))
    result = coefficients["UG"][key] * (
        unscaled * (coefficients["GS"][key] * unscaled + coefficients["GI"][key])
        + (coefficients["S"][key] * voltage_v + coefficients["I"][key])) * 1e6
    if not math.isfinite(result):
        raise ValueError("Independent ADC conversion is not finite")
    return result


def _pulses(words: list[int]) -> list[tuple[int, int]]:
    result, start = [], None
    for index, word in enumerate(words):
        high = bool(word & (1 << 24))
        if high and start is None:
            start = index
        elif not high and start is not None:
            result.append((start, index))
            start = None
    if start is not None:
        result.append((start, len(words)))
    return result


def _interval_qa(words: list[int], anomalies: list[int], start: int, stop: int) -> dict:
    """Inclusive stop checks the transition/word at the falling boundary too."""
    return {
        "checked_indices_inclusive": [start, stop],
        "counter_anomaly_indices": [i for i in anomalies if start <= i <= stop],
        "invalid_range_indices": [i for i in range(max(start, 0), min(stop + 1, len(words)))
                                  if ((words[i] >> 14) & 7) > 4],
        "bit17_set_indices": [i for i in range(max(start, 0), min(stop + 1, len(words)))
                              if words[i] & (1 << 17)],
    }


def _has_faults(qa: dict) -> bool:
    return any(qa[name] for name in ("counter_anomaly_indices", "invalid_range_indices", "bit17_set_indices"))


def _audit_role(root: Path, run_id: str, role: str, metadata: dict,
                metadata_source: dict, tolerance: float) -> dict:
    info: dict[str, Any] = {"role": role, "total_energy_uJ": None,
                            "total_proven": False, "pulses": [], "reasons": [],
                            "sources": {"metadata": metadata_source}}
    reasons = info["reasons"]
    try:
        wire, info["sources"]["wire"] = _evidence(root / "wire" / run_id / f"{role}.ppk2.bin", root)
        packed, info["sources"]["raw_csv_gzip"] = _evidence(root / role / "raw" / f"{run_id}.csv.gz", root)
        if not wire or len(wire) % 4:
            raise ValueError("Wire must contain a nonempty whole number of 32-bit words")
        words = [item[0] for item in struct.iter_unpack("<I", wire)]
        # Read through the gzip trailer: CRC/size errors must fail the audit.
        decoded = gzip.decompress(packed).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        required = {"sample_index", "current_uA", "logic_bits", "trigger"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("RAW CSV is missing required columns")
        currents, triggers, logic_mismatches = [], [], []
        for index, row in enumerate(reader):
            if int(row["sample_index"]) != index:
                raise ValueError("RAW CSV sample indices are not contiguous from zero")
            currents.append(float(row["current_uA"]))
            if int(row["trigger"]) == 1:
                triggers.append(index)
            elif int(row["trigger"]) != 0:
                raise ValueError("RAW trigger must be 0 or 1")
            if index < len(words) and int(row["logic_bits"]) != (words[index] >> 24):
                logic_mismatches.append(index)
        if len(currents) != len(words):
            raise ValueError("Wire and CSV sample counts differ")
        if len(triggers) != 1 or not 10 <= triggers[0] < len(words):
            raise ValueError("Expected one usable software-trigger sample")
        if logic_mismatches:
            raise ValueError(f"CSV digital values differ from wire at {len(logic_mismatches)} samples")
        endpoint = metadata["endpoints"][role]
        coefficients, voltage_v = _calibration(endpoint)
        trigger = triggers[0]
        baseline_start = min(int(.010 * SAMPLE_RATE_HZ), trigger // 4)
        baseline_stop = max(baseline_start + 1, trigger - int(.005 * SAMPLE_RATE_HZ))
        ranges = [(word >> 14) & 7 for word in words]
        counters = [(word >> 18) & 63 for word in words]
        anomalies = [i for i in range(1, len(words)) if counters[i] != (counters[i - 1] + 1) % 64]
        changes = [i for i in range(1, len(words)) if ranges[i] != ranges[i - 1]]
        baseline_qa = _interval_qa(words, anomalies, baseline_start, baseline_stop)
        baseline_nonfinite = [i for i in range(baseline_start, baseline_stop) if not math.isfinite(currents[i])]
        info.update(sample_count=len(words), software_trigger_index=trigger,
                    voltage_v=voltage_v,
                    calibration_flag=endpoint["ppk_calibration_metadata"].get("Calibrated"),
                    counter_anomaly_count=len(anomalies), counter_anomaly_indices=anomalies,
                    baseline_window_samples=[baseline_start, baseline_stop], baseline_qa=baseline_qa,
                    baseline_nonfinite_indices=baseline_nonfinite,
                    baseline_integrity_clean=not _has_faults(baseline_qa) and not baseline_nonfinite,
                    gzip_crc_checked_to_eof=True, wire_csv_logic_match=True)
        windows = _pulses(words)
        info["pulse_count"] = len(windows)
        for start, stop in windows:
            faults = []
            guard_start = start - FILTER_GUARD_SAMPLES
            qa = _interval_qa(words, anomalies, guard_start, stop)
            constant_range = guard_start >= 0 and len(set(ranges[guard_start:stop])) == 1
            pulse: dict[str, Any] = {
                "window_samples": [start, stop], "duration_samples": stop - start,
                "duration_ms": (stop - start) * 1000 / SAMPLE_RATE_HZ,
                "guard_window_samples": [guard_start, stop], "wire_qa": qa,
                "range_counts_guard": dict(collections.Counter(ranges[max(0, guard_start):stop])),
                "range_transitions_guard": [i for i in changes if guard_start < i < stop],
                "constant_valid_range_guard": constant_range and not qa["invalid_range_indices"],
                "direct_adc_dependency_proven": False,
                "adc_csv_max_difference_uA": None, "adc_csv_exact_match": None,
                "adc_csv_within_tolerance": None,
                "proof_passed": False, "total_energy_uJ": None, "csv_total_energy_uJ": None,
                "reasons": faults,
            }
            info["pulses"].append(pulse)
            if start == 0 or stop == len(words):
                faults.append("Pulse touches capture boundary; a complete edge is missing")
            if stop - start < 3:
                faults.append("Pulse has fewer than three samples")
            if start <= trigger:
                faults.append("Pulse does not follow the software trigger")
            if guard_start < 0:
                faults.append("Insufficient preceding samples for decoder dependency proof")
            if _has_faults(qa):
                faults.append("Wire anomaly touches the pulse, its decoder guard, or falling boundary")
            if not constant_range:
                faults.append("Range change reaches the pulse; stateful decoder independence is not proven")
            if any(not math.isfinite(value) for value in currents[start:stop]):
                faults.append("Nonfinite current in pulse")
            pulse["direct_adc_dependency_proven"] = bool(pulse["constant_valid_range_guard"])
            if not qa["invalid_range_indices"]:
                direct = [direct_current_uA(word, coefficients, voltage_v) for word in words[start:stop]]
                differences = [abs(a - b) for a, b in zip(direct, currents[start:stop])]
                max_difference = max(differences)
                finite = all(math.isfinite(value) for value in differences)
                pulse["adc_csv_max_difference_uA"] = max_difference if finite else None
                pulse["adc_csv_exact_match"] = finite and max_difference == 0
                pulse["adc_csv_within_tolerance"] = finite and max_difference <= tolerance
                if not pulse["adc_csv_within_tolerance"]:
                    faults.append("Independently calibrated ADC does not match CSV within tolerance")
                if not faults:
                    pulse["proof_passed"] = True
                    pulse["total_energy_uJ"] = math.fsum(direct) / SAMPLE_RATE_HZ * voltage_v
                    pulse["csv_total_energy_uJ"] = math.fsum(currents[start:stop]) / SAMPLE_RATE_HZ * voltage_v
            if faults:
                reasons.extend(f"Pulse [{start},{stop}): {reason}" for reason in faults)
        if len(windows) != 1:
            reasons.append(f"Expected one unambiguous pulse; observed {len(windows)}")
        if len(windows) == 1 and info["pulses"][0]["proof_passed"]:
            info["total_proven"] = True
            info["total_energy_uJ"] = info["pulses"][0]["total_energy_uJ"]
    except (OSError, EOFError, UnicodeError, ValueError, TypeError, KeyError, OverflowError, zlib.error) as exc:
        reasons.append(f"{type(exc).__name__}: {exc}")
    return info


def audit_result(result_root: Path, *, current_tolerance_uA: float = 1e-6) -> dict:
    """Read evidence and emit diagnostic proof only, never an acceptance decision."""
    if not math.isfinite(current_tolerance_uA) or current_tolerance_uA < 0:
        raise ValueError("Current comparison tolerance must be finite and nonnegative")
    root = resolve_measurement_path(result_root).resolve()
    packed, manifest_source = _evidence(root / "pairing.json", root)
    manifest = json.loads(packed)
    if manifest.get("sample_rate_hz") != SAMPLE_RATE_HZ:
        raise ValueError("Expected the PPK2 100000 Hz sample rate in pairing.json")
    report = {
        "schema_version": 1, "tool": "audit_radio_marker_totals",
        "result_root": str(root), "session_id": manifest.get("session_id"),
        "official_status_unchanged": manifest.get("status"),
        "integration_mode_recorded": manifest.get("integration_mode"),
        "acceptance_changed": False, "sample_rate_hz": SAMPLE_RATE_HZ,
        "current_tolerance_uA": current_tolerance_uA,
        "method": "Independent calibrated ADC integration with a constant-range three-sample dependency guard; no IIR correction, baseline subtraction, clipping or reindexing.",
        "decoder_reference": "ppk2-api 0.9.2 get_adc_result: stateful outputs on range change and the following two samples; direct ADC otherwise.",
        "edge_convention": "[first HIGH, first following LOW); QA includes the following LOW word and its incoming counter transition.",
        "limitations": [
            "This report does not accept a failed pair or establish delivery from a pulse.",
            "Counter continuity is modulo 64, not a checksum or proof of zero sample loss.",
            "Range changes fail this sufficient proof even if an alternative stateful analysis could validate them.",
            "Baseline/excess energy is not calculated, including when baseline integrity is clean.",
            "The current belongs to the whole measured endpoint, not an isolated internal RF block.",
            "Local PPK clocks remain independent; widths need not match for separate TX/RX signals.",
            "Voltage and calibration are taken from archived metadata, not remeasured by this audit.",
        ],
        "sources": {"pairing": manifest_source}, "runs": [], "errors": [],
    }
    metadata = {}
    for role in ("tx", "rx"):
        try:
            data, source = _evidence(root / role / "metadata.json", root)
            metadata[role] = (json.loads(data), source)
        except (OSError, ValueError, UnicodeError) as exc:
            report["errors"].append(f"{role} metadata: {type(exc).__name__}: {exc}")
    rows = manifest.get("rows", [])
    by_id = {}
    for row in rows:
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("Unsafe or missing run_id in pairing.json")
        if run_id in by_id:
            raise ValueError("Duplicate run_id in pairing.json")
        by_id[run_id] = row
    discovered = {path.name for path in (root / "wire").glob("run_*") if path.is_dir() and RUN_ID.fullmatch(path.name)}
    for role in ("tx", "rx"):
        discovered.update(path.name[:-7] for path in (root / role / "raw").glob("run_*.csv.gz")
                          if RUN_ID.fullmatch(path.name[:-7]))
    for run_id in sorted(set(by_id) | discovered):
        row = by_id.get(run_id, {})
        run = {"run_id": run_id, "present_in_pairing": run_id in by_id,
               "official_status_unchanged": row.get("status"),
               "delivery": {"packet_received_recorded": row.get("packet_received"),
                            "tx_status_recorded": row.get("tx_status"), "rx_status_recorded": row.get("rx_status"),
                            "source": "pairing.json; not inferred from energy or D0"}, "roles": {}}
        for role in ("tx", "rx"):
            if role in metadata:
                run["roles"][role] = _audit_role(root, run_id, role, *metadata[role], current_tolerance_uA)
            else:
                run["roles"][role] = {"total_proven": False, "total_energy_uJ": None,
                                      "reasons": ["Endpoint metadata unavailable"], "pulses": []}
        report["runs"].append(run)
    if not report["runs"]:
        report["errors"].append("No transfers found")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_root", type=Path)
    parser.add_argument("--current-tolerance-uA", type=float, default=1e-6)
    parser.add_argument("--output", type=Path, help="Create a new report file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        report = audit_result(args.result_root, current_tolerance_uA=args.current_tolerance_uA)
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            print(text, end="")
        else:
            with args.output.open("x", encoding="utf-8", newline="\n") as destination:
                destination.write(text)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Audit failed: {exc}\n")
    return 0  # Diagnostic completion, not campaign acceptance.


if __name__ == "__main__":
    raise SystemExit(main())
