import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_dual_ppk as diagnostic


class FakeSerial:
    def __init__(self):
        self.closed = False

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakePpk:
    def __init__(self, port, **kwargs):
        self.port = port
        self.ser = FakeSerial()
        self.running = False
        self.start_count = 0
        self.stop_count = 0
        self.ampere = False
        self.read_threads = set()
        self.fail_reads = False
        self.empty = False
        self.modifiers = {
            "HW": "test-PPK2", "Calibrated": "1",
            **{key: {str(i): 1.0 for i in range(5)} for key in ("R", "GS", "GI", "O", "S", "I", "UG")},
        }

    def toggle_DUT_power(self, state):
        raise AssertionError("Diagnostic must not change DUT power")

    def set_source_voltage(self, value):
        raise AssertionError("Diagnostic must not generate voltage")

    def start_measuring(self):
        self.running = True
        self.start_count += 1

    def stop_measuring(self):
        self.running = False
        self.stop_count += 1

    def get_data(self):
        if not self.running:
            return b""
        self.read_threads.add(threading.get_ident())
        if self.fail_reads:
            raise OSError("simulated USB disconnect")
        if self.empty:
            return b""
        time.sleep(0.0002)  # Model the GIL-releasing serial I/O of two USB devices.
        return b"\x00" * 4

    def get_modifiers(self):
        return True

    def use_ampere_meter(self):
        self.ampere = True

    def get_samples(self, raw):
        return [12.0] * (len(raw) // 4), [0] * (len(raw) // 4)


class DualPpkDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.devices = {}

    def factory(self, port, **kwargs):
        self.devices[port] = FakePpk(port, **kwargs)
        return self.devices[port]

    def diagnose(self, **kwargs):
        # Skip the quiet-period delay for simulated ports; no hardware exists.
        with patch.object(diagnostic, "_stop_and_drain", lambda api: api.stop_measuring()):
            return diagnostic.diagnose(tx_ppk_port="COM10", rx_ppk_port="COM11",
                                       api_factory=self.factory, **kwargs)

    def test_duplicate_alias_ports_rejected_before_open(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            diagnostic.diagnose(tx_ppk_port="com10", rx_ppk_port=r"\\.\COM10", api_factory=self.factory)
        self.assertFalse(self.devices)

    def test_invalid_duration_rejected_before_open(self):
        for duration in (-1, 6, float("nan"), float("inf")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.diagnose(capture_seconds=duration)
        self.assertFalse(self.devices)

    def test_metadata_only_never_starts_sampling_or_changes_power(self):
        report = self.diagnose(port_metadata={"COM10": {"serial_number": "TX-SERIAL"}})
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["devices"]["tx"]["usb_metadata"]["serial_number"], "TX-SERIAL")
        for api in self.devices.values():
            self.assertTrue(api.ampere)
            self.assertTrue(api.ser.closed)
            self.assertEqual(api.start_count, 0)
        self.assertFalse(report["radio_commands_sent"])
        self.assertFalse(report["dut_switch_commands_sent"])

    def test_parallel_readout_uses_two_workers_and_reports_currents(self):
        report = self.diagnose(capture_seconds=0.01)
        self.assertEqual(report["status"], "ok", report["errors"])
        self.assertFalse(report["hardware_synchronized"])
        self.assertIsNotNone(report["capture"]["both_started_host_monotonic_ns"])
        self.assertNotEqual(self.devices["COM10"].read_threads, self.devices["COM11"].read_threads)
        for item in report["devices"].values():
            self.assertGreater(item["sample_count"], 0)
            self.assertEqual(item["mean_current_uA"], 12)
            self.assertTrue(item["serial_closed"])

    def test_second_port_open_failure_closes_first(self):
        def factory(port, **kwargs):
            if port == "COM11":
                raise OSError("busy")
            return self.factory(port, **kwargs)
        report = diagnostic.diagnose(tx_ppk_port="COM10", rx_ppk_port="COM11", api_factory=factory)
        self.assertEqual(report["status"], "error")
        self.assertTrue(self.devices["COM10"].ser.closed)

    def test_incomplete_calibration_closes_both_without_sampling(self):
        original = self.factory
        def factory(port, **kwargs):
            api = original(port, **kwargs)
            api.modifiers["HW"] = None
            return api
        self.factory = factory
        report = self.diagnose(capture_seconds=0.01)
        self.assertEqual(report["status"], "error")
        self.assertTrue(all(api.ser.closed and api.start_count == 0 for api in self.devices.values()))

    def test_failed_metadata_response_cannot_use_api_defaults(self):
        original = self.factory
        def factory(port, **kwargs):
            api = original(port, **kwargs)
            api.get_modifiers = lambda: None
            return api
        self.factory = factory
        report = self.diagnose(capture_seconds=0.01)
        self.assertEqual(report["status"], "error")
        self.assertTrue(all(api.ser.closed and api.start_count == 0 for api in self.devices.values()))

    def test_usb_read_failure_stops_and_closes_both(self):
        original = self.factory
        def factory(port, **kwargs):
            api = original(port, **kwargs)
            api.fail_reads = port == "COM11"
            return api
        self.factory = factory
        report = self.diagnose(capture_seconds=0.01)
        self.assertEqual(report["status"], "error")
        self.assertIn("simulated USB disconnect", str(report["errors"]))
        self.assertTrue(all(api.ser.closed and not api.running for api in self.devices.values()))

    def test_empty_capture_is_not_success(self):
        original = self.factory
        def factory(port, **kwargs):
            api = original(port, **kwargs)
            api.empty = True
            return api
        self.factory = factory
        report = self.diagnose(capture_seconds=0.005)
        self.assertEqual(report["status"], "error")
        self.assertIn("no complete samples", str(report["errors"]))

    def test_existing_report_is_not_overwritten_or_hardware_opened(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "diagnostic.json"
            path.write_text("original", encoding="utf-8")
            with patch.object(diagnostic, "diagnose") as run, self.assertRaises(FileExistsError):
                diagnostic.main(["--tx-ppk-port", "COM10", "--rx-ppk-port", "COM11", "--output", str(path)])
            run.assert_not_called()
            self.assertEqual(path.read_text(encoding="utf-8"), "original")

    def test_error_report_is_written_and_cli_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "diagnostic.json"
            with patch.object(diagnostic, "diagnose", return_value={"status": "error", "errors": ["busy"]}), patch("builtins.print"):
                code = diagnostic.main(["--tx-ppk-port", "COM10", "--rx-ppk-port", "COM11", "--output", str(path)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(path.read_text())["errors"], ["busy"])


if __name__ == "__main__":
    unittest.main()
