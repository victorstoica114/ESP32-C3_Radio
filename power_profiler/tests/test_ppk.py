import contextlib
import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

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

    def test_close_releases_stale_handle_even_when_final_power_flush_fails(self):
        sampler = self._sampler()
        error = PermissionError(13, "ClearCommError failed after USB disconnect")
        with patch.object(sampler.api.ser, "flush", side_effect=error):
            with self.assertRaises(PermissionError) as caught:
                sampler.close(keep_power_on=True)
        self.assertIs(caught.exception, error)
        self.assertFalse(sampler.api.ser.is_open)
        self.assertEqual(sampler.api.toggles, ["ON"])
        self.assertFalse(sampler._continuous_hold)
        self.assertIn("power state could not be reasserted", " ".join(error.__notes__))

    def test_close_already_closed_handle_is_idempotent_and_sends_no_power_command(self):
        sampler = self._sampler()
        sampler.api.ser.is_open = False
        with patch.object(sampler.api, "stop_measuring") as stop:
            sampler.close()
            sampler.close(keep_power_on=False)
        stop.assert_not_called()
        self.assertEqual(sampler.api.toggles, [])
        self.assertEqual(sampler.api.ser.flush_count, 0)

    def test_power_failure_is_preserved_if_serial_cleanup_also_fails(self):
        sampler = self._sampler()
        error = PermissionError(13, "stale power write")
        with (patch.object(sampler.api, "toggle_DUT_power", side_effect=error),
              patch.object(sampler.api.ser, "close", side_effect=OSError("close failed")) as close):
            with self.assertRaises(PermissionError) as caught:
                sampler.close()
        self.assertIs(caught.exception, error)
        close.assert_called_once()
        self.assertTrue(sampler.api.ser.is_open)
        self.assertIn("serial close also failed", " ".join(error.__notes__))


class Ppk2DiscoveryTests(unittest.TestCase):
    @staticmethod
    def _port(device, serial_number=None, *, vid=0x1915, pid=0xC00A,
              interface=None, hwid=None, location=None):
        return types.SimpleNamespace(
            device=device, serial_number=serial_number, vid=vid, pid=pid,
            description="USB Serial Device", interface=interface, hwid=hwid, location=location,
        )

    @contextlib.contextmanager
    def _discovery(self, legacy_devices, ports):
        api = Mock(name="PPK2_API")
        api.list_devices.return_value = legacy_devices
        package = types.ModuleType("ppk2_api")
        api_module = types.ModuleType("ppk2_api.ppk2_api")
        api_module.PPK2_API = api
        package.ppk2_api = api_module
        serial_module = types.ModuleType("serial")
        serial_module.Serial = Mock(side_effect=AssertionError("Discovery opened a COM port"))
        tools_module = types.ModuleType("serial.tools")
        ports_module = types.ModuleType("serial.tools.list_ports")
        ports_module.comports = Mock(return_value=ports)
        serial_module.tools = tools_module
        tools_module.list_ports = ports_module
        with patch.dict(sys.modules, {
            "ppk2_api": package, "ppk2_api.ppk2_api": api_module,
            "serial": serial_module, "serial.tools": tools_module,
            "serial.tools.list_ports": ports_module,
        }):
            yield
        api.assert_not_called()
        serial_module.Serial.assert_not_called()

    def test_generic_windows_cdc_description_finds_both_ppk2_serials(self):
        with self._discovery([], [self._port("COM10", "E753C4E81F3D"), self._port("COM11", "CD2D332DB09A")]):
            self.assertEqual(Ppk2Sampler.list_devices(), [
                ("COM10", "E753C4E81F3D"), ("COM11", "CD2D332DB09A"),
            ])

    def test_legacy_strings_and_tuples_merge_without_losing_serials_or_duplicates(self):
        legacy = ["com10", ("COM10", None), ("COM11", "legacy-serial"), ("COM11", "")]
        ports = [self._port("COM10", "usb-serial"), self._port("COM11"), self._port("COM12", "new-serial")]
        with self._discovery(legacy, ports):
            self.assertEqual(Ppk2Sampler.list_devices(), [
                ("COM10", "usb-serial"), ("COM11", "legacy-serial"), ("COM12", "new-serial"),
            ])

    def test_fallback_excludes_other_nordic_products_and_non_usb_ports(self):
        ports = [self._port("COM1", vid=None, pid=None),
                 self._port("COM3", "nordic-other", pid=0x521F),
                 self._port("COM4", "other-vendor", vid=0x1366)]
        with self._discovery([], ports):
            self.assertEqual(Ppk2Sampler.list_devices(), [])

    def test_missing_serial_remains_empty_and_unix_paths_keep_case(self):
        with self._discovery([("/dev/ttyACM0", None), "/dev/ttyACM1"], [self._port("/dev/ttyACM0")]):
            self.assertEqual(Ppk2Sampler.list_devices(), [("/dev/ttyACM0", ""), ("/dev/ttyACM1", "")])

    def test_new_firmware_hwid_excludes_shell_even_when_legacy_api_returns_it(self):
        ports = [
            self._port("COM10", "TX", hwid=r"USB\VID_1915&PID_C00A&MI_01\TX"),
            self._port("COM22", "TX", hwid=r"USB\VID_1915&PID_C00A&MI_03\TX"),
            self._port("COM11", "RX", hwid=r"USB\VID_1915&PID_C00A&MI_01\RX"),
            self._port("COM24", "RX", hwid=r"USB\VID_1915&PID_C00A&MI_03\RX"),
        ]
        legacy = ["com22", ("COM24", "RX"), "COM10", ("COM11", "RX")]
        with self._discovery(legacy, ports):
            self.assertEqual(Ppk2Sampler.list_devices(), [("COM10", "TX"), ("COM11", "RX")])

    def test_windows_and_unix_location_select_interface_not_com_number(self):
        ports = [self._port("COM1", "TX", location="1-3:x.3"),
                 self._port("COM90", "TX", location="1-3:x.1"),
                 self._port("/dev/ttyACM0", "RX", location="1-4:1.3"),
                 self._port("/dev/ttyACM1", "RX", location="1-4:1.1")]
        with self._discovery(["COM1", ("/dev/ttyACM0", "RX")], ports):
            self.assertEqual(Ppk2Sampler.list_devices(), [("COM90", "TX"), ("/dev/ttyACM1", "RX")])

    def test_explicit_shell_interface_is_excluded_from_api_and_fallback(self):
        for interface in (3, "03", "0x03", "MI_03", "PPK2 Shell"):
            with self.subTest(interface=interface):
                ports = [self._port("COM22", "TX", interface=interface),
                         self._port("COM10", "TX", interface="MI_01")]
                with self._discovery([("com22", "TX")], ports):
                    self.assertEqual(Ppk2Sampler.list_devices(), [("COM10", "TX")])

    def test_hwid_location_filters_shell_when_location_attribute_is_missing(self):
        ports = [self._port("COM22", "TX", hwid="USB VID:PID=1915:C00A SER=TX LOCATION=1-3:x.3"),
                 self._port("COM10", "TX", hwid="USB VID:PID=1915:C00A SER=TX LOCATION=1-3:x.1")]
        with self._discovery(["COM22"], ports):
            self.assertEqual(Ppk2Sampler.list_devices(), [("COM10", "TX")])

    def test_unknown_legacy_interfaces_remain_available_without_com_heuristics(self):
        ports = [self._port("COM3", "old", interface="PPK2", location="1-3"),
                 self._port("/dev/ttyACM3", "unix", location="1-4")]
        with self._discovery([("/dev/ttyACM9", "api-only")], ports):
            self.assertEqual(Ppk2Sampler.list_devices(), [
                ("/dev/ttyACM9", "api-only"), ("COM3", "old"), ("/dev/ttyACM3", "unix"),
            ])

    def test_ports_command_identifies_generic_windows_ppk2_and_prints_serial(self):
        from radio_power_profiler.cli import cmd_ports

        output = io.StringIO()
        with self._discovery([], [self._port("COM10", "E753C4E81F3D")]), contextlib.redirect_stdout(output):
            self.assertEqual(cmd_ports(None), 0)
        self.assertIn("PPK2 SERIAL", output.getvalue())
        self.assertIn("COM10", output.getvalue())
        self.assertIn("PPK2", output.getvalue())
        self.assertIn("E753C4E81F3D", output.getvalue())


if __name__ == "__main__":
    unittest.main()
