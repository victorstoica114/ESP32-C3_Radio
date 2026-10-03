import json
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from radio_power_profiler.web_app import AppServer, JobManager, PowerPathConfig


class WebPowerTests(unittest.TestCase):
    def payload(self):
        return {"tx_ppk_port": "COM10", "rx_ppk_port": "COM11",
                "tx_voltage_mv": 5000, "rx_voltage_mv": 5000}

    def test_rejects_missing_duplicate_and_invalid_power_configuration(self):
        for payload in ({}, {**self.payload(), "rx_ppk_port": "COM10"},
                        {**self.payload(), "tx_ppk_port": ""},
                        {**self.payload(), "tx_voltage_mv": 5001},
                        {**self.payload(), "rx_voltage_mv": 2499},
                        {**self.payload(), "ppk_mode": "source"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                PowerPathConfig.from_mapping(payload)

    def test_refuses_radio_or_shell_ports_without_opening_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler:
                sampler.list_devices.return_value = [("COM10", "A"), ("COM11", "B")]
                for port in ("COM33", "COM22"):
                    config = PowerPathConfig.from_mapping({**self.payload(), "rx_ppk_port": port})
                    with self.assertRaisesRegex(ValueError, "detected PPK2 data ports"):
                        manager.enable_power_paths(config)
                sampler.assert_not_called()

    def test_both_current_paths_open_before_radio_initialization_and_handoff_keeps_power(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PowerPathConfig.from_mapping(self.payload())
            with (patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type,
                  patch("radio_power_profiler.paired_ppk.ContinuousDrain") as drain_type,
                  patch.object(manager, "start") as start):
                sampler_type.list_devices.return_value = [("COM10", "A"), ("COM11", "B")]
                first, second = MagicMock(), MagicMock()
                for sampler in (first, second):
                    sampler.api.ser.is_open = True
                    sampler.close.side_effect = lambda sampler=sampler, **_: setattr(sampler.api.ser, "is_open", False)
                sampler_type.side_effect = [first, second]
                drain_type.return_value.errors = []
                result = manager.enable_power_paths(config)
                self.assertTrue(result["paired_guard_active"])
                self.assertEqual(result["paired_guard_ports"], {"tx": "COM10", "rx": "COM11"})
                self.assertEqual(sampler_type.call_args_list,
                                 [call("COM10", voltage_mv=5000), call("COM11", voltage_mv=5000)])
                for sampler in (first, second):
                    sampler.start_continuous.assert_called_once_with()
                    sampler.api.use_source_meter.assert_not_called()
                    sampler.api.set_source_voltage.assert_not_called()
                start.assert_not_called()
                self.assertIsNone(manager._session_dir)
                with self.assertRaisesRegex(RuntimeError, "already owned"):
                    manager.enable_power_paths(config)
                self.assertEqual(sampler_type.call_count, 2)
                manager.release_paired_guard_for_diagnostics()
                drain_type.return_value.pause.assert_called_once_with()
                for sampler in (first, second):
                    sampler.close.assert_called_once_with(keep_power_on=True)
                    sampler.power_off.assert_not_called()
                self.assertFalse(manager.status()["paired_guard_active"])

    def test_cannot_change_power_during_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            manager._thread = types.SimpleNamespace(is_alive=lambda: True)
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler:
                sampler.list_devices.return_value = [("COM10", "A"), ("COM11", "B")]
                with self.assertRaisesRegex(RuntimeError, "while a test is running"):
                    manager.enable_power_paths(PowerPathConfig.from_mapping(self.payload()))
                sampler.assert_not_called()

    def test_api_accepts_power_request_without_radio_ports(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with (patch.object(manager, "enable_power_paths", return_value={"ok": True}) as enable,
                      patch.object(manager, "start") as start):
                    for payload in ({}, self.payload()):
                        request = urllib.request.Request(
                            f"http://{host}:{port}/api/ppk-power/enable", data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json"}, method="POST")
                        if payload:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                self.assertEqual(response.status, 202)
                        else:
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(raised.exception.code, 400)
                            enable.assert_not_called()
                    enable.assert_called_once_with(PowerPathConfig.from_mapping(self.payload()))
                    start.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
