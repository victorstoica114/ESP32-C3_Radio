import unittest

from tools.e79_frame_detection import detect_frames


class E79DetectionRefinementTests(unittest.TestCase):
    rate = 100_000
    trigger = 20_000

    def trace(self, intervals):
        samples = [5_000.0] * 50_000
        for start, stop, current in intervals:
            samples[start:stop] = [current] * (stop - start)
        return samples

    def test_isolated_crossings_cannot_extend_a_sustained_burst(self):
        samples = self.trace(
            [(21_500, 21_600, 5_400.0),
             (22_000, 22_600, 6_000.0),
             (23_000, 23_100, 5_400.0)]
        )
        for sensitivity in (3.0, 4.0, 5.0):
            with self.subTest(sensitivity=sensitivity):
                groups, diagnostic = detect_frames(
                    samples, self.trigger, self.rate, 600,
                    sensitivity=sensitivity,
                )
                self.assertEqual(groups, [(22_000, 22_600)])
                self.assertTrue(diagnostic["valid"])

    def test_sparse_crossings_do_not_form_frames_or_pretrigger_bursts(self):
        # Each crossing is one millisecond, separated by three quiet bins.
        # Their combined span must not masquerade as a sustained event.
        samples = self.trace(
            [(start, start + 100, 5_500.0)
             for start in (6_000, 6_400, 6_800, 22_000, 22_400, 22_800, 23_200)]
        )
        groups, diagnostic = detect_frames(samples, self.trigger, self.rate, 600)

        self.assertEqual(groups, [])
        self.assertTrue(diagnostic["valid"])
        self.assertEqual(diagnostic["pretrigger_frame_like_group_count"], 0)

    def test_short_internal_dips_do_not_split_a_low_power_plateau(self):
        samples = self.trace(
            [(21_000, 24_000, 5_600.0),
             (22_000, 22_200, 5_000.0),
             (23_000, 23_300, 5_000.0)]
        )
        groups, diagnostic = detect_frames(samples, self.trigger, self.rate, 3_000)

        self.assertEqual(groups, [(21_000, 24_000)])
        self.assertTrue(diagnostic["valid"])

    def test_additional_sustained_event_is_retained_for_count_validation(self):
        pulses = [(22_000, 22_600), (30_000, 30_300), (40_000, 40_600)]
        groups, diagnostic = detect_frames(
            self.trace([(a, b, 6_000.0) for a, b in pulses]),
            self.trigger, self.rate, 600,
        )

        self.assertEqual(groups, pulses)
        self.assertTrue(diagnostic["valid"])
        self.assertEqual(diagnostic["retained_group_count"], 3)

    def test_sustained_pretrigger_event_still_requires_review(self):
        samples = self.trace(
            [(6_000, 6_600, 6_000.0), (22_000, 22_600, 6_000.0)]
        )
        groups, diagnostic = detect_frames(samples, self.trigger, self.rate, 600)

        self.assertEqual(groups, [(22_000, 22_600)])
        self.assertFalse(diagnostic["valid"])
        self.assertIn("frame_like_pretrigger_noise", diagnostic["reasons"])

    def test_unequal_frame_windows_preserve_short_and_long_bursts(self):
        pulses = [(22_000, 23_300), (32_000, 32_300)]
        samples = self.trace([(a, b, 6_000.0) for a, b in pulses])
        _, uniform_diagnostic = detect_frames(
            samples, self.trigger, self.rate, 300
        )
        groups, diagnostic = detect_frames(
            samples, self.trigger, self.rate, 300,
            maximum_frame_window_samples=1_500,
        )

        self.assertIn("overlong_group_may_merge_frames", uniform_diagnostic["reasons"])
        self.assertEqual(groups, pulses)
        self.assertTrue(diagnostic["valid"])

    def test_long_frames_use_two_millisecond_noise_bins(self):
        samples = self.trace([(22_000, 35_000, 6_000.0)])
        groups, diagnostic = detect_frames(
            samples,
            self.trigger,
            self.rate,
            13_000,
        )

        self.assertEqual(diagnostic["bin_samples"], 200)
        self.assertEqual(groups, [(22_000, 35_000)])
        self.assertTrue(diagnostic["valid"])

    def test_merge_gap_keeps_its_millisecond_meaning_with_two_ms_bins(self):
        samples = self.trace(
            [(22_000, 26_000, 6_000.0), (26_400, 35_000, 6_000.0)]
        )
        groups, diagnostic = detect_frames(
            samples,
            self.trigger,
            self.rate,
            13_000,
            merge_gap_ms=5.0,
        )

        self.assertEqual(diagnostic["bin_samples"], 200)
        self.assertEqual(groups, [(22_000, 35_000)])
        self.assertTrue(diagnostic["valid"])


if __name__ == "__main__":
    unittest.main()
