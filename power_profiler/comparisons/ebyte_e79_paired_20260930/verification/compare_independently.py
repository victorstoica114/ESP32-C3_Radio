"""Compare separately computed numbers with the new production calculator."""
import argparse
import hashlib
import json
from pathlib import Path

folder = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("calculator_report", nargs="?", type=Path, default=folder.parent / "calculation.json")
parser.add_argument("--independent-report", type=Path, default=folder / "independent_200ms.json")
parser.add_argument("--output", type=Path, default=folder / "comparison.json")
args = parser.parse_args()
reference_path = args.calculator_report.resolve()
independent_path = args.independent_report.resolve()
reference = json.loads(reference_path.read_text(encoding="utf-8"))
independent = json.loads(independent_path.read_text(encoding="utf-8"))
checks = []


def check(label, actual, expected):
    checks.append({"label": label, "absolute_difference": abs(actual - expected)})
    assert abs(actual - expected) <= 1e-8, (label, actual, expected)


for row in independent["roles"]:
    key = row["role"], row["run_id"]
    observed = next(item for item in reference["observations"]
                    if (item["role"], item["run_id"]) == key and item["window_end_ms"] == 200)
    legacy = next(item for item in reference["legacy_reproduced"] if (item["role"], item["run_id"]) == key)
    for field in ("baseline_mean_uA", "energy_total_uJ"):
        check(f"{key}:{field}", observed[field], row[field])
    check(f"{key}:signed_delta_uJ", observed["energy_delta_signed_uJ"], row["energy_signed_delta_uJ"])
    check(f"{key}:baseline_power_mW", legacy["baseline_power_mW"], row["baseline_power_mW"])
    assert reference["input_sha256"][f"{key[0]}/raw/{key[1]}.csv.gz"] == row["raw_sha256"]
for row in independent["pairs"]:
    expected = next(item for item in reference["paired_budgets"] if item["run_id"] == row["run_id"])
    check(f"{row['run_id']}:pair_total_uJ", expected["energy_total_uJ"], row["pair_energy_total_uJ"])
    check(f"{row['run_id']}:pair_delta_uJ", expected["energy_delta_signed_uJ"], row["pair_energy_signed_delta_uJ"])
for role, metrics in independent["aggregate"].items():
    for field, values in metrics.items():
        if field == "baseline_mean_uA":
            continue
        expected_role = "tx_plus_rx" if role == "pair" else role
        metric = field.removeprefix("pair_").replace("energy_signed_delta", "energy_delta_signed")
        window = 4.76 if field == "baseline_power_mW" else 200
        expected = next(item for item in reference["aggregates"]
                        if item["role"] == expected_role and item["metric"] == metric and item["window_ms"] == window)
        for stat in ("mean", "sample_sd"):
            check(f"{role}:{field}:{stat}", expected[stat], values[stat])
result = {
    "pass": True, "matching_raw_sha256": 10, "numeric_comparisons": len(checks),
    "absolute_tolerance": 1e-8,
    "max_absolute_difference": max(item["absolute_difference"] for item in checks),
    "worst_comparison": max(checks, key=lambda item: item["absolute_difference"]),
    "compared": "Per-role 200ms total/signed delta/baseline; paired totals/deltas; means and sample SDs",
    "independent_report_sha256": hashlib.sha256(independent_path.read_bytes()).hexdigest(),
    "calculator_report_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
    "calculator_script_sha256": reference["calculation_script_sha256"],
}
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
