import unittest

from radio_power_profiler.cli import make_parser


class CliTests(unittest.TestCase):
    def test_rx_run_arguments_identify_measured_and_peer_ports(self):
        args = make_parser().parse_args(
            [
                "run",
                "--module",
                "RADIO_CC1101_V2_868",
                "--direction",
                "rx",
                "--radio-port",
                "COM4",
                "--transmitter-port",
                "COM5",
            ]
        )

        self.assertEqual(args.direction, "rx")
        self.assertEqual(args.radio_port, "COM4")
        self.assertEqual(args.transmitter_port, "COM5")
        self.assertIsNone(args.receiver_port)
        self.assertTrue(args.keep_power_on)

    def test_run_can_explicitly_power_off_after_completion(self):
        args = make_parser().parse_args(
            [
                "run",
                "--module",
                "RADIO_CC1101_V2_868",
                "--direction",
                "tx",
                "--radio-port",
                "COM4",
                "--power-off-after-run",
            ]
        )

        self.assertFalse(args.keep_power_on)

    def test_continuous_defaults_define_one_minute_power_sweep(self):
        args = make_parser().parse_args(
            [
                "continuous",
                "--module",
                "RADIO_CC1101_V2_868",
                "--direction",
                "rx",
                "--radio-port",
                "COM4",
                "--transmitter-port",
                "COM5",
            ]
        )

        self.assertEqual(args.duration_s, 60.0)
        self.assertEqual(args.powers, (-30.0, 0.0, 10.0))
        self.assertEqual(args.bit_rate_kbps, 38.4)
        self.assertEqual(args.frame_bytes, 32)
        self.assertEqual(args.gap_ms, 15)
        self.assertTrue(args.keep_power_on)


if __name__ == "__main__":
    unittest.main()
