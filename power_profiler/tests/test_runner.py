import csv
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from radio_power_profiler.analysis import analyze_capture
from radio_power_profiler.planning import build_cases, estimate_airtime_s
from radio_power_profiler.ppk import Capture
from radio_power_profiler.profiles import load_profile, override_profile
from radio_power_profiler.runner import (
    _execute_receive_transfer,
    _restore_after_reset,
    _should_reset_between_runs,
    _warm_up_radio_path,
    run_profile,
)
from radio_power_profiler.serial_radio import SerialRadio, TransmissionResult


class FakeReceiver:
    def __init__(self, lines):
        self.lines = lines
        self.configure_calls = []
        self.drain_calls = []

    def configure(self, commands):
        self.configure_calls.append(tuple(commands))
        return []

    def configure_profile_parameters(self, profile, parameters, **kwargs):
        from radio_power_profiler.planning import parameter_commands

        return self.configure(parameter_commands(profile, parameters))

    def drain(self, *, wait_s):
        self.drain_calls.append(wait_s)
        return self.lines


class FakeTransmitter:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.drain_calls = []

    def drain(self, *, wait_s):
        self.drain_calls.append(wait_s)
        return ()

    def send_packet(self, profile, payload_bytes, **kwargs):
        self.calls.append((profile, payload_bytes, kwargs))
        return self.result


class RunnerTests(unittest.TestCase):
    def _run_fragmented_case(self, root, *, save_raw, analysis):
        profile = dataclasses.replace(override_profile(
            load_profile("RADIO_EBYTE_E79_CC1352P"), sizes=(100,), repetitions=1,
            axis_overrides={"rf_profile": ("GFSK50",), "tx_power_dbm": (13,)},
        ), warmup_transfers=0)
        transmission = TransmissionResult(
            content_bytes=100, frame_payload_bytes=(64, 36),
            expected_payloads=(b"A" * 64, b"A" * 36), response_lines=("OK",),
        )
        capture = Capture([1_000.0] * 100_000, [], 20_000, 1.0, 100_000)
        radio = MagicMock()
        radio.drain.return_value = ()
        radio.send_packet.return_value = transmission
        sampler = MagicMock()
        def capture_and_trigger(**kwargs):
            kwargs["trigger"]()
            return capture
        sampler.capture.side_effect = capture_and_trigger
        with (
            patch("radio_power_profiler.runner.Ppk2Sampler", return_value=sampler),
            patch("radio_power_profiler.runner.SerialRadio", return_value=radio),
            patch("radio_power_profiler.runner.time.sleep"),
            patch("radio_power_profiler.runner.analyze_capture", side_effect=analysis) as analyze,
        ):
            result_dir = run_profile(
                profile, radio_port="COM_FAKE_RADIO", receiver_port=None,
                ppk_port="COM_FAKE_PPK", voltage_mv=3300, output_root=root,
                save_raw=save_raw, keep_power_on=True, boot_wait_s=0,
            )
        return result_dir, analyze, profile

    def test_fragmented_analysis_failure_retains_raw_when_save_raw_is_false(self):
        with tempfile.TemporaryDirectory() as temporary:
            result_dir, analyze, profile = self._run_fragmented_case(
                Path(temporary), save_raw=False, analysis=analyze_capture,
            )
            with (result_dir / "summary.csv").open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["status"], "analysis_review_required")
            self.assertEqual(row["energy_total_uJ"], "")
            self.assertIn("detected_frame_count_mismatch", row["analysis_error"])
            self.assertEqual(json.loads(row["integration_windows_ms"]), [])
            self.assertTrue((result_dir / "raw" / "run_00001.csv.gz").is_file())
            metadata = json.loads((result_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata["save_raw"])
            self.assertIn("always_on_analysis_error", metadata["raw_retention_policy"])
            diagnostic = json.loads((result_dir / "analysis" / "run_00001.json").read_text(encoding="utf-8"))
            self.assertTrue(diagnostic["raw_retained"])
            self.assertEqual(diagnostic["analysis_error"], row["analysis_error"])
            arguments = analyze.call_args.kwargs
            self.assertIsNone(arguments["search_window_s"])
            self.assertEqual(arguments["frame_airtimes_s"], tuple(
                estimate_airtime_s(profile, size, {"rf_profile": "GFSK50", "tx_power_dbm": 13})
                for size in (64, 36)
            ))
            self.assertNotEqual(*arguments["frame_airtimes_s"])

    def test_save_raw_precedes_an_unexpected_analysis_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                self._run_fragmented_case(root, save_raw=True, analysis=RuntimeError("analysis failed"))
            self.assertEqual(len(list(root.glob("*/raw/run_00001.csv.gz"))), 1)

    def test_unexpected_analysis_exception_retains_raw_when_save_raw_is_false(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                self._run_fragmented_case(root, save_raw=False, analysis=RuntimeError("analysis failed"))
            self.assertEqual(len(list(root.glob("*/raw/run_00001.csv.gz"))), 1)
            diagnostics = list(root.glob("*/analysis/run_00001.json"))
            self.assertEqual(len(diagnostics), 1)
            detail = json.loads(diagnostics[0].read_text(encoding="utf-8"))
            self.assertTrue(detail["raw_retained"])
            self.assertTrue(detail["diagnostics"]["unexpected_exception"])
            self.assertEqual(detail["analysis_error"], "RuntimeError: analysis failed")

    def test_e79_warmup_transfer_is_verified_and_unmeasured(self):
        profile = override_profile(
            load_profile("RADIO_EBYTE_E79_CC1352P"),
            sizes=(64,),
            repetitions=1,
            axis_overrides={
                "rf_profile": ("GFSK200",),
                "tx_power_dbm": (13,),
            },
        )
        case = build_cases(profile, "tx")[0]
        payload = SerialRadio.make_payload(64)
        result = TransmissionResult(
            content_bytes=64,
            frame_payload_bytes=(64,),
            expected_payloads=(payload,),
            response_lines=("OK",),
        )
        transmitter = FakeTransmitter(result)
        receiver = FakeReceiver((payload.decode("ascii"),))

        _warm_up_radio_path(transmitter, receiver, profile, case, "tx")

        self.assertEqual(len(transmitter.calls), 1)
        self.assertEqual(transmitter.drain_calls, [0.03])
        self.assertEqual(receiver.drain_calls, [0.03, profile.receive.post_receive_s])

    def test_e32_resets_only_long_runs_and_restores_full_configuration(self):
        profile = override_profile(
            load_profile("RADIO_EBYTE_E32_868T30D"),
            sizes=(8, 1024),
            repetitions=1,
            axis_overrides={
                "tx_power_dbm": (21,),
                "bit_rate_kbps": (0.3, 19.2),
            },
        )
        cases = build_cases(profile, "tx")
        short_case = next(
            case
            for case in cases
            if case.payload_bytes == 8 and case.parameters["bit_rate_kbps"] == 19.2
        )
        long_case = next(
            case
            for case in cases
            if case.payload_bytes == 1024 and case.parameters["bit_rate_kbps"] == 0.3
        )

        self.assertFalse(_should_reset_between_runs(profile, short_case))
        self.assertTrue(_should_reset_between_runs(profile, long_case))

        radio = FakeReceiver(())
        _restore_after_reset(
            radio,
            profile,
            long_case.parameters,
            profile.receiver_enable_commands,
        )
        self.assertEqual(radio.configure_calls[0], profile.setup_commands)
        self.assertEqual(
            radio.configure_calls[1],
            ("AT+POWER4", "AT+AIR1"),
        )
        self.assertEqual(
            radio.configure_calls[2],
            profile.receiver_enable_commands,
        )

    def test_e280_restore_does_not_repeat_inter_run_reset(self):
        profile = override_profile(
            load_profile("RADIO_EBYTE_E280_SX1280"),
            sizes=(32,),
            repetitions=1,
            axis_overrides={
                "tx_power_dbm": (12,),
                "air_rate": ("1K",),
            },
        )
        case = build_cases(profile, "tx")[0]
        radio = FakeReceiver(())

        _restore_after_reset(
            radio,
            profile,
            case.parameters,
            profile.receiver_enable_commands,
        )

        self.assertNotIn("AT+RESET", radio.configure_calls[0])
        self.assertEqual(radio.configure_calls[0].count("AT"), 1)
        self.assertEqual(
            radio.configure_calls[1],
            ("AT+POWER=12", "AT+AIR=1K"),
        )
        self.assertEqual(
            radio.configure_calls[2],
            profile.receiver_enable_commands,
        )

    def test_receive_transfer_bounds_rx_window_and_waits_for_sender(self):
        profile = override_profile(
            load_profile("RADIO_CC1101_V2_868"),
            sizes=(128,),
            repetitions=1,
            axis_overrides={
                "tx_power_dbm": (0,),
                "bit_rate_kbps": (38.4,),
            },
        )
        case = build_cases(profile, "rx")[0]
        payload = SerialRadio.make_payload(30)
        lines = (payload.decode("ascii"),) * 4
        result = TransmissionResult(
            content_bytes=120,
            frame_payload_bytes=(32,) * 4,
            expected_payloads=(payload,) * 4,
            response_lines=("TXBURST=128,FRAMES=4,FRAME_MAX=32,GAP_MS=15", "OK"),
        )
        receiver = FakeReceiver(lines)
        transmitter = FakeTransmitter(result)

        actual_result, actual_lines = _execute_receive_transfer(
            receiver,
            transmitter,
            profile,
            case,
        )

        self.assertIs(actual_result, result)
        self.assertEqual(actual_lines, lines)
        self.assertEqual(receiver.configure_calls, [])
        self.assertEqual(receiver.drain_calls, [profile.receive.post_receive_s])
        _, payload_bytes, kwargs = transmitter.calls[0]
        self.assertEqual(payload_bytes, 128)
        self.assertTrue(kwargs["wait_for_completion"])
        self.assertEqual(kwargs["inter_frame_gap_ms"], 15.0)


if __name__ == "__main__":
    unittest.main()
