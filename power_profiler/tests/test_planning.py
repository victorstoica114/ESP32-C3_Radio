import unittest

from radio_power_profiler.planning import (
    build_cases,
    estimate_airtime_s,
    parameter_commands,
    resolve_rate_bps,
)
from radio_power_profiler.profiles import list_profiles, load_profile, override_profile


class PlanningTests(unittest.TestCase):
    def test_all_profiles_load_and_build(self):
        profiles = list_profiles()
        self.assertGreaterEqual(len(profiles), 20)
        for profile in profiles:
            with self.subTest(profile=profile.profile_id):
                cases = build_cases(profile)
                self.assertTrue(cases)
                self.assertTrue(all(case.capture_after_trigger_s > 0 for case in cases))
                commands = parameter_commands(profile, cases[0].parameters)
                self.assertGreaterEqual(len(commands), len(profile.axes))
                self.assertTrue(all(command.startswith("AT+") for command in commands))

    def test_known_lora_airtime(self):
        profile = load_profile("RADIO_SX1278_NAKED")
        self.assertTrue(profile.reopen_continuous_between_powers)
        self.assertIn("AT+CR=5", profile.setup_commands)
        airtime = estimate_airtime_s(
            profile,
            20,
            {
                "tx_power_dbm": 10,
                "spreading_factor": 7,
                "bandwidth_khz": 125,
            },
        )
        self.assertAlmostEqual(airtime, 0.056576, places=6)

    def test_axis_override_preserves_command_mapping(self):
        profile = load_profile("RADIO_EBYTE_E32_433T33D")
        profile = override_profile(
            profile,
            sizes=(8,),
            repetitions=1,
            axis_overrides={"tx_power_dbm": (33,), "air_rate_code": (6,)},
        )
        cases = build_cases(profile)
        self.assertEqual(len(cases), 1)
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        self.assertEqual(power_axis.command_for(33), "AT+POWER1")

    def test_cc1101_fragmented_transfer_airtime(self):
        profile = load_profile("RADIO_CC1101_V2_868")
        self.assertEqual(profile.transmit.frame_sizes(1024), (32,) * 32)
        airtime = estimate_airtime_s(
            profile,
            1024,
            {"tx_power_dbm": 10, "bit_rate_kbps": 1.2},
        )
        self.assertAlmostEqual(airtime, 11.4026666667, places=6)

    def test_cc1101_rx_plan_includes_rearm_gaps_and_settle_time(self):
        profile = load_profile("RADIO_CC1101_V2_868")
        cases = build_cases(profile, "rx")
        case = next(
            item
            for item in cases
            if item.payload_bytes == 1024
            and item.parameters == {"tx_power_dbm": -30, "bit_rate_kbps": 1.2}
        )

        expected_extra_s = 31 * 0.015 + 0.05
        self.assertAlmostEqual(
            case.estimated_event_s,
            case.estimated_airtime_s + expected_extra_s,
            places=6,
        )
        self.assertGreater(case.capture_after_trigger_s, case.estimated_event_s)

    def test_cc1101_rate_expands_to_coherent_phy_commands(self):
        profile = load_profile("RADIO_CC1101_V2_868")
        commands = parameter_commands(
            profile,
            {"tx_power_dbm": 0, "bit_rate_kbps": 250},
        )

        self.assertEqual(
            commands,
            ["AT+PWR=0", "AT+BR=250", "AT+DEV=127", "AT+BW=541.67"],
        )

        overridden = override_profile(
            profile,
            axis_overrides={"bit_rate_kbps": (250.0,)},
        )
        self.assertIn(
            "AT+BW=541.67",
            parameter_commands(
                overridden,
                {"tx_power_dbm": 0, "bit_rate_kbps": 250.0},
            ),
        )

    def test_e79_profile_supports_fragmented_tx_and_controlled_rx(self):
        profile = load_profile("RADIO_EBYTE_E79_CC1352P")

        self.assertEqual(profile.transmit.frame_sizes(1024), (64,) * 16)
        self.assertTrue(profile.transmit.wait_for_ok)
        self.assertTrue(profile.capture.align_tx_airtime_window)
        self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
        self.assertEqual(len(build_cases(profile, "tx")), 630)
        self.assertEqual(len(build_cases(profile, "rx")), 630)
        self.assertEqual(
            parameter_commands(
                profile,
                {"rf_profile": "GFSK200", "tx_power_dbm": 13},
            ),
            ["AT+PROFILE=GFSK200", "AT+PWR=13"],
        )
        self.assertEqual(
            resolve_rate_bps(profile, {"rf_profile": "SLR2K5"}),
            2500.0,
        )
        self.assertEqual(
            resolve_rate_bps(profile, {"rf_profile": "IEEE154G50"}),
            50000.0,
        )
        slow = override_profile(
            profile,
            sizes=(1024,),
            repetitions=1,
            axis_overrides={
                "rf_profile": ("SLR2K5",),
                "tx_power_dbm": (-20,),
            },
        )
        slow_rx = build_cases(slow, "rx")[0]
        self.assertGreater(
            slow_rx.capture_after_trigger_s,
            slow_rx.estimated_event_s,
        )

    def test_e32_t30_profile_supports_large_transfers_and_three_rates(self):
        profile = load_profile("RADIO_EBYTE_E32_868T30D")

        self.assertEqual(
            profile.transmit.frame_sizes(1024),
            (58,) * 17 + (38,),
        )
        self.assertEqual(profile.receiver_enable_commands, ("AT+BRIDGE=ON",))
        self.assertFalse(profile.restore_after_receive)
        self.assertEqual(
            profile.inter_run_commands,
            ("AT+RESET", "AT+BRIDGE=ON"),
        )
        self.assertTrue(profile.power_cycle_between_runs)
        self.assertEqual(profile.power_cycle_min_airtime_s, 10.0)
        self.assertEqual(profile.power_cycle_off_s, 10.0)
        overridden = override_profile(
            profile,
            sizes=(128,),
            repetitions=1,
            axis_overrides={
                "tx_power_dbm": (21,),
                "bit_rate_kbps": (0.3,),
            },
        )
        self.assertEqual(overridden.inter_run_commands, profile.inter_run_commands)
        self.assertTrue(overridden.power_cycle_between_runs)
        self.assertFalse(overridden.restore_after_receive)
        self.assertEqual(len(build_cases(profile, "tx")), 270)
        self.assertEqual(len(build_cases(profile, "rx")), 270)
        self.assertEqual(
            parameter_commands(
                profile,
                {"tx_power_dbm": 30, "bit_rate_kbps": 4.8},
            ),
            ["AT+POWER1", "AT+AIR4"],
        )

    def test_rx_plan_rejects_profile_without_controlled_receiver(self):
        with self.assertRaisesRegex(ValueError, "does not support controlled RX"):
            build_cases(load_profile("RADIO_HC12"), "rx")


if __name__ == "__main__":
    unittest.main()
