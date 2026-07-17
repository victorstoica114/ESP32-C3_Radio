import csv
import tempfile
import unittest
from pathlib import Path

from radio_power_profiler.results import ResultWriter
from tools.generate_transfer_report import build_report


class ResultTests(unittest.TestCase):
    def test_rx_direction_and_metrics_reach_aggregate_and_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary) / "rx_session"
            metadata = {
                "profile": {
                    "profile_id": "RADIO_CC1101_V2_868",
                    "display_name": "CC1101 V2 868 MHz",
                },
                "measurement_direction": "rx",
            }
            writer = ResultWriter(result_dir, metadata)
            writer.add(
                {
                    "profile_id": "RADIO_CC1101_V2_868",
                    "measurement_direction": "rx",
                    "payload_bytes": 128,
                    "frame_count": 2,
                    "max_frame_payload_bytes": 64,
                    "parameters_json": (
                        '{"bit_rate_kbps": 38.4, "tx_power_dbm": 0}'
                    ),
                    "voltage_mv": 3300,
                    "ppk_mode": "ampere",
                    "event_detected": True,
                    "packet_received": True,
                    "status": "ok",
                    "sample_loss_percent": 0.0,
                    "event_duration_ms": 30.0,
                    "tx_mean_uA": 15000.0,
                    "tx_peak_uA": 17000.0,
                    "rx_mean_uA": 15000.0,
                    "rx_peak_uA": 17000.0,
                    "event_mean_uA": 15000.0,
                    "event_peak_uA": 17000.0,
                    "energy_total_uJ": 1485.0,
                    "energy_excess_uJ": 990.0,
                }
            )
            writer.write_aggregates()
            writer.close()

            with (result_dir / "aggregates.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                aggregate = next(csv.DictReader(stream))
            self.assertEqual(aggregate["measurement_direction"], "rx")
            self.assertEqual(float(aggregate["rx_mean_uA_mean"]), 15000.0)
            self.assertEqual(int(aggregate["packets_attempted"]), 1)
            self.assertEqual(int(aggregate["packets_lost"]), 0)
            self.assertEqual(float(aggregate["packet_loss_percent"]), 0.0)

            report, _summary, _metadata = build_report(result_dir)
            self.assertEqual(report[0]["measurement_direction"], "rx")
            self.assertEqual(report[0]["event_mean_uA_mean"], 15000.0)
            self.assertEqual(report[0]["packet_loss_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
