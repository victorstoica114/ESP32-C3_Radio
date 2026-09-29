import unittest
from unittest.mock import patch

from radio_power_profiler.analysis import _frame_sample_lengths, analyze_capture
from radio_power_profiler.models import CaptureSpec


class AnalysisTests(unittest.TestCase):
    def test_ieee154_integer_frame_lengths_do_not_lose_a_sample_to_float_sum(self):
        for frames in (8, 16):
            with self.subTest(frames=frames):
                self.assertEqual(_frame_sample_lengths((0.01548,) * frames, 100_000),
                                 (1548,) * frames)

    def test_fragmented_tx_finds_late_frame_and_excludes_idle_gap(self):
        samples = [1_000.0] * 15_000
        samples[2_200:2_400] = [6_000.0] * 200
        samples[12_000:12_200] = [6_000.0] * 200
        metrics = analyze_capture(
            samples, trigger_index=2_000, sample_rate_hz=10_000,
            voltage_mv=3_300, capture_spec=CaptureSpec(),
            expected_event_count=2, search_window_s=0.1,
            integration_window_s=0.04, align_integration_window=True,
            frame_airtimes_s=(0.02, 0.02),
        )
        self.assertTrue(metrics.event_detected, metrics.analysis_error)
        self.assertEqual(metrics.integration_windows_ms, ((20.0, 40.0), (1000.0, 1020.0)))
        self.assertAlmostEqual(metrics.event_duration_ms, 40.0)
        self.assertAlmostEqual(metrics.energy_total_uJ, 792.0)
        self.assertEqual(metrics.integration_method, "per_frame_modeled_airtime_v1")

    def test_fragmented_tx_rejects_extra_or_missing_frames_without_energy(self):
        for detected in (1, 3):
            with self.subTest(detected=detected):
                samples = [1_000.0] * 10_000
                for start in (2_200, 4_200, 6_200)[:detected]:
                    samples[start:start + 200] = [6_000.0] * 200
                metrics = analyze_capture(
                    samples, trigger_index=2_000, sample_rate_hz=10_000,
                    voltage_mv=3_300, capture_spec=CaptureSpec(),
                    expected_event_count=2, frame_airtimes_s=(0.02, 0.02),
                )
                self.assertFalse(metrics.event_detected)
                self.assertIn("detected_frame_count_mismatch", metrics.analysis_error)
                self.assertIsNone(metrics.energy_total_uJ)
                self.assertIsNone(metrics.energy_excess_uJ)
                self.assertIsNone(metrics.event_duration_ms)
                self.assertEqual(metrics.integration_windows_ms, ())

    def test_fragmented_tx_integrates_a_shorter_final_frame(self):
        samples = [1_000.0] * 10_000
        samples[2_200:2_400] = [6_000.0] * 200
        samples[6_000:6_080] = [9_000.0] * 80
        metrics = analyze_capture(
            samples, trigger_index=2_000, sample_rate_hz=10_000,
            voltage_mv=3_300, capture_spec=CaptureSpec(),
            expected_event_count=2, frame_airtimes_s=(0.02, 0.008),
        )
        self.assertTrue(metrics.event_detected, metrics.analysis_error)
        self.assertEqual(metrics.integration_windows_ms, ((20.0, 40.0), (400.0, 408.0)))
        self.assertAlmostEqual(metrics.event_duration_ms, 28.0)
        self.assertAlmostEqual(metrics.energy_total_uJ, (200 * 6000 + 80 * 9000) / 10000 * 3.3)

    def test_per_frame_quantization_preserves_total_for_unequal_durations(self):
        airtimes = (0.01516, 0.01068)
        lengths = _frame_sample_lengths(airtimes, 10_000)
        self.assertEqual(lengths, (151, 107))
        self.assertEqual(sum(lengths), int(sum(airtimes) * 10_000))
        equal_frames = (0.1296666666667,) * 16
        self.assertEqual(sum(_frame_sample_lengths(equal_frames, 100_000)), int(sum(equal_frames) * 100_000))
        with self.assertRaises(ValueError):
            _frame_sample_lengths((0.000001, 0.01), 1_000)

    def test_fragmented_tx_rejects_clipped_or_overlapping_windows(self):
        for windows in ([(2200, 2400), (9900, 10100)], [(2200, 2400), (2300, 2500)]):
            with self.subTest(windows=windows), patch(
                "radio_power_profiler.analysis.locate_frame_windows",
                return_value={"valid": True, "windows": windows, "reasons": [], "diagnostics": {}},
            ):
                metrics = analyze_capture(
                    [1_000.0] * 10_000, trigger_index=2_000,
                    sample_rate_hz=10_000, voltage_mv=3_300,
                    capture_spec=CaptureSpec(), expected_event_count=2,
                    frame_airtimes_s=(0.02, 0.02),
                )
                self.assertFalse(metrics.event_detected)
                self.assertIn("Invalid or overlapping", metrics.analysis_error)
                self.assertIsNone(metrics.energy_total_uJ)

    def test_short_fragmented_capture_returns_analysis_error(self):
        metrics = analyze_capture(
            [1000.0] * 50, trigger_index=5, sample_rate_hz=100_000,
            voltage_mv=3300, capture_spec=CaptureSpec(), expected_event_count=2,
            frame_airtimes_s=(0.02, 0.02),
        )
        self.assertFalse(metrics.event_detected)
        self.assertTrue(metrics.analysis_error)
        self.assertIsNone(metrics.energy_total_uJ)
        self.assertIsNone(metrics.baseline_median_uA)

    def test_uses_bounded_fallback_window_for_quiet_rx(self):
        samples = [20_000.0] * 2_000
        metrics = analyze_capture(
            samples,
            trigger_index=500,
            sample_rate_hz=1_000,
            voltage_mv=3_300,
            capture_spec=CaptureSpec(threshold_margin_uA=1_000.0),
            fallback_window_s=0.1,
        )

        self.assertTrue(metrics.event_detected)
        self.assertAlmostEqual(metrics.event_start_ms, 0.0)
        self.assertAlmostEqual(metrics.event_duration_ms, 100.0)
        self.assertAlmostEqual(metrics.energy_total_uJ, 6_600.0)

    def test_fixed_rx_window_wins_over_short_noise_spikes(self):
        samples = [20_000.0] * 2_000
        samples[550:560] = [50_000.0] * 10

        metrics = analyze_capture(
            samples,
            trigger_index=500,
            sample_rate_hz=1_000,
            voltage_mv=3_300,
            capture_spec=CaptureSpec(
                threshold_margin_uA=1_000.0,
                minimum_event_ms=1.0,
            ),
            integration_window_s=0.1,
        )

        self.assertTrue(metrics.event_detected)
        self.assertAlmostEqual(metrics.event_start_ms, 0.0)
        self.assertAlmostEqual(metrics.event_duration_ms, 100.0)
        self.assertAlmostEqual(metrics.energy_total_uJ, 7_590.0)

    def test_aligned_fixed_window_integrates_a_low_power_tx_plateau(self):
        samples = [5_000.0] * 2_000
        samples[800:930] = [6_000.0] * 130
        samples[650:660] = [8_000.0] * 10

        metrics = analyze_capture(
            samples,
            trigger_index=500,
            sample_rate_hz=1_000,
            voltage_mv=3_300,
            capture_spec=CaptureSpec(
                threshold_margin_uA=1_500.0,
                minimum_event_ms=1.0,
            ),
            search_window_s=0.6,
            integration_window_s=0.13,
            align_integration_window=True,
        )

        self.assertTrue(metrics.event_detected)
        self.assertAlmostEqual(metrics.event_start_ms, 300.0)
        self.assertAlmostEqual(metrics.event_duration_ms, 130.0)
        self.assertAlmostEqual(metrics.energy_total_uJ, 2_574.0)

    def test_detects_tx_event_and_integrates_energy(self):
        sample_rate = 100_000
        samples = [1000.0] * 60_000
        for index in range(22_000, 23_000):
            samples[index] = 50_000.0

        metrics = analyze_capture(
            samples,
            trigger_index=20_000,
            sample_rate_hz=sample_rate,
            voltage_mv=3300,
            capture_spec=CaptureSpec(threshold_margin_uA=500.0),
        )

        self.assertTrue(metrics.event_detected)
        self.assertAlmostEqual(metrics.baseline_median_uA, 1000.0)
        self.assertAlmostEqual(metrics.event_start_ms, 19.9, places=1)
        self.assertAlmostEqual(metrics.event_duration_ms, 10.2, places=1)
        self.assertGreater(metrics.energy_total_uJ, 1600.0)
        self.assertLess(metrics.energy_total_uJ, 1700.0)

    def test_reports_missing_event(self):
        metrics = analyze_capture(
            [1200.0] * 30_000,
            trigger_index=10_000,
            sample_rate_hz=100_000,
            voltage_mv=3300,
            capture_spec=CaptureSpec(),
        )
        self.assertFalse(metrics.event_detected)
        self.assertIsNone(metrics.energy_total_uJ)

    def test_aggregates_multiple_expected_radio_events(self):
        samples = [1000.0] * 2000
        samples[600:650] = [6000.0] * 50
        samples[800:850] = [6000.0] * 50

        metrics = analyze_capture(
            samples,
            trigger_index=500,
            sample_rate_hz=1000,
            voltage_mv=3300,
            capture_spec=CaptureSpec(
                threshold_margin_uA=500.0,
                minimum_event_ms=1.0,
            ),
            expected_event_count=2,
            search_window_s=0.5,
        )

        self.assertTrue(metrics.event_detected)
        self.assertGreater(metrics.event_duration_ms, 95.0)
        self.assertLess(metrics.event_duration_ms, 110.0)
        self.assertGreater(metrics.energy_total_uJ, 1900.0)


if __name__ == "__main__":
    unittest.main()
