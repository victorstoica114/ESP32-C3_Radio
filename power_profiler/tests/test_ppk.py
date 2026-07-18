import sys
import types
import unittest
from unittest.mock import patch

from radio_power_profiler.ppk import Ppk2Sampler


class _FakeSerial:
    def __init__(self):
        self.is_open = True
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1

    def close(self):
        self.is_open = False


class _FakePpkApi:
    instances = []

    def __init__(self, port, timeout=0):
        self.port = port
        self.timeout = timeout
        self.ser = _FakeSerial()
        self.toggles = []
        self.current_vdd = None
        self.__class__.instances.append(self)

    def use_ampere_meter(self):
        return None

    def stop_measuring(self):
        return None

    def toggle_DUT_power(self, state):
        self.toggles.append(state)


class Ppk2SamplerTests(unittest.TestCase):
    def setUp(self):
        _FakePpkApi.instances.clear()

    def _modules(self):
        package = types.ModuleType("ppk2_api")
        api_module = types.ModuleType("ppk2_api.ppk2_api")
        api_module.PPK2_API = _FakePpkApi
        package.ppk2_api = api_module
        return {
            "ppk2_api": package,
            "ppk2_api.ppk2_api": api_module,
        }

    def _sampler(self):
        with (
            patch.dict(sys.modules, self._modules()),
            patch.object(Ppk2Sampler, "_stop_and_drain"),
            patch.object(Ppk2Sampler, "_read_modifiers_with_retry"),
        ):
            return Ppk2Sampler("COM11", voltage_mv=3300)

    def test_initialization_and_default_close_never_power_the_dut_off(self):
        sampler = self._sampler()
        self.assertEqual(sampler.api.toggles, [])

        sampler.power_on()
        sampler.close()

        self.assertEqual(sampler.api.toggles, ["ON", "ON"])
        self.assertEqual(sampler.api.ser.flush_count, 2)
        self.assertFalse(sampler.api.ser.is_open)

    def test_default_close_reasserts_on_even_without_an_earlier_power_call(self):
        sampler = self._sampler()

        sampler.close()

        self.assertEqual(sampler.api.toggles, ["ON"])

    def test_power_off_requires_an_explicit_close_option(self):
        sampler = self._sampler()

        sampler.power_on()
        sampler.close(keep_power_on=False)

        self.assertEqual(sampler.api.toggles, ["ON", "OFF"])


if __name__ == "__main__":
    unittest.main()
