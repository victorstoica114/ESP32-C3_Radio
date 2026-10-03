"""Read-only reproduction of the accepted CH340 release captures, without hardware.

The CH340 fixture is a separate context from historical CH9340C. This tool checks
the archived windows directly and independently reruns the current analyzer. It
reports threshold-dependent frame counts instead of equating arithmetic agreement
with unambiguous RF timing. Original captures and telemetry are never rewritten.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "power_profiler"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radio_power_profiler.analysis import analyze_capture, _frame_sample_lengths
from radio_power_profiler.models import CaptureSpec, TransmitSpec
from radio_power_profiler.planning import estimate_airtime_s
from reanalyze_e79_tx import load_trace

LOTS = (
    ("lot45_gfsk200_consensus/20260929_185646_radio_ebyte_e79_cc1352p", ("GFSK200",)),
    ("lot270_other_profiles_final_candidate2/20260929_193856_radio_ebyte_e79_cc1352p",
     ("GFSK4K8", "GFSK50", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50")),
)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def require(value, message):
    if not value:
        raise ValueError(message)


def verify_run(folder, row, meta):
    rate = meta["sample_rate_hz"]
    raw = folder / "raw" / (row["run_id"] + ".csv.gz")
    samples, trigger = load_trace(raw)  # Full gzip read validates CRC and numeric samples.
    require(len(samples) == int(row["captured_samples"]), "RAW sample count mismatch")
    require(row["profile_id"] == "RADIO_EBYTE_E79_CC1352P" and row["measurement_direction"] == "tx", "Wrong profile/direction")
    require(row["status"] in ("ok", "rx_missing") and not row["analysis_error"], "Unaccepted status")
    require(row["integration_method"] == "per_frame_modeled_airtime_v1", "Wrong method")
    require(float(row["voltage_mv"]) == 3300 and row["ppk_mode"] == "ampere", "Wrong voltage/mode")
    profile = SimpleNamespace(airtime=meta["profile"]["airtime"], transmit=TransmitSpec(**meta["profile"]["transmit"]))
    params = json.loads(row["parameters_json"])
    frame_sizes = profile.transmit.frame_sizes(int(row["payload_bytes"]))
    airtimes = tuple(estimate_airtime_s(profile, size, params) for size in frame_sizes)
    lengths = _frame_sample_lengths(airtimes, rate)
    windows_ms = json.loads(row["integration_windows_ms"])
    windows = [(trigger + round(a * rate / 1000), trigger + round(b * rate / 1000)) for a, b in windows_ms]
    require(len(windows) == len(frame_sizes) == int(row["frame_count"]), "Frame/window count mismatch")
    require(all(trigger <= a < b <= len(samples) and b-a == n for (a,b), n in zip(windows, lengths)), "Invalid modeled windows")
    require(all(a[1] <= b[0] for a,b in zip(windows,windows[1:])), "Overlapping windows")
    require(math.isclose(sum(lengths)*1000/rate, float(row["event_duration_ms"]), abs_tol=1e-8), "Duration mismatch")
    baseline_start = min(int(.010 * rate), trigger // 4)
    baseline_end = max(baseline_start + 1, trigger - int(.005 * rate))
    baseline = statistics.median(samples[baseline_start:baseline_end])
    require(math.isclose(baseline,float(row["baseline_median_uA"]),abs_tol=1e-8), "Baseline mismatch")
    event = [value for a,b in windows for value in samples[a:b]]
    energy = math.fsum(max(0,value) for value in event) / rate * 3.3
    excess = math.fsum(max(0,value-baseline) for value in event) / rate * 3.3
    original = float(row["energy_total_uJ"])
    original_excess = float(row["energy_excess_uJ"])
    require(math.isclose(energy,original,rel_tol=1e-8,abs_tol=1e-6), "Archived total energy not reproduced")
    require(math.isclose(excess,original_excess,rel_tol=1e-8,abs_tol=1e-6), "Archived excess energy not reproduced")
    archived_diag = read_json(folder / "analysis" / (row["run_id"] + ".json"))
    require(archived_diag["integration_windows_ms"] == windows_ms and not archived_diag["analysis_error"], "Archived diagnostic mismatch")
    current = analyze_capture(samples,trigger_index=trigger,sample_rate_hz=rate,voltage_mv=3300,
                              capture_spec=CaptureSpec(**meta["profile"]["capture"]),
                              expected_event_count=len(frame_sizes),frame_airtimes_s=airtimes)
    diag = current.analysis_diagnostics
    primary = next((s for s in diag.get("sensitivity",[]) if s["multiplier"] == 4), {})
    consensus = diag.get("sensitivity_consensus",{})
    return {
        "source_directory": folder.name, "run_id":row["run_id"],
        "raw_sha256":digest(raw), "rf_profile":params["rf_profile"], "tx_power_dbm":params["tx_power_dbm"],
        "payload_bytes":int(row["payload_bytes"]), "repetition":int(row["repetition"]),
        "status":row["status"], "sample_loss_percent":float(row["sample_loss_percent"]),
        "captured_samples":len(samples), "expected_frames":len(frame_sizes),
        "archived_energy_total_uJ":original, "archived_energy_excess_uJ":original_excess,
        "total_reproduction_error_uJ":energy-original, "excess_reproduction_error_uJ":excess-original_excess,
        "archived_windows_ms":windows_ms, "current_windows_ms":current.integration_windows_ms,
        "windows_equal":tuple(tuple(w) for w in windows_ms)==current.integration_windows_ms,
        "current_analysis_error":current.analysis_error,
        "current_energy_total_uJ":current.energy_total_uJ,
        "current_energy_difference_percent":100*(current.energy_total_uJ/original-1) if current.energy_total_uJ is not None else None,
        "current_consensus":consensus, "primary_detected_frames":primary.get("detected_frames"),
        "primary_reasons":primary.get("reasons",[]),
        "threshold_counts":{str(s["multiplier"]):s["detected_frames"] for s in diag.get("sensitivity",[])},
        "current_diagnostics":diag,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args=parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.session.resolve()), "Output must be outside original session")
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for relative,phys in LOTS:
        folder=args.session/relative
        meta=read_json(folder/"metadata.json")
        rows=read_csv(folder/"summary.csv")
        require(meta["save_raw"] and meta["sample_rate_hz"]==100000 and meta["voltage_mv"]==3300, "Invalid metadata")
        require(meta["profile"]["baudrate"]==1000000, "Wrong UART rate")
        expected=Counter(itertools.product(phys,(-20,0,13),(128,512,1024),range(1,6)))
        actual=Counter((json.loads(r["parameters_json"])["rf_profile"],json.loads(r["parameters_json"])["tx_power_dbm"],int(r["payload_bytes"]),int(r["repetition"])) for r in rows)
        require(actual==expected and meta["test_count"]==len(rows), "Matrix mismatch")
        require({p.name for p in (folder/"raw").glob("*.csv.gz")}=={r["run_id"]+".csv.gz" for r in rows}, "RAW coverage mismatch")
        for row in rows:
            result=verify_run(folder,row,meta)
            result["source_relative_directory"]=relative
            results.append(result)
            if len(results)%15==0:
                print(f"Verified {len(results)}/315",flush=True)
    code_names=("analysis.py","frame_detection.py","frame_windows.py","planning.py","models.py")
    summary={
        "fixture":"CH340; not CH9340C", "runs":len(results),
        "status_counts":dict(Counter(r["status"] for r in results)),
        "sample_count":sum(r["captured_samples"] for r in results),
        "sample_loss_percent_max":max(r["sample_loss_percent"] for r in results),
        "energy_reproduced_from_raw":len(results),
        "max_abs_reproduction_error_uJ":max(max(abs(r["total_reproduction_error_uJ"]),abs(r["excess_reproduction_error_uJ"])) for r in results),
        "current_analyzer_valid":sum(not r["current_analysis_error"] for r in results),
        "unchanged_windows":sum(r["windows_equal"] for r in results),
        "consensus_modes":dict(Counter(r["current_consensus"].get("mode","invalid") for r in results)),
        "primary_frame_count_mismatch":sum(r["primary_detected_frames"]!=r["expected_frames"] for r in results),
        "max_abs_energy_change_percent":max(abs(r["current_energy_difference_percent"]) for r in results if r["current_energy_difference_percent"] is not None),
        "code_sha256":{name:digest(ROOT/"power_profiler/radio_power_profiler"/name) for name in code_names},
        "note":"Arithmetic reproduction does not by itself validate RF timing or fixture equivalence. Threshold-dependent count cases require explicit review.",
    }
    (args.output/"runs.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    (args.output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    fields=[k for k in results[0] if k not in ("current_diagnostics","archived_windows_ms","current_windows_ms","current_consensus","threshold_counts","primary_reasons")]
    with (args.output/"runs.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":
    main()
