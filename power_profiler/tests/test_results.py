import csv
import tempfile
import unittest
from pathlib import Path

from radio_power_profiler.results import ResultWriter
from tools.generate_transfer_report import _bit_rate_kbps, _tx_power_dbm, build_report


class ResultTests(unittest.TestCase):
    def test_analysis_error_is_preserved_and_does_not_publish_a_partial_mean(self):
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary) / "session"
            with ResultWriter(result_dir, {}) as writer:
                common = {
                    "profile_id": "RADIO_EBYTE_E79_CC1352P",
                    "measurement_direction": "tx", "payload_bytes": 128,
                    "frame_count": 2, "max_frame_payload_bytes": 64,
                    "parameters_json": '{"rf_profile": "GFSK50", "tx_power_dbm": 13}',
                    "voltage_mv": 3300, "ppk_mode": "ampere",
                    "integration_method": "per_frame_modeled_airtime_v1",
                    "baseline_median_uA": 1000.0,
                }
                writer.add(dict(common, run_id="run_00001", event_detected=True,
                                status="ok", energy_total_uJ=1000.0,
                                integration_windows_ms="[[10, 30], [100, 120]]"))
                writer.add(dict(common, run_id="run_00002", event_detected=False,
                                status="analysis_review_required", energy_total_uJ=None,
                                analysis_error="detected_frame_count_mismatch",
                                integration_windows_ms="[]"))
                writer.write_aggregates()
            with (result_dir / "summary.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[1]["analysis_error"], "detected_frame_count_mismatch")
            self.assertEqual(rows[1]["energy_total_uJ"], "")
            self.assertEqual(rows[0]["integration_windows_ms"], "[[10, 30], [100, 120]]")
            with (result_dir / "aggregates.csv").open(encoding="utf-8", newline="") as stream:
                aggregate = next(csv.DictReader(stream))
            self.assertEqual(aggregate["analysis_valid_runs"], "1")
            self.assertEqual(aggregate["analysis_error_runs"], "1")
            self.assertEqual(aggregate["energy_total_uJ_mean"], "")
            self.assertEqual(aggregate["energy_total_uJ_stdev"], "")
            self.assertEqual(float(aggregate["baseline_median_uA_mean"]), 1000.0)

    def test_transfer_report_derives_nominal_lora_bit_rate(self):
        metadata = {
            "profile": {
                "airtime": {
                    "kind": "lora",
                    "sf_axis": "spreading_factor",
                    "bw_axis": "bandwidth_hz",
                    "bw_multiplier": 1,
                    "coding_rate_denominator": 5,
                }
            }
        }

        self.assertEqual(
            _bit_rate_kbps(
                {
                    "spreading_factor": 7,
                    "bandwidth_hz": 125000,
                    "tx_power_dbm": -9,
                },
                metadata,
            ),
            5.46875,
        )

    def test_transfer_report_normalizes_cc1101_drive_power_axis(self):
        self.assertEqual(_tx_power_dbm({"cc1101_drive_dbm": -30}), -30.0)
        self.assertEqual(_tx_power_dbm({"tx_power_dbm": 10}), 10.0)
        with self.assertRaises(ValueError):
            _tx_power_dbm({"bit_rate_kbps": 38.4})

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
