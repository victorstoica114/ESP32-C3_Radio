import copy
import csv
import gzip
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.recalculate_paired_pilot import budget, calculate, load_trace, segment, stats, wire_counters


class PairedPilotRecalculationTests(unittest.TestCase):
    def test_constant_current_integrates_with_microcoulomb_and_microjoule_units(self):
        result = budget([2000.0] * 200, 1000, 3.3, 1000.0)
        self.assertAlmostEqual(result["duration_ms"], 200.0)
        self.assertAlmostEqual(result["charge_uC"], 400.0)
        self.assertAlmostEqual(result["energy_total_uJ"], 1320.0)
        self.assertAlmostEqual(result["baseline_energy_uJ"], 660.0)
        self.assertAlmostEqual(result["energy_delta_signed_uJ"], 660.0)

    def test_signed_delta_preserves_negative_values_and_cancellation(self):
        negative = budget([500.0] * 200, 1000, 3.3, 1000.0)
        self.assertAlmostEqual(negative["energy_total_uJ"], 330.0)
        self.assertAlmostEqual(negative["energy_delta_signed_uJ"], -330.0)
        cancelling = budget([500.0, 1500.0] * 100, 1000, 3.3, 1000.0)
        self.assertAlmostEqual(cancelling["energy_delta_signed_uJ"], 0.0)
        # Rectifying each residual would produce +165 uJ for this trace.
        self.assertNotEqual(cancelling["energy_delta_signed_uJ"], 165.0)

    def test_windows_are_half_open_at_both_capture_boundaries(self):
        samples = list(range(10))
        self.assertEqual(segment(samples, 4, 1000, (-4, 0)), [0, 1, 2, 3])
        self.assertEqual(segment(samples, 4, 1000, (0, 6)), [4, 5, 6, 7, 8, 9])
        for bounds in ((-5, 0), (0, 7), (0, 0), (2, 1)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                segment(samples, 4, 1000, bounds)

    def test_dispersion_is_sample_sd_not_population_sd(self):
        result = stats([1.0, 3.0, 5.0])
        self.assertEqual(result["mean"], 3.0)
        self.assertEqual(result["sample_sd"], 2.0)

    @staticmethod
    def write_trace(path, rows):
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"])
            writer.writerows(rows)

    def test_raw_loader_checks_indices_time_nonfinite_values_and_marker(self):
        good = [[0, 0, 100.0, 0, 0], [1, 1, 200.0, 1, 1], [2, 2, 300.0, 0, 0]]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw.csv.gz"
            self.write_trace(path, good)
            self.assertEqual(load_trace(path, 1000), ([100.0, 200.0, 300.0], 1, [0, 1]))
            cases = [(1, 0, 4), (1, 1, 1.5), (1, 1, "nan"),
                     (1, 2, "nan"), (1, 2, "inf"), (1, 2, "-inf"),
                     (1, 4, 0), (0, 4, 1), (0, 4, 2)]
            for row_index, column, value in cases:
                changed = copy.deepcopy(good)
                changed[row_index][column] = value
                self.write_trace(path, changed)
                with self.subTest(row=row_index, column=column, value=value), self.assertRaises(ValueError):
                    load_trace(path, 1000)

    def test_raw_loader_checks_gzip_trailer_crc(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw.csv.gz"
            self.write_trace(path, [[0, 0, 100.0, 0, 1]])
            encoded = bytearray(path.read_bytes())
            encoded[-8] ^= 1
            path.write_bytes(encoded)
            with self.assertRaises(gzip.BadGzipFile):
                load_trace(path, 1000)

    def test_wire_counter_wrap_and_isolated_disagreement_are_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wire.bin"
            words = [((index % 64) << 18) | (index % 65536) for index in range(1024)]
            path.write_bytes(b"".join(struct.pack("<I", word) for word in words))
            clean = wire_counters(path)
            self.assertEqual(clean["counter_transition_anomalies"], 0)
            self.assertEqual(clean["dominant_phase_after_sample1000"], 0)
            words[1008] ^= 1 << 18
            encoded = b"".join(struct.pack("<I", word) for word in words)
            path.write_bytes(encoded)
            diagnostic = wire_counters(path)
            self.assertEqual(diagnostic["counter_transition_anomalies"], 2)
            self.assertEqual(diagnostic["counter_first_anomaly_indices"], [1008, 1009])
            self.assertEqual(diagnostic["phase_disagreement_indices_after_sample1000"], [1008])
            self.assertEqual(path.read_bytes(), encoded)


class PairedPilotMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.pairing = {
            "status": "valid", "profile_id": "RADIO_EBYTE_E79_CC1352P", "payload_bytes": 32,
            "rf_profile": "GFSK200", "tx_power_dbm": 13, "sample_rate_hz": 100000,
            "voltage_confirmed": True, "voltage_provenance": "Synthetic confirmed 3.3 V fixture",
            "session_id": "synthetic", "created_utc": "2026-10-01T00:00:00Z",
            "interface_label": "CH340", "ppk_mode": "ampere",
            "endpoints": {role: {"voltage_mv": 3300, "radio_port": f"COM{12 + index}",
                "ppk_port": f"COM{10 + index}", "identity": f"Synthetic {role}", "modem_preflight": {}}
                for index, role in enumerate(("tx", "rx"))},
            "rows": [],
        }
        cls.summaries = {"tx": [], "rx": []}
        samples, marker = 70000, 20000
        wire_bytes = b"".join(struct.pack("<I", (index % 64) << 18) for index in range(samples))
        for index in range(1, 6):
            run_id = f"run_{index:05d}"
            cls.pairing["rows"].append({
                "run_id": run_id, "paired_transfer_id": f"synthetic:{run_id}",
                "status": "valid", "packet_received": True,
                "tx_raw": f"tx/raw/{run_id}.csv.gz", "rx_raw": f"rx/raw/{run_id}.csv.gz",
                "timing": {"host_marker_skew_ms": 0.0, "trigger_callback_finished_host_ns": 1_120_000_000,
                    "devices": {role: {"trigger_index": marker, "wire_bytes": samples * 4,
                        "trailing_bytes": 0, "marker_host_ns": 1_000_000_000} for role in ("tx", "rx")}},
            })
        for role, current in (("tx", 1000.0), ("rx", 2000.0)):
            raw_folder = cls.root / role / "raw"
            raw_folder.mkdir(parents=True)
            text = io.StringIO(newline="")
            writer = csv.writer(text)
            writer.writerow(["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"])
            writer.writerows((index, index / 100, current, 0, int(index == marker)) for index in range(samples))
            encoded = gzip.compress(text.getvalue().encode("utf-8"))
            for pair in cls.pairing["rows"]:
                run_id = pair["run_id"]
                (raw_folder / f"{run_id}.csv.gz").write_bytes(encoded)
                wire_folder = cls.root / "wire" / run_id
                wire_folder.mkdir(parents=True, exist_ok=True)
                (wire_folder / f"{role}.ppk2.bin").write_bytes(wire_bytes)
                cls.summaries[role].append({
                    "run_id": run_id, "status": "ok", "packet_received": "True",
                    "measurement_direction": role, "voltage_mv": "3300", "captured_samples": str(samples),
                    "sample_loss_percent": "0", "integration_windows_ms": "[[0,4.76]]",
                    "energy_total_uJ": str(current * 3.3 * .00476), "energy_excess_uJ": "0",
                    "baseline_median_uA": str(current),
                })

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.write_pairing(self.pairing)
        for role, rows in self.summaries.items():
            self.write_summary(role, rows)

    def write_pairing(self, pairing):
        (self.root / "pairing.json").write_text(json.dumps(pairing), encoding="utf-8")

    def write_summary(self, role, rows):
        with (self.root / role / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_complete_synthetic_fixture_preserves_legacy_and_paired_energy(self):
        result = calculate(self.root)
        self.assertEqual(len(result["trace_checks"]), 10)
        self.assertEqual(len(result["observations"]), 50)
        self.assertEqual(len(result["input_sha256"]), 23)
        self.assertEqual(len(result["paired_budgets"]), 5)
        self.assertEqual(result["quality_status"], "numerically_reproduced")
        self.assertEqual(result["method"]["maximum_host_callback_end_ms"], 120.0)
        for row in result["observations"]:
            self.assertEqual(row["host_callback_within_window"], row["window_end_ms"] > 120)
        for row in result["paired_budgets"]:
            self.assertAlmostEqual(row["energy_total_uJ"], 1980.0)
            self.assertAlmostEqual(row["energy_delta_signed_uJ"], 0.0)
        for row in result["legacy_reproduced"]:
            self.assertAlmostEqual(row["legacy_rectified_excess_uJ"], 0.0)

    def test_wrong_pilot_metadata_is_rejected(self):
        for field, value in (("status", "failed"), ("rf_profile", "SLR2K5"), ("payload_bytes", 64),
                             ("sample_rate_hz", 99999), ("voltage_confirmed", False),
                             ("voltage_confirmed", "false"), ("voltage_provenance", "")):
            changed = copy.deepcopy(self.pairing)
            changed[field] = value
            self.write_pairing(changed)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                calculate(self.root)

    def test_transfer_identity_must_belong_to_its_session_and_run(self):
        changed = copy.deepcopy(self.pairing)
        changed["rows"][0]["paired_transfer_id"] = "other-session:run_99999"
        self.write_pairing(changed)
        with self.assertRaises(ValueError):
            calculate(self.root)

    def test_callback_outside_primary_window_is_rejected(self):
        for end in (1_000_000_000, 1_200_000_000, 1_201_000_000, float("nan")):
            changed = copy.deepcopy(self.pairing)
            changed["rows"][0]["timing"]["trigger_callback_finished_host_ns"] = end
            self.write_pairing(changed)
            with self.subTest(end=end), self.assertRaises(ValueError):
                calculate(self.root)

    def test_raw_software_marker_must_match_manifest_marker(self):
        changed = copy.deepcopy(self.pairing)
        changed["rows"][0]["timing"]["devices"]["tx"]["trigger_index"] += 1
        self.write_pairing(changed)
        with self.assertRaisesRegex(ValueError, "RAW/wire/marker mismatch"):
            calculate(self.root)

    def test_corrupt_summary_loss_voltage_count_and_legacy_energy_are_rejected(self):
        for field, value in (("sample_loss_percent", "NaN"), ("sample_loss_percent", "1.01"),
                             ("voltage_mv", "5000"), ("captured_samples", "69999"),
                             ("energy_total_uJ", "999.0")):
            changed = copy.deepcopy(self.summaries["tx"])
            changed[0][field] = value
            self.write_summary("tx", changed)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                calculate(self.root)


if __name__ == "__main__":
    unittest.main()
