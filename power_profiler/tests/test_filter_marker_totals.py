from copy import deepcopy
import math
from pathlib import Path
import random
import struct
import tempfile
from types import SimpleNamespace
import unittest

from ppk2_api.ppk2_api import PPK2_API

from radio_power_profiler.filter_marker_totals import (
    ENERGY_HISTORY_RELATIVE_TOLERANCE, _energy_history_relative_bound,
    _global_bounds, _recurrence, _upper_difference, prove_filter_marker_total,
)


class FilterMarkerTotalsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "wire.bin"
        self.calibration = {name: {str(i): value for i in range(5)} for name, value in
                            {"R": 1.0, "O": 0.0, "GS": 0.0, "GI": 1.0,
                             "S": 0.0, "I": 0.0, "UG": 1.0}.items()}
        self.window = (500, 530)
        self.words = self.make_words([3] * 700, [100] * 700)

    def make_words(self, ranges, codes):
        start, stop = self.window
        return [code | (r << 14) | ((index % 64) << 18) | (int(start <= index < stop) << 24)
                for index, (r, code) in enumerate(zip(ranges, codes))]

    def vendor_capture(self):
        # Bypass __init__: comparison executes only the installed arithmetic decoder,
        # never serial construction, discovery, configuration, reads or writes.
        api = PPK2_API.__new__(PPK2_API)
        api.ser = None
        api.modifiers = deepcopy(self.calibration)
        api.current_vdd = 3300
        api.adc_mult = 1.8 / 163840
        api.rolling_avg = api.rolling_avg4 = api.prev_range = None
        api.consecutive_range_samples = api.after_spike = 0
        api.spike_filter_alpha, api.spike_filter_alpha5, api.spike_filter_samples = .18, .06, 3
        currents = [api.get_adc_result(str((word >> 14) & 7), (word & 0x3FFF) * 4) * 1e6
                    for word in self.words]
        return SimpleNamespace(samples_uA=currents, logic_bits=[word >> 24 for word in self.words])

    def prove(self, capture=None, **kwargs):
        capture = capture or self.vendor_capture()
        self.path.write_bytes(b"".join(struct.pack("<I", word) for word in self.words))
        return prove_filter_marker_total(capture, self.path, kwargs.pop("window", self.window),
                                         kwargs.pop("calibration", self.calibration),
                                         kwargs.pop("voltage_mv", 3300), **kwargs)

    def assert_invalid(self, proof):
        self.assertFalse(proof["valid"], proof)
        self.assertTrue(proof["reasons"])
        self.assertIsNone(proof["charge_total_uC"])
        self.assertIsNone(proof["energy_total_uJ"])

    def test_constant_range_keeps_distinct_proof_and_matches_analytic_total(self):
        proof = self.prove()
        self.assertTrue(proof["valid"], proof)
        self.assertEqual(proof["method"], "bounded_filter_replay_marker_total")
        self.assertEqual(proof["filter_replay_compared_samples"], 700)
        self.assertEqual(proof["filter_replay_max_difference_uA"], 0)
        self.assertEqual(proof["history_interval_max_width_uA"], 0)
        self.assertEqual(proof["combined_error_bound_uA"], 0)
        self.assertEqual(proof["global_adc_domain_values"], 81920)
        self.assertTrue(proof["global_state_invariant"])
        self.assertFalse(any(key.startswith("direct_adc_") for key in proof))
        self.assertEqual(proof["charge_total_uC"], 4394.53125 * 30 / 100000)
        self.assertEqual(proof["energy_total_uJ"], proof["charge_total_uC"] * 3.3)
        for metric in ("charge", "energy"):
            suffix = "uC" if metric == "charge" else "uJ"
            low, high = proof[f"{metric}_interval_{suffix}"]
            self.assertLessEqual(low, proof[f"{metric}_total_{suffix}"])
            self.assertGreaterEqual(high, proof[f"{metric}_total_{suffix}"])

    def test_filter_replay_matches_installed_decoder_on_randomized_ranges_initial4_and_fast_toggles(self):
        rng = random.Random(246802)
        self.calibration = {
            "R": dict(zip(map(str, range(5)), (1004.4, 102.1, 10.29, .97, .056))),
            "O": {str(i): 101.3 - 9 * i for i in range(5)},
            "GS": {str(i): 17.04 * i for i in range(5)},
            "GI": {str(i): .94 + i / 1000 for i in range(5)},
            "S": {str(i): (i - 2) * 3.2e-5 for i in range(5)},
            "I": {str(i): (i - 3) * 2.4e-5 for i in range(5)},
            "UG": {str(i): .99 + i / 100 for i in range(5)},
        }
        sequences = [[4] * 1200, [4, 3, 4, 2, 4, 1, 4, 0] * 150,
                     [4] + [rng.randrange(5) for _ in range(1199)]]
        for ranges in sequences:
            with self.subTest(prefix=ranges[:8]):
                self.words = self.make_words(ranges, [rng.randrange(16384) for _ in ranges])
                proof = self.prove()
                self.assertTrue(proof["valid"], proof)
                self.assertEqual(proof["filter_replay_max_difference_uA"], 0)
                self.assertEqual(proof["filter_replay_compared_samples"], len(ranges))

    def test_range4_freezes_both_states_for_first_two_samples_then_uses_slow_state(self):
        ranges, codes = [3] * 700, [100] * 700
        ranges[500:510], codes[500:] = [4] * 10, [200] * 200
        self.words = self.make_words(ranges, codes)
        capture = self.vendor_capture()
        previous = capture.samples_uA[499]
        self.assertEqual(capture.samples_uA[500:502], [previous, previous])
        expected_third = (.06 * (8789.0625 / 1e6) + .94 * (previous / 1e6)) * 1e6
        self.assertEqual(capture.samples_uA[502], expected_third)
        proof = self.prove(capture)
        self.assertTrue(proof["valid"], proof)
        self.assertFalse(proof["constant_range_guard"])
        self.assertEqual(proof["filter_replay_max_difference_uA"], 0)

    def test_prior_counter_fault_is_bounded_after_clean_history_without_repair(self):
        ranges = [3] * 700
        ranges[510:517] = [2] * 7
        self.words = self.make_words(ranges, [100] * 700)
        self.words[20] ^= 1 << 18
        original = list(self.words)
        proof = self.prove()
        self.assertTrue(proof["valid"], proof)
        self.assertEqual(proof["history_last_suspect_index"], 21)
        self.assertEqual(proof["history_clean_suffix_start"], 22)
        self.assertEqual(proof["outside_counter_anomaly_count"], 2)
        self.assertLessEqual(proof["combined_error_bound_uA"], 1e-6)
        # Constant input can retain distinct adjacent binary64 fixed points.
        # Exact convergence is optional: the certified width, not a zero flag, is the gate.
        self.assertIsNone(proof["history_state_converged_samples"]["fast"])
        self.assertGreater(proof["history_interval_max_width_uA"], 0)
        self.assertEqual(self.words, original)

    def test_prior_fault_with_rapid_range4_freezes_is_bounded_using_slow_and_fast_states(self):
        self.window = (1200, 1230)
        rng = random.Random(52311)
        ranges = [4, 3] * 700
        self.words = self.make_words(ranges, [rng.randrange(16384) for _ in ranges])
        self.words[20] ^= 1 << 18
        proof = self.prove()
        self.assertTrue(proof["valid"], proof)
        self.assertFalse(proof["constant_range_guard"])
        self.assertEqual(proof["filter_replay_max_difference_uA"], 0)
        self.assertLessEqual(proof["combined_error_bound_uA"], 1e-6)

    def test_positive_error_at_tolerance_boundary_rounds_outward_and_is_not_falsely_accepted(self):
        self.words = self.make_words([3] * 700, [0] * 700)
        capture = self.vendor_capture()
        capture.samples_uA[500] = 1e-6
        proof = self.prove(capture)
        self.assert_invalid(proof)
        self.assertGreater(proof["filter_replay_max_difference_uA"], 1e-6)
        self.assertGreater(proof["combined_error_bound_uA"], 1e-6)
        capture.samples_uA[500] = .999e-6
        self.assertTrue(self.prove(capture)["valid"])

    def test_insufficient_history_rejects_filter_state_even_when_nominal_replay_is_exact(self):
        self.window = (15, 35)
        ranges = [3] * 50
        ranges[15:] = [4] * 35
        self.words = self.make_words(ranges, [100] * 50)
        self.words[10] ^= 1 << 18
        proof = self.prove()
        self.assert_invalid(proof)
        self.assertEqual(proof["counter_anomaly_indices_guard"], [])
        self.assertTrue(proof["filter_replay_match"])
        self.assertGreater(proof["history_interval_max_width_uA"], 1e-6)
        self.assertFalse(proof["history_bound_valid"])

    def test_local_counter_fault_rejects_even_if_replay_and_history_numerically_match(self):
        for index in (497, 499, 500, 517, 530, 531):
            with self.subTest(index=index):
                self.words[index] ^= 1 << 18
                proof = self.prove()
                self.assert_invalid(proof)
                self.assertTrue(proof["counter_anomaly_indices_guard"])
                self.words[index] ^= 1 << 18

    def test_bit17_local_rejects_and_prior_bit17_is_disclosed_and_bounded(self):
        self.words[20] |= 1 << 17
        proof = self.prove()
        self.assertTrue(proof["valid"], proof)
        self.assertEqual(proof["history_last_suspect_index"], 20)
        self.assertEqual(proof["outside_bit17_count"], 1)
        self.words[500] |= 1 << 17
        self.assert_invalid(self.prove())

    def test_invalid_range_anywhere_refuses_full_replay_even_outside_guard(self):
        capture = self.vendor_capture()
        for index in (20, 500, 650):
            with self.subTest(index=index):
                saved = self.words[index]
                self.words[index] = (saved & ~(7 << 14)) | (7 << 14)
                proof = self.prove(capture)
                self.assert_invalid(proof)
                self.assertTrue(any("invalid range" in reason for reason in proof["reasons"]))
                self.words[index] = saved

    def test_full_replay_rejects_corruption_and_nonfinite_currents_outside_marker(self):
        for index in (10, 500, 699):
            for invalid in (math.nan, math.inf, .01):
                with self.subTest(index=index, invalid=invalid):
                    capture = self.vendor_capture()
                    capture.samples_uA[index] = invalid if not math.isfinite(invalid) else capture.samples_uA[index] + invalid
                    self.assert_invalid(self.prove(capture))
        capture = self.vendor_capture()
        capture.samples_uA[500] += 1e-7
        proof = self.prove(capture)
        self.assertTrue(proof["valid"], proof)
        self.assertGreater(proof["combined_error_bound_uA"], 0)

    def test_logic_marker_and_wire_length_integrity_are_required(self):
        capture = self.vendor_capture()
        capture.logic_bits[20] ^= 1
        self.assert_invalid(self.prove(capture))
        for window in ((501, 530), (500, 529), (1, 530), (500, 700)):
            with self.subTest(window=window):
                self.assert_invalid(self.prove(window=window))
        capture = self.vendor_capture()
        self.prove(capture)
        self.path.write_bytes(self.path.read_bytes()[:-1])
        self.assert_invalid(prove_filter_marker_total(capture, self.path, self.window, self.calibration, 3300))

    def test_calibration_domain_and_input_arguments_fail_closed(self):
        capture = self.vendor_capture()
        for field, value in (("R", 0), ("GI", math.nan), ("R", 1e-310)):
            wrong = deepcopy(self.calibration)
            wrong[field]["4"] = value
            with self.subTest(field=field):
                self.assert_invalid(self.prove(capture, calibration=wrong))
        for voltage in (0, math.inf, math.nan):
            self.assert_invalid(self.prove(capture, voltage_mv=voltage))
        for rate in (0, True, 100000.5):
            self.assert_invalid(self.prove(capture, sample_rate_hz=rate))

    def test_enumerated_bounds_are_invariant_under_both_binary64_recurrences_and_width_rounds_outward(self):
        coefficients = tuple(tuple(self.calibration[name][str(i)] for i in range(5))
                             for name in ("R", "O", "GS", "GI", "S", "I", "UG"))
        amin, amax, low, high, _ = _global_bounds(coefficients, 3.3)
        self.assertLessEqual(low, amin)
        self.assertGreaterEqual(high, amax)
        for alpha in (.18, .06):
            self.assertGreaterEqual(_recurrence(amin, low, alpha), low)
            self.assertLessEqual(_recurrence(amax, high, alpha), high)
        self.assertEqual(_upper_difference(1, 1), 0)
        self.assertGreater(_upper_difference(1, .1), 1 - .1)

    def test_default_schema1_remains_identical_to_explicit_original_policy(self):
        default = self.prove()
        self.assertEqual(default, self.prove(history_policy="current_equivalence_v1"))
        self.assertEqual(default["schema_version"], 1)
        self.assertNotIn("history_policy", default)
        self.assertFalse(any(key.startswith("energy_history_") for key in default))
        for invalid in ("energy", "", None, True):
            with self.subTest(policy=invalid):
                proof = self.prove(history_policy=invalid)
                self.assert_invalid(proof)
                self.assertTrue(any("Unknown filter history policy" in reason for reason in proof["reasons"]))

    def test_energy_policy_separates_exact_replay_from_small_prior_history_energy_uncertainty(self):
        ranges = [3] * 700
        ranges[500:507] = [2] * 7
        self.words = self.make_words(ranges, [100] * 700)
        self.words[400] ^= 1 << 18
        capture = self.vendor_capture()
        original = list(capture.samples_uA)
        legacy = self.prove(capture)
        self.assert_invalid(legacy)
        proof = self.prove(capture, history_policy="energy_relative_v2")
        self.assertTrue(proof["valid"], proof)
        self.assertEqual(proof["schema_version"], 2)
        self.assertEqual(proof["history_policy"], "energy_relative_v2")
        self.assertEqual(proof["method"], legacy["method"])
        self.assertTrue(proof["filter_replay_match"])
        self.assertEqual(proof["filter_replay_max_difference_uA"], 0)
        self.assertGreater(proof["combined_error_bound_uA"], 1e-6)
        self.assertEqual(proof["combined_error_bound_uA"], legacy["combined_error_bound_uA"])
        self.assertEqual(proof["energy_interval_uJ"], legacy["energy_interval_uJ"])
        self.assertTrue(proof["history_bound_valid"])
        self.assertTrue(proof["energy_history_budget_valid"])
        self.assertEqual(proof["energy_history_relative_tolerance"], 1e-4)
        self.assertLess(proof["energy_history_relative_bound"], 1e-4)
        self.assertGreater(proof["energy_history_relative_bound"], 0)
        self.assertEqual(proof["charge_total_uC"], math.fsum(original[500:530]) / 100000)
        self.assertEqual(capture.samples_uA, original)

    def test_energy_policy_still_rejects_material_history_uncertainty_and_local_counter_fault(self):
        self.window = (15, 35)
        ranges = [3] * 50
        ranges[15:] = [4] * 35
        self.words = self.make_words(ranges, [100] * 50)
        self.words[10] ^= 1 << 18
        proof = self.prove(history_policy="energy_relative_v2")
        self.assert_invalid(proof)
        self.assertTrue(proof["filter_replay_match"])
        self.assertFalse(proof["energy_history_budget_valid"])
        self.assertFalse(proof["history_bound_valid"])
        self.assertGreater(proof["energy_history_relative_bound"], 1e-4)
        self.words[10] ^= 1 << 18
        self.words[17] ^= 1 << 18
        proof = self.prove(history_policy="energy_relative_v2")
        self.assert_invalid(proof)
        self.assertTrue(proof["counter_anomaly_indices_guard"])

    def test_energy_policy_never_weakens_full_replay_or_word_integrity(self):
        for fault in ("replay", "nonfinite", "logic", "bit17", "range"):
            with self.subTest(fault=fault):
                capture = self.vendor_capture()
                saved = self.words[500]
                if fault == "replay":
                    capture.samples_uA[20] += .001
                elif fault == "nonfinite":
                    capture.samples_uA[20] = math.nan
                elif fault == "logic":
                    capture.logic_bits[20] ^= 1
                elif fault == "bit17":
                    self.words[500] |= 1 << 17
                else:
                    self.words[500] = (saved & ~(7 << 14)) | (7 << 14)
                self.assert_invalid(self.prove(capture, history_policy="energy_relative_v2"))
                self.words[500] = saved

    def test_relative_budget_rounding_threshold_and_invalid_denominators(self):
        tolerance = ENERGY_HISTORY_RELATIVE_TOLERANCE
        # Division result equal to the cap is conservatively rounded above it.
        self.assertGreater(_energy_history_relative_bound([1.0, 2.0], 1.5, tolerance), tolerance)
        below = math.nextafter(math.nextafter(tolerance, 0), 0)
        self.assertLess(_energy_history_relative_bound([1.0, 2.0], 1.5, below), tolerance)
        self.assertEqual(_energy_history_relative_bound([1.0, 1.0], 1.0, 0.0), 0.0)
        for interval, nominal, width in (([0, 1], .5, 1), ([-1, 1], .5, 2), ([-2, -1], -1.5, 1),
                                         ([1, 2], 0, 1), ([1, math.inf], 1, 1),
                                         ([1, 2], math.nan, 1), ([1e-320, 1e10], 1, 1e10)):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                _energy_history_relative_bound(interval, nominal, width)
        # Underflow of a positive division must not produce a false zero bound.
        self.assertGreater(_energy_history_relative_bound([1e100, 1e101], 1e100, math.ulp(0.0)), 0)

    def test_energy_policy_rejects_zero_and_negative_energy_even_with_perfect_replay(self):
        self.words = self.make_words([3] * 700, [0] * 700)
        proof = self.prove(history_policy="energy_relative_v2")
        self.assert_invalid(proof)
        self.assertTrue(proof["filter_replay_match"])
        self.assertFalse(proof["energy_history_budget_valid"])
        self.calibration["I"]["3"] = -.001
        proof = self.prove(history_policy="energy_relative_v2")
        self.assert_invalid(proof)
        self.assertTrue(proof["filter_replay_match"])
        self.assertLess(proof["energy_interval_uJ"][1], 0)


if __name__ == "__main__":
    unittest.main()
