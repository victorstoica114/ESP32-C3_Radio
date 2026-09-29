import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from tools.e79_frame_detection import detect_frames
from tools.reanalyze_e79_tx import aligned_windows, analyze_job, energies


class E79ReanalysisTests(unittest.TestCase):
    rate = 100_000
    trigger = 20_000
    baseline = 5_000.0
    pulse_current = 10_000.0
    frame_samples = 600

    def trace(self, pulses, *, length=60_000):
        samples = [self.baseline] * length
        for start, stop in pulses:
            samples[start:stop] = [self.pulse_current] * (stop - start)
        return samples

    def test_recovers_late_frame_outside_old_search_and_integrates_both(self):
        pulses = [(22_000, 22_600), (52_000, 52_600)]
        samples = self.trace(pulses)
        # The old search was 1.5 * summed airtime + 150 ms. The second
        # physical frame is deliberately later than that modeled deadline.
        old_search_stop = self.trigger + round((0.012 * 1.5 + 0.150) * self.rate)
        self.assertGreater(pulses[1][0], old_search_stop)

        groups, diagnostic = detect_frames(
            samples, self.trigger, self.rate, self.frame_samples
        )
        self.assertTrue(diagnostic["valid"])
        self.assertEqual(groups, pulses)
        windows = aligned_windows(
            samples, self.baseline, self.trigger, groups, 2 * self.frame_samples
        )

        self.assertEqual(windows, pulses)
        self.assertEqual(sum(stop - start for start, stop in windows), 1_200)
        total, excess = energies(samples, windows, self.baseline, self.rate, 3.3)
        # 12 ms of 10 mA at 3.3 V; the 294 ms command gap is excluded.
        self.assertAlmostEqual(total, 396.0)
        self.assertAlmostEqual(excess, 198.0)

    def test_conserves_odd_total_sample_count_without_overlapping_frames(self):
        pulses = [(22_000, 22_600), (32_000, 32_600)]
        samples = self.trace(pulses)
        windows = aligned_windows(
            samples, self.baseline, self.trigger, pulses, 1_201
        )

        self.assertEqual(sum(stop - start for start, stop in windows), 1_201)
        self.assertLessEqual(windows[0][1], windows[1][0])
        for (start, stop), (pulse_start, pulse_stop) in zip(windows, pulses):
            self.assertLessEqual(start, pulse_start)
            self.assertGreaterEqual(stop, pulse_stop)
        total, excess = energies(samples, windows, self.baseline, self.rate, 3.3)
        # One rounding sample adds baseline energy, not another active sample.
        self.assertAlmostEqual(total, 396.165)
        self.assertAlmostEqual(excess, 198.0)

    def test_flat_baseline_does_not_create_frames_or_integration_windows(self):
        samples = self.trace([])
        groups, diagnostic = detect_frames(
            samples, self.trigger, self.rate, self.frame_samples
        )

        self.assertEqual(groups, [])
        self.assertEqual(diagnostic["retained_group_count"], 0)
        with self.assertRaisesRegex(ValueError, "No independently detected frames"):
            aligned_windows(samples, self.baseline, self.trigger, groups, 1_200)

    def test_reports_every_independent_frame_instead_of_limiting_count(self):
        pulses = [(22_000, 22_600), (32_000, 32_600), (52_000, 52_600)]
        groups, diagnostic = detect_frames(
            self.trace(pulses), self.trigger, self.rate, self.frame_samples
        )

        self.assertTrue(diagnostic["valid"])
        self.assertEqual(groups, pulses)
        self.assertEqual(diagnostic["retained_group_count"], 3)

    def test_rejects_window_that_cannot_fit_between_neighboring_frames(self):
        pulses = [(21_000, 21_600), (22_000, 22_600)]
        samples = self.trace(pulses, length=30_000)

        with self.assertRaisesRegex(ValueError, "cannot fit"):
            aligned_windows(samples, self.baseline, self.trigger, pulses, 6_000)

    def test_flags_frame_that_reaches_capture_end(self):
        groups, diagnostic = detect_frames(
            self.trace([(59_400, 60_000)]),
            self.trigger,
            self.rate,
            self.frame_samples,
        )

        self.assertEqual(len(groups), 1)
        self.assertFalse(diagnostic["valid"])
        self.assertIn("activity_near_capture_end", diagnostic["reasons"])

    def test_missing_expected_frame_remains_review_required(self):
        # A valid trace containing one pulse must not receive a second window
        # simply because its source metadata expected two physical frames.
        rate, trigger = 1_000, 200
        samples = self.trace([(220, 226)], length=800)
        row = {
            "run_id": "run_00001",
            "captured_samples": str(len(samples)),
            "voltage_mv": "3300",
            "event_start_ms": "20",
            "event_duration_ms": "12",
            "energy_total_uJ": "297",
            "energy_excess_uJ": "99",
            "frame_count": "2",
            "parameters_json": '{"rf_profile": "GFSK200", "tx_power_dbm": 13}',
            "payload_bytes": "128",
            "repetition": "1",
            "sample_loss_percent": "0",
            "status": "ok",
            "packet_received": "True",
        }
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "run_00001.csv.gz"
            with gzip.open(raw, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ["sample_index", "time_ms", "current_uA", "logic_bits", "trigger"]
                )
                writer.writerows(
                    (index, index * 1000 / rate, current, 0, int(index == trigger))
                    for index, current in enumerate(samples)
                )
            result = analyze_job(
                (str(raw), row, "synthetic_two_frame_step", rate, "raw/run_00001.csv.gz")
            )

        self.assertEqual(result["expected_frames"], 2)
        self.assertEqual(result["detected_frames"], 1)
        self.assertEqual(result["quality"], "review_required")
        self.assertTrue(any(reason.startswith("detected_frame_count_mismatch")
                            for reason in result["reasons"]))
        self.assertNotIn("recalculated_energy_total_uJ", result)


if __name__ == "__main__":
    unittest.main()
