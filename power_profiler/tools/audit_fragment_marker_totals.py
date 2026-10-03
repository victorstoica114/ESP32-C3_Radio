"""Offline, independent audit of E79 128/512/1024 B local-marker totals.

Read one paired result directory; --output creates a new JSON file exclusively.
Uses the independent single-pulse audit's ADC and wire checks, never production
analysis modules. Every 64-byte frame is required; gaps are not integrated.
Exit 0 means all recorded transfers pass this audit, 1 means a completed audit
has discrepancies, and 2 means invalid input or an output error. No acceptance,
RAW, configuration, or hardware state is changed.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_power_profiler.storage import resolve_measurement_path
import zlib

try:  # Direct script and `python -m tools.audit_fragment_marker_totals`.
    from . import audit_radio_marker_totals as independent
except ImportError:
    import audit_radio_marker_totals as independent


METHOD = "independent_radio_fragment_marker_totals"
POLICY = "total_only_with_direct_adc_proof"
FRAME_COUNTS = {128: 2, 512: 8, 1024: 16}
PROFILES = {"GFSK4K8", "GFSK50", "GFSK200", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50"}
PAYLOAD = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
NULL_FIELDS = ("baseline_median_uA", "threshold_uA", "charge_excess_uC", "energy_excess_uJ")


def _number(value) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite measurement")
    return result


def _matches(actual, expected) -> bool:
    try:
        return math.isclose(_number(actual), expected, rel_tol=1e-10, abs_tol=1e-8)
    except (TypeError, ValueError, OverflowError):
        return False


def _summary(root: Path, role: str) -> tuple[dict, dict]:
    packed, source = independent._evidence(root / role / "summary.csv", root)
    rows = list(csv.DictReader(io.StringIO(packed.decode("utf-8-sig"))))
    by_id = {}
    for row in rows:
        run_id = row.get("run_id", "")
        if not independent.RUN_ID.fullmatch(run_id) or run_id in by_id:
            raise ValueError(f"{role} summary has unsafe or duplicate run_id")
        by_id[run_id] = row
    return by_id, source


def _fragment_role(detail: dict, root: Path, run_id: str, role: str, frame_count: int) -> None:
    """Extend independent per-pulse proofs; preserve every fault except count=1.

    The reused auditor already proves each pulse, even when it reports that its
    single-frame policy cannot combine them. Only that exact policy diagnostic
    is replaced here. Guard-current finiteness is additionally checked through
    the falling LOW sample, matching the stronger direct-ADC sufficient proof.
    """
    observed = detail.get("pulse_count", 0)
    one_pulse_reason = f"Expected one unambiguous pulse; observed {observed}"
    detail["reasons"] = [reason for reason in detail["reasons"] if reason != one_pulse_reason]
    detail.update(total_proven=False, total_energy_uJ=None, charge_total_uC=None,
                  duration_samples=None, duration_ms=None, mean_uA=None, peak_uA=None)
    if observed != frame_count:
        detail["reasons"].append(f"Expected exactly {frame_count} local D0 pulses; observed {observed}")
    try:
        packed, source = independent._evidence(root / role / "raw" / f"{run_id}.csv.gz", root)
        if source != detail["sources"].get("raw_csv_gzip"):
            raise ValueError("RAW changed during audit")
        rows = csv.DictReader(io.StringIO(gzip.decompress(packed).decode("utf-8-sig")))
        currents = [float(row["current_uA"]) for row in rows]
        if any(not math.isfinite(value) for value in currents):
            detail["reasons"].append("Nonfinite current in captured RAW")
        for pulse in detail["pulses"]:
            start, stop = pulse["window_samples"]
            nonfinite = [i for i in range(max(0, start - 3), min(stop + 1, len(currents)))
                         if not math.isfinite(currents[i])]
            pulse["nonfinite_current_indices_guard"] = nonfinite
            if nonfinite:
                pulse["proof_passed"] = False
                detail["reasons"].append(f"Nonfinite current in pulse [{start},{stop}) guard")
        if (not detail["reasons"] and len(detail["pulses"]) == frame_count
                and all(pulse["proof_passed"] for pulse in detail["pulses"])):
            voltage = detail["voltage_v"]
            energy = math.fsum(pulse["total_energy_uJ"] for pulse in detail["pulses"])
            charge = math.fsum(pulse["total_energy_uJ"] / voltage for pulse in detail["pulses"])
            duration = sum(pulse["duration_samples"] for pulse in detail["pulses"])
            active = [currents[i] for pulse in detail["pulses"]
                      for i in range(*pulse["window_samples"])]
            detail.update(total_proven=True, total_energy_uJ=energy, charge_total_uC=charge,
                          duration_samples=duration, duration_ms=duration / 100,
                          mean_uA=charge * independent.SAMPLE_RATE_HZ / duration,
                          peak_uA=max(active))
    except (OSError, EOFError, UnicodeError, ValueError, TypeError, KeyError, OverflowError, zlib.error) as exc:
        detail["reasons"].append(f"{type(exc).__name__}: {exc}")
    detail["windows_samples"] = [pulse["window_samples"] for pulse in detail["pulses"]]


def _compare_role(detail: dict, row: dict, recorded: dict, manifest: dict, role: str) -> list[str]:
    errors = []
    expected = {
        "status": "ok", "measurement_direction": role,
        "integration_method": METHOD, "analysis_error": "",
        "packet_received": "True", "packet_lost": "False", "event_detected": "True",
        "payload_bytes": str(manifest["payload_bytes"]),
        "frame_count": str(manifest["frame_count"]), "max_frame_payload_bytes": "64",
        "serial_content_bytes": str(manifest["payload_bytes"]),
        **dict.fromkeys(NULL_FIELDS, ""),
    }
    for key, value in expected.items():
        if row.get(key) != value:
            errors.append(f"{role} summary {key} differs from the fragmented total-only contract")
    try:
        parameters = json.loads(row["parameters_json"])
        if parameters.get("rf_profile") != manifest["rf_profile"] or parameters.get("tx_power_dbm") != 13:
            errors.append(f"{role} summary RF parameters differ from pairing")
        loss = _number(row["sample_loss_percent"])
        if not 0 <= loss <= 1:
            errors.append(f"{role} sample-loss estimator outside 0..1 percent")
        if int(row["captured_samples"]) != detail.get("sample_count"):
            errors.append(f"{role} CSV sample count differs from RAW/wire")
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        errors.append(f"{role} summary metadata: {exc}")
    if not detail["total_proven"]:
        return errors
    trigger = detail["software_trigger_index"]
    windows = [[(a - trigger) / 100, (b - trigger) / 100] for a, b in detail["windows_samples"]]
    try:
        stored_windows = json.loads(row["integration_windows_ms"])
        if (len(stored_windows) != len(windows)
                or any(len(a) != 2 or any(not _matches(x, y) for x, y in zip(a, b))
                       for a, b in zip(stored_windows, windows))):
            errors.append(f"{role} summary integration windows differ from independent D0 edges")
    except (KeyError, ValueError, TypeError) as exc:
        errors.append(f"{role} summary integration windows: {exc}")
    for key, value in {
        "voltage_mv": detail["voltage_v"] * 1000,
        "charge_total_uC": detail["charge_total_uC"], "energy_total_uJ": detail["total_energy_uJ"],
        "event_start_ms": windows[0][0], "event_duration_ms": detail["duration_ms"],
        "tx_mean_uA": detail["mean_uA"], "event_mean_uA": detail["mean_uA"],
        "tx_peak_uA": detail["peak_uA"], "event_peak_uA": detail["peak_uA"],
        **({"rx_mean_uA": detail["mean_uA"], "rx_peak_uA": detail["peak_uA"]} if role == "rx" else {}),
    }.items():
        if not _matches(row.get(key), value):
            errors.append(f"{role} summary {key} differs from independent active-frame sum")
    if recorded.get("valid") is not True or recorded.get("reasons") != []:
        errors.append(f"{role} recorded marker diagnostics are not valid")
    if recorded.get("windows_samples") != detail["windows_samples"]:
        errors.append(f"{role} recorded sample windows differ from wire")
    for key, value in (("duration_samples", detail["duration_samples"]),
                       ("charge_total_uC", detail["charge_total_uC"]),
                       ("energy_total_uJ", detail["total_energy_uJ"])):
        if not _matches(recorded.get(key), value):
            errors.append(f"{role} recorded {key} differs from independent proof")
    proofs = recorded.get("frame_proofs", [])
    if len(proofs) != len(detail["pulses"]):
        errors.append(f"{role} recorded per-frame proof count mismatch")
    for index, (proof, pulse) in enumerate(zip(proofs, detail["pulses"]), 1):
        if (proof.get("valid") is not True or proof.get("reasons") != []
                or proof.get("window_samples") != pulse["window_samples"]
                or proof.get("guard_window_samples") != pulse["guard_window_samples"]
                or not _matches(proof.get("energy_total_uJ"), pulse["total_energy_uJ"])
                or not _matches(proof.get("charge_total_uC"), pulse["total_energy_uJ"] / detail["voltage_v"])):
            errors.append(f"{role} recorded frame {index} proof disagrees with independent audit")
    return errors


def audit_result(result_root: Path) -> dict:
    root = resolve_measurement_path(result_root).resolve()
    packed, source = independent._evidence(root / "pairing.json", root)
    manifest = json.loads(packed)
    payload = manifest.get("payload_bytes")
    if (type(payload) is not int or payload not in FRAME_COUNTS
            or manifest.get("fragmented") is not True
            or type(manifest.get("frame_count")) is not int
            or manifest["frame_count"] != FRAME_COUNTS[payload]
            or manifest.get("frame_payload_bytes") != [64] * FRAME_COUNTS[payload]
            or manifest.get("profile_id") != "RADIO_EBYTE_E79_CC1352P"
            or manifest.get("tx_power_dbm") != 13 or manifest.get("rf_profile") not in PROFILES
            or manifest.get("integration_mode") != "radio_markers"
            or manifest.get("marker_totals_only") is not True
            or manifest.get("integration_method") != METHOD or manifest.get("energy_policy") != POLICY):
        raise ValueError("Expected an explicit E79 128/512/1024-byte +13 dBm fragmented local-marker total-only result")
    report = independent.audit_result(root)
    if report["sources"]["pairing"] != source:
        raise ValueError("pairing.json changed during audit")
    report.update(tool="audit_fragment_marker_totals", integration_method=METHOD,
                  payload_bytes=payload, frame_count=FRAME_COUNTS[payload], rf_profile=manifest["rf_profile"],
                  tx_power_dbm=13, gap_policy="excluded", baseline_and_excess="not calculated",
                  numeric_comparison={"relative_tolerance": 1e-10, "absolute_tolerance": 1e-8},
                  total_proven=False, accepted=False)
    report["limitations"].append("Identical 64-byte test frames permit a delivery count, not unique frame identity or marker-to-UART timing attribution.")
    summaries = {}
    for role in ("tx", "rx"):
        try:
            summaries[role], report["sources"][role + "_summary"] = _summary(root, role)
        except (OSError, ValueError, UnicodeError) as exc:
            report["errors"].append(f"{role} summary: {exc}")
            summaries[role] = {}
    pairs = {row["run_id"]: row for row in manifest["rows"]}
    for role in ("tx", "rx"):
        if set(summaries[role]) != set(pairs):
            report["errors"].append(f"{role} summary and pairing run IDs differ")
    for run in report["runs"]:
        run_id, errors = run["run_id"], []
        pair = pairs.get(run_id, {})
        diag = pair.get("marker_diagnostics", {})
        if (pair.get("status") != "valid" or pair.get("packet_received") is not True
                or pair.get("tx_status") != "ok" or pair.get("rx_status") != "ok"
                or pair.get("frame_payload_bytes") != [64] * report["frame_count"]
                or pair.get("capture_errors") != {}):
            errors.append("Recorded pair status, delivery, frame layout or capture errors are not acceptable")
        if (diag.get("valid") is not True or diag.get("reasons") != []
                or diag.get("integration_method") != METHOD
                or diag.get("expected_frame_count") != report["frame_count"]):
            errors.append("Recorded fragment diagnostics contract is invalid")
        for role in ("tx", "rx"):
            detail = run["roles"][role]
            _fragment_role(detail, root, run_id, role, report["frame_count"])
            errors.extend(f"{role}: {reason}" for reason in detail["reasons"])
            errors.extend(_compare_role(detail, summaries[role].get(run_id, {}),
                                        diag.get("roles", {}).get(role, {}), manifest, role))
        responses = [summaries[role].get(run_id, {}).get("receiver_response", "") for role in ("tx", "rx")]
        lines = [line.strip() for line in responses[0].split(" | ") if line.strip()]
        delivery_count = sum(line == PAYLOAD or line.upper() == PAYLOAD.encode().hex().upper() for line in lines)
        all_delivered = responses[0] == responses[1] and delivery_count == report["frame_count"]
        run["delivery"].update(independently_counted_payload_lines=delivery_count, all_frames_delivered=all_delivered,
                               method="Exact archived 64-byte ASCII/hex payload lines; one distinct line per frame; identical payloads are not unique IDs")
        if not all_delivered:
            errors.append("RX transcript does not independently confirm every expected frame in both summaries")
        if any(line.strip().upper().startswith("#ERROR") for role in ("tx", "rx")
               for field in ("transmitter_response", "receiver_response")
               for line in summaries[role].get(run_id, {}).get(field, "").split(" | ")):
            errors.append("Archived UART transcript contains a radio error")
        run.update(errors=errors, total_proven=all(role["total_proven"] for role in run["roles"].values()),
                   accepted=not errors)
        report["errors"].extend(f"{run_id}: {error}" for error in errors)
    report["counts"] = {
        "transfers": len(report["runs"]), "expected_transfers": manifest.get("expected_rows"),
        "accepted_transfers": sum(run["accepted"] for run in report["runs"]),
        "proven_roles": sum(role["total_proven"] for run in report["runs"] for role in run["roles"].values()),
        "proven_frames": sum(pulse["proof_passed"] for run in report["runs"]
                             for role in run["roles"].values() for pulse in role["pulses"]),
    }
    if manifest.get("status") != "valid" or manifest.get("errors") != []:
        report["errors"].append("Official batch is not valid; independent totals cannot accept a failed batch")
    if type(manifest.get("expected_rows")) is not int or manifest["expected_rows"] != 5 or len(report["runs"]) != 5:
        report["errors"].append("A fragmented campaign batch requires exactly five planned and recorded transfers")
    report["total_proven"] = bool(report["runs"]) and all(run["total_proven"] for run in report["runs"])
    report["accepted"] = not report["errors"]
    report["acceptance_note"] = "accepted is an offline audit verdict only; official files and acceptance remain unchanged"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_root", type=Path)
    parser.add_argument("--output", type=Path, help="Exclusively create a new JSON report")
    args = parser.parse_args(argv)
    try:
        report = audit_result(args.result_root)
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            print(text, end="")
        else:
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Audit failed: {exc}\n")
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
