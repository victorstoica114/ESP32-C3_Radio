import unittest

from radio_power_profiler.analysis import analyze_capture
from radio_power_profiler.models import CaptureSpec


class AnalysisTests(unittest.TestCase):
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
