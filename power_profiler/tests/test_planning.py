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

    def test_xl1276_profile_supports_controlled_rx_and_continuous_sweeps(self):
        profile = load_profile("RADIO_XL1276_D01_SX1276")
        self.assertIn("AT+CR=5", profile.setup_commands)
        self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
        self.assertEqual(profile.post_config_commands, ("AT+RX=OFF",))
        self.assertTrue(profile.reopen_continuous_between_powers)
        self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_ra01h_profile_matches_rx_gated_firmware_and_airtime(self):
        profile = load_profile("RADIO_RA01H_SX1276")
        self.assertIn("AT+FREQ=868", profile.setup_commands)
        self.assertIn("AT+CR=5", profile.setup_commands)
        self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
        self.assertEqual(profile.post_config_commands, ("AT+RX=ON",))
        self.assertEqual(profile.transmit.line_overhead_bytes, 2)
        self.assertEqual(profile.airtime["preamble_symbols"], 15)
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        self.assertEqual(power_axis.values, (2, 10, 20))
        self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_ra01sh_profile_matches_sx1262_front_end_and_receiver_control(self):
        profile = load_profile("RADIO_RA01SH_SX1262")
        self.assertIn("AT+FREQ=868", profile.setup_commands)
        self.assertIn("AT+CR=5", profile.setup_commands)
        self.assertIn("AT+LDRO=OFF", profile.setup_commands)
        self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
        self.assertEqual(profile.post_config_commands, ("AT+RX=OFF",))
        self.assertEqual(profile.airtime["preamble_symbols"], 15)
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        self.assertEqual(power_axis.values, (-9, 10, 22))
        self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_ra02_profile_matches_sx1278_firmware_and_airtime(self):
        profile = load_profile("RADIO_RA02_SX1278")
        self.assertIn("AT+FREQ=433", profile.setup_commands)
        self.assertIn("AT+CR=5", profile.setup_commands)
        self.assertIn("AT+PREAMBLE=15", profile.setup_commands)
        self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
        self.assertEqual(profile.post_config_commands, ("AT+RX=OFF",))
        self.assertTrue(profile.reopen_continuous_between_powers)
        self.assertEqual(profile.airtime["preamble_symbols"], 15)
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        self.assertEqual(power_axis.values, (-4, 10, 20))
        self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_ra02_2cap_profile_matches_classic_ra02_test_matrix(self):
        classic = load_profile("RADIO_RA02_SX1278")
        two_cap = load_profile("RADIO_RA02_SX1278_2CAP")
        self.assertEqual(two_cap.firmware_selection, classic.firmware_selection)
        self.assertEqual(two_cap.setup_commands, classic.setup_commands)
        self.assertEqual(two_cap.post_config_commands, classic.post_config_commands)
        self.assertEqual(two_cap.receiver_enable_commands, classic.receiver_enable_commands)
        self.assertEqual(two_cap.payload_sizes, classic.payload_sizes)
        self.assertEqual(two_cap.axes, classic.axes)
        self.assertEqual(two_cap.airtime, classic.airtime)
        self.assertTrue(two_cap.reopen_continuous_between_powers)
        self.assertEqual(len(build_cases(two_cap, "tx")), 135)
        self.assertEqual(len(build_cases(two_cap, "rx")), 135)

    def test_e28_profile_has_deterministic_sx1280_phy_and_controlled_rx(self):
        profile = load_profile("RADIO_E28_SX1280")
        self.assertIn("AT+FREQ=2410.5", profile.setup_commands)
        self.assertIn("AT+CR=6", profile.setup_commands)
        self.assertIn("AT+PREAMBLE=16", profile.setup_commands)
        self.assertIn("AT+CRC=OFF", profile.setup_commands)
        self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
        self.assertEqual(profile.airtime["coding_rate_denominator"], 6)
        self.assertEqual(profile.airtime["preamble_symbols"], 16)
        self.assertFalse(profile.airtime["crc"])
        self.assertEqual(len(build_cases(profile, "tx")), 135)
        self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_e280_profile_uses_a_channel_valid_at_every_air_rate(self):
        profile = load_profile("RADIO_EBYTE_E280_SX1280")
        self.assertIn("AT+CHAN=10", profile.setup_commands)
        self.assertIn("AT+FIXED=OFF", profile.setup_commands)
        self.assertEqual(profile.receiver_enable_commands, ("AT+BRIDGE=ON",))
        self.assertFalse(profile.restore_after_receive)
        self.assertTrue(profile.reopen_continuous_between_powers)
        self.assertEqual(profile.continuous_inter_power_commands, ("AT+RESET",))
        self.assertNotIn("AT+FIXED=OFF", profile.continuous_reopen_setup_commands)
        self.assertIn("AT+BRIDGE=ON", profile.continuous_reopen_setup_commands)
        self.assertEqual(profile.capture.search_window_margin_s, 0.30)
        self.assertEqual(profile.payload_sizes, (8, 32, 64))
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        rate_axis = next(axis for axis in profile.axes if axis.name == "air_rate")
        self.assertEqual(power_axis.values, (4, 7, 12))
        self.assertEqual(rate_axis.values, ("1K", "100K", "2M"))
        self.assertEqual(len(build_cases(profile, "tx")), 135)
        self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_nrf24l01_profile_has_deterministic_phy_and_controlled_rx(self):
        for profile_id in ("RADIO_NRF24L01", "RADIO_NRF24L01_PA"):
            with self.subTest(profile_id=profile_id):
                profile = load_profile(profile_id)
                self.assertIn("AT+CHAN=80", profile.setup_commands)
                self.assertIn("AT+ADDR=0123456789", profile.setup_commands)
                self.assertEqual(profile.receiver_enable_commands, ("AT+RX=ON",))
                self.assertEqual(profile.post_config_commands, ("AT+RX=OFF",))
                self.assertEqual(profile.payload_sizes, (8, 16, 32))
                self.assertEqual(profile.transmit.frame_payload_bytes, 32)
                power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
                rate_axis = next(axis for axis in profile.axes if axis.name == "data_rate_kbps")
                self.assertEqual(power_axis.values, (-18, -6, 0))
                self.assertEqual(rate_axis.values, (250, 1000, 2000))
                self.assertEqual(len(build_cases(profile, "tx")), 135)
                self.assertEqual(len(build_cases(profile, "rx")), 135)

    def test_axis_override_preserves_command_mapping(self):
        profile = load_profile("RADIO_EBYTE_E32_433T33D")
        profile = override_profile(
            profile,
            sizes=(8,),
            repetitions=1,
            axis_overrides={"tx_power_dbm": (30,), "bit_rate_kbps": (19.2,)},
        )
        cases = build_cases(profile)
        self.assertEqual(len(cases), 1)
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        self.assertEqual(power_axis.command_for(30), "AT+POWER2")
        self.assertEqual(
            power_axis.expected_responses_for(30),
            ("TX Power: code 1 (30 dBm)",),
        )

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

    def test_e32_868_t20_profile_is_explicit_and_campaign_ready(self):
        profile = load_profile("RADIO_EBYTE_E32_868T20D")

        self.assertEqual(profile.display_name, "Ebyte E32-868T20D UART")
        self.assertEqual(profile.firmware_selection, "RADIO_EBYTE + AT_COMMANDS")
        self.assertEqual(profile.transmit.frame_sizes(1024), (58,) * 17 + (38,))
        self.assertEqual(profile.receiver_enable_commands, ("AT+BRIDGE=ON",))
        self.assertFalse(profile.restore_after_receive)
        self.assertTrue(profile.power_cycle_between_runs)
        self.assertEqual(profile.parameter_verification_command, "AT+CFG?")
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        rate_axis = next(axis for axis in profile.axes if axis.name == "bit_rate_kbps")
        self.assertEqual(power_axis.values, (10, 14, 20))
        self.assertEqual(rate_axis.values, (0.3, 4.8, 19.2))
        self.assertEqual(len(build_cases(profile, "tx")), 270)
        self.assertEqual(len(build_cases(profile, "rx")), 270)
        self.assertEqual(
            parameter_commands(
                profile,
                {"tx_power_dbm": 20, "bit_rate_kbps": 19.2},
            ),
            ["AT+POWER1", "AT+AIR6"],
        )

    def test_e32_433_t20_profile_is_separate_from_868_variant(self):
        profile_433 = load_profile("RADIO_EBYTE_E32_433T20D")
        profile_868 = load_profile("RADIO_EBYTE_E32_868T20D")

        self.assertEqual(profile_433.display_name, "Ebyte E32-433T20D UART")
        self.assertEqual(profile_868.display_name, "Ebyte E32-868T20D UART")
        self.assertEqual(profile_433.firmware_selection, profile_868.firmware_selection)
        self.assertEqual(profile_433.payload_sizes, profile_868.payload_sizes)
        self.assertEqual(profile_433.axes, profile_868.axes)

    def test_e32_t33_profile_supports_large_transfers_and_three_rates(self):
        profile = load_profile("RADIO_EBYTE_E32_433T33D")

        self.assertEqual(profile.transmit.frame_sizes(1024), (58,) * 17 + (38,))
        self.assertEqual(profile.receiver_enable_commands, ("AT+BRIDGE=ON",))
        self.assertFalse(profile.restore_after_receive)
        self.assertEqual(profile.inter_run_commands, ("AT+RESET", "AT+BRIDGE=ON"))
        self.assertTrue(profile.power_cycle_between_runs)
        power_axis = next(axis for axis in profile.axes if axis.name == "tx_power_dbm")
        rate_axis = next(axis for axis in profile.axes if axis.name == "bit_rate_kbps")
        self.assertEqual(power_axis.values, (24, 27, 30))
        self.assertEqual(rate_axis.values, (0.3, 4.8, 19.2))
        self.assertEqual(len(build_cases(profile, "tx")), 270)
        self.assertEqual(len(build_cases(profile, "rx")), 270)
        self.assertEqual(
            parameter_commands(
                profile,
                {"tx_power_dbm": 30, "bit_rate_kbps": 19.2},
            ),
            ["AT+POWER2", "AT+AIR6"],
        )
        self.assertEqual(profile.parameter_verification_command, "AT+CFG?")

    def test_hc12_profile_maps_real_power_air_rates_and_fu4_uart(self):
        profile = load_profile("RADIO_HC12")
        self.assertEqual(profile.payload_sizes, (8, 32, 60))
        self.assertEqual(profile.receiver_enable_commands, ("AT+BRIDGE=ON",))
        self.assertEqual(profile.receive.post_receive_s, 1.5)
        self.assertLess(profile.setup_commands.index("AT+FU=3"), profile.setup_commands.index("AT+BAUD=9600"))
        self.assertEqual(len(build_cases(profile, "tx")), 135)
        self.assertEqual(len(build_cases(profile, "rx")), 135)
        self.assertEqual(
            parameter_commands(
                profile,
                {"tx_power_dbm": -1, "bit_rate_kbps": 0.5},
            ),
            ["AT+POWER=1", "AT+BAUD=1200", "AT+FU=4"],
        )
        self.assertEqual(
            parameter_commands(
                profile,
                {"tx_power_dbm": 8, "bit_rate_kbps": 15},
            ),
            ["AT+POWER=4", "AT+FU=3", "AT+BAUD=9600"],
        )
        self.assertEqual(
            parameter_commands(
                profile,
                {"tx_power_dbm": 8, "bit_rate_kbps": 0.5},
                previous_parameters={
                    "tx_power_dbm": -1,
                    "bit_rate_kbps": 0.5,
                },
            ),
            ["AT+POWER=4"],
        )
        self.assertAlmostEqual(
            estimate_airtime_s(
                profile,
                60,
                {"tx_power_dbm": 20, "bit_rate_kbps": 0.5},
            ),
            0.98,
        )

    def test_rx_plan_rejects_profile_without_controlled_receiver(self):
        with self.assertRaisesRegex(ValueError, "does not support controlled RX"):
            build_cases(load_profile("RA08_ASR6601"), "rx")


if __name__ == "__main__":
    unittest.main()
