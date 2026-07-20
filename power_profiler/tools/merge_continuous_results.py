from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMMON_FIELDS = (
    "profile_id",
    "module",
    "measurement_direction",
    "measured_port",
    "peer_port",
    "ppk_port",
    "voltage_mv",
    "bit_rate_kbps",
    "air_rate",
    "rf_profile",
    "frame_bytes",
    "inter_frame_gap_ms",
    "requested_duration_s",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_gzip(path: Path) -> int:
    total = 0
    with gzip.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
    return total


def merge(output: Path, sources: list[Path]) -> dict[str, Any]:
    if len(sources) < 2:
        raise ValueError("At least two continuous result directories are required")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    rows: list[dict[str, str]] = []
    metadata_items: list[dict[str, Any]] = []
    fieldnames: list[str] | None = None
    raw_items: list[tuple[Path, Path, int, str]] = []
    source_records: list[dict[str, Any]] = []
    for source in sources:
        source = source.resolve()
        metadata_path = source / "metadata.json"
        summary_path = source / "summary.csv"
        if not metadata_path.is_file() or not summary_path.is_file():
            raise ValueError(f"Incomplete continuous result: {source}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        with summary_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            source_rows = list(reader)
            current_fields = list(reader.fieldnames or [])
        if len(source_rows) != 1:
            raise ValueError(f"Expected one row in split result: {source}")
        if fieldnames is None:
            fieldnames = current_fields
        elif current_fields != fieldnames:
            raise ValueError(f"CSV schema mismatch: {source}")
        rows.extend(source_rows)
        metadata_items.append(metadata)

        raw_files = sorted((source / "raw").glob("*.csv.gz"))
        if len(raw_files) != 1:
            raise ValueError(f"Expected one raw capture in split result: {source}")
        raw = raw_files[0]
        uncompressed = _verify_gzip(raw)
        digest = _sha256(raw)
        raw_items.append((source, raw, uncompressed, digest))
        source_records.append(
            {
                "source_directory": str(source),
                "summary_sha256": _sha256(summary_path),
                "raw_file": raw.name,
                "raw_sha256": digest,
                "raw_compressed_bytes": raw.stat().st_size,
                "raw_uncompressed_bytes": uncompressed,
            }
        )

    assert fieldnames is not None
    reference = rows[0]
    for row in rows[1:]:
        mismatches = [field for field in COMMON_FIELDS if row.get(field) != reference.get(field)]
        if mismatches:
            raise ValueError(f"Continuous result mismatch in {', '.join(mismatches)}")
    powers = sorted(float(row["tx_power_dbm"]) for row in rows)
    if len(set(powers)) != len(powers):
        raise ValueError(f"Duplicate TX powers: {powers}")
    if any(row.get("status") != "ok" for row in rows):
        raise ValueError("Only status=ok rows can be merged")
    if any(float(row.get("active_window_s", 0)) < 59.99 for row in rows):
        raise ValueError("A continuous result does not contain a complete 60 s window")

    output.mkdir(parents=True)
    raw_output = output / "raw"
    raw_output.mkdir()
    ordered = sorted(zip(rows, raw_items), key=lambda item: float(item[0]["tx_power_dbm"]))
    merged_rows: list[dict[str, str]] = []
    for index, (row, (_source, raw, _uncompressed, _digest)) in enumerate(ordered, start=1):
        merged = dict(row)
        merged["run_id"] = f"continuous_{index:03d}"
        merged_rows.append(merged)
        shutil.copy2(raw, raw_output / f"continuous_{index:03d}.csv.gz")

    with (output / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)

    metadata = deepcopy(metadata_items[0])
    metadata["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata["powers_dbm"] = powers
    metadata["merged_split_results"] = True
    metadata["source_directories"] = [record["source_directory"] for record in source_records]
    (output / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    provenance = {
        "created_utc": metadata["created_utc"],
        "purpose": "Merge independent single-power continuous measurements",
        "powers_dbm": powers,
        "sources": source_records,
    }
    (output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge validated single-power continuous result directories"
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    result = merge(args.output, args.sources)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
