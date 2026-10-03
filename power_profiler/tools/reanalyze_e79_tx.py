"""Offline sensitivity analysis of archived E79/ESP32 packet TX captures.

Does not access hardware, rewrite source results, or apply ESP32 corrections to
CH9340C data. Outputs are a separate analysis under the original airtime model.
Run from the repository root with Python 3.10+; standard library only.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_power_profiler.frame_windows import align_windows, locate_frame_windows


def load_trace(path: Path) -> tuple[list[float], int]:
    samples, triggers = [], []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader) != ["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"]:
            raise ValueError(f"Unexpected raw schema: {path}")
        for index, row in enumerate(reader):
            value = float(row[2])
            if not math.isfinite(value) or int(row[0]) != index:
                raise ValueError(f"Invalid sample {index}: {path}")
            samples.append(value)
            if row[4] == "1":
                triggers.append(index)
    if len(triggers) != 1:
        raise ValueError(f"Expected one trigger, got {triggers}: {path}")
    return samples, triggers[0]


def aligned_windows(samples, baseline, trigger, groups, total_samples):
    """Compatibility wrapper using the shared acquisition/reanalysis engine."""
    if not groups:
        raise ValueError("No independently detected frames")
    quotient, remainder = divmod(total_samples, len(groups))
    lengths = tuple(quotient + (index < remainder) for index in range(len(groups)))
    return align_windows(samples, baseline, trigger, groups, lengths)


def energies(samples, windows, baseline, rate, voltage):
    total = excess = 0.0
    for start, stop in windows:
        for value in samples[start:stop]:
            total += max(0.0, value)
            excess += max(0.0, value - baseline)
    return total * voltage / rate, excess * voltage / rate


def analyze_job(job):
    raw_path, row, step_id, rate, source_relative = job
    samples, trigger = load_trace(Path(raw_path))
    if len(samples) != int(row["captured_samples"]):
        raise ValueError(f"Sample count mismatch: {raw_path}")
    baseline = statistics.median(samples[min(int(.010 * rate), trigger // 4):max(1, trigger - int(.005 * rate))])
    voltage = float(row["voltage_mv"]) / 1000
    old_start = trigger + round(float(row["event_start_ms"]) * rate / 1000)
    total_samples = round(float(row["event_duration_ms"]) * rate / 1000)
    old_window = (old_start, old_start + total_samples)
    old_energy, old_excess = energies(samples, [old_window], baseline, rate, voltage)
    old_reported = float(row["energy_total_uJ"])
    old_reported_excess = float(row["energy_excess_uJ"])
    if not math.isclose(old_energy, old_reported, rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError(f"Original integration not reproduced: {raw_path}")
    if not math.isclose(old_excess, old_reported_excess, rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError(f"Original excess not reproduced: {raw_path}")
    expected = int(row["frame_count"])
    parameters = json.loads(row["parameters_json"])
    result = {
        "step_id": step_id, "run_id": row["run_id"], "raw_relative_path": source_relative,
        "raw_sha256": hashlib.sha256(Path(raw_path).read_bytes()).hexdigest(),
        "rf_profile": parameters["rf_profile"], "tx_power_dbm": parameters["tx_power_dbm"],
        "payload_bytes": int(row["payload_bytes"]), "repetition": int(row["repetition"]),
        "expected_frames": expected, "detected_frames": None,
        "sample_rate_hz": rate, "sample_loss_percent": float(row["sample_loss_percent"]),
        "original_status": row["status"], "packet_received": row["packet_received"],
        "baseline_uA": baseline, "original_energy_total_uJ": old_reported,
        "original_energy_excess_uJ": old_reported_excess,
        "original_reproduction_error_uJ": old_energy - old_reported,
        "original_excess_reproduction_error_uJ": old_excess - old_reported_excess,
        "model_integration_duration_ms": total_samples * 1000 / rate,
        "original_window_ms": [(old_start-trigger)*1000/rate, (old_window[1]-trigger)*1000/rate],
        "detected_pulses_ms": [], "detector": {},
        "quality": "review_required", "reasons": [],
    }
    if expected == 1:
        # No frame omission exists in a one-window, one-frame metric. Keep
        # the recorded window and values, after independent RAW reproduction.
        windows = [old_window]
        new_total, new_excess = old_reported, old_reported_excess
        result["integration_method"] = "original_single_frame_window_verified"
        result["detector"] = {"not_required": "Single-frame source window retained and reproduced from RAW"}
    else:
        if int(row["payload_bytes"]) != 64 * expected:
            raise ValueError("Offline E79 archive reanalysis expects uniform 64-byte fragments")
        quotient, remainder = divmod(total_samples, expected)
        lengths = tuple(quotient + (index < remainder) for index in range(expected))
        located = locate_frame_windows(samples, trigger_index=trigger, sample_rate_hz=rate,
                                       baseline_uA=baseline, frame_lengths=lengths)
        diagnostic = located["diagnostics"]
        reference = diagnostic["sensitivity"][0]
        result.update(detector=diagnostic, detected_frames=reference["detected_frames"],
                      detected_pulses_ms=[[(a-trigger)*1000/rate,(b-trigger)*1000/rate] for a,b in reference["groups"]],
                      integration_method="per_frame_modeled_airtime_v1",
                      sensitivity=diagnostic["sensitivity"])
        if not located["valid"]:
            result["reasons"] = located["reasons"]
            return result
        windows = located["windows"]
        new_total, new_excess = energies(samples, windows, baseline, rate, voltage)
    relative_windows = [[(a-trigger)*1000/rate, (b-trigger)*1000/rate] for a,b in windows]
    corrected = dict(row)
    if expected > 1:
        event = [value for start, end in windows for value in samples[start:end]]
        mean, peak = statistics.fmean(event), max(event)
        corrected.update(event_start_ms=relative_windows[0][0], event_duration_ms=total_samples*1000/rate,
                         tx_mean_uA=mean, tx_peak_uA=peak, event_mean_uA=mean, event_peak_uA=peak,
                         charge_total_uC=new_total/voltage, charge_excess_uC=new_excess/voltage,
                         energy_total_uJ=new_total, energy_excess_uJ=new_excess)
    corrected.update(integration_method=result["integration_method"],
                     integration_windows_ms=json.dumps(relative_windows), analysis_error="")
    result.update(frame_windows_ms=relative_windows, corrected_summary=corrected,
                  recalculated_energy_total_uJ=new_total, recalculated_energy_excess_uJ=new_excess,
                  change_total_percent=100*(new_total/old_reported-1),
                  change_excess_percent=100*(new_excess/old_reported_excess-1) if old_reported_excess else None,
                  last_window_to_capture_end_ms=(len(samples)-windows[-1][1])*1000/rate,
                  quality="model_window_reanalysis")
    return result


def jobs_from_archive(root):
    archive = root / "measurements/raw/archive"
    manifest_path = archive / "comparisons/ebyte_e79_400dm2005s/campaign_logs/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = []
    for step in manifest["steps"]:
        if not step["step_id"].startswith("tx_p"):
            continue
        source = step["accepted_result"].replace("\\", "/").split("power_profiler/", 1)[1]
        directory = archive / source
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        rate = int(metadata["sample_rate_hz"])
        with (directory / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["measurement_direction"] != "tx":
                    raise ValueError("Unexpected non-TX source")
                relative = source + "/raw/" + row["run_id"] + ".csv.gz"
                jobs.append((str(archive / relative), row, step["step_id"], rate, relative))
    if len(jobs) != 630 or len({job[0] for job in jobs}) != 630:
        raise ValueError("Expected 630 distinct accepted E79 ESP32 TX captures")
    return jobs


def write_outputs(results, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "runs.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    scalar_keys = [k for k in results[0] if k not in {"detector", "original_window_ms", "detected_pulses_ms", "frame_windows_ms", "sensitivity", "corrected_summary", "reasons"}]
    scalar_keys = list(dict.fromkeys(scalar_keys + ["recalculated_energy_total_uJ", "recalculated_energy_excess_uJ", "change_total_percent", "change_excess_percent", "last_window_to_capture_end_ms"]))
    with (output / "runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, scalar_keys + ["reasons"], extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({**row, "reasons": ";".join(row["reasons"])})
    aggregates = []
    for step in dict.fromkeys(r["step_id"] for r in results):
        rows = [r for r in results if r["step_id"] == step]
        complete = all(r["quality"] == "model_window_reanalysis" for r in rows)
        aggregate = {k: rows[0][k] for k in ("step_id", "rf_profile", "tx_power_dbm", "payload_bytes", "expected_frames")}
        aggregate.update(runs=len(rows), reanalyzed_runs=sum(r["quality"] == "model_window_reanalysis" for r in rows), quality="model_window_reanalysis" if complete else "review_required")
        aggregate["original_energy_total_uJ_mean"] = statistics.fmean(r["original_energy_total_uJ"] for r in rows)
        aggregate["original_energy_excess_uJ_mean"] = statistics.fmean(r["original_energy_excess_uJ"] for r in rows)
        if complete:
            for field in ("recalculated_energy_total_uJ", "recalculated_energy_excess_uJ"):
                aggregate[field + "_mean"] = statistics.fmean(r[field] for r in rows)
                aggregate[field + "_stdev"] = statistics.stdev(r[field] for r in rows)
            aggregate["change_total_percent"] = 100 * (aggregate["recalculated_energy_total_uJ_mean"] / aggregate["original_energy_total_uJ_mean"] - 1)
            aggregate["change_excess_percent"] = 100 * (aggregate["recalculated_energy_excess_uJ_mean"] / aggregate["original_energy_excess_uJ_mean"] - 1)
        aggregates.append(aggregate)
    fields = list(dict.fromkeys(k for row in aggregates for k in row))
    with (output / "aggregates.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(aggregates)
    summary = {
        "method": "Independent pulse detection; one charge-aligned modeled-airtime window per pulse; original total integration time retained.",
        "interpretation": "Offline sensitivity analysis under the original airtime model, not synchronized RF timing or end-to-end energy. Publishing is a separate step; no correction transferred to CH9340C.",
        "runs": len(results), "reanalyzed_runs": sum(r["quality"] == "model_window_reanalysis" for r in results),
        "review_required": [{k:r[k] for k in ("step_id", "run_id", "reasons")} for r in results if r["quality"] != "model_window_reanalysis"],
        "original_energy_max_absolute_error_uJ": max(abs(r["original_reproduction_error_uJ"]) for r in results),
        "physical_captures_performed": 0,
    }
    for name, frame_test in (("single_frame", lambda n:n==1), ("fragmented", lambda n:n>1)):
        rows = [r for r in results if frame_test(r["expected_frames"]) and r["quality"] == "model_window_reanalysis"]
        summary[name] = {"runs":len(rows)}
        if rows:
            summary[name].update({"total_change_percent_min":min(r["change_total_percent"] for r in rows), "total_change_percent_max":max(r["change_total_percent"] for r in rows), "total_change_percent_median":statistics.median(r["change_total_percent"] for r in rows)})
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--step-contains", default="")
    args = parser.parse_args()
    jobs = [job for job in jobs_from_archive(args.root) if args.step_contains in job[2]]
    if not jobs:
        parser.error("No matching captures")
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(analyze_job, jobs):
            results.append(result)
            if len(results) % 25 == 0:
                print(f"Processed {len(results)}/{len(jobs)}", flush=True)
    write_outputs(results, args.output)


if __name__ == "__main__":
    main()
