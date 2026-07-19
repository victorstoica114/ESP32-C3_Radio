from __future__ import annotations

import unittest
from unittest.mock import call, patch

from radio_power_profiler.continuous_runner import (
    _continuous_capture_after_trigger_s,
    _continuous_receiver_tail_s,
    _reopen_continuous_radios,
)
from radio_power_profiler.profiles import load_profile


class _FakeRadio:
    def __init__(self) -> None:
        self.closed = False
        self.configured: list[tuple[str, ...]] = []

    def close(self) -> None:
        self.closed = True

    def configure(self, commands) -> None:
        self.configured.append(tuple(commands))


class ContinuousRunnerTests(unittest.TestCase):
    def test_continuous_receiver_tail_covers_last_frame_airtime(self) -> None:
        profile = load_profile("RADIO_RA01H_SX1276")

        self.assertEqual(
            _continuous_receiver_tail_s(profile, frame_airtime_s=0.01),
            0.15,
        )
        self.assertAlmostEqual(
            _continuous_receiver_tail_s(profile, frame_airtime_s=2.5),
            2.55,
        )
        self.assertAlmostEqual(
            _continuous_capture_after_trigger_s(
                profile,
                measurement_direction="rx",
                duration_s=60.0,
                frame_airtime_s=2.5,
            ),
            63.05,
        )
        self.assertAlmostEqual(
            _continuous_capture_after_trigger_s(
                profile,
                measurement_direction="tx",
                duration_s=60.0,
                frame_airtime_s=2.5,
            ),
            60.75,
        )

    def test_reopens_and_restores_both_lora_radios_between_powers(self) -> None:
        profile = load_profile("RADIO_SX1278_SHIELDED")
        old_radio = _FakeRadio()
        old_peer = _FakeRadio()
        new_radio = _FakeRadio()
        new_peer = _FakeRadio()

        with (
            patch(
                "radio_power_profiler.continuous_runner.SerialRadio",
                side_effect=[new_radio, new_peer],
            ) as constructor,
            patch("radio_power_profiler.continuous_runner.time.sleep") as sleep,
        ):
            reopened_radio, reopened_peer = _reopen_continuous_radios(
                old_radio,
                old_peer,
                profile,
                radio_port="COM22",
                transmitter_port="COM21",
            )

        self.assertTrue(old_radio.closed)
        self.assertTrue(old_peer.closed)
        sleep.assert_called_once_with(1.0)
        self.assertEqual(
            constructor.call_args_list,
            [call("COM22", 9600), call("COM21", 9600)],
        )
        self.assertIs(reopened_radio, new_radio)
        self.assertIs(reopened_peer, new_peer)
        self.assertEqual(
            new_radio.configured,
            [profile.setup_commands, profile.post_config_commands],
        )
        self.assertEqual(
            new_peer.configured,
            [profile.setup_commands, profile.post_config_commands],
        )


if __name__ == "__main__":
    unittest.main()
