"""Independent offline check; stdlib only, no production analysis imports."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
from pathlib import Path


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path, help="Local paired capture root containing pairing.json and TX/RX RAW")
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
args = parser.parse_args()
ROOT, OUT = args.source.resolve(), args.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise SystemExit("Verification output must be separate from the original capture")
OUT.mkdir(parents=True, exist_ok=True)
manifest = json.loads((ROOT / "pairing.json").read_text(encoding="utf-8"))
fs = manifest["sample_rate_hz"]
assert fs == 100000
role_rows = []
for transfer in manifest["rows"]:
    for role in ("tx", "rx"):
        path = ROOT / transfer[f"{role}_raw"]
        values, marks = [], []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            assert reader.fieldnames == ["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"]
            for row in reader:
                index = len(values)
                assert int(row["sample_index"]) == index
                assert abs(float(row["time_ms"]) - index * 1000 / fs) < 1e-8
                current = float(row["current_uA"])
                assert math.isfinite(current)
                values.append(current)
                if row["trigger"] == "1":
                    marks.append(index)
        # Reaching gzip EOF above also validates its trailer and CRC.
        assert len(marks) == 1
        marker = marks[0]
        assert marker == transfer["timing"]["devices"][role]["trigger_index"]
        baseline_start, baseline_end = marker - 18000, marker - 2000
        event_start, event_end = marker, marker + 20000
        assert baseline_start >= 0 and event_end <= len(values)
        baseline = math.fsum(values[baseline_start:baseline_end]) / 16000
        observed = values[event_start:event_end]
        voltage_v = manifest["endpoints"][role]["voltage_mv"] / 1000
        charge = math.fsum(observed) / fs
        signed_delta_charge = math.fsum(value - baseline for value in observed) / fs
        role_rows.append({
            "run_id": transfer["run_id"], "paired_transfer_id": transfer["paired_transfer_id"],
            "role": role, "raw": path.relative_to(ROOT).as_posix(),
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sample_count": len(values), "sample_rate_hz": fs, "trigger_index": marker,
            "baseline_start_index": baseline_start, "baseline_end_index_exclusive": baseline_end,
            "observation_start_index": event_start, "observation_end_index_exclusive": event_end,
            "voltage_v": voltage_v, "baseline_mean_uA": baseline,
            "baseline_power_mW": baseline * voltage_v / 1000,
            "observation_mean_uA": math.fsum(observed) / len(observed),
            "charge_total_uC": charge, "charge_signed_delta_uC": signed_delta_charge,
            "energy_total_uJ": charge * voltage_v,
            "energy_signed_delta_uJ": signed_delta_charge * voltage_v,
            "baseline_equivalent_energy_uJ": baseline * voltage_v * 0.2,
        })

pair_rows = []
for transfer in manifest["rows"]:
    tx, rx = [row for row in role_rows if row["run_id"] == transfer["run_id"]]
    pair_rows.append({
        "run_id": transfer["run_id"],
        "tx_energy_total_uJ": tx["energy_total_uJ"], "rx_energy_total_uJ": rx["energy_total_uJ"],
        "pair_energy_total_uJ": tx["energy_total_uJ"] + rx["energy_total_uJ"],
        "tx_energy_signed_delta_uJ": tx["energy_signed_delta_uJ"],
        "rx_energy_signed_delta_uJ": rx["energy_signed_delta_uJ"],
        "pair_energy_signed_delta_uJ": tx["energy_signed_delta_uJ"] + rx["energy_signed_delta_uJ"],
    })


def stats(values):
    return {"n": len(values), "mean": statistics.fmean(values), "sample_sd": statistics.stdev(values)}


aggregate = {
    role: {key: stats([row[key] for row in role_rows if row["role"] == role]) for key in (
        "baseline_mean_uA", "baseline_power_mW", "energy_total_uJ", "energy_signed_delta_uJ",
    )} for role in ("tx", "rx")
}
aggregate["pair"] = {key: stats([row[key] for row in pair_rows]) for key in (
    "pair_energy_total_uJ", "pair_energy_signed_delta_uJ",
)}
report = {
    "method": "Independent rectangular sample integration; signed delta with no clipping; each role uses own trigger marker",
    "baseline_ms_half_open": [-180, -20], "observation_ms_half_open": [0, 200],
    "sd_definition": "sample standard deviation, n-1", "source_root": str(ROOT),
    "independent_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "roles": role_rows, "pairs": pair_rows, "aggregate": aggregate,
}
(OUT / "independent_200ms.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
for name, rows in (("roles", role_rows), ("pairs", pair_rows)):
    with (OUT / f"independent_200ms_{name}.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
print(json.dumps({"pairs": pair_rows, "aggregate": aggregate}, indent=2))
