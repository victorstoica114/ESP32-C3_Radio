from __future__ import annotations

import csv
import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .ppk import Capture, SAMPLE_RATE_HZ


FIELDS = [
    "run_id",
    "timestamp_utc",
    "profile_id",
    "module",
    "firmware_selection",
    "repetition",
    "payload_bytes",
    "frame_count",
    "max_frame_payload_bytes",
    "serial_content_bytes",
    "parameters_json",
    "ppk_mode",
    "voltage_mv",
    "estimated_airtime_ms",
    "captured_samples",
    "sample_loss_percent",
    "event_detected",
    "baseline_median_uA",
    "threshold_uA",
    "event_start_ms",
    "event_duration_ms",
    "tx_mean_uA",
    "tx_peak_uA",
    "charge_total_uC",
    "charge_excess_uC",
    "energy_total_uJ",
    "energy_excess_uJ",
    "radio_response",
    "receiver_port",
    "receiver_response",
    "packet_received",
    "status",
]


class ResultWriter:
    def __init__(self, output_dir: Path, metadata: dict[str, Any]):
        self.output_dir = output_dir
        self.raw_dir = output_dir / "raw"
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        self.summary_path = output_dir / "summary.csv"
        self._stream = self.summary_path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._stream, fieldnames=FIELDS)
        self._writer.writeheader()
        self._stream.flush()
        self.rows: list[dict[str, Any]] = []

    def add(self, row: dict[str, Any]) -> None:
        normalized = {field: row.get(field, "") for field in FIELDS}
        self._writer.writerow(normalized)
        self._stream.flush()
        self.rows.append(normalized)

    def save_raw(self, run_id: str, capture: Capture) -> Path:
        self.raw_dir.mkdir(exist_ok=True)
        path = self.raw_dir / f"{run_id}.csv.gz"
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"])
            for index, current in enumerate(capture.samples_uA):
                logic = capture.logic_bits[index] if index < len(capture.logic_bits) else ""
                writer.writerow(
                    [
                        index,
                        index * 1000.0 / SAMPLE_RATE_HZ,
                        current,
                        logic,
                        1 if index == capture.trigger_index else 0,
                    ]
                )
        return path

    def write_aggregates(self) -> Path:
        path = self.output_dir / "aggregates.csv"
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in self.rows:
            key = (
                row["profile_id"],
                row["payload_bytes"],
                row["frame_count"],
                row["max_frame_payload_bytes"],
                row["parameters_json"],
                row["voltage_mv"],
                row["ppk_mode"],
            )
            grouped[key].append(row)

        metric_names = [
            "baseline_median_uA",
            "event_duration_ms",
            "tx_mean_uA",
            "tx_peak_uA",
            "charge_total_uC",
            "charge_excess_uC",
            "energy_total_uJ",
            "energy_excess_uJ",
        ]
        fields = [
            "profile_id",
            "payload_bytes",
            "frame_count",
            "max_frame_payload_bytes",
            "parameters_json",
            "voltage_mv",
            "ppk_mode",
            "runs",
            "events_detected",
            "packets_received",
        ]
        for metric in metric_names:
            fields.extend([f"{metric}_mean", f"{metric}_stdev"])

        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for key, rows in grouped.items():
                aggregate: dict[str, Any] = {
                    "profile_id": key[0],
                    "payload_bytes": key[1],
                    "frame_count": key[2],
                    "max_frame_payload_bytes": key[3],
                    "parameters_json": key[4],
                    "voltage_mv": key[5],
                    "ppk_mode": key[6],
                    "runs": len(rows),
                    "events_detected": sum(
                        str(row["event_detected"]).lower() == "true" for row in rows
                    ),
                    "packets_received": sum(
                        str(row["packet_received"]).lower() == "true" for row in rows
                    ),
                }
                for metric in metric_names:
                    values = [
                        float(row[metric])
                        for row in rows
                        if row[metric] not in (None, "")
                    ]
                    aggregate[f"{metric}_mean"] = statistics.fmean(values) if values else ""
                    aggregate[f"{metric}_stdev"] = (
                        statistics.stdev(values) if len(values) > 1 else 0.0 if values else ""
                    )
                writer.writerow(aggregate)
        return path

    def close(self) -> None:
        if not self._stream.closed:
            self._stream.close()

    def __enter__(self) -> "ResultWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
