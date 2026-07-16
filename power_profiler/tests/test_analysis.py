import unittest

from radio_power_profiler.analysis import analyze_capture
from radio_power_profiler.models import CaptureSpec


class AnalysisTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
