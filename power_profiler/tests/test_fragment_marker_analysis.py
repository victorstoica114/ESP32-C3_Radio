from copy import deepcopy
from dataclasses import replace
import math
from pathlib import Path
import struct
import tempfile
import unittest

from radio_power_profiler.fragment_marker_analysis import (
    analyze_fragmented_radio_marker_pair, FRAGMENT_TOTALS_INTEGRATION_METHOD,
)
from radio_power_profiler.marker_analysis import RADIO_MARKER_SOURCES, TOTAL_ONLY_ENERGY_POLICY
from radio_power_profiler.ppk import Capture


class FragmentMarkerAnalysisTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.calibration = {
            name: {str(i): value for i in range(5)}
            for name, value in {"R": 21.97265625, "O": 0., "GS": 0., "GI": 1.,
                                "S": 0., "I": 0., "UG": 1.}.items()
        }
        self.captures, self.paths, self.words = {}, {}, {}

    def make_role(self, role, windows=((200, 210), (300, 330)), *,
                  currents=None, trigger=100, length=800, gap_current=10000.):
        samples, logic = [gap_current] * length, [0] * length
        if currents is None:
            currents = [2000. + 200. * i for i in range(len(windows))]
        for (start, stop), current in zip(windows, currents):
            samples[start:stop] = [current] * (stop - start)
            logic[start:stop] = [1] * (stop - start)
        self.captures[role] = Capture(samples, logic, trigger, length / 100000, length)
        self.words[role] = [round(value / 2) | (3 << 14) | ((index % 64) << 18) | (bit << 24)
                            for index, (value, bit) in enumerate(zip(samples, logic))]
        self.paths[role] = self.directory / f"{role}.ppk2.bin"

    def analyze(self, **overrides):
        for role, path in self.paths.items():
            path.write_bytes(b"".join(struct.pack("<I", word) for word in self.words[role]))
        kwargs = dict(sample_rate_hz=100000, voltages_mv={"tx": 3300, "rx": 3200},
                      wire_paths=self.paths, calibrations={role: self.calibration for role in self.captures},
                      expected_frame_count=2)
        kwargs.update(overrides)
        return analyze_fragmented_radio_marker_pair(self.captures, **kwargs)

    def assert_pair_invalid(self, metrics, diagnostic):
        self.assertFalse(diagnostic["valid"], diagnostic)
        self.assertTrue(diagnostic["reasons"])
        for metric in metrics.values():
            self.assertFalse(metric.event_detected)
            self.assertTrue(metric.analysis_error)
            self.assertIsNone(metric.energy_total_uJ)
            self.assertIsNone(metric.charge_total_uC)
            self.assertIsNone(metric.energy_excess_uJ)
            self.assertIsNone(metric.baseline_median_uA)
            self.assertEqual(metric.integration_windows_ms, ())
            self.assertEqual(metric.integration_method, FRAGMENT_TOTALS_INTEGRATION_METHOD)

    def test_two_eight_and_sixteen_independent_frames_have_a_real_proof_each(self):
        for count in (2, 8, 16):
            with self.subTest(count=count):
                tx = [(200 + i * 50, 210 + i * 50) for i in range(count)]
                rx = [(250 + i * 52, 256 + i * 52) for i in range(count)]
                self.make_role("tx", tx, length=1200)
                self.make_role("rx", rx, trigger=120, length=1200)
                metrics, diagnostic = self.analyze(expected_frame_count=count)
                self.assertTrue(diagnostic["valid"], diagnostic)
                self.assertEqual(diagnostic["expected_frame_count"], count)
                self.assertEqual(diagnostic["method"], FRAGMENT_TOTALS_INTEGRATION_METHOD)
                self.assertEqual(diagnostic["energy_policy"], TOTAL_ONLY_ENERGY_POLICY)
                self.assertFalse(diagnostic["hardware_synchronized"])
                self.assertIsNone(diagnostic["width_tolerance_samples"])
                for role, windows in (("tx", tx), ("rx", rx)):
                    info, metric = diagnostic["roles"][role], metrics[role]
                    self.assertTrue(info["valid"])
                    self.assertEqual(info["pulse_count"], count)
                    self.assertEqual(info["source"], RADIO_MARKER_SOURCES[role])
                    self.assertEqual(info["windows_samples"], [list(window) for window in windows])
                    self.assertEqual(len(info["frame_proofs"]), count)
                    self.assertTrue(all(p["valid"] and p["direct_adc_match"] for p in info["frame_proofs"]))
                    self.assertTrue(all(p["guard_qa_includes_stop"] for p in info["frame_proofs"]))
                    self.assertEqual(info["duration_samples"], sum(b - a for a, b in windows))
                    self.assertEqual(len(metric.integration_windows_ms), count)
                    self.assertEqual(metric.event_duration_ms, sum(b - a for a, b in windows) / 100)
                    self.assertIs(metric.analysis_diagnostics["marker_diagnostics"], diagnostic)
                    self.assertIsNone(metric.baseline_median_uA)
                    self.assertIsNone(metric.threshold_uA)
                    self.assertIsNone(metric.charge_excess_uC)
                    self.assertIsNone(metric.energy_excess_uJ)

    def test_known_charge_energy_weighted_mean_and_peak_exclude_high_current_gaps(self):
        self.make_role("tx", currents=(2000., 4000.))
        self.make_role("rx", ((240, 245), (440, 455)), currents=(6000., 2000.), trigger=120)
        originals = deepcopy(self.captures)
        metrics, diagnostic = self.analyze()
        self.assertTrue(diagnostic["valid"], diagnostic)
        self.assertAlmostEqual(metrics["tx"].charge_total_uC, 1.4)
        self.assertAlmostEqual(metrics["tx"].energy_total_uJ, 4.62)
        self.assertAlmostEqual(metrics["tx"].event_duration_ms, .4)
        self.assertAlmostEqual(metrics["tx"].tx_mean_uA, 3500.)
        self.assertEqual(metrics["tx"].tx_peak_uA, 4000.)
        self.assertEqual(metrics["tx"].integration_windows_ms, ((1., 1.1), (2., 2.3)))
        self.assertAlmostEqual(metrics["rx"].charge_total_uC, .6)
        self.assertAlmostEqual(metrics["rx"].energy_total_uJ, 1.92)
        self.assertAlmostEqual(metrics["rx"].tx_mean_uA, 3000.)
        self.assertEqual(metrics["rx"].integration_windows_ms, ((1.2, 1.25), (3.2, 3.35)))
        self.assertEqual(self.captures, originals)
        for role, path in self.paths.items():
            self.assertEqual(path.read_bytes(), b"".join(struct.pack("<I", word) for word in self.words[role]))

    def test_missing_extra_glitch_pretrigger_and_incomplete_pulses_fail_both_roles(self):
        bad_windows = (
            (), ((200, 210),), ((200, 210), (300, 310), (400, 410)),
            ((200, 202), (300, 310)), ((80, 90), (300, 310)),
            ((100, 110), (300, 310)), ((0, 10), (300, 310)),
            ((200, 210), (790, 800)),
        )
        for windows in bad_windows:
            with self.subTest(windows=windows):
                self.make_role("tx")
                self.make_role("rx", windows)
                self.assert_pair_invalid(*self.analyze())

    def test_second_frame_fault_is_not_hidden_by_a_valid_first_frame(self):
        for fault, index in (("counter", 297), ("counter", 305), ("counter", 330),
                             ("range", 299), ("bit17", 330), ("current", 305)):
            with self.subTest(fault=fault, index=index):
                self.make_role("tx")
                self.make_role("rx")
                if fault == "counter":
                    self.words["tx"][index] ^= 1 << 18
                elif fault == "range":
                    self.words["tx"][index] = (self.words["tx"][index] & ~(7 << 14)) | (2 << 14)
                elif fault == "bit17":
                    self.words["tx"][index] |= 1 << 17
                else:
                    self.captures["tx"].samples_uA[index] += 1.
                metrics, diagnostic = self.analyze()
                self.assert_pair_invalid(metrics, diagnostic)
                proofs = diagnostic["roles"]["tx"]["frame_proofs"]
                self.assertEqual(len(proofs), 2)
                self.assertTrue(proofs[0]["valid"])
                self.assertFalse(proofs[1]["valid"])
                self.assertTrue(diagnostic["roles"]["rx"]["valid"])
                self.assertTrue(any("frame 2" in reason for reason in diagnostic["reasons"]))

    def test_counter_fault_in_gap_is_reported_without_changing_active_totals(self):
        self.make_role("tx")
        self.make_role("rx")
        clean, _ = self.analyze()
        self.words["tx"][250] ^= 1 << 18
        metrics, diagnostic = self.analyze()
        self.assertTrue(diagnostic["valid"], diagnostic)
        self.assertTrue(diagnostic["warnings"])
        self.assertEqual(metrics["tx"].energy_total_uJ, clean["tx"].energy_total_uJ)
        self.assertTrue(all(p["outside_counter_anomaly_count"] == 2
                            for p in diagnostic["roles"]["tx"]["frame_proofs"]))

    def test_required_evidence_calibration_count_and_rate_fail_closed(self):
        self.make_role("tx")
        self.make_role("rx")
        cases = [dict(wire_paths={"tx": self.paths["tx"]}), dict(calibrations={}),
                 dict(voltages_mv={"tx": 3300, "rx": math.nan})]
        cases += [dict(expected_frame_count=value) for value in (1, 3, 4, 0, True, 2.)]
        cases += [dict(sample_rate_hz=value) for value in (0, -1, True, 100000.)]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                self.assert_pair_invalid(*self.analyze(**kwargs))

    def test_missing_capture_nonfinite_current_and_sample_loss_fail_closed(self):
        self.make_role("tx")
        self.make_role("rx")
        original = self.captures.pop("rx")
        self.assert_pair_invalid(*self.analyze())
        self.captures["rx"] = replace(original, expected_samples=1000)
        self.assert_pair_invalid(*self.analyze())
        self.captures["rx"] = original
        original.samples_uA[250] = math.nan
        self.assert_pair_invalid(*self.analyze())

    def test_other_digital_channels_do_not_create_or_replace_d0_markers(self):
        self.make_role("tx")
        self.make_role("rx")
        for index in range(500, 550):
            self.captures["rx"].logic_bits[index] = 2
            self.words["rx"][index] |= 2 << 24
        self.assertTrue(self.analyze()[1]["valid"])
        for index, value in enumerate(self.captures["rx"].logic_bits):
            self.captures["rx"].logic_bits[index] = value << 1
            self.words["rx"][index] = (self.words["rx"][index] & 0xFFFFFF) | (value << 25)
        self.assert_pair_invalid(*self.analyze())


if __name__ == "__main__":
    unittest.main()
