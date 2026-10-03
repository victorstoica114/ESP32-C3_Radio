from copy import deepcopy
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest

from radio_power_profiler.marker_totals import prove_marker_total


class MarkerTotalsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "capture.ppk2.bin"
        self.calibration = {name: {str(i): value for i in range(5)}
                            for name, value in {"R": 1, "O": 0, "GS": 0, "GI": 1,
                                               "S": 0, "I": 0, "UG": 1}.items()}
        self.window = (100, 118)
        self.words = [100 | (3 << 14) | ((index % 64) << 18)
                      | (int(100 <= index < 118) << 24) for index in range(300)]
        self.capture = SimpleNamespace(samples_uA=[4394.53125] * 300,
                                       logic_bits=[word >> 24 for word in self.words])

    def prove(self, **kwargs):
        self.path.write_bytes(b"".join(struct.pack("<I", word) for word in self.words))
        return prove_marker_total(self.capture, self.path, kwargs.pop("window", self.window),
                                  kwargs.pop("calibration", self.calibration),
                                  kwargs.pop("voltage_mv", 3300), **kwargs)

    def assert_invalid(self, result):
        self.assertFalse(result["valid"], result)
        self.assertTrue(result["reasons"], result)
        self.assertIsNone(result["charge_total_uC"])
        self.assertIsNone(result["energy_total_uJ"])

    def test_clean_proof_returns_complete_evidence_and_analytic_energy(self):
        result = self.prove()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["guard_window_samples"], [97, 118])
        self.assertEqual(result["range_code"], 3)
        self.assertTrue(result["constant_range_guard"])
        self.assertTrue(result["wire_logic_match_full_capture"])
        self.assertTrue(result["calibration_valid"])
        self.assertTrue(result["marker_window_complete"])
        self.assertEqual(result["direct_adc_compared_samples"], 18)
        self.assertEqual(result["direct_adc_max_difference_uA"], 0)
        self.assertEqual(result["charge_total_uC"], 4394.53125 * 18 / 100000)
        self.assertEqual(result["energy_total_uJ"], 4394.53125 * 18 / 100000 * 3.3)
        self.assertEqual(result["reasons"], [])
        self.assertNotIn("baseline_uA", result)
        self.assertNotIn("energy_excess_uJ", result)

    def test_prior_counter_fault_remains_warning_without_entering_total(self):
        self.words[10] ^= 1 << 18
        result = self.prove()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["outside_counter_anomaly_count"], 2)
        self.assertTrue(result["warnings"])
        self.assertEqual(result["counter_anomaly_indices_guard"], [])

    def test_counter_fault_in_guard_pulse_or_falling_boundary_fails(self):
        for index in (97, 99, 100, 110, 118):
            with self.subTest(index=index):
                self.words[index] ^= 1 << 18
                result = self.prove()
                self.assert_invalid(result)
                self.assertIn(index, result["counter_anomaly_indices_guard"])
                self.words[index] ^= 1 << 18

    def test_range_change_in_guard_is_rejected_even_if_adc_happens_to_match(self):
        for index in (97, 98, 99, 100, 117):
            with self.subTest(index=index):
                original = self.words[index]
                self.words[index] = (original & ~(7 << 14)) | (2 << 14)
                result = self.prove()
                self.assert_invalid(result)
                self.assertFalse(result["constant_range_guard"])
                self.words[index] = original

    def test_transition_at_guard_start_has_finished_filtering_before_integration(self):
        self.words[96] = (self.words[96] & ~(7 << 14)) | (2 << 14)
        self.words[10] ^= 1 << 18
        self.assertTrue(self.prove()["valid"])

    def test_invalid_range_and_bit17_on_either_boundary_fail(self):
        for index in (97, 110, 118):
            with self.subTest(index=index):
                original = self.words[index]
                self.words[index] = (original & ~(7 << 14)) | (7 << 14)
                result = self.prove()
                self.assert_invalid(result)
                self.assertIn(index, result["invalid_range_indices_guard"])
                self.words[index] = original | (1 << 17)
                result = self.prove()
                self.assert_invalid(result)
                self.assertIn(index, result["bit17_indices_guard"])
                self.words[index] = original

    def test_decoded_current_must_match_adc_with_fixed_tolerance(self):
        self.capture.samples_uA[101] += 1e-7
        result = self.prove()
        self.assertTrue(result["valid"])
        self.assertGreater(result["direct_adc_max_difference_uA"], 0)
        self.assertEqual(result["direct_adc_tolerance_uA"], 1e-6)
        self.capture.samples_uA[101] += .01
        self.assert_invalid(self.prove())

    def test_wrong_missing_nonfinite_or_nonpositive_calibration_fails(self):
        wrong = deepcopy(self.calibration)
        wrong["GI"]["3"] = 1.1
        self.assert_invalid(self.prove(calibration=wrong))
        missing = deepcopy(self.calibration)
        del missing["GS"]["3"]
        self.assert_invalid(self.prove(calibration=missing))
        for name, value in (("GS", math.nan), ("R", 0), ("R", -1)):
            invalid = deepcopy(self.calibration)
            invalid[name]["3"] = value
            self.assert_invalid(self.prove(calibration=invalid))

    def test_logic_must_match_over_full_capture_not_only_marker(self):
        self.capture.logic_bits[20] ^= 1
        result = self.prove()
        self.assert_invalid(result)
        self.assertEqual(result["wire_logic_mismatch_count"], 1)
        self.assertFalse(result["wire_logic_match_full_capture"])

    def test_incomplete_marker_or_wrong_window_fails(self):
        for window in ((101, 118), (100, 117), (99, 118), (100, 119), (1, 118), (100, 300)):
            with self.subTest(window=window):
                self.assert_invalid(self.prove(window=window))

    def test_relevant_nonfinite_data_and_invalid_voltage_or_rate_fail(self):
        self.capture.samples_uA[97] = math.nan
        result = self.prove()
        self.assert_invalid(result)
        self.assertEqual(result["nonfinite_current_indices_guard"], [97])
        self.capture.samples_uA[97] = 4394.53125
        for voltage in (0, -3300, math.inf, math.nan):
            self.assert_invalid(self.prove(voltage_mv=voltage))
        for rate in (0, -1, 100000.5, True):
            self.assert_invalid(self.prove(sample_rate_hz=rate))

    def test_wire_length_mismatch_and_missing_file_fail_without_mutating_capture(self):
        self.prove()
        original_samples = list(self.capture.samples_uA)
        original_logic = list(self.capture.logic_bits)
        self.path.write_bytes(self.path.read_bytes()[:-1])
        result = prove_marker_total(self.capture, self.path, self.window, self.calibration, 3300)
        self.assert_invalid(result)
        self.path.unlink()
        self.assert_invalid(prove_marker_total(self.capture, self.path, self.window, self.calibration, 3300))
        self.assertEqual(self.capture.samples_uA, original_samples)
        self.assertEqual(self.capture.logic_bits, original_logic)


if __name__ == "__main__":
    unittest.main()
