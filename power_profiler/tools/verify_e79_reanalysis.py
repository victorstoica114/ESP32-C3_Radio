"""Independent read-only verification of E79 final results and production math."""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "measurements/raw/archive"
PROOF = ROOT / ".tmp/recapture-audit-20260929/e79-final-verification.json"
REPORTS = ROOT / "power_profiler/audits/2026-09-29"
sys.path.insert(0, str(ROOT / "power_profiler"))
from radio_power_profiler.analysis import analyze_capture, _frame_sample_lengths
from radio_power_profiler.models import CaptureSpec, TransmitSpec
from radio_power_profiler.planning import estimate_airtime_s


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trace(path):
    samples, triggers = [], []
    with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            assert int(row["sample_index"]) == index
            value = float(row["current_uA"])
            assert math.isfinite(value)
            samples.append(value)
            if row["trigger"] == "1":
                triggers.append(index)
    assert len(triggers) == 1
    return samples, triggers[0]


def main():
    current_path = REPORTS / "e79-tx-corrected/runs.json"
    prior_path = REPORTS / "e79-tx-reanalysis/runs.json"
    aggregate_path = REPORTS / "e79-tx-corrected/aggregates.csv"
    code = [ROOT / "power_profiler/radio_power_profiler" / name for name in
            ("analysis.py", "frame_windows.py", "frame_detection.py", "planning.py", "models.py")]
    before_code_hashes = {str(path.relative_to(ROOT)): sha(path) for path in code}
    results = json.loads(current_path.read_text(encoding="utf-8"))
    prior_results = json.loads(prior_path.read_text(encoding="utf-8"))
    prior = {row["raw_relative_path"]: row for row in prior_results}
    source = {}
    frozen = {}
    manifest_path = ARCHIVE / "comparisons/ebyte_e79_400dm2005s/campaign_logs/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for step in manifest["steps"]:
        if not step["step_id"].startswith("tx_p"):
            continue
        relative = step["accepted_result"].replace("\\", "/").split("power_profiler/", 1)[1]
        directory = ARCHIVE / relative
        frozen[step["step_id"]] = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        with (directory / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = relative + "/raw/" + row["run_id"] + ".csv.gz"
                source[key] = row

    errors = []
    check = lambda condition, detail: None if condition else errors.append(detail)
    check(len(results) == 630, {"check": "runs", "actual": len(results)})
    check(set(source) == set(prior) == {r["raw_relative_path"] for r in results}, "RAW identity sets differ")
    groups = defaultdict(list)
    window_details = []
    mono_mismatches = []
    hash_mismatches = []
    print("Checking 630 compressed RAW hashes against current batch and previous audit...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        raw_hashes = dict(zip(source, pool.map(sha, (ARCHIVE / key for key in source))))
    quantization = []
    for run in results:
        key = run["raw_relative_path"]
        row = source[key]
        groups[run["step_id"]].append(run)
        if not raw_hashes[key] == run["raw_sha256"] == prior[key]["raw_sha256"]:
            hash_mismatches.append(key)
        check(run["quality"] == "model_window_reanalysis" and not run["reasons"], {"check": "QC", "raw": key})
        rate = run["sample_rate_hz"]
        windows = [(round(a * rate / 1000), round(b * rate / 1000)) for a, b in run["frame_windows_ms"]]
        lengths = tuple(b - a for a, b in windows)
        historical_length = round(float(row["event_duration_ms"]) * rate / 1000)
        overlap = any(a[1] > b[0] for a, b in zip(windows, windows[1:]))
        check(not overlap and all(a >= 0 and b > a for a, b in windows), {"check": "nonoverlap_positive_posttrigger", "raw": key})
        check(sum(lengths) == historical_length, {"check": "duration_preserved", "raw": key, "window_sum": sum(lengths), "historical": historical_length})
        check(len(windows) == run["expected_frames"], {"check": "window_count", "raw": key})
        check(run["last_window_to_capture_end_ms"] >= 0, {"check": "capture_tail", "raw": key})
        if run["expected_frames"] == 1:
            changes = {field: {"source": value, "corrected": run["corrected_summary"].get(field)}
                       for field, value in row.items() if run["corrected_summary"].get(field) != value}
            if changes:
                mono_mismatches.append({"raw": key, "changes": changes})
            check(run["recalculated_energy_total_uJ"] == float(row["energy_total_uJ"]), {"check": "mono_total_exact", "raw": key})
            check(run["recalculated_energy_excess_uJ"] == float(row["energy_excess_uJ"]), {"check": "mono_excess_exact", "raw": key})
        window_details.append({"raw_relative_path": key, "frame_count": len(windows), "lengths_samples": lengths,
                               "integration_samples": sum(lengths), "historical_samples": historical_length,
                               "overlap": overlap, "tail_ms": run["last_window_to_capture_end_ms"]})
    check(not hash_mismatches, {"check": "raw_hashes", "mismatches": hash_mismatches})
    check(not mono_mismatches, {"check": "mono_source_fields_exact", "mismatches": mono_mismatches})

    for step, rows in groups.items():
        check(len(rows) == 5 and sorted(r["repetition"] for r in rows) == list(range(1, 6)), {"check": "five_repetitions", "step": step})
        if rows[0]["expected_frames"] == 1:
            continue
        meta = frozen[step]
        profile = SimpleNamespace(airtime=meta["profile"]["airtime"], transmit=TransmitSpec(**meta["profile"]["transmit"]))
        original = source[rows[0]["raw_relative_path"]]
        params = json.loads(original["parameters_json"])
        frames = profile.transmit.frame_sizes(int(original["payload_bytes"]))
        airtimes = tuple(estimate_airtime_s(profile, size, params) for size in frames)
        quantization_error = None
        try:
            lengths = _frame_sample_lengths(airtimes, meta["sample_rate_hz"])
        except ValueError as exc:
            lengths = None
            quantization_error = str(exc)
        offline = tuple(round((b - a) * meta["sample_rate_hz"] / 1000) for a, b in rows[0]["frame_windows_ms"])
        item = {"step_id": step, "frames_bytes": frames, "frame_airtimes_s": airtimes, "production_lengths_samples": lengths,
                "offline_lengths_samples": offline, "equal": lengths == offline,
                "quantization_error": quantization_error,
                "sum_individual_floored_samples": sum(int(t * meta["sample_rate_hz"]) for t in airtimes),
                "floored_sum_airtime_samples": int(sum(airtimes) * meta["sample_rate_hz"]),
                "modeled_transfer_airtime_s": estimate_airtime_s(profile, int(original["payload_bytes"]), params),
                "original_airtime_s": float(original["estimated_airtime_ms"]) / 1000}
        quantization.append(item)
        check(item["equal"], {"check": "production_quantization", **item})
        for run in rows:
            other = tuple(round((b-a) * meta["sample_rate_hz"] / 1000) for a, b in run["frame_windows_ms"])
            check(other == offline, {"check": "within_condition_quantization", "raw": run["raw_relative_path"]})

    with aggregate_path.open(encoding="utf-8-sig", newline="") as stream:
        aggregates = list(csv.DictReader(stream))
    aggregate_mismatches = []
    check(len(aggregates) == len(groups) == 126, {"check": "aggregate_count", "aggregates": len(aggregates), "conditions": len(groups)})
    check({a["step_id"] for a in aggregates} == set(groups), "aggregate condition sets differ")
    for aggregate in aggregates:
        rows = groups[aggregate["step_id"]]
        check(int(aggregate["runs"]) == int(aggregate["reanalyzed_runs"]) == 5, {"check": "aggregate_repetitions", "step": aggregate["step_id"]})
        for field in ("recalculated_energy_total_uJ", "recalculated_energy_excess_uJ"):
            for suffix, function in (("mean", statistics.fmean), ("stdev", statistics.stdev)):
                expected = function(r[field] for r in rows)
                reported = float(aggregate[field + "_" + suffix])
                if reported != expected:
                    aggregate_mismatches.append({"step": aggregate["step_id"], "field": field + "_" + suffix, "expected": expected, "actual": reported})
    check(not aggregate_mismatches, {"check": "aggregate_math", "mismatches": aggregate_mismatches})

    print("Checking production integration on fast, slow, low-power and formerly rejected IEEE RAW...", flush=True)
    reproductions = []
    selected = ["tx_p13_rf_profile-GFSK200_s1024", "tx_p13_rf_profile-SLR2K5_s1024", "tx_p-20_rf_profile-GFSK4K8_s1024",
                "tx_p13_rf_profile-IEEE154G50_s1024"]
    for step in selected:
        run = next(r for r in groups[step] if r["repetition"] == 1)
        samples, trigger = trace(ARCHIVE / run["raw_relative_path"])
        original = source[run["raw_relative_path"]]
        meta = frozen[step]
        profile = SimpleNamespace(airtime=meta["profile"]["airtime"], transmit=TransmitSpec(**meta["profile"]["transmit"]))
        params = json.loads(original["parameters_json"])
        airtimes = tuple(estimate_airtime_s(profile, size, params) for size in profile.transmit.frame_sizes(int(original["payload_bytes"])))
        metrics = analyze_capture(samples, trigger_index=trigger, sample_rate_hz=meta["sample_rate_hz"],
                                  voltage_mv=meta["voltage_mv"], capture_spec=CaptureSpec(**meta["profile"]["capture"]),
                                  expected_event_count=run["expected_frames"], frame_airtimes_s=airtimes)
        windows = [[a, b] for a, b in metrics.integration_windows_ms]
        total_diff = metrics.energy_total_uJ - run["recalculated_energy_total_uJ"] if metrics.event_detected else None
        excess_diff = metrics.energy_excess_uJ - run["recalculated_energy_excess_uJ"] if metrics.event_detected else None
        item = {"step_id": step, "raw_relative_path": run["raw_relative_path"], "sample_count": len(samples), "trigger_index": trigger,
                "event_detected": metrics.event_detected, "analysis_error": metrics.analysis_error,
                "production_total_uJ": metrics.energy_total_uJ, "offline_total_uJ": run["recalculated_energy_total_uJ"],
                "production_excess_uJ": metrics.energy_excess_uJ, "offline_excess_uJ": run["recalculated_energy_excess_uJ"],
                "total_difference_uJ": total_diff, "excess_difference_uJ": excess_diff,
                "windows_exact_equal": windows == run["frame_windows_ms"],
                "production_windows_ms": windows, "baseline_exact_equal": metrics.baseline_median_uA == run["baseline_uA"]}
        reproductions.append(item)
        check(metrics.event_detected, {"check": "production_detection", **item})
        check(item["windows_exact_equal"] and item["baseline_exact_equal"], {"check": "production_window_baseline", **item})
        check(total_diff is not None and math.isclose(metrics.energy_total_uJ, run["recalculated_energy_total_uJ"], rel_tol=2e-14, abs_tol=1e-9), {"check": "production_total", **item})
        check(excess_diff is not None and math.isclose(metrics.energy_excess_uJ, run["recalculated_energy_excess_uJ"], rel_tol=2e-14, abs_tol=1e-9), {"check": "production_excess", **item})
        print(f"  {step}: total difference={total_diff}, excess difference={excess_diff}, windows equal={item['windows_exact_equal']}", flush=True)

    after_code_hashes = {str(path.relative_to(ROOT)): sha(path) for path in code}
    check(before_code_hashes == after_code_hashes, "Production code changed during verification")
    proof = {"created_utc": datetime.now(timezone.utc).isoformat(), "status": "passed" if not errors else "failed",
             "scope": "Independent source/RAW hash, frozen metadata, duration, aggregate and production reproduction verification; no hardware or data edits.",
             "artifacts_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (current_path, prior_path, aggregate_path, manifest_path, Path(__file__))},
             "production_code_sha256": before_code_hashes, "production_code_unchanged_during_verification": before_code_hashes == after_code_hashes,
             "run_count": len(results), "single_frame_count": sum(r["expected_frames"] == 1 for r in results),
             "fragmented_count": sum(r["expected_frames"] > 1 for r in results), "condition_count": len(groups),
             "fragmented_condition_count": len(quantization), "raw_hashes_recomputed": len(raw_hashes),
             "raw_hash_mismatches": hash_mismatches, "single_frame_source_field_mismatches": mono_mismatches,
             "aggregate_mismatches": aggregate_mismatches, "errors": errors,
             "quantization": quantization, "production_reproductions": reproductions, "window_checks": window_details,
             "source_raw_hashes": raw_hashes,
             "limitations": ["Numerical consistency does not independently validate the RF airtime model.",
                             "Reported acquisition sample loss remains; unavailable missing samples are not reconstructed.",
                             "Frame segmentation is charge-based and lacks synchronized physical RF boundaries."]}
    PROOF.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("status", "run_count", "single_frame_count", "fragmented_count", "condition_count", "fragmented_condition_count", "raw_hashes_recomputed", "errors")}), flush=True)


if __name__ == "__main__":
    main()
