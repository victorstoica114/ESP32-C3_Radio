"""Read-only audit of the eight 5 V fixtures against historical source data.

Writes only evidence.json and modules.csv alongside this script. Does not
rewrite captures or calculate replacement measurement results. RAW files are
checked for existence; one CSV header per module is inspected, not full CRC.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
COVERAGE = ROOT / "power_profiler/audits/2026-09-29/authoritative_coverage.csv"
MODULES = {
    "ebyte_e22_400m30s": "Ebyte E22-400M30S",
    "e280": "Ebyte E280-2G4T12S",
    "ebyte_e32_433t20d": "Ebyte E32-433T20D",
    "ebyte_e32_433t33d": "Ebyte E32-433T33D",
    "ebyte_e32_868t20d": "Ebyte E32-868T20D",
    "ebyte_e32_868t30d": "Ebyte E32-868T30D",
    "hc12": "HC-12",
    "sx1278_adafruit_level_shifter": "SX1278, placa tip Adafruit cu level shifter",
}
FILES = {}


def relative(path):
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def register(path):
    name = relative(path)
    if name not in FILES:
        FILES[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return name


def read_csv(path):
    register(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def imported_path(value):
    # The selection snapshot contains machine-specific absolute paths.
    marker = "web_sessions/"
    tail = value.replace("\\", "/").split(marker, 1)[1]
    return ROOT / "measurements/raw/archive/web_sessions" / tail


def close_check(actual, expected):
    actual = float(actual)
    assert math.isfinite(actual) and math.isfinite(expected)
    error = abs(actual - expected) / max(abs(expected), 1e-12)
    return error, math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8)


def main():
    register(ROOT / "PCB/TENSIUNI_ALIMENTARE.md")
    reference_path = OUT / "supply_reference.json"
    register(reference_path)
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    supplies = {row["slug"]: row["supply_voltage_mv"] for row in reference["modules"]}
    selected = read_csv(COVERAGE)
    details, flat = [], []
    for slug, label in MODULES.items():
        assert supplies[slug] == 5000, slug
        entries = [row for row in selected if row["comparison"] == slug]
        assert entries, slug
        unique = {(row["summary_path"], row["run_id"]) for row in entries}
        assert len(unique) == len(entries), slug
        summary_paths = sorted({imported_path(row["summary_path"]) for row in entries})
        tables = {path: {row["run_id"]: row for row in read_csv(path)}
                  for path in summary_paths}
        meta = {}
        for path in summary_paths:
            metadata = path.with_name("metadata.json")
            register(metadata)
            meta[path] = json.loads(metadata.read_text(encoding="utf-8-sig"))
        voltages, modes, metadata_voltages = Counter(), Counter(), Counter()
        formulas, raw_present, row_details = Counter(), 0, []
        max_error, failures = 0.0, []
        for entry in entries:
            path = imported_path(entry["summary_path"])
            row = tables[path][entry["run_id"]]
            metadata = meta[path]
            voltage = float(row["voltage_mv"])
            voltages[str(voltage)] += 1
            modes[row.get("ppk_mode") or metadata.get("ppk_mode", "missing")] += 1
            raw = imported_path(entry["raw_path"])
            exists = raw.is_file()
            raw_present += exists
            checks = []
            if entry["category"].startswith("packet_"):
                for kind in ("total", "excess"):
                    if row.get(f"energy_{kind}_uJ") and row.get(f"charge_{kind}_uC"):
                        checks.append((f"packet_energy_{kind}", row[f"energy_{kind}_uJ"],
                                       float(row[f"charge_{kind}_uC"]) * voltage / 1000))
            else:
                checks.append(("continuous_mean_power", row["mean_power_mW"],
                               float(row["mean_current_uA"]) * voltage / 1e6))
                checks.append(("continuous_energy", row["energy_60s_mJ"],
                               float(row["mean_power_mW"]) * float(row["active_window_s"])))
            for name, actual, expected in checks:
                error, passed = close_check(actual, expected)
                max_error = max(max_error, error)
                formulas[name] += 1
                if not passed:
                    failures.append({"summary": relative(path), "run_id": row["run_id"],
                                     "formula": name, "relative_error": error})
            row_details.append({"summary": relative(path), "run_id": row["run_id"],
                                "category": entry["category"], "voltage_mv": voltage,
                                "raw": relative(raw), "raw_exists": exists})
        for metadata in meta.values():
            metadata_voltages[str(metadata.get("voltage_mv", "missing"))] += 1
        first_raw = next(imported_path(row["raw_path"]) for row in entries
                         if imported_path(row["raw_path"]).is_file())
        with gzip.open(first_raw, "rt", encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
        comparison_dir = ROOT / "power_profiler/comparisons" / slug
        published = {}
        for suffix in ("tx", "rx", "continuous"):
            file = comparison_dir / f"{slug}_{suffix}.csv"
            rows = read_csv(file)
            published[suffix] = {"path": relative(file), "rows": len(rows),
                                 "voltage_mv": sorted({row["voltage_mv"] for row in rows
                                                        if "voltage_mv" in row}),
                                 "has_voltage_column": bool(rows and "voltage_mv" in rows[0])}
        record = {
            "slug": slug, "module": label, "fixture_voltage_mv": supplies[slug],
            "physical_supply_confirmed": True, "verdict": "voltage_mismatch",
            "source_counts": dict(Counter(row["category"] for row in entries)),
            "source_summary_files": len(summary_paths),
            "source_voltage_mv_counts": dict(voltages), "ppk_mode_counts": dict(modes),
            "metadata_voltage_mv_counts": dict(metadata_voltages),
            "expected_raw": len(entries), "raw_present": raw_present,
            "sampled_raw_header": header, "sampled_raw_path": relative(first_raw),
            "formula_checks": dict(formulas), "max_formula_relative_error": max_error,
            "formula_failures": failures, "published_exports": published,
            "source_rows": row_details,
        }
        details.append(record)
        flat.append({"module": label, "slug": slug, "fixture_voltage_mv": 5000,
                     "source_voltage_mv": ";".join(voltages),
                     "packet_tx_runs": record["source_counts"].get("packet_tx", 0),
                     "packet_rx_runs": record["source_counts"].get("packet_rx", 0),
                     "continuous_runs": sum(value for key, value in record["source_counts"].items()
                                            if key.startswith("continuous_")),
                     "raw_present": raw_present, "raw_expected": len(entries),
                     "published_packet_points": published["tx"]["rows"] + published["rx"]["rows"],
                     "published_continuous_rows": published["continuous"]["rows"],
                     "formula_failure_count": len(failures)})
    evidence = {
        "audit_date": "2026-10-03", "scope": "Eight confirmed 5 V supplies compared to the calculation voltage",
        "selection": relative(COVERAGE),
        "physical_voltage_status": "Operator confirmed PPK in series at the radio jumper and actual supplies according to PCB/TENSIUNI_ALIMENTARE.md; recorded in supply_reference.json.",
        "limits": ["No hardware access; no historical measurements overwritten.",
                   "RAW existence and one header per module, not a new full gzip/CRC audit.",
                   "Formula checks use saved calibrated current/charge, not independent current verification.",
                   "Frozen selection includes recovery overrides from the September audit."],
        "summary": {"modules": len(details), "source_runs": sum(item["expected_raw"] for item in details),
                    "raw_present": sum(item["raw_present"] for item in details),
                    "source_metadata_files": sum(item["source_summary_files"] for item in details),
                    "formula_checks": sum(sum(item["formula_checks"].values()) for item in details),
                    "max_formula_relative_error": max(item["max_formula_relative_error"] for item in details),
                    "published_packet_points": sum(item["published_packet_points"] for item in flat),
                    "published_continuous_rows": sum(item["published_continuous_rows"] for item in flat),
                    "formula_failure_count": sum(len(item["formula_failures"]) for item in details)},
        "modules": details, "sha256_inputs": FILES,
    }
    (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (OUT / "modules.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    print(json.dumps(evidence["summary"]))
    print(json.dumps(flat, ensure_ascii=False))


if __name__ == "__main__":
    main()
