import unittest

from radio_power_profiler.planning import build_cases, estimate_airtime_s, parameter_commands
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
                self.assertEqual(len(commands), len(profile.axes))
                self.assertTrue(all(command.startswith("AT+") for command in commands))

    def test_known_lora_airtime(self):
        profile = load_profile("RADIO_RA01_SX1278")
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
        self.assertEqual(profile.transmit.frame_sizes(1024), (64,) * 16)
        airtime = estimate_airtime_s(
            profile,
            1024,
            {"tx_power_dbm": 10, "bit_rate_kbps": 1.2},
        )
        self.assertAlmostEqual(airtime, 7.728, places=6)


if __name__ == "__main__":
    unittest.main()
