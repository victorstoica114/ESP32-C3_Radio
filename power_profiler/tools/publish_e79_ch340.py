"""Publish the verified CH340 TX-only supplement, preserving other comparisons.

The accepted release uses a different adapter and measured DUT from the original
CH9340C plan. It must never replace that historical series. Requires the complete
independent RAW/window verification and preserves measured radio losses.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "power_profiler"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_transfer_report import build_report, write_csv as write_report_csv, write_xlsx
from generate_web_campaign_reports import _radio_settings, _write_tx_tex
from publish_e79_reanalysis import render_graphs

BASE = "e79_ch340"
OUTPUT = ROOT / "power_profiler/comparisons/ebyte_e79_ch340_20260929"
RELEASE_COMMIT = "37599a2a5394de9aa3a84432e578dbcaadfd6da2"
RELEASE_URL = "https://github.com/victorstoica114/ESP32-C3_Radio/releases/download/e79-ch340-tx-recapture-20260929/e79_ch340_tx_recapture_20260929_full_session.zip"
RELEASE_SHA256 = "fe09b18b6332ba34362133ab4ca97297633f2f786a21d0af6377544787e6068a"
SESSION_MANIFEST_SHA256 = "d79432dc03c19153fab5ff6930b721d385b6f51d5eb28db0840ea44d90b8eb54"
LOTS = (
    "lot45_gfsk200_consensus/20260929_185646_radio_ebyte_e79_cc1352p",
    "lot270_other_profiles_final_candidate2/20260929_193856_radio_ebyte_e79_cc1352p",
)
PHYS = ("GFSK4K8", "GFSK50", "GFSK200", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def key(row):
    return str(row["rf_profile"]), float(row["tx_power_dbm"]), int(row["payload_bytes"])


def validate(session, verification, archive, regression):
    proof = read_json(verification / "summary.json")
    for field in ("runs", "energy_reproduced_from_raw", "current_analyzer_valid", "unchanged_windows"):
        require(proof.get(field) == 315, f"Independent verification incomplete: {field}")
    require(proof["status_counts"] == {"ok": 245, "rx_missing": 70}, "Unexpected accepted status cohort")
    require(sha256(archive) == RELEASE_SHA256, "Release archive SHA-256 mismatch")
    session_manifest = session / "SESSION_MANIFEST_SHA256.csv"
    require(sha256(session_manifest) == SESSION_MANIFEST_SHA256, "Session manifest SHA-256 mismatch")
    manifest_rows = read_csv(session_manifest)
    source_hashes = {row["relative_path"].replace("\\", "/"): row["sha256"] for row in manifest_rows}
    proof_rows = read_json(verification / "runs.json")
    proof_lookup = {(row["source_relative_directory"], row["run_id"]): row for row in proof_rows}
    require(len(proof_lookup) == len(proof_rows) == 315, "Duplicate or missing verification identities")
    for name, expected_hash in proof["code_sha256"].items():
        require(sha256(ROOT / "power_profiler/radio_power_profiler" / name) == expected_hash,
                "Analyzer code changed since independent verification: " + name)
    regression_summary = read_json(regression / "summary.json")
    require(regression_summary["processed_runs"] == 315 and not regression_summary["errors"], "ESP32 regression incomplete")
    require(regression_summary["quality_counts"] == {"model_window_reanalysis": 315}, "ESP32 regression rejected captures")

    def check_source(relative):
        digest = sha256(session / relative)
        require(source_hashes.get(relative) == digest, "Release file hash mismatch: " + relative)
        return digest

    reports, runs, metadata, inputs = [], [], {}, {}
    for lot in LOTS:
        folder = session / lot
        for name in ("metadata.json", "summary.csv", "aggregates.csv"):
            relative = lot + "/" + name
            inputs[relative] = check_source(relative)
        report, source_runs, meta = build_report(folder)
        require(meta["measured_port"] == "COM16" and meta["ppk_port"] == "COM13", "Wrong accepted DUT/PPK mapping")
        require(meta["voltage_mv"] == 3300 and meta["sample_rate_hz"] == 100000 and meta["ppk_mode"] == "ampere", "Wrong measurement settings")
        require(meta["profile"]["baudrate"] == 1000000 and meta["save_raw"] is True, "Wrong UART/RAW settings")
        metadata[lot] = meta
        grouped = defaultdict(list)
        for row in source_runs:
            require(row["status"] in ("ok", "rx_missing") and not row["analysis_error"], "Rejected source row")
            require(row["integration_method"] == "per_frame_modeled_airtime_v1", "Wrong integration method")
            params = json.loads(row["parameters_json"])
            group_key = (params["rf_profile"], float(params["tx_power_dbm"]), int(row["payload_bytes"]))
            grouped[group_key].append(row)
            verified = proof_lookup[(lot, row["run_id"])]
            require(not verified["current_analysis_error"] and verified["windows_equal"], "Unverified current analysis")
            require(verified["archived_windows_ms"] == json.loads(row["integration_windows_ms"]), "Verified/source windows differ")
            require(verified["archived_energy_total_uJ"] == float(row["energy_total_uJ"]), "Verified/source total differs")
            require(verified["archived_energy_excess_uJ"] == float(row["energy_excess_uJ"]), "Verified/source excess differs")
            raw_relative = lot + "/raw/" + row["run_id"] + ".csv.gz"
            require(check_source(raw_relative) == verified["raw_sha256"], "RAW differs from verified trace")
            inputs[raw_relative] = verified["raw_sha256"]
            runs.append({"source_lot": lot, "source_run_key": lot + "/" + row["run_id"], **row})
        for aggregate in report:
            original = grouped[key(aggregate)]
            require(len(original) == aggregate["runs"] == 5, "Incomplete aggregate")
            for metric, summary_field in (("energy_total_uJ_mean", "energy_total_uJ"),
                                          ("energy_excess_uJ_mean", "energy_excess_uJ"),
                                          ("event_duration_ms_mean", "event_duration_ms")):
                mean = statistics.fmean(float(row[summary_field]) for row in original)
                require(math.isclose(mean, aggregate[metric], rel_tol=1e-12, abs_tol=1e-9), "Stale aggregate: " + metric)
            aggregate["module"] = "Ebyte E79-400DM2005S via CH340 (CC1352P)"
        reports.extend(report)
    expected = Counter(itertools.product(PHYS, (-20.0, 0.0, 13.0), (128, 512, 1024)))
    require(Counter(key(row) for row in reports) == expected, "Incomplete or duplicate 63-condition report")
    actual_runs = Counter((*key({**json.loads(row["parameters_json"]), "payload_bytes": row["payload_bytes"]}), int(row["repetition"])) for row in runs)
    require(actual_runs == Counter((*condition, rep) for condition in expected for rep in range(1, 6)), "Incomplete 315-run matrix")
    require(Counter(row["status"] for row in runs) == Counter(proof["status_counts"]), "RF-loss cohort changed")
    reports.sort(key=lambda row: (row["tx_power_dbm"], row["bit_rate_kbps"], row["rf_profile"], row["payload_bytes"]))
    runs.sort(key=lambda row: (row["source_lot"], int(row["run_id"].split("_")[-1])))
    return reports, runs, metadata, proof, proof_rows, inputs, source_hashes, regression_summary


def compare_esp32(reports, metadata):
    folder = ROOT / "power_profiler/comparisons/ebyte_e79_400dm2005s"
    publication = read_json(folder / "ebyte_e79_400dm2005s_reanalysis_manifest.json")
    csv_path = folder / "ebyte_e79_400dm2005s_tx.csv"
    require(sha256(csv_path) == publication["artifacts_sha256"][csv_path.name], "Published ESP32 CSV changed")
    old = {key(row): row for row in read_csv(csv_path) if int(row["payload_bytes"]) > 64}
    require(set(old) == {key(row) for row in reports}, "ESP32 matched matrix differs")
    result = []
    checked_sources = {str(csv_path.relative_to(ROOT)).replace("\\", "/"): sha256(csv_path)}
    for row in reports:
        phy, power, payload = key(row)
        counterpart = old[(phy, power, payload)]
        step = f"tx_p{power:g}_rf_profile-{phy}_s{payload}"
        source = folder / publication["derived_results"] / step
        frozen = read_json(source / "metadata.json")
        source_rows = read_csv(source / "summary.csv")
        for name in ("metadata.json", "summary.csv"):
            path = source / name
            require(sha256(path) == publication["artifacts_sha256"][str(path.relative_to(folder)).replace("\\", "/")], "ESP32 derivation changed")
            checked_sources[str(path.relative_to(ROOT)).replace("\\", "/")] = sha256(path)
        require(frozen["voltage_mv"] == 3300 and frozen["sample_rate_hz"] == 100000, "ESP32 voltage/sample rate incompatible")
        require({float(r["voltage_mv"]) for r in source_rows} == {3300.0}, "ESP32 run voltage incompatible")
        require(frozen["profile"]["airtime"] == next(iter(metadata.values()))["profile"]["airtime"], "Airtime models differ")
        require(int(counterpart["frame_count"]) == row["frame_count"], "Physical frame counts differ")
        require(math.isclose(float(counterpart["event_duration_ms_mean"]), row["event_duration_ms_mean"], abs_tol=1e-8), "Modeled durations differ")
        item = {"rf_profile": phy, "tx_power_dbm": power, "payload_bytes": payload,
                "frame_count": row["frame_count"], "voltage_mv": 3300,
                "modeled_duration_ms": row["event_duration_ms_mean"], "ch340_runs": row["runs"], "esp32_runs": int(counterpart["runs"])}
        for field in ("energy_total_uJ_mean", "energy_total_uJ_stdev", "energy_excess_uJ_mean", "packet_loss_percent",
                      "packets_received", "packets_lost", "sample_loss_percent_max"):
            item["ch340_" + field] = row[field]
            item["esp32_" + field] = float(counterpart[field])
        item["total_energy_ratio_ch340_over_esp32"] = row["energy_total_uJ_mean"] / float(counterpart["energy_total_uJ_mean"])
        item["excess_energy_ratio_ch340_over_esp32"] = row["energy_excess_uJ_mean"] / float(counterpart["energy_excess_uJ_mean"])
        item["total_energy_difference_percent"] = 100 * (item["total_energy_ratio_ch340_over_esp32"] - 1)
        result.append(item)
    return result, checked_sources


def ratio_tex(path, rows):
    lines = [r"\documentclass[tikz,border=7pt]{standalone}", r"\usepackage[T1]{fontenc}",
             r"\usepackage{lmodern}", r"\usepackage{pgfplots}", r"\usepgfplotslibrary{groupplots}",
             r"\pgfplotsset{compat=1.18}", r"\begin{document}", r"\begin{tikzpicture}",
             r"\begin{groupplot}[group style={group size=3 by 1,horizontal sep=1.0cm},width=6.5cm,height=7cm,",
             r"xlabel={Logical payload [B]},xmode=log,log basis x=2,ymin=0.98,ymax=1.27,",
             r"xtick={128,512,1024},xticklabels={128,512,1024},grid=both,legend style={at={(0.5,-0.23)},anchor=north,legend columns=2,font=\scriptsize}]"]
    colors = ("blue", "red", "green!55!black", "orange", "violet", "cyan!70!black", "black")
    for power in (-20, 0, 13):
        ylabel = ",ylabel={CH340 / ESP32 TX-window energy}" if power == -20 else ""
        lines.append(rf"\nextgroupplot[title={{{power:+d} dBm}}{ylabel}]")
        lines.append(r"\addplot[gray,dashed,forget plot] coordinates {(128,1) (1024,1)};")
        for phy, color in zip(PHYS, colors):
            points = sorted((r for r in rows if r["rf_profile"] == phy and r["tx_power_dbm"] == power), key=lambda r:r["payload_bytes"])
            coords = " ".join(f"({r['payload_bytes']},{r['total_energy_ratio_ch340_over_esp32']:.10g})" for r in points)
            lines.append(rf"\addplot[color={color},mark=*,line width=0.8pt] coordinates {{{coords}}};")
            if power == 0:
                lines.append(rf"\addlegendentry{{{phy}}}")
    lines.extend([r"\end{groupplot}", r"\node[anchor=south,font=\bfseries] at (group c2r1.north) [yshift=30pt] {Separate CH340 and ESP32 acquisition contexts};",
                  r"\node[anchor=north,font=\small,align=center] at (group c2r1.south) [yshift=-110pt] {63 matched condition means, five attempts each; all RF losses retained.\\Ratios describe radio-module windows and session differences, not converter energy or causality.};",
                  r"\end{tikzpicture}", r"\end{document}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def readme(comparison, proof, regression):
    examples = [r for r in comparison if r["rf_profile"] == "GFSK200" and r["tx_power_dbm"] == 13]
    table = "\n".join(f"| {r['payload_bytes']} | {r['ch340_energy_total_uJ_mean']/1000:.6f} | {r['esp32_energy_total_uJ_mean']/1000:.6f} | {r['total_energy_ratio_ch340_over_esp32']:.4f} | {int(r['ch340_packets_received'])}/5 |" for r in examples)
    return f"""# E79 CH340 fragmented-TX supplement, 29 September 2026

This separate dataset contains **315 measured attempts, 63 configurations and seven PHYs**, with five attempts at each combination of -20/0/+13 dBm and 128/512/1024 bytes. Both adapters were physically replaced by CH340 units. These observations do not replace historical CH9340C data or supply its missing all-frame measurements. No 8/32/64-byte CH340, RX or continuous values are synthesized.

The accepted measured E79 DUT is **COM16 through PPK2 COM13**, with COM4 as peer, following the documented switch from the initial COM4/PPK2 COM12 path. The adapter and measured-unit/session changes prevent an isolated USB-bridge causal comparison. Converter supply power is outside the measured radio-module boundary. Firmware was E79 AT modem 0.3.0, UART 1 Mbaud, declared/measured supply 3.3 V and PPK2 Ampere mode at 100 kS/s; see [the original bench notes](source_lots/BENCH_NOTES.md).

## Results and interpretation

- **245 `ok` and 70 `rx_missing`** are retained. No measured RF-loss attempt was removed or retried selectively in the accepted lots. Entire earlier diagnostic/aborted attempts remain in the release archive and are not pooled into these results.
- The metric sums 2/8/16 disjoint modeled-airtime windows around detected current bursts. It excludes inter-frame host/UART/ACK gaps and is not full-transaction energy. `event_duration_ms` is summed window length, not wall-clock transfer span. Excess energy subtracts the pre-trigger baseline within these windows; it is not independently measured standby energy.
- Independent full-RAW verification reproduced all 315 archived energies and all 315 windows; current analyzer results are valid for all 315. Maximum reported sample loss is {proof['sample_loss_percent_max']:.6f}%; unavailable samples are not reconstructed.
- Primary 4-MAD consensus selected 312 traces. Runs 00009 and 00012 in the 270-run lot use the qualified long-frame low-signal bracket; run 00264 uses the high-signal bracket. Their original diagnostics and inspection PNGs are retained under `evidence/`. The three traces were visually reviewed against their saved windows. Arithmetic agreement and charge-based segmentation do not establish synchronized RF boundaries.
- The ESP32 comparator retains its published values. Re-running its 315 fragmented RAW traces with the new detector accepts all 315, keeps 294 windows identical and changes 21 SLR2K5 windows; the maximum total-energy difference is {regression['maximum_absolute_total_delta_percent']:.9f}%. This method sensitivity remains a comparison limit, not a PPK uncertainty estimate. No ESP32 exports were replaced.

GFSK200 at +13 dBm (means of all five attempts):

| Payload [B] | CH340 window energy [mJ] | Published ESP32 [mJ] | CH340/ESP32 | CH340 received |
| --- | --- | --- | --- | --- |
{table}

## Artifacts

- [`e79_ch340_tx.csv`](e79_ch340_tx.csv), [`e79_ch340_tx.xlsx`](e79_ch340_tx.xlsx): 63 condition aggregates; the workbook contains all 315 summary rows with `source_lot` and globally unique `source_run_key` because run IDs repeat between lots. The PHY-aware matrix has 21 power/PHY rows.
- [`e79_ch340_summary_runs.csv`](e79_ch340_summary_runs.csv): all 315 attempts and recorded delivery telemetry.
- [`e79_ch340_vs_esp32.csv`](e79_ch340_vs_esp32.csv): 63 matched configurations with total/excess energy, standard deviation, loss, compatible modeled duration and voltage, and ratios.
- [`e79_ch340_tx_energy.pdf`](e79_ch340_tx_energy.pdf), [`e79_ch340_vs_esp32.pdf`](e79_ch340_vs_esp32.pdf): TX curves and all 63 matched energy ratios; matching PNG and editable LaTeX files accompany them.
- `source_lots/`: byte-identical original metadata, summary and aggregate files for both accepted lots; bench notes and session file manifest.
- `provenance/`: independent CH340 verification and ESP32 detector-regression summaries/results. The [canonical 30 September audit](../../audits/2026-09-30/) also preserves the release integrity checks and independent proofs. [`publication_manifest.json`](publication_manifest.json) records input, code and output SHA-256 values.

## Source and reproduction

The [complete release archive]({RELEASE_URL}) includes all accepted RAW and all diagnostic/aborted attempts. Archive SHA-256: `{RELEASE_SHA256}`. Release code commit: `{RELEASE_COMMIT}`. This repository supplement does not duplicate the large RAW archive.

After extracting that release and running `tools/verify_e79_ch340_release.py` and the ESP32 regression verification, invoke from the repository root:

```powershell
python -B power_profiler/tools/publish_e79_ch340.py --session <extracted-session> --verification <verification-dir> --archive <release.zip> --esp32-regression <regression-dir>
```

`--validate-only` checks publication gates without writing outputs. Rendering requires `pdflatex` and `mgs`; CSV/XLSX creation requires `openpyxl`. Historical CH9340C/ESP32 comparisons and the main 28-entry study are not modified by this command.
"""


def publish(args):
    session, verification, archive, regression = (p.resolve() for p in (args.session, args.verification, args.archive, args.esp32_regression))
    reports, runs, metadata, proof, proof_rows, source_inputs, session_hashes, regression_summary = validate(session, verification, archive, regression)
    comparison, esp_inputs = compare_esp32(reports, metadata)
    if args.validate_only:
        return {"status": "validated", "runs": len(runs), "conditions": len(reports), "matched_esp32": len(comparison)}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=OUTPUT) as temporary:
        stage = Path(temporary)
        write_report_csv(stage / f"{BASE}_tx.csv", reports)
        campaign_meta = copy.deepcopy(next(iter(metadata.values())))
        campaign_meta["created_utc"] = "2026-09-29; combined accepted lots, see source_lots"
        campaign_meta["profile"]["display_name"] = reports[0]["module"]
        campaign_meta["profile"]["payload_sizes"] = [128, 512, 1024]
        for axis in campaign_meta["profile"]["axes"]:
            axis["values"] = list(PHYS) if axis["name"] == "rf_profile" else [-20, 0, 13] if axis["name"] == "tx_power_dbm" else axis["values"]
        write_xlsx(stage / f"{BASE}_tx.xlsx", reports, runs, campaign_meta)
        write_csv(stage / f"{BASE}_summary_runs.csv", runs)
        write_csv(stage / f"{BASE}_vs_esp32.csv", comparison)
        copy_inputs = {}
        for lot in LOTS:
            for name in ("metadata.json", "summary.csv", "aggregates.csv"):
                relative = lot + "/" + name
                dest = stage / "source_lots" / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(session / relative, dest)
                require(sha256(dest) == source_inputs[relative], "Original source copy changed")
        for name in ("BENCH_NOTES.md", "SESSION_TRANSFER_README.txt", "SESSION_MANIFEST_SHA256.csv"):
            shutil.copy2(session / name, stage / "source_lots" / name)
            copy_inputs[name] = sha256(session / name)
        evidence = stage / "evidence"
        evidence.mkdir()
        fallback = [r for r in proof_rows if r["current_consensus"].get("mode") != "primary_4_MAD"]
        for row in fallback:
            relative = row["source_relative_directory"] + "/analysis/" + row["run_id"] + ".json"
            require(sha256(session / relative) == session_hashes[relative], "Fallback diagnostic hash mismatch")
            shutil.copy2(session / relative, evidence / ("lot270_" + row["run_id"] + ".json"))
            copy_inputs[relative] = session_hashes[relative]
        for stem in ("lot270_inspection_gfsk4k8_rep4", "lot270_inspection_gfsk4k8_rep2", "lot270_inspection_ieee154g50_rep4"):
            name = stem + ".png"
            require(sha256(session / name) == session_hashes[name], "Inspection image hash mismatch")
            shutil.copy2(session / name, evidence / name)
            copy_inputs[name] = session_hashes[name]
        provenance = stage / "provenance"
        provenance.mkdir()
        verification_inputs = {}
        for prefix, directory in (("ch340_verification", verification), ("esp32_regression", regression)):
            for name in ("summary.json", "runs.json" if prefix == "ch340_verification" else "comparisons.csv"):
                shutil.copy2(directory / name, provenance / (prefix + "_" + name))
                verification_inputs[prefix + "_" + name] = sha256(directory / name)
        tx_tex = stage / f"{BASE}_tx_energy.tex"
        _write_tx_tex(tx_tex, reports, [128, 512, 1024], [-20, 0, 13], _radio_settings(reports), reports[0]["module"], 64, "TX frame-window energy")
        text = tx_tex.read_text(encoding="utf-8").replace(r"\usepackage[T1]{fontenc}", "\\usepackage[T1]{fontenc}\n\\usepackage{lmodern}")
        text = text.replace("Mean total energy [mJ]", "Mean TX-window energy [mJ]")
        text = text.replace("Mean of 5 repetitions;", "All five attempts retained, including RF losses; host gaps excluded. Mean of 5 repetitions;")
        tx_tex.write_text(text, encoding="utf-8")
        comparison_tex = stage / f"{BASE}_vs_esp32.tex"
        ratio_tex(comparison_tex, comparison)
        rendering = render_graphs([tx_tex, comparison_tex], False)
        require(rendering["status"] == "rendered", "Publication requires PDF/PNG rendering")
        for suffix in (".aux", ".log"):
            for path in stage.glob("*" + suffix):
                path.unlink()
        (stage / "README.md").write_text(readme(comparison, proof, regression_summary), encoding="utf-8")
        code_files = [Path(__file__), ROOT / "power_profiler/tools/generate_transfer_report.py", ROOT / "power_profiler/tools/generate_web_campaign_reports.py", ROOT / "power_profiler/tools/verify_e79_ch340_release.py", ROOT / "power_profiler/tools/publish_e79_reanalysis.py"]
        manifest = {"kind": "separate_e79_ch340_tx_supplement", "runs": 315, "conditions": 63, "matched_esp32_conditions": 63,
                    "status_counts": proof["status_counts"], "measurement_date": "2026-09-29", "measured_port": "COM16", "ppk_port": "COM13",
                    "release": {"url": RELEASE_URL, "code_commit": RELEASE_COMMIT, "archive_sha256": RELEASE_SHA256,
                                "archive_bytes": archive.stat().st_size, "session_manifest_sha256": SESSION_MANIFEST_SHA256},
                    "accepted_source_lots": LOTS, "source_files_sha256": {**source_inputs, **copy_inputs},
                    "verification_inputs_sha256": verification_inputs, "verification_analyzer_code_sha256": proof["code_sha256"],
                    "publication_code_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in code_files},
                    "published_esp32_inputs_sha256": esp_inputs, "rendering": rendering,
                    "scope": "Separate CH340 TX-only supplement. No historical CH9340C, ESP32, RX, continuous or main-study exports replaced.",
                    "artifacts_sha256": {str(p.relative_to(stage)).replace("\\", "/"): sha256(p) for p in sorted(stage.rglob("*")) if p.is_file()}}
        (stage / "publication_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                destination = OUTPUT / path.relative_to(stage)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    return {"status": "published", "output": str(OUTPUT), "runs": 315, "conditions": 63,
            "gfsk200_13dbm": [r for r in comparison if r["rf_profile"] == "GFSK200" and r["tx_power_dbm"] == 13]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--esp32-regression", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    print(json.dumps(publish(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
