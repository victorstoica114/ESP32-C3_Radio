"""Offline E79 paired-pilot accounting; standard library, no hardware access.

Preserves the legacy metrics and adds explicitly bounded observation budgets.
Neither the fixed host windows nor baseline subtraction isolate RF-only energy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct


BASELINE_MS = (-180, -20)
BASELINE_VARIANTS_MS = ((-180, -100), (-100, -20))
OBSERVATION_MS = (100, 150, 200, 300, 500)
PRIMARY_MS = 200
COUNTER_SOURCE = "https://github.com/nordicsemi/pc-nrfconnect-ppk/blob/881d596480f60dea045ad6f3643afdc3f9d5a0a6/src/device/serialDevice.ts"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_trace(path, rate):
    samples, triggers, logic = [], [], set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"]:
            raise ValueError(f"Unexpected RAW schema: {path}")
        for index, row in enumerate(reader):
            current, time_ms = float(row["current_uA"]), float(row["time_ms"])
            if (int(row["sample_index"]) != index or not math.isfinite(current)
                    or not math.isclose(time_ms, index * 1000 / rate, abs_tol=1e-7)):
                raise ValueError(f"Invalid RAW sample {index}: {path}")
            if row["trigger"] not in ("0", "1"):
                raise ValueError(f"Invalid trigger flag: {path}")
            if row["trigger"] == "1":
                triggers.append(index)
            samples.append(current)
            logic.add(int(row["logic_bits"]))
    if len(triggers) != 1:
        raise ValueError(f"Expected one software marker: {path}")
    return samples, triggers[0], sorted(logic)


def segment(samples, marker, rate, bounds_ms):
    """Half-open windows; reject truncation instead of silently slicing."""
    first, last = (marker + round(value * rate / 1000) for value in bounds_ms)
    if not 0 <= first < last <= len(samples):
        raise ValueError(f"Window {bounds_ms} ms outside RAW")
    return samples[first:last]


def budget(values, rate, voltage_v, baseline_uA):
    duration_s = len(values) / rate
    charge_uC = math.fsum(values) / rate
    baseline_uC = baseline_uA * duration_s
    return {
        "duration_ms": duration_s * 1000,
        "mean_current_uA": statistics.fmean(values),
        "charge_uC": charge_uC,
        "energy_total_uJ": voltage_v * charge_uC,
        "baseline_energy_uJ": voltage_v * baseline_uC,
        "energy_delta_signed_uJ": voltage_v * (charge_uC - baseline_uC),
    }


def stats(values):
    return {"n": len(values), "mean": statistics.fmean(values),
            "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
            "min": min(values), "max": max(values)}


def wire_counters(path):
    """Audit the Nordic 6-bit counter; never infer a loss count or repair ADC."""
    counters = [(word[0] >> 18) & 63 for word in struct.iter_unpack("<I", path.read_bytes())]
    transitions = [index for index in range(1, len(counters))
                   if counters[index] != (counters[index - 1] + 1) % 64]
    # Ignore startup for this *diagnostic* dominant-phase comparison. Genuine
    # persistent phase changes and isolated counter errors remain distinct.
    phase_counts = Counter((value - index) % 64 for index, value in enumerate(counters) if index >= 1000)
    phase = phase_counts.most_common(1)[0][0] if phase_counts else None
    outliers = [index for index in range(1000, len(counters))
                if (counters[index] - index) % 64 != phase]
    return {"counter_transition_anomalies": len(transitions),
            "counter_first_anomaly_indices": transitions[:12],
            "dominant_phase_after_sample1000": phase,
            "phase_disagreement_indices_after_sample1000": outliers}


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def calculate(source):
    source = source.resolve()
    pairing_path = source / "pairing.json"
    pairing = json.loads(pairing_path.read_text(encoding="utf-8"))
    if (pairing["status"] != "valid" or pairing["profile_id"] != "RADIO_EBYTE_E79_CC1352P"
            or pairing["payload_bytes"] != 32 or pairing["rf_profile"] != "GFSK200"
            or pairing["tx_power_dbm"] != 13 or pairing["sample_rate_hz"] != 100000):
        raise ValueError("Expected the validated E79 32 B GFSK200 +13 dBm pilot")
    pairs = pairing["rows"]
    if len(pairs) != 5 or len({p["run_id"] for p in pairs}) != 5:
        raise ValueError("Expected five unique paired transfers")
    if any(p["paired_transfer_id"] != f"{pairing['session_id']}:{p['run_id']}" for p in pairs):
        raise ValueError("Paired transfer identity does not match session/run")
    if pairing["voltage_confirmed"] is not True or not pairing["voltage_provenance"].strip():
        raise ValueError("Missing supply provenance")
    rate = pairing["sample_rate_hz"]
    files = {"pairing.json": sha256(pairing_path)}
    original, observations, baseline_sensitivity = [], [], []
    trace_checks, reference_windows, timing_rows, wire_checks = [], [], [], []
    for role in ("tx", "rx"):
        summary_path = source / role / "summary.csv"
        summaries = read_csv(summary_path)
        by_id = {row["run_id"]: row for row in summaries}
        if len(summaries) != 5 or set(by_id) != {p["run_id"] for p in pairs}:
            raise ValueError(f"Unpaired summary rows: {role}")
        files[f"{role}/summary.csv"] = sha256(summary_path)
        voltage_v = pairing["endpoints"][role]["voltage_mv"] / 1000
        if not math.isfinite(voltage_v) or voltage_v <= 0:
            raise ValueError("Invalid supply voltage")
        for pair in pairs:
            run_id = pair["run_id"]
            row = by_id[run_id]
            if (pair["status"] != "valid" or pair["packet_received"] is not True
                    or row["status"] != "ok" or row["packet_received"] != "True"
                    or row["measurement_direction"] != role
                    or int(row["voltage_mv"]) != round(voltage_v * 1000)):
                raise ValueError(f"Invalid endpoint result: {role}/{run_id}")
            raw_relative = f"{role}/raw/{run_id}.csv.gz"
            if pair[f"{role}_raw"] != raw_relative:
                raise ValueError("Unexpected RAW pairing")
            raw = source / raw_relative
            samples, marker, logic = load_trace(raw, rate)
            timing = pair["timing"]["devices"][role]
            callback_end_ms = (pair["timing"]["trigger_callback_finished_host_ns"] - timing["marker_host_ns"]) / 1e6
            if not math.isfinite(callback_end_ms) or not 0 < callback_end_ms < PRIMARY_MS:
                raise ValueError("Primary observation does not encompass the host callback")
            wire_relative = f"wire/{run_id}/{role}.ppk2.bin"
            wire = source / wire_relative
            if (marker != timing["trigger_index"] or len(samples) != int(row["captured_samples"])
                    or wire.stat().st_size != len(samples) * 4
                    or timing["wire_bytes"] != wire.stat().st_size or timing["trailing_bytes"] != 0):
                raise ValueError(f"RAW/wire/marker mismatch: {role}/{run_id}")
            counter = wire_counters(wire)
            wire_checks.append({"role": role, "run_id": run_id, **counter})
            for relative, path in ((raw_relative, raw), (wire_relative, wire)):
                files[relative] = sha256(path)
            baseline = statistics.fmean(segment(samples, marker, rate, BASELINE_MS))
            baseline_median = statistics.median(samples[min(int(.010 * rate), marker // 4):
                                                         max(1, marker - int(.005 * rate))])
            windows = json.loads(row["integration_windows_ms"])
            if len(windows) != 1 or not math.isclose(windows[0][1] - windows[0][0], 4.76):
                raise ValueError("Unexpected legacy modeled window")
            event = segment(samples, marker, rate, windows[0])
            legacy_total = math.fsum(max(0, value) for value in event) * voltage_v / rate
            legacy_rectified = math.fsum(max(0, value - baseline_median) for value in event) * voltage_v / rate
            for actual, recorded in ((legacy_total, float(row["energy_total_uJ"])),
                                     (legacy_rectified, float(row["energy_excess_uJ"])),
                                     (baseline_median, float(row["baseline_median_uA"]))):
                if not math.isclose(actual, recorded, rel_tol=1e-10, abs_tol=1e-7):
                    raise ValueError(f"Legacy result does not reproduce: {role}/{run_id}")
            original.append({"role": role, "run_id": run_id,
                             "window_start_ms": windows[0][0], "window_end_ms": windows[0][1],
                             "legacy_total_uJ": legacy_total, "legacy_rectified_excess_uJ": legacy_rectified,
                             "legacy_total_nJ_per_payload_bit": legacy_total * 1000 / (8 * pairing["payload_bytes"]),
                             "baseline_mean_uA": baseline, "baseline_power_mW": baseline * voltage_v / 1000,
                             "legacy_window_delta_signed_uJ": budget(event, rate, voltage_v, baseline)["energy_delta_signed_uJ"]})
            # Nonoverlapping same-duration baseline windows expose the legacy
            # positive bias from rectifying noisy current minus its median.
            reference = segment(samples, marker, rate, BASELINE_MS)
            width = len(event)
            for index in range(0, len(reference) - width + 1, width):
                chunk = reference[index:index + width]
                reference_windows.append({"role": role, "run_id": run_id,
                    "start_ms": BASELINE_MS[0] + index * 1000 / rate,
                    "legacy_rectified_excess_uJ": math.fsum(max(0, value - baseline_median) for value in chunk) * voltage_v / rate,
                    **budget(chunk, rate, voltage_v, baseline)})
            for duration in OBSERVATION_MS:
                values = segment(samples, marker, rate, (0, duration))
                observations.append({"role": role, "run_id": run_id,
                    "window_start_ms": 0, "window_end_ms": duration,
                    "host_callback_finished_ms": callback_end_ms,
                    "host_callback_within_window": callback_end_ms < duration,
                    "baseline_mean_uA": baseline, **budget(values, rate, voltage_v, baseline)})
            values = segment(samples, marker, rate, (0, PRIMARY_MS))
            for bounds in (BASELINE_MS,) + BASELINE_VARIANTS_MS:
                alternative = statistics.fmean(segment(samples, marker, rate, bounds))
                baseline_sensitivity.append({"role": role, "run_id": run_id,
                    "baseline_start_ms": bounds[0], "baseline_end_ms": bounds[1],
                    "baseline_mean_uA": alternative, **budget(values, rate, voltage_v, alternative)})
            pre_mean = statistics.fmean(segment(samples, marker, rate, (-100, -20)))
            post_mean = statistics.fmean(segment(samples, marker, rate, (200, 500)))
            loss = float(row["sample_loss_percent"])
            if not math.isfinite(loss) or not 0 <= loss <= 1:
                raise ValueError("Source loss estimate outside pilot acceptance range")
            trace_checks.append({"role": role, "run_id": run_id, "samples": len(samples),
                "marker_index": marker, "logic_values": logic, "voltage_v_assumed_constant": voltage_v,
                "source_loss_estimate_percent": loss, "pre_mean_uA_minus100_minus20ms": pre_mean,
                "post_mean_uA_200_500ms": post_mean, "post_minus_pre_uA": post_mean - pre_mean,
                "counter_transition_anomalies": counter["counter_transition_anomalies"],
                "phase_disagreements_after_sample1000": len(counter["phase_disagreement_indices_after_sample1000"])})
            timing_rows.append({"role": role, "run_id": run_id,
                "host_marker_skew_ms": pair["timing"]["host_marker_skew_ms"],
                "callback_finished_from_local_host_marker_ms": callback_end_ms})
    paired = []
    for pair in pairs:
        endpoints = [r for r in observations if r["run_id"] == pair["run_id"] and r["window_end_ms"] == PRIMARY_MS]
        paired.append({"run_id": pair["run_id"], "paired_transfer_id": pair["paired_transfer_id"],
                       "endpoint_window_ms": PRIMARY_MS,
                       **{key: math.fsum(r[key] for r in endpoints)
                          for key in ("energy_total_uJ", "baseline_energy_uJ", "energy_delta_signed_uJ")}})
    aggregates = []
    for role in ("tx", "rx"):
        records = [r for r in original if r["role"] == role]
        for metric in ("legacy_total_uJ", "legacy_rectified_excess_uJ", "baseline_power_mW", "legacy_window_delta_signed_uJ"):
            aggregates.append({"role": role, "scope": "legacy_window_or_baseline", "window_ms": 4.76,
                               "metric": metric, **stats([r[metric] for r in records])})
        for duration in OBSERVATION_MS:
            records = [r for r in observations if r["role"] == role and r["window_end_ms"] == duration]
            for metric in ("energy_total_uJ", "baseline_energy_uJ", "energy_delta_signed_uJ"):
                aggregates.append({"role": role, "scope": "local_observation", "window_ms": duration,
                                   "metric": metric, **stats([r[metric] for r in records])})
    for metric in ("energy_total_uJ", "baseline_energy_uJ", "energy_delta_signed_uJ"):
        aggregates.append({"role": "tx_plus_rx", "scope": "sum_of_local_observation_budgets", "window_ms": PRIMARY_MS,
                           "metric": metric, **stats([r[metric] for r in paired])})
    return {"source_session_id": pairing["session_id"], "sample_rate_hz": rate,
            "source_created_utc": pairing["created_utc"],
            "fixture": {"interface_label": pairing["interface_label"], "ppk_mode": pairing["ppk_mode"],
                        "payload_bytes": pairing["payload_bytes"], "rf_profile": pairing["rf_profile"],
                        "tx_power_dbm": pairing["tx_power_dbm"],
                        "endpoints": {role: {key: pairing["endpoints"][role][key]
                                             for key in ("radio_port", "ppk_port", "voltage_mv", "identity", "modem_preflight")}
                                      for role in ("tx", "rx")}},
            "quality_status": "numerically_reproduced_stream_review_required" if any(r["counter_transition_anomalies"] for r in wire_checks) else "numerically_reproduced",
            "supply_provenance": pairing["voltage_provenance"], "input_sha256": files,
            "calculation_script_sha256": sha256(Path(__file__).resolve()),
            "method": {"baseline_ms": BASELINE_MS, "observation_durations_ms": OBSERVATION_MS,
                "primary_observation_ms": PRIMARY_MS, "baseline_variants_ms": BASELINE_VARIANTS_MS,
                "energy_uJ": "V * sum(current_uA) / sample_rate_hz",
                "delta_uJ": "energy_uJ - V * pretrigger_mean_uA * window_seconds; signed, no clipping",
                "dispersion": "Sample SD across the five transfers; not absolute measurement uncertainty",
                "primary_window_reason": "Fixed 0..200 ms per local marker; host callback coverage is checked, but independent sample clocks do not define synchronized RF boundaries",
                "maximum_host_callback_end_ms": max(r["callback_finished_from_local_host_marker_ms"] for r in timing_rows),
                "scope": "Observation budgets include listening, idle, UART and firmware activity; baseline subtraction is not RF-only energy",
                "voltage": "Constant operator-confirmed supply; voltage was not sampled with current",
                "loss": "Recorded sample-loss value is a duration/count estimate, not proof of stream continuity",
                "wire_counter_source": COUNTER_SOURCE,
                "wire_counter_caveat": "Modulo-64 continuity cannot detect losses of multiples of 64; counter anomalies do not identify ADC corruption or a definite number of missing samples. No samples repaired or removed.",
                "legacy_rx": "0..4.76 ms at host marker is listening; it precedes the observed receive-associated activity",
                "legacy_tx": "Aligned 4.76 ms model = (32+12)*8/200000 s + 0.003 s; not measured RF airtime",
                "rf_only_rx_energy_uJ": None,
                "rf_only_rx_status": "Not identifiable from software-marker/current data without a validated RF-active interval"},
            "legacy_reproduced": original, "observations": observations, "paired_budgets": paired,
            "baseline_sensitivity": baseline_sensitivity, "baseline_reference_windows": reference_windows,
            "trace_checks": trace_checks, "wire_checks": wire_checks, "timing": timing_rows, "aggregates": aggregates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output == source or source in output.parents:
        raise SystemExit("Output must be separate from the original capture")
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Refusing to overwrite a nonempty output directory")
    result = calculate(source)
    output.mkdir(parents=True, exist_ok=True)
    (output / "calculation.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name in ("legacy_reproduced", "observations", "paired_budgets", "baseline_sensitivity",
                 "baseline_reference_windows", "trace_checks", "timing", "aggregates"):
        write_csv(output / f"{name}.csv", result[name])
    print(json.dumps({"source": result["source_session_id"], "output": str(output),
                      "raw_files_verified": len(result["trace_checks"]),
                      "primary_aggregates": [r for r in result["aggregates"] if r["window_ms"] == PRIMARY_MS]}, indent=2))


if __name__ == "__main__":
    main()
