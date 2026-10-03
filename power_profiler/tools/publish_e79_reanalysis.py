"""Publish validated E79 ESP32 TX reanalysis without altering archived captures.

Usage: python power_profiler/tools/publish_e79_reanalysis.py --reanalysis DIR
Use --validate-only for preflight, or --output DIR to stage comparison exports.
RX/continuous source exports and the imported measurement archive are read-only.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CODE_ROOT / "power_profiler"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from radio_power_profiler.results import FIELDS, ResultWriter
from generate_transfer_report import build_report, write_csv, write_xlsx
import generate_web_campaign_reports as campaign

BASE = "ebyte_e79_400dm2005s"
SESSION = "20260719_003026_campaign_radio_ebyte_e79_cc1352p"
EXTRA_FIELDS = ("analysis_error", "integration_method", "integration_windows_ms")
METRIC_FIELDS = {
    "event_start_ms", "event_duration_ms", "tx_mean_uA", "tx_peak_uA",
    "event_mean_uA", "event_peak_uA", "charge_total_uC", "charge_excess_uC",
    "energy_total_uJ", "energy_excess_uJ",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def contained_path(root, relative):
    normalized = str(relative).replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Expected an archive-relative path: {relative}")
    path = root.joinpath(*normalized.split("/")).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes archive: {relative}")
    return path


def historical_relative(value):
    parts = re.split(r"[\\/]+", value)
    if "power_profiler" not in parts:
        raise ValueError(f"Historical result has no power_profiler root: {value}")
    return "/".join(parts[parts.index("power_profiler") + 1:])


def load_integrity_cache(path):
    if path is None or not path.is_file():
        return {}, None
    entries = {}
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            item = json.loads(line)
            key = item["path"].replace("\\", "/")
            if key in entries:
                raise ValueError(f"Duplicate integrity-cache entry: {key}")
            entries[key] = item
    return entries, path.stat().st_mtime_ns


def verify_raw(path, relative, expected_hash, cache, cache_mtime):
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_hash)) or not path.is_file():
        raise ValueError(f"Missing RAW or invalid SHA256 provenance: {relative}")
    item = cache.get(relative)
    stat = path.stat()
    if item is not None:
        if not item.get("valid") or item.get("sha256_compressed") != expected_hash:
            raise ValueError(f"RAW hash disagrees with verified integrity audit: {relative}")
        if stat.st_size != item.get("compressed_bytes"):
            raise ValueError(f"RAW size changed since integrity audit: {relative}")
        if cache_mtime is not None and stat.st_mtime_ns <= cache_mtime:
            return "prior_full_integrity_audit_plus_size_and_mtime"
    if sha256(path) != expected_hash:
        raise ValueError(f"RAW SHA256 mismatch: {relative}")
    return "fresh_sha256"


def validate_corrected(record, original):
    if record.get("quality") != "model_window_reanalysis" or record.get("reasons") != []:
        raise ValueError(f"Reanalysis still requires review: {record.get('step_id')}/{record.get('run_id')}")
    corrected = record.get("corrected_summary")
    if not isinstance(corrected, dict) or corrected.get("analysis_error") != "":
        raise ValueError("Missing corrected_summary or nonempty analysis_error")
    if any(field not in corrected for field in FIELDS):
        raise ValueError("Corrected summary lacks required result fields")
    if corrected.get("measurement_direction") != "tx":
        raise ValueError("Publisher accepts TX only")
    for key, value in original.items():
        if key not in METRIC_FIELDS and key not in EXTRA_FIELDS:
            if str(corrected.get(key, "")) != str(value):
                raise ValueError(f"Reanalysis changed original configuration/telemetry: {key}")
    for label in ("total", "excess"):
        source = float(original[f"energy_{label}_uJ"])
        if not math.isclose(float(record[f"original_energy_{label}_uJ"]), source, rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError("Original summary disagrees with reanalysis provenance")
        new = float(corrected[f"energy_{label}_uJ"])
        if not math.isfinite(new) or new < 0 or not math.isclose(new, float(record[f"recalculated_energy_{label}_uJ"]), rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError("Corrected energy disagrees with reanalysis result")
    method = corrected.get("integration_method")
    if method not in {"original_single_frame_window_verified", "per_frame_modeled_airtime_v1"}:
        raise ValueError(f"Unrecognized integration method: {method}")
    windows = json.loads(corrected["integration_windows_ms"])
    if windows != record.get("frame_windows_ms") or len(windows) != int(original["frame_count"]):
        raise ValueError("Integration-window provenance or frame count mismatch")
    previous_end = -math.inf
    for start, end in windows:
        if not all(math.isfinite(x) for x in (start, end)) or start < previous_end or end <= start:
            raise ValueError("Invalid or overlapping integration windows")
        previous_end = end
    duration = sum(end - start for start, end in windows)
    if not math.isclose(duration, float(corrected["event_duration_ms"]), rel_tol=1e-9, abs_tol=0.011):
        raise ValueError("Corrected duration does not equal the integration-window union")
    energy = float(corrected["event_mean_uA"]) * duration * float(corrected["voltage_mv"]) / 1e6
    if not math.isclose(energy, float(corrected["energy_total_uJ"]), rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError("Corrected mean current, duration and energy are inconsistent")
    if int(original["frame_count"]) == 1:
        if method != "original_single_frame_window_verified" or any(
            not math.isclose(float(corrected[field]), float(original[field]), rel_tol=1e-12, abs_tol=1e-8)
            for field in METRIC_FIELDS
        ):
            raise ValueError("Single-frame measurements must retain their original metrics")
    return corrected


def validate_inputs(root, reanalysis, integrity_audit):
    archive = root / "measurements/raw/archive"
    runs_path = reanalysis / "runs.json"
    records = read_json(runs_path)
    if not isinstance(records, list) or len(records) != 630:
        raise ValueError("Publication requires exactly 630 E79 ESP32 TX repetitions")
    manifest_path = archive / "comparisons" / BASE / "campaign_logs/manifest.json"
    manifest = read_json(manifest_path)
    expected, source_metadata, originals = {}, {}, {}
    for step in manifest["steps"]:
        if not step["step_id"].startswith("tx_p"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", step["step_id"]):
            raise ValueError("Unsafe step identifier in source manifest")
        if step.get("status") != "completed" or not step.get("accepted_result"):
            raise ValueError("Incomplete authoritative TX manifest")
        relative = historical_relative(step["accepted_result"])
        if not relative.startswith(f"web_sessions/{SESSION}/packet_tx/"):
            raise ValueError("Unexpected authoritative E79 TX source")
        directory = contained_path(archive, relative)
        metadata_path, summary_path = directory / "metadata.json", directory / "summary.csv"
        source_metadata[step["step_id"]] = read_json(metadata_path)
        hashes = {"source_metadata_sha256": sha256(metadata_path), "source_summary_sha256": sha256(summary_path)}
        for row in read_csv(summary_path):
            key = (step["step_id"], row["run_id"])
            if key in expected:
                raise ValueError("Duplicate run in authoritative source manifest")
            expected[key] = relative + "/raw/" + row["run_id"] + ".csv.gz"
            originals[key] = (row, hashes)
    if len(expected) != 630:
        raise ValueError("Authoritative source matrix is incomplete")
    cache, cache_mtime = load_integrity_cache(integrity_audit)
    grouped, provenance, seen = defaultdict(list), [], set()
    for record in records:
        key = (record["step_id"], record["run_id"])
        relative = record["raw_relative_path"].replace("\\", "/")
        if key in seen or expected.get(key) != relative:
            raise ValueError(f"Duplicate or non-authoritative reanalysis run: {key}")
        seen.add(key)
        original, source_hashes = originals[key]
        corrected = validate_corrected(record, original)
        mode = verify_raw(contained_path(archive, relative), relative, record.get("raw_sha256"), cache, cache_mtime)
        grouped[key[0]].append(corrected)
        provenance.append({
            "step_id": key[0], "run_id": key[1], "raw_relative_path": relative,
            "raw_sha256": record["raw_sha256"], "raw_verification": mode, **source_hashes,
            "integration_method": corrected["integration_method"],
            "integration_windows_ms": corrected["integration_windows_ms"],
            "payload_bytes": original["payload_bytes"], "parameters_json": original["parameters_json"],
            "status": original["status"], "packet_received": original["packet_received"],
            "old_energy_total_uJ": original["energy_total_uJ"],
            "new_energy_total_uJ": corrected["energy_total_uJ"],
            "old_energy_excess_uJ": original["energy_excess_uJ"],
            "new_energy_excess_uJ": corrected["energy_excess_uJ"],
            "change_total_percent": 100 * (float(corrected["energy_total_uJ"]) / float(original["energy_total_uJ"]) - 1),
        })
    if seen != set(expected) or len(grouped) != 126:
        raise ValueError("Reanalysis does not cover every authoritative TX condition")
    for step_id, rows in grouped.items():
        if len(rows) != 5 or {int(row["repetition"]) for row in rows} != set(range(1, 6)):
            raise ValueError(f"Missing five-repetition group: {step_id}")
    inputs = {"runs_sha256": sha256(runs_path), "source_manifest_sha256": sha256(manifest_path)}
    if runs_path.resolve().is_relative_to(root.resolve()):
        inputs["runs_repository_path"] = runs_path.resolve().relative_to(root.resolve()).as_posix()
    if integrity_audit is not None and integrity_audit.is_file():
        inputs["integrity_audit_sha256"] = sha256(integrity_audit)
    return grouped, source_metadata, provenance, inputs


def numeric_report(rows):
    text = {"profile_id", "module", "measurement_direction", "rf_profile"}
    integer = {"payload_bytes", "frame_count", "max_frame_payload_bytes", "runs", "events_detected", "packets_attempted", "packets_received", "packets_lost", "status_ok_runs"}
    return [{key: value if key in text else int(value or 0) if key in integer else float(value or 0) for key, value in row.items()} for row in rows]


def find_program(name):
    candidate = shutil.which(name)
    if candidate:
        return Path(candidate)
    candidate = Path("C:/Program Files/MiKTeX/miktex/bin/x64") / (name + ".exe")
    return candidate if candidate.is_file() else None


def render_graphs(tex_files, no_render):
    latex, ghostscript = find_program("pdflatex"), find_program("mgs")
    if no_render or latex is None or ghostscript is None:
        return {"status": "not_rendered", "reason": "explicit --no-render" if no_render else "pdflatex or mgs unavailable"}
    for tex in tex_files:
        result = subprocess.run([str(latex), "-interaction=nonstopmode", "-halt-on-error", tex.name], cwd=tex.parent, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(f"LaTeX rendering failed: {tex.name}\n{result.stdout[-3000:]}")
        subprocess.run([str(ghostscript), "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pngalpha", "-r180", f"-sOutputFile={tex.with_suffix('.png').name}", tex.with_suffix(".pdf").name], cwd=tex.parent, check=True, capture_output=True)
    return {"status": "rendered", "tex_files": [path.name for path in tex_files]}


def publish(root, reanalysis, output, integrity_audit=None, *, no_render=False, validate_only=False):
    root, reanalysis, output = root.resolve(), reanalysis.resolve(), output.resolve()
    canonical = root / "power_profiler/comparisons" / BASE
    archive = root / "measurements/raw/archive"
    if not output.is_relative_to(root) or output.is_relative_to(archive):
        raise ValueError("Publication output must be inside the repository and outside the source archive")
    grouped, metadata, provenance, inputs = validate_inputs(root, reanalysis, integrity_audit)
    if validate_only:
        return {"status": "validated", "runs": 630, "conditions": 126, "inputs": inputs}
    rx_rows = numeric_report(read_csv(canonical / f"{BASE}_rx.csv"))
    old_combined = read_csv(canonical / f"{BASE}_data.csv")
    old_rx = [row for row in old_combined if row["measurement_direction"] == "rx"]
    protected = {
        path: sha256(path) for path in canonical.iterdir()
        if path.is_file()
        and ("_rx." in path.name or "_continuous" in path.name or "_loss_vs_rate" in path.name)
        and "_continuous_average_power" not in path.name
    }
    temp_root = root / ".tmp"
    temp_root.mkdir(exist_ok=True)
    derivation = Path("reanalysis") / ("modeled_tx_" + inputs["runs_sha256"][:12])
    with tempfile.TemporaryDirectory(prefix="e79-publication-", dir=temp_root) as temporary:
        stage = Path(temporary)
        report, summary = [], []
        for step_id, rows in sorted(grouped.items()):
            destination = stage / derivation / step_id
            item_metadata = copy.deepcopy(metadata[step_id])
            item_metadata["derived_from"] = {"raw_root": "measurements/raw/archive", "source_step": step_id, **inputs}
            item_metadata["save_raw"] = False
            item_metadata["analysis_note"] = "Derived modeled-airtime frame windows; archived RAW and original summaries remain unchanged. Host gaps and standby transitions are outside this metric."
            with ResultWriter(destination, item_metadata) as writer:
                for row in sorted(rows, key=lambda value: int(value["repetition"])):
                    writer.add(row)
                writer.write_aggregates()
            # Keep the integration provenance even with historical ResultWriter
            # versions whose FIELDS predate the three analysis columns.
            fields = list(dict.fromkeys([*FIELDS, *EXTRA_FIELDS]))
            with (destination / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(sorted(rows, key=lambda value: int(value["repetition"])))
            aggregates, run_rows, _ = build_report(destination)
            if len(aggregates) != 1:
                raise ValueError(f"Expected one derived aggregate per step: {step_id}")
            report.extend(aggregates)
            summary.extend(run_rows)
        report.sort(key=lambda row: (row["tx_power_dbm"], row["bit_rate_kbps"], row["rf_profile"], row["payload_bytes"]))
        sizes, powers, settings, rx_power, module, frame_limit = campaign._validate_energy_matrix(report, rx_rows, 5)
        campaign_metadata = campaign._campaign_metadata(next(iter(metadata.values())), "tx", sizes, powers, settings)
        campaign_metadata["derived_from"] = {"method": "modeled per-frame TX windows", **inputs}
        for suffix, rows, run_rows in [
            ("_tx", report, summary),
            ("_payload_128_512_1024", [row for row in report if row["payload_bytes"] >= 128], [row for row in summary if int(row["payload_bytes"]) >= 128]),
        ]:
            write_csv(stage / f"{BASE}{suffix}.csv", rows)
            write_xlsx(stage / f"{BASE}{suffix}.xlsx", rows, run_rows, campaign_metadata)
        combined = report + old_rx
        combined.sort(key=lambda row: (row["measurement_direction"], float(row["tx_power_dbm"]), float(row["bit_rate_kbps"]), row["rf_profile"], int(row["payload_bytes"])))
        campaign._write_energy_data(stage / f"{BASE}_data.csv", combined)
        if [row for row in read_csv(stage / f"{BASE}_data.csv") if row["measurement_direction"] == "rx"] != old_rx:
            raise ValueError("Combined export would change original RX values or ordering")
        campaign._write_energy_data(stage / f"{BASE}_energy_vs_payload_data.csv", report)
        tex_files = [stage / f"{BASE}{suffix}.tex" for suffix in ("_tx_energy", "_energy_vs_payload", "_tx_rx_energy")]
        campaign._write_tx_tex(tex_files[0], report, sizes, powers, settings, module, frame_limit, "reanalysed TX window energy")
        campaign._write_tx_tex(tex_files[1], report, sizes, powers, settings, module, frame_limit, "reanalysed energy versus logical payload")
        campaign._write_tx_rx_tex(tex_files[2], report, rx_rows, sizes, settings, rx_power, module)
        for tex in tex_files:
            text = tex.read_text(encoding="utf-8")
            text = text.replace("Mean total energy [mJ]", "Mean window energy [mJ]")
            text = text.replace("RX energy includes receiver activation, reception, and processing of all physical frames.", "RX retains its original modeled-airtime listening window; receiver wake-up and shutdown are excluded.")
            text = text.replace("Mean of 5 repetitions;", "TX sums modeled-airtime frame windows; inter-frame gaps are excluded. Mean of 5 repetitions;")
            tex.write_text(text, encoding="utf-8")
        continuous_tex = stage / f"{BASE}_continuous_average_power.tex"
        continuous_text = (canonical / continuous_tex.name).read_text(encoding="utf-8")
        continuous_text = continuous_text.replace("Putere peste standby", "Putere peste baseline pretrigger")
        continuous_tex.write_text(continuous_text, encoding="utf-8")
        tex_files.append(continuous_tex)
        for tex in tex_files:
            # Use scalable T1 fonts instead of asking MiKTeX to generate PK
            # bitmap fonts in a user-level cache during a repository build.
            text = tex.read_text(encoding="utf-8")
            if r"\usepackage{lmodern}" not in text:
                text = text.replace(r"\usepackage[T1]{fontenc}", "\\usepackage[T1]{fontenc}\n\\usepackage{lmodern}")
            tex.write_text(text, encoding="utf-8")
        rendering = render_graphs(tex_files, no_render)
        provenance_path = stage / f"{BASE}_reanalysis_old_vs_new.csv"
        with provenance_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, list(provenance[0]))
            writer.writeheader()
            writer.writerows(sorted(provenance, key=lambda row: (row["step_id"], row["run_id"])))
        # Publish only declared report assets; LaTeX auxiliaries remain temporary.
        assets = [path for path in stage.rglob("*") if path.is_file() and path.suffix in {".json", ".csv", ".xlsx", ".tex", ".pdf", ".png"}]
        publication = {
            "kind": "derived_e79_esp32_tx", "runs": 630, "conditions": 126,
            "interpretation": "Sum of modeled-airtime windows per detected frame, not end-to-end transaction energy. Single-frame original windows retained; original RF losses retained.",
            "inputs": inputs, "rendering": rendering, "derived_results": derivation.as_posix(),
            "code_sha256": {str(path.relative_to(CODE_ROOT)): sha256(path) for path in [Path(__file__), CODE_ROOT / "power_profiler/tools/reanalyze_e79_tx.py", CODE_ROOT / "power_profiler/radio_power_profiler/frame_detection.py", CODE_ROOT / "power_profiler/radio_power_profiler/frame_windows.py"] if path.is_file()},
            "artifacts_sha256": {path.relative_to(stage).as_posix(): sha256(path) for path in sorted(assets)},
            "protected_exports_sha256": {path.name: digest for path, digest in protected.items()},
            "source_archive_modified": False,
        }
        publication["manifest_sha256"] = hashlib.sha256(json.dumps(publication, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest = stage / f"{BASE}_reanalysis_manifest.json"
        dump_json(manifest, publication)
        assets.append(manifest)  # Commit the manifest after the assets it names.
        if any(sha256(path) != digest for path, digest in protected.items()):
            raise ValueError("An RX/continuous source export changed during publication")
        for source in assets:
            destination = output / source.relative_to(stage)
            destination.parent.mkdir(parents=True, exist_ok=True)
            pending = destination.with_name(destination.name + ".publishing")
            shutil.copy2(source, pending)
            os.replace(pending, destination)
    return publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=CODE_ROOT)
    parser.add_argument("--reanalysis", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--integrity-audit", type=Path)
    parser.add_argument("--no-render", action="store_true", help="Explicitly defer PDF/PNG rendering; recorded in the manifest")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / "power_profiler/comparisons" / BASE
    audit = args.integrity_audit or root / "power_profiler/audits/2026-09-29/raw-full-integrity.jsonl"
    if not audit.is_file() and args.integrity_audit is None:
        audit = root / ".tmp/recapture-audit-20260929/raw-full-integrity.jsonl"
    try:
        result = publish(root, args.reanalysis, output, audit, no_render=args.no_render, validate_only=args.validate_only)
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Publication refused: {error}\n")
    print(json.dumps({
        "status": result.get("status", "published"),
        "runs": result["runs"], "conditions": result["conditions"],
        **({"rendering": result["rendering"]} if "rendering" in result else {}),
    }, indent=2))


if __name__ == "__main__":
    main()
