import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from radio_power_profiler.paired_ppk import capture_pair


class FakeSampler:
    def __init__(self, *, empty=False, decode_error=False):
        self.running = False
        self.empty = empty
        self.decode_error = decode_error
        self.read_count = 0
        self.api = self
        self.ser = SimpleNamespace(flush=lambda: None, in_waiting=0)

    def _stop_and_drain(self):
        self.running = False

    def start_measuring(self):
        self.running = True

    def stop_measuring(self):
        self.running = False

    def get_data(self):
        time.sleep(.001)
        if not self.running or self.empty:
            return b""
        self.read_count += 1
        return b"\0" * 400

    def get_samples(self, raw):
        if self.decode_error:
            raise ValueError("bad decoder")
        return [100.] * (len(raw) // 4), [0] * (len(raw) // 4)


class PairedCaptureTests(unittest.TestCase):
    def run_pair(self, samplers, trigger):
        with tempfile.TemporaryDirectory() as temp:
            result = capture_pair(samplers, pre_s=.005, after_trigger_s=.015,
                                  trigger=trigger, wire_directory=Path(temp) / "wire",
                                  ready_timeout_s=.06, trigger_timeout_s=.1)
            raw = {role: Path(path).read_bytes() for role, path in result.wire_paths.items()}
            self.assertTrue((Path(temp) / "wire/timing.json").is_file())
            return result, raw

    def test_both_streams_ready_before_single_trigger(self):
        samplers = {role: FakeSampler() for role in ("tx", "rx")}
        calls = []
        def trigger():
            calls.append(1)
            self.assertTrue(all(s.running and s.read_count >= 5 for s in samplers.values()))
        result, wire = self.run_pair(samplers, trigger)
        self.assertEqual(calls, [1])
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(set(result.captures), {"tx", "rx"})
        self.assertTrue(all(wire.values()))
        self.assertFalse(result.timing["hardware_synchronized"])
        self.assertTrue(all(not s.running for s in samplers.values()))

    def test_unready_ppk_prevents_rf_trigger_and_preserves_other_wire(self):
        samplers = {"tx": FakeSampler(), "rx": FakeSampler(empty=True)}
        calls = []
        result, wire = self.run_pair(samplers, lambda: calls.append(1))
        self.assertEqual(calls, [])
        self.assertFalse(result.trigger_called)
        self.assertIn("coordinator", result.errors)
        self.assertTrue(wire["tx"])
        self.assertFalse(wire["rx"])

    def test_decode_failure_retains_both_wire_files_and_other_capture(self):
        samplers = {"tx": FakeSampler(decode_error=True), "rx": FakeSampler()}
        result, wire = self.run_pair(samplers, lambda: None)
        self.assertIn("tx_decode", result.errors)
        self.assertIn("rx", result.captures)
        self.assertTrue(all(wire.values()))

    def test_radio_error_keeps_both_current_records(self):
        def fail():
            raise RuntimeError("radio failed")
        result, wire = self.run_pair({role: FakeSampler() for role in ("tx", "rx")}, fail)
        self.assertIn("trigger", result.errors)
        self.assertEqual(set(result.captures), {"tx", "rx"})
        self.assertTrue(all(wire.values()))


if __name__ == "__main__":
    unittest.main()
