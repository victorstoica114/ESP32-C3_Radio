import unittest
from unittest.mock import patch

from radio_power_profiler.frame_windows import locate_frame_windows


class FrameWindowConsensusTests(unittest.TestCase):
    def setUp(self):
        self.samples = [5_000.0] * 4_000
        self.samples[1_200:1_300] = [10_000.0] * 100

    @staticmethod
    def detail(*, valid=True, reasons=(), bin_samples=200):
        return {
            "valid": valid,
            "reasons": list(reasons),
            "bin_samples": bin_samples,
        }

    def locate_with(self, detections):
        def fake_detect(*args, sensitivity, **kwargs):
            return detections[sensitivity]

        with patch(
            "radio_power_profiler.frame_windows.detect_frames",
            side_effect=fake_detect,
        ):
            return locate_frame_windows(
                self.samples,
                trigger_index=1_000,
                sample_rate_hz=100_000,
                baseline_uA=5_000.0,
                frame_lengths=(100,),
            )

    def test_primary_and_lower_sensitivity_consensus_accepts_upper_outlier(self):
        result = self.locate_with({
            4.0: ([(1_200, 1_300)], self.detail()),
            3.0: ([(1_200, 1_300)], self.detail()),
            5.0: ([], self.detail()),
        })

        self.assertTrue(result["valid"])
        self.assertEqual(result["windows"], [(1_200, 1_300)])
        self.assertEqual(
            result["diagnostics"]["sensitivity_consensus"]["supporting_multipliers"],
            [4.0, 3.0],
        )

    def test_primary_and_upper_sensitivity_consensus_accepts_lower_outlier(self):
        result = self.locate_with({
            4.0: ([(1_200, 1_300)], self.detail()),
            3.0: ([(1_200, 1_450)], self.detail(
                valid=False, reasons=("overlong_group_may_merge_frames",)
            )),
            5.0: ([(1_200, 1_300)], self.detail()),
        })

        self.assertTrue(result["valid"])
        self.assertEqual(result["windows"], [(1_200, 1_300)])
        self.assertEqual(
            result["diagnostics"]["sensitivity_consensus"]["supporting_multipliers"],
            [4.0, 5.0],
        )

    def test_invalid_primary_is_rejected_without_full_low_signal_bracket(self):
        result = self.locate_with({
            4.0: ([], self.detail()),
            3.0: ([(1_200, 1_300)], self.detail()),
            5.0: ([], self.detail()),
            2.5: ([(1_200, 1_300)], self.detail()),
            2.0: ([(1_200, 1_300)], self.detail()),
            2.25: ([(1_200, 1_300)], self.detail()),
            2.75: ([], self.detail()),
        })

        self.assertFalse(result["valid"])
        self.assertIn("detected_frame_count_mismatch_at_4_MAD", result["reasons"])
        self.assertIn("insufficient_low_signal_sensitivity_consensus", result["reasons"])

    def test_full_low_signal_bracket_can_replace_invalid_primary(self):
        result = self.locate_with({
            4.0: ([], self.detail()),
            3.0: ([(1_200, 1_300)], self.detail()),
            5.0: ([], self.detail()),
            2.5: ([(1_200, 1_300)], self.detail()),
            2.0: ([(1_200, 1_300)], self.detail()),
            2.25: ([(1_200, 1_300)], self.detail()),
            2.75: ([(1_200, 1_300)], self.detail()),
        })

        self.assertTrue(result["valid"])
        self.assertEqual(result["windows"], [(1_200, 1_300)])
        consensus = result["diagnostics"]["sensitivity_consensus"]
        self.assertEqual(consensus["mode"], "long_frame_low_signal_fallback")
        self.assertEqual(
            consensus["supporting_multipliers"],
            [2.5, 2.0, 2.25, 2.75],
        )

    def test_full_high_signal_bracket_can_replace_overlong_primary(self):
        result = self.locate_with({
            4.0: ([(1_150, 1_300)], self.detail(
                valid=False, reasons=("overlong_group_may_merge_frames",),
                bin_samples=100,
            )),
            3.0: ([], self.detail(bin_samples=100)),
            5.0: ([(1_200, 1_300)], self.detail(bin_samples=100)),
            4.5: ([(1_200, 1_300)], self.detail(bin_samples=100)),
            5.5: ([(1_200, 1_300)], self.detail(bin_samples=100)),
        })

        self.assertTrue(result["valid"])
        self.assertEqual(result["windows"], [(1_200, 1_300)])
        consensus = result["diagnostics"]["sensitivity_consensus"]
        self.assertEqual(consensus["mode"], "high_signal_5_MAD_fallback")
        self.assertEqual(consensus["supporting_multipliers"], [5.0, 4.5, 5.5])

    def test_low_signal_fallback_is_not_used_for_one_ms_bins(self):
        result = self.locate_with({
            4.0: ([], self.detail(bin_samples=100)),
            3.0: ([(1_200, 1_300)], self.detail(bin_samples=100)),
            5.0: ([], self.detail(bin_samples=100)),
        })

        self.assertFalse(result["valid"])
        self.assertIn("insufficient_sensitivity_consensus", result["reasons"])

    def test_primary_without_a_confirming_neighbor_is_rejected(self):
        result = self.locate_with({
            4.0: ([(1_200, 1_300)], self.detail()),
            3.0: ([], self.detail()),
            5.0: ([], self.detail()),
        })

        self.assertFalse(result["valid"])
        self.assertIn("insufficient_sensitivity_consensus", result["reasons"])


if __name__ == "__main__":
    unittest.main()
