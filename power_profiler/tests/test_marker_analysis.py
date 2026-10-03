import struct
import tempfile
import unittest
from pathlib import Path

from radio_power_profiler.marker_analysis import (
    analyze_tx_marker_pair, INTEGRATION_METHOD, analyze_radio_marker_pair,
    RADIO_INTEGRATION_METHOD, RADIO_MARKER_SOURCE, RADIO_MARKER_SOURCES,
    RADIO_TOTALS_INTEGRATION_METHOD, TOTAL_ONLY_ENERGY_POLICY,
    FILTER_RADIO_TOTALS_INTEGRATION_METHOD, FILTER_TOTAL_ONLY_ENERGY_POLICY,
)
from radio_power_profiler.ppk import Capture


class MarkerAnalysisTests(unittest.TestCase):
    @staticmethod
    def capture(pulses=((300, 310),), *, trigger=200, length=800, bit=0, current=2000.0):
        samples, logic = [1000.0] * length, [0] * length
        for start, stop in pulses:
            samples[start:stop] = [current] * (stop - start)
            logic[start:stop] = [1 << bit] * (stop - start)
        return Capture(samples, logic, trigger, length / 1000, length)

    def analyze(self, tx=None, rx=None, **kwargs):
        return analyze_tx_marker_pair(
            {"tx": tx if tx is not None else self.capture(), "rx": rx if rx is not None else self.capture()},
            sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3300}, **kwargs,
        )

    def test_valid_common_pulse_uses_local_edges_and_preserves_independent_clocks(self):
        metrics, diagnostic = self.analyze(rx=self.capture(((420, 432),), trigger=205))
        self.assertTrue(diagnostic["valid"], diagnostic)
        self.assertFalse(diagnostic["hardware_synchronized"])
        self.assertEqual(diagnostic["roles"]["tx"]["window_samples"], [300, 310])
        self.assertEqual(diagnostic["roles"]["rx"]["window_samples"], [420, 432])
        self.assertEqual(metrics["tx"].integration_windows_ms, ((100.0, 110.0),))
        self.assertEqual(metrics["rx"].integration_windows_ms, ((215.0, 227.0),))
        self.assertEqual(metrics["tx"].integration_method, INTEGRATION_METHOD)
        self.assertAlmostEqual(metrics["tx"].energy_total_uJ, 66.0)
        self.assertAlmostEqual(metrics["rx"].energy_total_uJ, 79.2)
        self.assertAlmostEqual(metrics["tx"].energy_excess_uJ, 33.0)
        self.assertIn("Legacy rectified excess", metrics["tx"].analysis_diagnostics["excess_energy_definition"])

    def test_total_is_signed_raw_sum_while_legacy_excess_remains_rectified(self):
        metrics, diagnostic = self.analyze(tx=self.capture(current=-1000.0))
        self.assertTrue(diagnostic["valid"])
        self.assertAlmostEqual(metrics["tx"].energy_total_uJ, -33.0)
        self.assertEqual(metrics["tx"].energy_excess_uJ, 0.0)

    def test_missing_multiple_glitch_pretrigger_and_truncated_pulses_fail_entire_pair(self):
        invalid = {
            "absent": self.capture(()),
            "multiple": self.capture(((300, 310), (400, 410))),
            "isolated_glitch": self.capture(((300, 301),)),
            "two_sample_glitch": self.capture(((300, 302),)),
            "glitch_beside_valid_pulse": self.capture(((300, 310), (420, 421))),
            "pretrigger": self.capture(((150, 160),)),
            "at_trigger": self.capture(((200, 210),)),
            "high_at_start": self.capture(((0, 5),)),
            "high_at_end": self.capture(((790, 800),)),
            "wrong_digital_channel": self.capture(bit=1),
            "width_disagreement": self.capture(((300, 313),)),
        }
        for name, capture in invalid.items():
            with self.subTest(name=name):
                metrics, diagnostic = self.analyze(rx=capture)
                self.assertFalse(diagnostic["valid"])
                self.assertTrue(diagnostic["reasons"])
                for role in ("tx", "rx"):
                    self.assertFalse(metrics[role].event_detected)
                    self.assertTrue(metrics[role].analysis_error)
                    self.assertIsNone(metrics[role].energy_total_uJ)
                    self.assertIsNone(metrics[role].energy_excess_uJ)
                    self.assertEqual(metrics[role].integration_windows_ms, ())

    def test_missing_or_corrupt_capture_fails_closed(self):
        good = self.capture()
        corrupt = [
            Capture(good.samples_uA, good.logic_bits[:-1], 200, .8, 800),
            Capture([float("nan")] + good.samples_uA[1:], good.logic_bits, 200, .8, 800),
            Capture(good.samples_uA, good.logic_bits, 200, .8, 1000),
        ]
        for capture in corrupt:
            with self.subTest(capture=capture):
                metrics, diagnostic = self.analyze(tx=capture)
                self.assertFalse(diagnostic["valid"])
                self.assertIsNone(metrics["rx"].energy_total_uJ)
        metrics, diagnostic = analyze_tx_marker_pair(
            {"tx": good}, sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3300},
        )
        self.assertFalse(diagnostic["valid"])
        self.assertIn("Missing decoded capture", metrics["tx"].analysis_error)

    def test_counter_anomalies_in_used_intervals_fail_but_outside_are_disclosed(self):
        capture = self.capture()
        words = [(index % 64) << 18 | capture.logic_bits[index] << 24 for index in range(800)]
        with tempfile.TemporaryDirectory() as temporary:
            paths = {role: Path(temporary) / f"{role}.bin" for role in ("tx", "rx")}
            def write_tx(glitch):
                changed = list(words)
                if glitch is not None:
                    changed[glitch] ^= 1 << 18
                paths["tx"].write_bytes(b"".join(struct.pack("<I", word) for word in changed))
            paths["rx"].write_bytes(b"".join(struct.pack("<I", word) for word in words))
            for glitch in (None, 100, 305, 310, 700):
                with self.subTest(glitch=glitch):
                    write_tx(glitch)
                    encoded = paths["tx"].read_bytes()
                    metrics, diagnostic = self.analyze(wire_paths=paths)
                    self.assertEqual(diagnostic["valid"], glitch in (None, 700))
                    self.assertEqual(paths["tx"].read_bytes(), encoded)
                    if glitch == 700:
                        self.assertTrue(diagnostic["warnings"])
                    elif glitch is not None:
                        self.assertIsNone(metrics["tx"].energy_total_uJ)

    def test_independent_radio_markers_use_unequal_local_intervals_without_clock_alignment(self):
        captures = {"tx": self.capture(((300, 318),)),
                    "rx": self.capture(((480, 494),), trigger=225, current=3000.0)}
        metrics, diagnostic = analyze_radio_marker_pair(
            captures, sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3200},
        )
        self.assertTrue(diagnostic["valid"], diagnostic)
        self.assertIsNone(diagnostic["width_tolerance_samples"])
        self.assertEqual(diagnostic["width_comparison"], "not_applicable_independent_radio_intervals")
        self.assertEqual(diagnostic["source"], RADIO_MARKER_SOURCE)
        self.assertFalse(diagnostic["hardware_synchronized"])
        self.assertEqual(metrics["tx"].integration_windows_ms, ((100.0, 118.0),))
        self.assertEqual(metrics["rx"].integration_windows_ms, ((255.0, 269.0),))
        self.assertAlmostEqual(metrics["tx"].energy_total_uJ, 118.8)
        self.assertAlmostEqual(metrics["rx"].energy_total_uJ, 134.4)
        self.assertAlmostEqual(metrics["rx"].energy_excess_uJ, 89.6)
        for role in ("tx", "rx"):
            self.assertEqual(metrics[role].integration_method, RADIO_INTEGRATION_METHOD)
            self.assertEqual(diagnostic["roles"][role]["source"], RADIO_MARKER_SOURCES[role])
        self.assertIn("sync detected to packet end/abort", diagnostic["measurement_scope"])
        self.assertIn("whole powered", diagnostic["measurement_scope"])
        # Identical inputs remain invalid for the shared-TX-marker contract.
        _, common = analyze_tx_marker_pair(
            captures, sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3200},
        )
        self.assertFalse(common["valid"])
        self.assertIn("TX/RX marker widths disagree", common["reasons"][0])

    def test_independent_rx_marker_is_required_without_modeled_or_tx_window_fallback(self):
        for pulses in ((), ((300, 302),), ((300, 314), (500, 514)), ((790, 800),)):
            with self.subTest(pulses=pulses):
                metrics, diagnostic = analyze_radio_marker_pair(
                    {"tx": self.capture(((300, 318),)), "rx": self.capture(pulses)},
                    sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3300},
                )
                self.assertFalse(diagnostic["valid"])
                for role in ("tx", "rx"):
                    self.assertIsNone(metrics[role].energy_total_uJ)
                    self.assertIsNone(metrics[role].energy_excess_uJ)
                    self.assertEqual(metrics[role].integration_method, RADIO_INTEGRATION_METHOD)

    def test_independent_mode_keeps_counter_gate_for_both_baselines_and_local_boundaries(self):
        captures = {"tx": self.capture(((300, 318),)), "rx": self.capture(((480, 494),))}
        with tempfile.TemporaryDirectory() as temporary:
            paths = {role: Path(temporary) / f"{role}.bin" for role in captures}
            for role in captures:
                for glitch in (None, 100, 300 if role == "tx" else 480,
                               318 if role == "tx" else 494, 700):
                    with self.subTest(role=role, glitch=glitch):
                        for endpoint, capture in captures.items():
                            words = [(i % 64) << 18 | bit << 24 for i, bit in enumerate(capture.logic_bits)]
                            if endpoint == role and glitch is not None:
                                words[glitch] ^= 1 << 18
                            paths[endpoint].write_bytes(b"".join(struct.pack("<I", word) for word in words))
                        originals = {endpoint: path.read_bytes() for endpoint, path in paths.items()}
                        metrics, diagnostic = analyze_radio_marker_pair(
                            captures, sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3300}, wire_paths=paths,
                        )
                        self.assertEqual(diagnostic["valid"], glitch in (None, 700))
                        self.assertEqual({endpoint: path.read_bytes() for endpoint, path in paths.items()}, originals)
                        if glitch not in (None, 700):
                            self.assertEqual(diagnostic["roles"][role]["counter_qa"]["status"], "review_required")
                            self.assertIsNone(metrics["tx"].energy_total_uJ)
                            self.assertIsNone(metrics["rx"].energy_total_uJ)

    def test_total_only_requires_direct_proof_and_retains_legacy_baseline_review(self):
        captures = {"tx": self.capture(((300, 318),)), "rx": self.capture(((480, 494),))}
        calibration = {key: {str(index): value for index in range(5)} for key, value in
                       {"R": 21.97265625, "O": 0., "GS": 0., "GI": 1., "S": 0., "I": 0., "UG": 1.}.items()}
        with tempfile.TemporaryDirectory() as temporary:
            paths = {role: Path(temporary) / f"{role}.bin" for role in captures}
            for role, capture in captures.items():
                words = [(index % 64) << 18 | bit << 24 | 3 << 14 | round(capture.samples_uA[index] / 2)
                         for index, bit in enumerate(capture.logic_bits)]
                if role == "tx":
                    words[100] ^= 1 << 18
                paths[role].write_bytes(b"".join(struct.pack("<I", word) for word in words))
            originals = {role: path.read_bytes() for role, path in paths.items()}
            kwargs = dict(sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3200}, wire_paths=paths)
            strict, strict_diagnostic = analyze_radio_marker_pair(captures, **kwargs)
            self.assertFalse(strict_diagnostic["valid"])
            self.assertIsNone(strict["tx"].energy_total_uJ)
            metrics, diagnostic = analyze_radio_marker_pair(
                captures, marker_totals_only=True, calibrations={role: calibration for role in captures}, **kwargs,
            )
            self.assertTrue(diagnostic["valid"], diagnostic)
            self.assertEqual(diagnostic["energy_policy"], TOTAL_ONLY_ENERGY_POLICY)
            self.assertEqual(diagnostic["roles"]["tx"]["counter_qa"]["status"], "review_required")
            self.assertEqual(diagnostic["roles"]["tx"]["counter_qa"]["relevant_anomaly_count"], 2)
            self.assertTrue(diagnostic["warnings"])
            for role in captures:
                self.assertEqual(metrics[role].integration_method, RADIO_TOTALS_INTEGRATION_METHOD)
                self.assertIsNone(metrics[role].baseline_median_uA)
                self.assertIsNone(metrics[role].threshold_uA)
                self.assertIsNone(metrics[role].charge_excess_uC)
                self.assertIsNone(metrics[role].energy_excess_uJ)
                self.assertTrue(diagnostic["roles"][role]["total_qa"]["valid"])
            self.assertAlmostEqual(metrics["tx"].energy_total_uJ, 118.8)
            self.assertAlmostEqual(metrics["rx"].energy_total_uJ, 89.6)
            self.assertEqual({role: path.read_bytes() for role, path in paths.items()}, originals)
            # The same clean marker trace cannot opt in without measured calibration.
            no_calibration, diagnostic = analyze_radio_marker_pair(captures, marker_totals_only=True, **kwargs)
            self.assertFalse(diagnostic["valid"])
            self.assertTrue(all(value.energy_total_uJ is None for value in no_calibration.values()))

    def test_total_only_without_wire_or_with_missing_local_marker_has_no_fallback(self):
        for rx in (self.capture(), self.capture(())):
            with self.subTest(missing_marker=not any(rx.logic_bits)):
                metrics, diagnostic = analyze_radio_marker_pair(
                    {"tx": self.capture(), "rx": rx}, marker_totals_only=True,
                    sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3300},
                )
                self.assertFalse(diagnostic["valid"])
                self.assertTrue(all(value.energy_total_uJ is None for value in metrics.values()))
                self.assertTrue(all(value.integration_method == RADIO_TOTALS_INTEGRATION_METHOD for value in metrics.values()))

    def test_filter_aware_mode_requires_explicit_total_only_and_still_needs_wire(self):
        options = dict(sample_rate_hz=1000, voltages_mv={"tx": 3300, "rx": 3300})
        captures = {"tx": self.capture(), "rx": self.capture()}
        for value in (True, "false", 1):
            with self.subTest(filter_aware_totals=value), self.assertRaises(ValueError):
                analyze_radio_marker_pair(captures, filter_aware_totals=value, **options)
        metrics, diagnostics = analyze_radio_marker_pair(
            captures, marker_totals_only=True, filter_aware_totals=True, **options,
        )
        self.assertFalse(diagnostics["valid"])
        self.assertEqual(diagnostics["energy_policy"], FILTER_TOTAL_ONLY_ENERGY_POLICY)
        for metric in metrics.values():
            self.assertIsNone(metric.energy_total_uJ)
            self.assertEqual(metric.integration_method, FILTER_RADIO_TOTALS_INTEGRATION_METHOD)
            self.assertIn("analog transition accuracy", metric.analysis_diagnostics["total_energy_definition"])


if __name__ == "__main__":
    unittest.main()
