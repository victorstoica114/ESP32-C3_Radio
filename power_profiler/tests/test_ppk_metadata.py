import copy
import itertools
import sys
import types
import unittest
from unittest.mock import Mock, patch

from radio_power_profiler.ppk import Ppk2Sampler


def metadata(**changes):
    fields = {"Calibrated": "0", "HW": "59154", "IA": "56"}
    fields.update({f"{key}{i}": str(100 + i if key == "R" else i + 0.25)
                   for key in ("R", "O", "GS", "GI", "S", "I", "UG") for i in range(5)})
    fields.update(changes)
    return ("\r\n".join(f"{k}: {v}" for k, v in fields.items() if v is not None)
            + "\r\nEND\r\n").encode("ascii")


class FakeSerial:
    def __init__(self, responses):
        self.responses, self.chunks, self.events = iter(responses), [], []
        self.write = Mock(side_effect=self._write)
        self.flush = Mock(side_effect=lambda: self.events.append("flush"))
        self.read = Mock(side_effect=self._read)
        self.close = Mock()

    def _write(self, value):
        if value != b"\x19":
            raise AssertionError("Unexpected command")
        self.events.append("write")
        self.chunks = list(next(self.responses))
        return 1

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def _read(self, count):
        self.events.append("read")
        chunk = self.chunks.pop(0)
        assert len(chunk) == count
        return chunk


class PpkMetadataTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("radio_power_profiler.ppk.time.monotonic",
                           side_effect=itertools.count(0, 0.05))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.sleep = patch("radio_power_profiler.ppk.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def sampler(self, responses):
        sampler = object.__new__(Ppk2Sampler)
        defaults = Ppk2Sampler._parse_calibration_metadata(metadata(R0="999").decode())
        sampler.api = types.SimpleNamespace(ser=FakeSerial(responses), modifiers=defaults,
                                           get_modifiers=Mock(side_effect=AssertionError("Buggy parser used")),
                                           use_ampere_meter=Mock(), toggle_DUT_power=Mock())
        sampler._stop_and_drain = Mock(side_effect=lambda: sampler.api.ser.chunks.clear())
        return sampler

    def test_split_coefficients_and_END_are_accumulated_before_assignment(self):
        body = metadata()[:-5]
        sampler = self.sampler([[body[:19], body[19:101], body[101:], b"E", b"N", b"D\r\n"]])
        original = sampler.api.modifiers
        read = sampler.api.ser.read.side_effect
        def checked_read(count):
            self.assertIs(sampler.api.modifiers, original)
            return read(count)
        sampler.api.ser.read.side_effect = checked_read
        sampler._read_modifiers_with_retry()
        self.assertEqual(sampler.api.modifiers["R"], {str(i): 100 + i for i in range(5)})
        self.assertEqual(sampler.api.modifiers["Calibrated"], "0")
        self.assertEqual(sampler.api.ser.events[:3], ["write", "flush", "read"])
        sampler.api.ser.write.assert_called_once_with(b"\x19")
        sampler._stop_and_drain.assert_not_called()

    def test_incomplete_response_with_END_retries_with_fresh_response(self):
        sampler = self.sampler([[metadata(R4=None, O0="123")], [metadata()]])
        sampler._read_modifiers_with_retry()
        self.assertEqual(sampler.api.modifiers["O"]["0"], 0.25)
        self.assertEqual(sampler.api.ser.write.call_count, 2)
        self.assertEqual(sampler.api.ser.flush.call_count, 2)
        sampler._stop_and_drain.assert_called_once()

    def test_invalid_metadata_never_falls_back_to_defaults(self):
        for changes in ({"UG4": None}, {"Calibrated": None}, {"HW": ""}, {"IA": None},
                        {"R2": "0"}, {"R1": "-1"}, {"GS3": "nan"}, {"I0": "inf"}):
            with self.subTest(changes=changes):
                sampler = self.sampler([[metadata(**changes)]] * 3)
                original, snapshot = sampler.api.modifiers, copy.deepcopy(sampler.api.modifiers)
                with self.assertRaises(RuntimeError):
                    sampler._read_modifiers_with_retry()
                self.assertIs(sampler.api.modifiers, original)
                self.assertEqual(original, snapshot)
                self.assertEqual(sampler.api.ser.write.call_count, 3)

    def test_missing_or_nonstandalone_END_times_out_in_three_attempts(self):
        for response in (metadata()[:-5], metadata()[:-5] + b"FRIEND\r\n", b""):
            with self.subTest(response=response[-20:]):
                sampler = self.sampler([[response]] * 3 if response else [[]] * 3)
                with self.assertRaises(RuntimeError):
                    sampler._read_modifiers_with_retry()
                self.assertEqual(sampler.api.ser.write.call_count, 3)
                self.assertIn(sampler._stop_and_drain.call_count, (2, 3))

    def test_transport_failure_or_partial_command_is_not_retried(self):
        for operation, error in (("write", OSError("write failed")),
                                 ("write", TimeoutError("transport timeout")),
                                 ("flush", OSError("flush failed")), ("write", None)):
            with self.subTest(operation=operation, error=error):
                sampler = self.sampler([[metadata()]] * 3)
                getattr(sampler.api.ser, operation).side_effect = error
                if error is None:
                    sampler.api.ser.write.return_value = 0
                with self.assertRaises(OSError) as caught:
                    sampler._read_modifiers_with_retry()
                if error is not None:
                    self.assertIs(caught.exception, error)
                sampler.api.ser.write.assert_called_once()
                sampler._stop_and_drain.assert_not_called()

    def test_constructor_failure_closes_serial_without_power_commands(self):
        api = self.sampler([[metadata(R0=None)]] * 3).api
        package, module = types.ModuleType("ppk2_api"), types.ModuleType("ppk2_api.ppk2_api")
        package.ppk2_api, module.PPK2_API = module, Mock(return_value=api)
        with patch.dict(sys.modules, {"ppk2_api": package, "ppk2_api.ppk2_api": module}), \
                patch.object(Ppk2Sampler, "_stop_and_drain"):
            with self.assertRaises(RuntimeError):
                Ppk2Sampler("FAKE", voltage_mv=3300)
        api.ser.close.assert_called_once()
        api.toggle_DUT_power.assert_not_called()
        api.use_ampere_meter.assert_not_called()
