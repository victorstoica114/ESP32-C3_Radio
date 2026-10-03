import csv
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from radio_power_profiler import paired_runner as runner
from radio_power_profiler.analysis import analyze_capture
from radio_power_profiler.marker_analysis import (
    analyze_tx_marker_pair, INTEGRATION_METHOD,
    analyze_radio_marker_pair, RADIO_INTEGRATION_METHOD,
    RADIO_TOTALS_INTEGRATION_METHOD, TOTAL_ONLY_ENERGY_POLICY,
    FILTER_RADIO_TOTALS_INTEGRATION_METHOD, FILTER_TOTAL_ONLY_ENERGY_POLICY,
    ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD, ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY,
)
from radio_power_profiler.paired_ppk import PairedCapture
from radio_power_profiler.fragment_marker_analysis import (
    analyze_fragmented_radio_marker_pair, FRAGMENT_TOTALS_INTEGRATION_METHOD,
)
from radio_power_profiler.ppk import Capture
from radio_power_profiler.serial_radio import TransmissionResult
from radio_power_profiler.web_app import CommandStep, validate_result


class PairedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.samplers = []
        self.radios = []
        self.radio_kwargs = []
        self.tx_version = "0.3.0"
        self.rx_version = "0.3.0"
        self.marker_reply = ("+TXMARKER:DIO=17,SOURCE=RAT_GPO0,ACTIVE=HIGH", "OK")
        self.local_marker_replies = {}
        self.local_marker_set_replies = {}
        self.marker_calls = []
        self.radio_configuration_at_capture = []
        self.usb_poll_count = 0
        self.payload_bytes = 32
        self.rf_profile = "GFSK200"
        self.tx_power_dbm = 13
        self.config_overrides = {}
        self.sent_cases = []
        self.calibration = {key: {str(index): value for index in range(5)} for key, value in
                            {"R": 21.97265625, "O": 0., "GS": 0., "GI": 1., "S": 0., "I": 0., "UG": 1.}.items()}

    def sampler(self, *args, **kwargs):
        sampler = MagicMock()
        sampler.api.modifiers = {"HW": "fake", "Calibrated": "1", **self.calibration}
        self.samplers.append(sampler)
        return sampler

    def radio(self, *args, **kwargs):
        self.assertEqual(len(self.samplers), 2)
        self.assertTrue(all(s.start_continuous.called for s in self.samplers))
        self.radio_kwargs.append(kwargs)
        radio = MagicMock()
        radio.drain.return_value = ()
        radio.drain_bounded.return_value = ()
        radio.send_packet.return_value = TransmissionResult(
            self.payload_bytes, (self.payload_bytes,), (b"A" * self.payload_bytes,), ("OK",))
        role = "tx" if len(self.radios) == 0 else "rx"
        if role == "rx":
            radio.drain.return_value = (f"+RXHEX:{self.payload_bytes},-45," + (b"A" * self.payload_bytes).hex().upper(),)
        rates = {"GFSK4K8": 4800, "GFSK50": 50000, "GFSK200": 200000,
                 "SLR2K5": 2500, "SLR5": 5000, "OOK4K8": 4800, "IEEE154G50": 50000}
        actual = {"PROFILE": self.rf_profile, "RATE": str(rates[self.rf_profile]), "PWR": str(self.tx_power_dbm)}
        actual.update(self.config_overrides.get(role, {}))
        config = f"+CFG:PROFILE={actual['PROFILE']},FREQ=433920000,RATE={actual['RATE']},PWR={actual['PWR']},MOD=2GFSK,SYNC=0x930B51DE,RX={'OFF' if role == 'tx' else 'ON'},SLEEP=NO,DEBUG=OFF"
        version = self.tx_version if role == "tx" else self.rx_version
        if version == "0.3.2":
            config += ",MARKER=" + role.upper()
        local_marker = f"+MARKER:ROLE={role.upper()},DIO=17,SOURCE=RAT_GPO{'0' if role == 'tx' else '1'},ACTIVE=HIGH"
        replies = {
            "AT+VERSION?": (f"+VERSION:E79_AT_MODEM,{version},SDK", "OK"),
            "AT+CFG?": (config, "OK"), "AT+TXMARKER?": self.marker_reply,
            "AT+MARKER=" + role.upper(): self.local_marker_set_replies.get(role, ("OK",)),
            "AT+MARKER?": self.local_marker_replies.get(role, (local_marker, "OK")),
        }
        radio.command.side_effect = lambda command, **kwargs: type("Reply", (), {"lines": replies[command]})()
        self.radios.append(radio)
        return radio

    def run_pilot(self, root, *, received=True, decode_error=False, ppk_mode="ampere",
                  short_capture=False, sample_loss=False, resume_error=False,
                  integration_mode="modeled", marker_pulses=None, tx_version=None,
                  rx_version=None, marker_counter_faults=None,
                  usb_snapshots=None, interface_label="CH340", real_warmup=False,
                  payload_bytes=32, rf_profile="GFSK200", tx_power_dbm=13,
                  marker_totals_only=False, total_word_fault=None, fragmented=False,
                  sampling_probe=None, filter_aware_totals=False,
                  filter_history_policy="current_equivalence_v1"):
        self.payload_bytes, self.rf_profile, self.tx_power_dbm = payload_bytes, rf_profile, tx_power_dbm
        self.tx_version = tx_version or ("0.3.2" if integration_mode == "radio_markers" else "0.3.1" if integration_mode == "tx_marker" else "0.3.0")
        self.rx_version = rx_version or ("0.3.2" if integration_mode == "radio_markers" else "0.3.0")
        capture = Capture([100.] * 1000 + [20_000.] * 500 + [100.] * 3500, [0] * 5000, 1000, .05, 5000)
        if short_capture:
            capture = Capture([100.] * 1000 + [20_000.], [0] * 1001, 1000, .01, 1001)
        elif sample_loss:
            capture = Capture(capture.samples_uA, capture.logic_bits, 1000, .05, 5200)
        frames = (64,) * (payload_bytes // 64) if fragmented else (payload_bytes,)
        expected_payloads = tuple(b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_" for _ in frames) if fragmented else (b"A" * payload_bytes,)
        transfer = TransmissionResult(payload_bytes, frames, expected_payloads, ("OK",) * len(frames))
        def send_transfer(receiver, transmitter, profile, case):
            self.sent_cases.append(case)
            self.assertEqual(case.payload_bytes, payload_bytes)
            self.assertEqual(case.parameters, {"rf_profile": rf_profile, "tx_power_dbm": tx_power_dbm})
            self.assertEqual(profile.transmit.frame_sizes(case.payload_bytes), frames)
            return transfer, tuple(payload.decode("ascii") for payload in expected_payloads) if fragmented and received else ()
        calls = []
        def paired(samplers, **kwargs):
            if sampling_probe:
                sampling_probe("capture_started")
            self.radio_configuration_at_capture.append([
                (r.configure.call_args_list[:], r.configure_profile_parameters.call_args_list[:],
                 r.command.call_args_list[:]) for r in self.radios
            ])
            kwargs["trigger"]()
            calls.append(1)
            captures = {"tx": capture, "rx": capture}
            wire_paths = {}
            if integration_mode in {"tx_marker", "radio_markers"}:
                default_rx_stop = 1440 if integration_mode == "radio_markers" else 1476
                pulses = marker_pulses if marker_pulses is not None else {"tx": ((1200, 1376),), "rx": ((1300, default_rx_stop),)}
                if fragmented and marker_pulses is None:
                    pulses = {role: tuple((1200 + i * 200, 1200 + i * 200 + width)
                                          for i in range(len(frames)))
                              for role, width in (("tx", 176), ("rx", 140))}
                folder = kwargs["wire_directory"]
                folder.mkdir(parents=True, exist_ok=True)
                for role in ("tx", "rx"):
                    logic = [0] * len(capture.samples_uA)
                    for first, last in pulses[role]:
                        logic[first:last] = [1] * (last - first)
                    captures[role] = Capture(capture.samples_uA, logic, capture.trigger_index,
                                             capture.elapsed_s, capture.expected_samples)
                    wire = folder / f"{role}.ppk2.bin"
                    words = [(index % 64) << 18 | value << 24 for index, value in enumerate(logic)]
                    if marker_totals_only:
                        words = [word | 3 << 14 | round(capture.samples_uA[index] / 2)
                                 for index, word in enumerate(words)]
                        if total_word_fault and role == total_word_fault[0]:
                            words[total_word_fault[1]] ^= total_word_fault[2]
                    if marker_counter_faults and role in marker_counter_faults:
                        words[marker_counter_faults[role]] ^= 1 << 18
                    wire.write_bytes(b"".join(struct.pack("<I", word) for word in words))
                    wire_paths[role] = str(wire)
            errors = {}
            if decode_error:
                captures.pop("tx")
                errors["tx_decode"] = "simulated decoder failure"
            if sampling_probe:
                sampling_probe("capture_stopped")
            return PairedCapture(captures=captures, errors=errors, trigger_called=True, wire_paths=wire_paths,
                                 timing={"hardware_synchronized": False,
                                         "devices": {role: {"trigger_index": item.trigger_index} for role, item in captures.items()}})
        analysis_calls = []
        def analyze(*args, **kwargs):
            if sampling_probe:
                sampling_probe("analysis")
            index = len(analysis_calls) // 2 + 1
            if not decode_error:
                roots = list(root.glob("*_e79_paired_pilot"))
                for role in ("tx", "rx"):
                    self.assertTrue((roots[0] / role / "raw" / f"run_{index:05d}.csv.gz").is_file())
            analysis_calls.append(kwargs)
            return analyze_capture(*args, **kwargs)
        def marker_analyze(*args, **kwargs):
            if sampling_probe:
                sampling_probe("analysis")
            index = len(self.marker_calls) + 1
            roots = list(root.glob("*_e79_paired_pilot"))
            for role in ("tx", "rx"):
                self.assertTrue((roots[0] / role / "raw" / f"run_{index:05d}.csv.gz").is_file())
            self.marker_calls.append(kwargs)
            analyze_markers = analyze_radio_marker_pair if integration_mode == "radio_markers" else analyze_tx_marker_pair
            if fragmented:
                analyze_markers = analyze_fragmented_radio_marker_pair
            return analyze_markers(*args, **kwargs)
        def usb_metadata():
            self.assertFalse(self.samplers, "USB enumeration must precede opening either PPK2")
            self.assertFalse(self.radios, "USB enumeration must precede opening either UART")
            self.usb_poll_count += 1
            if usb_snapshots is not None:
                return usb_snapshots[min(self.usb_poll_count - 1, len(usb_snapshots) - 1)]
            return {port: {"device": port, "serial_number": port + "-USB"}
                    for port in ("COM10", "COM11", "COM12", "COM13")}
        with (
            patch.object(runner, "Ppk2Sampler", side_effect=self.sampler),
            patch.object(runner, "SerialRadio", side_effect=self.radio),
            patch.object(runner, "ContinuousDrain") as drain,
            patch.object(runner, "_warm_up_radio_path", side_effect=runner._warm_up_radio_path if real_warmup else None) as warm,
            patch.object(runner, "_send_one_transfer", side_effect=send_transfer) as send,
            patch.object(runner, "_usb_metadata", side_effect=usb_metadata),
            patch.object(runner, "_received_all_frames", return_value=received),
            patch.object(runner, "capture_pair", side_effect=paired),
            patch.object(runner, "analyze_capture", side_effect=analyze),
            patch.object(runner, "analyze_tx_marker_pair", side_effect=marker_analyze),
            patch.object(runner, "analyze_radio_marker_pair", side_effect=marker_analyze),
            patch.object(runner, "analyze_fragmented_radio_marker_pair", side_effect=marker_analyze),
            patch.object(runner.time, "sleep"),
        ):
            starts = 0
            def start_hold():
                nonlocal starts
                starts += 1
                if sampling_probe:
                    sampling_probe("hold_start")
                if resume_error and starts == 2:
                    self.samplers[0].api.start_measuring()  # First PPK starts, second fails.
                    raise RuntimeError("resume failed")
            drain.return_value.start.side_effect = start_hold
            output = runner.run_paired_pilot(
                tx_radio_port="COM12", rx_radio_port="COM13", tx_ppk_port="COM10", rx_ppk_port="COM11",
                tx_voltage_mv=3300, rx_voltage_mv=3300, output_root=root,
                tx_identity="physical A", rx_identity="physical B", voltage_confirmed=True,
                voltage_provenance="Operator measured external VIN", ppk_mode=ppk_mode,
                integration_mode=integration_mode, interface_label=interface_label,
                payload_bytes=payload_bytes, rf_profile=rf_profile, tx_power_dbm=tx_power_dbm,
                marker_totals_only=marker_totals_only, fragmented=fragmented,
                filter_aware_totals=filter_aware_totals,
                filter_history_policy=filter_history_policy,
            )
        return output, calls, analysis_calls, send.call_count, warm.call_count

    def test_usb_reenumeration_waits_for_all_ports_then_runs_once_with_serial_identities(self):
        usb = {port: {"device": port, "serial_number": port + "-USB"}
               for port in ("COM10", "COM11", "COM12", "COM13")}
        # Each role's PPK2 can return at a different time; do not combine stale snapshots.
        snapshots = [{p: usb[p] for p in ("COM12", "COM13")},
                     {p: usb[p] for p in ("COM10", "COM12", "COM13")},
                     {p: usb[p] for p in ("COM11", "COM12", "COM13")}, usb]
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, send_count, warm_count = self.run_pilot(
                Path(temp), integration_mode="tx_marker", usb_snapshots=snapshots,
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual(self.usb_poll_count, 4)
            self.assertEqual((len(calls), send_count, warm_count), (5, 5, 1))
            for role, port in (("tx", "COM10"), ("rx", "COM11")):
                self.assertEqual(manifest["endpoints"][role]["ppk_usb"]["serial_number"], port + "-USB")

    def test_usb_reenumeration_timeout_fails_before_opening_hardware_or_transmitting(self):
        usb = {port: {"device": port, "serial_number": port + "-USB"} for port in ("COM12", "COM13")}
        with tempfile.TemporaryDirectory() as temp, patch.object(
            runner.time, "monotonic", side_effect=[100., 100., 111.5, 112.],
        ):
            output, calls, _, send_count, warm_count = self.run_pilot(Path(temp), usb_snapshots=[usb])
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("USB enumeration timed out after 12s", manifest["errors"][0])
            self.assertIn("COM10, COM11", manifest["errors"][0])
            self.assertEqual(self.usb_poll_count, 3)
            self.assertEqual((calls, send_count, warm_count), ([], 0, 0))
            self.assertEqual(manifest["rows"], [])
            self.assertFalse(self.samplers)
            self.assertFalse(self.radios)
            self.assertFalse(list(output.rglob("*.csv.gz")))

    def test_reenumerated_ppk_without_serial_identity_still_fails_before_hardware(self):
        usb = {port: {"device": port, "serial_number": port + "-USB"}
               for port in ("COM10", "COM11", "COM12", "COM13")}
        usb["COM11"]["serial_number"] = None
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, send_count, warm_count = self.run_pilot(Path(temp), usb_snapshots=[{}, usb])
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("rx: cannot establish the PPK2 USB serial identity", manifest["errors"][0])
            self.assertEqual((calls, send_count, warm_count), ([], 0, 0))
            self.assertFalse(self.samplers)
            self.assertFalse(self.radios)

    def test_ch340_resets_both_radios_before_preflight_once_without_changing_global_profile(self):
        original_preflight = runner._preflight
        preflight_roles = []
        def preflight(radio, role, integration_mode, **kwargs):
            index = self.radios.index(radio)
            self.assertTrue(self.radio_kwargs[index]["reset_on_open"])
            self.assertIs(self.radio_kwargs[index]["dtr"], False)
            self.assertIs(self.radio_kwargs[index]["rts"], False)
            preflight_roles.append(role)
            return original_preflight(radio, role, integration_mode, **kwargs)
        self.assertFalse(runner.load_profile("RADIO_EBYTE_E79_CC1352P").serial_reset_on_open)
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "_preflight", side_effect=preflight):
            output, calls, _, send_count, _ = self.run_pilot(Path(temp), integration_mode="tx_marker")
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual(preflight_roles, ["tx", "rx"])
            self.assertEqual(len(self.radio_kwargs), 2, "Do not reopen/reset radios between transfers")
            self.assertEqual((len(calls), send_count), (5, 5))
            self.assertIs(manifest["serial_reset_on_open"], True)
            self.assertEqual(manifest["serial_reset_rts_pulse_ms"], 100)
            self.assertIs(manifest["serial_dtr"], False)
            self.assertIs(manifest["serial_rts"], False)
            self.assertEqual(manifest["serial_reset_scope"], "once_per_radio_before_initial_AT_sync_and_preflight")
            for role in ("tx", "rx"):
                metadata = json.loads((output / role / "metadata.json").read_text())
                self.assertIs(metadata["profile"]["serial_reset_on_open"], True)
                self.assertEqual(metadata["serial_reset_rts_pulse_ms"], 100)
        self.assertFalse(runner.load_profile("RADIO_EBYTE_E79_CC1352P").serial_reset_on_open)

    def test_other_interface_keeps_reset_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            output, *_ = self.run_pilot(Path(temp), interface_label="ESP32-C3")
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertIs(manifest["serial_reset_on_open"], False)
            self.assertEqual(manifest["serial_reset_rts_pulse_ms"], 0)
            self.assertTrue(all(k["reset_on_open"] is False for k in self.radio_kwargs))

    def test_five_transfers_produce_both_raw_before_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, send_count, warm_count = self.run_pilot(Path(temp))
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual(len(calls), 5)
            self.assertEqual(send_count, 5)
            self.assertEqual(warm_count, 1)
            for role in ("tx", "rx"):
                self.assertEqual(len(list((output / role / "raw").glob("*.csv.gz"))), 5)
                with (output / role / "summary.csv").open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual([r["run_id"] for r in rows], [p["run_id"] for p in manifest["rows"]])
                self.assertEqual({r["integration_method"] for r in rows},
                                 {"aligned_modeled_airtime" if role == "tx" else "fixed_modeled_airtime"})
            self.assertTrue(all(item["align_integration_window"] for item in analyses[::2]))
            self.assertTrue(all(not item["align_integration_window"] and item["frame_airtimes_s"] is None for item in analyses[1::2]))
            self.assertTrue(all(k["dtr"] is False and k["rts"] is False for k in self.radio_kwargs))
            self.assertTrue(all(s.close.call_args.kwargs == {"keep_power_on": True} for s in self.samplers))

    def test_rx_missing_is_kept_without_selective_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, send_count, _ = self.run_pilot(Path(temp), received=False)
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid")
            self.assertEqual(send_count, 5)
            self.assertTrue(all(p["tx_status"] == p["rx_status"] == "rx_missing" for p in manifest["rows"]))

    def test_common_marker_mode_saves_both_raw_and_integrates_local_pulse_without_model(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, send_count, _ = self.run_pilot(Path(temp), integration_mode="tx_marker")
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual(manifest["integration_mode"], "tx_marker")
            self.assertFalse(manifest["hardware_synchronized"])
            validation = validate_result(CommandStep(
                "marker", "marker", ["--integration-mode", "tx_marker"], "paired", 5,
            ), output)
            self.assertTrue(validation["valid"], validation)
            self.assertEqual((len(calls), send_count, len(self.marker_calls)), (5, 5, 5))
            self.assertFalse(analyses)
            self.assertEqual(manifest["endpoints"]["tx"]["modem_preflight"]["tx_marker"]["dio"], 17)
            self.assertNotIn("tx_marker", manifest["endpoints"]["rx"]["modem_preflight"])
            for pair in manifest["rows"]:
                self.assertTrue(pair["marker_diagnostics"]["valid"])
            for role in ("tx", "rx"):
                with (output / role / "summary.csv").open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 5)
                for row in rows:
                    self.assertEqual(row["integration_method"], INTEGRATION_METHOD)
                    self.assertIn("TX marker requires TX 0.3.1", row["firmware_selection"])
                    self.assertIn(f"observed {role.upper()} modem " + ("0.3.1" if role == "tx" else "0.3.0"), row["firmware_selection"])
                    self.assertNotIn("0.3.0 required", row["firmware_selection"])
                    self.assertAlmostEqual(float(row["event_duration_ms"]), 1.76)
                    self.assertAlmostEqual(float(row["energy_total_uJ"]), 116.16)
                analysis = json.loads((output / role / "analysis/run_00001.json").read_text())
                self.assertTrue(analysis["raw_retained"])
                self.assertTrue(analysis["diagnostics"]["marker_diagnostics"]["valid"])
                self.assertIn("Legacy rectified excess", analysis["diagnostics"]["excess_energy_definition"])

    def test_radio_markers_integrate_unequal_pulses_and_keep_same_receiver_configuration_for_five_packets(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, send_count, warm_count = self.run_pilot(
                Path(temp), integration_mode="radio_markers", real_warmup=True,
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual((len(calls), send_count, warm_count, len(self.marker_calls)), (5, 5, 1, 5))
            self.assertFalse(analyses)
            self.assertEqual(manifest["rx_arming_policy"], "continuous_across_warmup_and_five_transfers")
            self.assertIs(manifest["rx_rearm_between_transfers"], False)
            # No RX enable, reset, profile change or marker reconfiguration between captures.
            self.assertEqual(len(self.radios), 2)
            self.assertTrue(all(snapshot == self.radio_configuration_at_capture[0]
                                for snapshot in self.radio_configuration_at_capture))
            rx = self.radios[1]
            profile = runner.load_profile("RADIO_EBYTE_E79_CC1352P")
            rx_enable = profile.receiver_enable_commands
            self.assertEqual(sum(call.args == (rx_enable,) for call in rx.configure.call_args_list), 1)
            self.assertEqual(self.radios[0].send_packet.call_count, profile.warmup_transfers)
            rx.send_packet.assert_not_called()
            validation = validate_result(CommandStep(
                "local", "local", ["--integration-mode", "radio_markers"], "paired", 5,
            ), output)
            self.assertTrue(validation["valid"], validation)
            for index, role in enumerate(("tx", "rx")):
                preflight = manifest["endpoints"][role]["modem_preflight"]
                self.assertEqual(preflight["firmware_version"], "0.3.2")
                self.assertEqual(preflight["radio_marker"]["role"], role.upper())
                self.assertEqual(preflight["radio_marker"]["source"], f"RAT_GPO{index}")
                commands = [call.args[0] for call in self.radios[index].command.call_args_list]
                self.assertEqual(commands, ["AT+VERSION?", "AT+MARKER=" + role.upper(), "AT+MARKER?", "AT+CFG?"])
                metadata = json.loads((output / role / "metadata.json").read_text())
                self.assertEqual(metadata["observed_endpoint"]["modem_preflight"], preflight)
                with (output / role / "summary.csv").open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 5)
                for row in rows:
                    self.assertEqual(row["integration_method"], RADIO_INTEGRATION_METHOD)
                    self.assertIn(f"observed {role.upper()} modem 0.3.2", row["firmware_selection"])
                    self.assertAlmostEqual(float(row["event_duration_ms"]), 1.76 if role == "tx" else 1.40)
                    self.assertAlmostEqual(float(row["energy_total_uJ"]), 116.16 if role == "tx" else 92.4)
                self.assertEqual(len(list((output / role / "raw").glob("*.csv.gz"))), 5)
            self.assertIn("sync detected to packet end/abort", manifest["rx_metric_definition"])
            self.assertIn("listening", manifest["rx_metric_definition"])

    def test_radio_markers_require_firmware_032_on_both_roles_before_any_warmup(self):
        for role in ("tx", "rx"):
            self.setUp()
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp:
                output, calls, _, send_count, warm_count = self.run_pilot(
                    Path(temp), integration_mode="radio_markers", **{role + "_version": "0.3.1"},
                )
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "failed")
                self.assertIn(f"{role}: independent radio markers require E79_AT_MODEM firmware 0.3.2", manifest["errors"][0])
                self.assertEqual((calls, send_count, warm_count), ([], 0, 0))

    def test_radio_marker_role_set_and_query_must_be_acknowledged_and_exact(self):
        proper = "+MARKER:ROLE=RX,DIO=17,SOURCE=RAT_GPO1,ACTIVE=HIGH"
        invalid = [
            ("set", ()), ("set", ("#ERROR:BAD_MARKER", "OK")),
            ("query", (proper.replace("ROLE=RX", "ROLE=TX"), "OK")),
            ("query", (proper.replace("RAT_GPO1", "RAT_GPO0"), "OK")),
            ("query", (proper.replace("DIO=17", "DIO=16"), "OK")),
            ("query", (proper,)), ("query", (proper, proper, "OK")),
            ("query", (proper, "#ERROR:FAIL", "OK")),
        ]
        for stage, reply in invalid:
            self.setUp()
            target = self.local_marker_set_replies if stage == "set" else self.local_marker_replies
            target["rx"] = reply
            with self.subTest(stage=stage, reply=reply), tempfile.TemporaryDirectory() as temp:
                output, calls, _, send_count, warm_count = self.run_pilot(Path(temp), integration_mode="radio_markers")
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "failed")
                self.assertIn("rx:", manifest["errors"][0])
                self.assertEqual((calls, send_count, warm_count), ([], 0, 0))

    def test_missing_local_rx_pulse_fails_entire_pair_and_retains_both_raw_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, send_count, _ = self.run_pilot(
                Path(temp), integration_mode="radio_markers", marker_pulses={"tx": ((1200, 1376),), "rx": ()},
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual((len(calls), send_count), (1, 1))
            self.assertFalse(analyses)
            self.assertFalse(manifest["rows"][0]["marker_diagnostics"]["valid"])
            for role in ("tx", "rx"):
                self.assertTrue((output / role / "raw/run_00001.csv.gz").is_file())
                with (output / role / "summary.csv").open(newline="") as stream:
                    row = next(csv.DictReader(stream))
                self.assertEqual(row["status"], "analysis_review_required")
                self.assertEqual(row["energy_total_uJ"], "")
                self.assertEqual(row["integration_method"], RADIO_INTEGRATION_METHOD)

    def test_local_marker_counter_faults_keep_conservative_rejection_for_both_roles(self):
        for role, index in (("tx", 400), ("rx", 400), ("tx", 1250), ("rx", 1440)):
            self.setUp()
            with self.subTest(role=role, index=index), tempfile.TemporaryDirectory() as temp:
                output, calls, _, send_count, _ = self.run_pilot(
                    Path(temp), integration_mode="radio_markers", marker_counter_faults={role: index},
                )
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "failed")
                self.assertEqual((len(calls), send_count), (1, 1))
                pair = manifest["rows"][0]
                self.assertEqual(pair["marker_diagnostics"]["roles"][role]["counter_qa"]["status"], "review_required")
                self.assertEqual((pair["tx_status"], pair["rx_status"]), ("analysis_review_required",) * 2)

    def test_common_marker_mode_accepts_032_by_selecting_tx_before_legacy_query(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, send_count, _ = self.run_pilot(
                Path(temp), integration_mode="tx_marker", tx_version="0.3.2", rx_version="0.3.2",
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual((len(calls), send_count), (5, 5))
            self.assertEqual([call.args[0] for call in self.radios[0].command.call_args_list],
                             ["AT+VERSION?", "AT+MARKER=TX", "AT+MARKER?", "AT+CFG?", "AT+TXMARKER?"])
            self.assertNotIn("AT+MARKER?", [call.args[0] for call in self.radios[1].command.call_args_list])

    def test_modeled_mode_accepts_032_without_configuring_or_querying_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            output, *_ = self.run_pilot(Path(temp), tx_version="0.3.2", rx_version="0.3.2")
            self.assertEqual(json.loads((output / "pairing.json").read_text())["status"], "valid")
            for radio in self.radios:
                self.assertEqual([call.args[0] for call in radio.command.call_args_list], ["AT+VERSION?", "AT+CFG?"])

    def test_invalid_marker_retains_raw_and_fails_both_roles_without_fallback_or_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, send_count, _ = self.run_pilot(
                Path(temp), integration_mode="tx_marker", marker_pulses={"tx": (), "rx": ((1300, 1476),)},
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual((len(calls), send_count), (1, 1))
            self.assertFalse(analyses)
            self.assertFalse(manifest["rows"][0]["marker_diagnostics"]["valid"])
            for role in ("tx", "rx"):
                self.assertTrue((output / role / "raw/run_00001.csv.gz").is_file())
                with (output / role / "summary.csv").open(newline="") as stream:
                    row = next(csv.DictReader(stream))
                self.assertEqual(row["status"], "analysis_review_required")
                self.assertEqual(row["energy_total_uJ"], "")
                self.assertEqual(row["integration_method"], INTEGRATION_METHOD)

    def test_marker_mode_requires_new_tx_firmware_before_warmup(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, send_count, warm_count = self.run_pilot(
                Path(temp), integration_mode="tx_marker", tx_version="0.3.0",
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("requires E79_AT_MODEM firmware 0.3.1", manifest["errors"][0])
            self.assertEqual((calls, send_count, warm_count), ([], 0, 0))

    def test_marker_mode_rejects_unconfirmed_dio_route(self):
        for reply in (("+TXMARKER:DIO=16,SOURCE=RAT_GPO0,ACTIVE=HIGH", "OK"),
                      ("+TXMARKER:DIO=17,SOURCE=RAT_GPO0,ACTIVE=HIGH",)):
            self.setUp()
            self.marker_reply = reply
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as temp:
                output, calls, _, send_count, warm_count = self.run_pilot(Path(temp), integration_mode="tx_marker")
                self.assertEqual(json.loads((output / "pairing.json").read_text())["status"], "failed")
                self.assertEqual((calls, send_count, warm_count), ([], 0, 0))

    def test_modeled_mode_accepts_new_firmware_without_querying_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            output, *_ = self.run_pilot(Path(temp), tx_version="0.3.1")
            self.assertEqual(json.loads((output / "pairing.json").read_text())["status"], "valid")
            for radio in self.radios:
                self.assertNotIn("AT+TXMARKER?", [call.args[0] for call in radio.command.call_args_list])

    def test_decode_failure_preserves_other_raw_and_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, send_count, _ = self.run_pilot(Path(temp), decode_error=True)
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(send_count, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(manifest["rows"][0]["tx_status"], "analysis_review_required")
            self.assertEqual(manifest["rows"][0]["rx_status"], "ok")
            self.assertTrue((output / "rx/raw/run_00001.csv.gz").is_file())
            self.assertTrue(all(s.close.called for s in self.samplers))

    def test_source_mode_is_explicit_and_set_before_power_start(self):
        with tempfile.TemporaryDirectory() as temp:
            output, *_ = self.run_pilot(Path(temp), ppk_mode="source")
            self.assertEqual(json.loads((output / "pairing.json").read_text())["ppk_mode"], "source")
            for sampler in self.samplers:
                methods = [call[0] for call in sampler.mock_calls]
                self.assertLess(methods.index("api.set_source_voltage"), methods.index("start_continuous"))
                sampler.api.set_source_voltage.assert_called_once_with(3300)

    def test_truncated_modeled_window_is_rejected_even_with_zero_reported_sample_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, _, _ = self.run_pilot(Path(temp), short_capture=True)
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(len(calls), 1)
            self.assertFalse(analyses)
            self.assertTrue((output / "tx/raw/run_00001.csv.gz").is_file())
            self.assertTrue((output / "rx/raw/run_00001.csv.gz").is_file())

    def test_sample_loss_stops_before_next_measured_transfer(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, _, _ = self.run_pilot(Path(temp), sample_loss=True)
            self.assertEqual(json.loads((output / "pairing.json").read_text())["status"], "failed")
            self.assertEqual(len(calls), 1)
            self.assertFalse(analyses)

    def test_resume_failure_still_persists_both_decoded_raw_records(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, _, _ = self.run_pilot(Path(temp), resume_error=True)
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["failure_context"], {"phase": "inter_capture_hold_resume", "run_id": "run_00001"})
            self.assertEqual(manifest["rows"][0]["status"], "valid", "A hold failure must not erase preceding capture evidence")
            self.assertIn("resume failed", manifest["rows"][0]["hold_resume_error"])
            self.assertEqual(len(calls), 1)
            for role, sampler, radio in zip(("tx", "rx"), self.samplers, self.radios):
                self.assertTrue((output / role / "raw/run_00001.csv.gz").is_file())
                self.assertTrue((output / role / "analysis/run_00001.json").is_file())
                with (output / role / "summary.csv").open(newline="") as stream:
                    self.assertEqual(len(list(csv.DictReader(stream))), 1)
                sampler.api.stop_measuring.assert_called_once()
                sampler.api.ser.flush.assert_called_once()
                sampler.close.assert_called_once_with(keep_power_on=True)
                sampler.power_off.assert_not_called()
                radio.close.assert_called_once()

    def test_both_ppks_remain_stopped_through_raw_analysis_and_persistence(self):
        active = False
        starts = 0
        captures = 0
        stages = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def probe(stage):
                nonlocal active, starts, captures
                stages.append(stage)
                if stage == "hold_start":
                    self.assertFalse(active)
                    if captures:
                        folder = next(root.glob("*_e79_paired_pilot"))
                        manifest = json.loads((folder / "pairing.json").read_text())
                        self.assertEqual(len(manifest["rows"]), captures)
                        self.assertEqual(manifest["rows"][-1]["status"], "valid")
                        for role in ("tx", "rx"):
                            self.assertTrue((folder / role / "analysis" / f"run_{captures:05d}.json").is_file())
                    starts += 1
                    active = True
                elif stage == "capture_started":
                    self.assertTrue(active, "Resume only between captures")
                    captures += 1
                elif stage == "capture_stopped":
                    active = False
                else:
                    self.assertFalse(active, f"Sampling must be stopped during {stage}")
            originals = {name: getattr(runner.ResultWriter, name) for name in ("save_raw", "save_analysis", "add", "write_aggregates")}
            def wrap(name):
                def check(writer, *args, **kwargs):
                    probe(name)
                    return originals[name](writer, *args, **kwargs)
                return check
            save_pairing = runner._save_pairing
            def persist(folder, manifest):
                if manifest["rows"] and manifest["rows"][-1]["status"] != "capturing":
                    probe("pairing_persistence")
                return save_pairing(folder, manifest)
            with (patch.object(runner.ResultWriter, "save_raw", autospec=True, side_effect=wrap("save_raw")),
                  patch.object(runner.ResultWriter, "save_analysis", autospec=True, side_effect=wrap("save_analysis")),
                  patch.object(runner.ResultWriter, "add", autospec=True, side_effect=wrap("add")),
                  patch.object(runner.ResultWriter, "write_aggregates", autospec=True, side_effect=wrap("write_aggregates")),
                  patch.object(runner, "_save_pairing", side_effect=persist)):
                output, calls, _, sends, _ = self.run_pilot(root, integration_mode="radio_markers",
                    marker_totals_only=True, fragmented=True, payload_bytes=1024, sampling_probe=probe)
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual((starts, captures, len(calls), sends), (5, 5, 5, 5))
            self.assertFalse(active, "Last transfer must not restart sampling before final persistence")
            self.assertEqual(stages.count("analysis"), 5)
            self.assertEqual(stages.count("save_raw"), 10)
            self.assertEqual(stages.count("save_analysis"), 10)
            self.assertEqual(manifest["ppk_sampling_policy"], "stopped_during_postprocessing; resumed_between_valid_transfers_only")
            self.assertIn("DUT power remains ON", manifest["ppk_postprocessing_power_policy"])
            for role, sampler in zip(("tx", "rx"), self.samplers):
                metadata = json.loads((output / role / "metadata.json").read_text())
                self.assertEqual(metadata["ppk_sampling_policy"], manifest["ppk_sampling_policy"])
                sampler.power_off.assert_not_called()
                sampler.close.assert_called_once_with(keep_power_on=True)

    def test_writer_close_error_does_not_skip_radio_and_ppk_cleanup(self):
        original_close = runner.ResultWriter.close
        def fail_after_close(writer):
            original_close(writer)
            if writer.output_dir.name == "tx":
                raise OSError("simulated final flush error")
        with tempfile.TemporaryDirectory() as temp, patch.object(runner.ResultWriter, "close", autospec=True, side_effect=fail_after_close):
            output, *_ = self.run_pilot(Path(temp))
            self.assertEqual(json.loads((output / "pairing.json").read_text())["status"], "failed")
            self.assertTrue(all(s.close.called for s in self.samplers))
            self.assertTrue(all(r.close.called for r in self.radios))

    def test_wrong_modem_configuration_fails_before_warmup_or_capture(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "_preflight", side_effect=ValueError("wrong PROFILE")):
            output, calls, _, send_count, warm_count = self.run_pilot(Path(temp))
            self.assertEqual(json.loads((output / "pairing.json").read_text())["status"], "failed")
            self.assertEqual((calls, send_count, warm_count), ([], 0, 0))

    def test_rx_constructor_transport_failure_records_port_phase_and_closes_owned_resources(self):
        import serial
        original_radio_factory = self.radio
        def factory(*args, **kwargs):
            if args[0] == "COM13":
                error = serial.SerialTimeoutException("Write timeout")
                error.add_note("UART initialization on COM13, phase=initial_AT_synchronization")
                raise error
            return original_radio_factory(*args, **kwargs)
        self.radio = factory
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, sends, warms = self.run_pilot(Path(temp), integration_mode="radio_markers")
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["failure_context"],
                             {"phase": "uart_open_and_initial_sync", "role": "rx", "port": "COM13"})
            self.assertIn("SerialTimeoutException: Write timeout", manifest["failure_traceback"])
            self.assertIn("phase=initial_AT_synchronization", manifest["failure_traceback"])
            self.assertEqual((calls, sends, warms), ([], 0, 0))
            self.assertTrue(self.radios[0].close.called)
            self.assertTrue(all(s.close.call_args.kwargs == {"keep_power_on": True} for s in self.samplers))
            self.assertEqual(manifest["rows"], [])

    def test_catalog_batches_apply_requested_condition_to_both_radios_and_all_evidence(self):
        # Exercise every PHY/rate, every allowed size and every allowed power.
        profiles = ["GFSK4K8", "GFSK50", "GFSK200", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50"]
        for index, phy in enumerate(profiles):
            self.setUp()
            size, power = (8, 32, 64)[index % 3], (-20, 0, 13)[index % 3]
            params = {"rf_profile": phy, "tx_power_dbm": power}
            with self.subTest(phy=phy, size=size, power=power), tempfile.TemporaryDirectory() as temp:
                output, calls, analyses, sends, warms = self.run_pilot(
                    Path(temp), integration_mode="radio_markers", real_warmup=True,
                    payload_bytes=size, rf_profile=phy, tx_power_dbm=power,
                )
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "valid", manifest["errors"])
                self.assertEqual((len(calls), sends, warms), (5, 5, 1))
                self.assertFalse(analyses, "Hardware windows must not fall back to modeled analysis")
                self.assertEqual((manifest["payload_bytes"], manifest["rf_profile"], manifest["tx_power_dbm"]),
                                 (size, phy, power))
                self.assertEqual(manifest["expected_rows"], 5)
                self.assertEqual(manifest["max_frame_payload_bytes"], 64)
                validation = validate_result(CommandStep(
                    "batch", "batch", ["--integration-mode", "radio_markers", "--payload-bytes", str(size),
                                       "--rf-profile", phy, "--tx-power-dbm", str(power)], "paired", 5,
                ), output)
                self.assertTrue(validation["valid"], validation)
                self.assertTrue(all(snapshot == self.radio_configuration_at_capture[0]
                                    for snapshot in self.radio_configuration_at_capture))
                self.assertEqual([case.repetition for case in self.sent_cases], [1, 2, 3, 4, 5])
                for role, radio in zip(("tx", "rx"), self.radios):
                    radio.configure_profile_parameters.assert_called_once()
                    profile, observed_params = radio.configure_profile_parameters.call_args.args
                    self.assertEqual(observed_params, params)
                    self.assertEqual(profile.payload_sizes, (size,))
                    metadata = json.loads((output / role / "metadata.json").read_text())
                    self.assertEqual(metadata["test_count"], 5)
                    self.assertEqual(metadata["payload_bytes"], size)
                    cfg = metadata["observed_endpoint"]["modem_preflight"]["config"]
                    self.assertEqual((cfg["PROFILE"], cfg["PWR"]), (phy, str(power)))
                    with (output / role / "summary.csv").open(newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual(len(rows), 5)
                    self.assertTrue(all(json.loads(row["parameters_json"]) == params for row in rows))
                    self.assertTrue(all((row["payload_bytes"], row["max_frame_payload_bytes"], row["frame_count"])
                                        == (str(size), "64", "1") for row in rows))
                    self.assertEqual(len(list((output / role / "raw").glob("*.csv.gz"))), 5)

    def test_nondefault_batch_readback_mismatch_stops_before_warmup(self):
        for field, wrong in (("PROFILE", "GFSK200"), ("RATE", "200000"), ("PWR", "13")):
            self.setUp()
            self.config_overrides["rx"] = {field: wrong}
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                output, captures, _, sends, warms = self.run_pilot(
                    Path(temp), integration_mode="radio_markers", payload_bytes=64,
                    rf_profile="SLR2K5", tx_power_dbm=-20,
                )
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "failed")
                self.assertIn("rx: actual modem configuration does not match the requested batch", manifest["errors"][0])
                self.assertEqual((captures, sends, warms), ([], 0, 0))
                self.assertFalse(list(output.rglob("*.csv.gz")))

    def test_filter_replay_policy_survives_acquisition_and_ui_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, captures, _, sends, _ = self.run_pilot(
                Path(temporary), integration_mode="radio_markers", marker_totals_only=True,
                filter_aware_totals=True, interface_label="ESP32",
            )
            manifest = json.loads((result / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual((len(captures), sends), (5, 5))
            self.assertIs(manifest["filter_aware_totals"], True)
            self.assertEqual(manifest["energy_policy"], FILTER_TOTAL_ONLY_ENERGY_POLICY)
            self.assertEqual(manifest["marker_contract"]["energy_policy"], FILTER_TOTAL_ONLY_ENERGY_POLICY)
            for role in ("tx", "rx"):
                metadata = json.loads((result / role / "metadata.json").read_text())
                self.assertEqual(metadata["energy_policy"], FILTER_TOTAL_ONLY_ENERGY_POLICY)
                with (result / role / "summary.csv").open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 5)
                self.assertEqual({row["integration_method"] for row in rows}, {FILTER_RADIO_TOTALS_INTEGRATION_METHOD})
                for pair in manifest["rows"]:
                    proof = pair["marker_diagnostics"]["roles"][role]["total_qa"]
                    self.assertEqual(proof["method"], "bounded_filter_replay_marker_total")
                    self.assertTrue(proof["valid"], proof["reasons"])
            step = CommandStep("paired_pilot", "pilot", ["--integration-mode", "radio_markers",
                               "--marker-totals-only", "--filter-aware-totals"], "paired", 5)
            acceptance = validate_result(step, result)
            self.assertTrue(acceptance["valid"], acceptance)

    def test_energy_history_v2_policy_survives_saved_data_and_ui_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, captures, _, sends, _ = self.run_pilot(
                Path(temporary), integration_mode="radio_markers", marker_totals_only=True,
                filter_aware_totals=True, filter_history_policy="energy_relative_v2", interface_label="ESP32",
            )
            manifest = json.loads((result / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual((len(captures), sends), (5, 5))
            self.assertEqual(manifest["energy_policy"], ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY)
            self.assertEqual(manifest["filter_history_policy"], "energy_relative_v2")
            for role in ("tx", "rx"):
                metadata = json.loads((result / role / "metadata.json").read_text())
                self.assertEqual(metadata["energy_policy"], ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY)
                with (result / role / "summary.csv").open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual({row["integration_method"] for row in rows}, {ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD})
                for pair in manifest["rows"]:
                    proof = pair["marker_diagnostics"]["roles"][role]["total_qa"]
                    self.assertEqual(proof["schema_version"], 2)
                    self.assertEqual(proof["energy_history_relative_tolerance"], 1e-4)
                    self.assertTrue(proof["energy_history_budget_valid"])
            step = CommandStep("paired_pilot", "pilot", ["--integration-mode", "radio_markers",
                               "--marker-totals-only", "--filter-aware-totals",
                               "--filter-history-policy", "energy_relative_v2"], "paired", 5)
            acceptance = validate_result(step, result)
            self.assertTrue(acceptance["valid"], acceptance)

    def test_filter_replay_policy_still_stops_at_first_local_counter_fault(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, captures, _, sends, _ = self.run_pilot(
                Path(temporary), integration_mode="radio_markers", marker_totals_only=True,
                filter_aware_totals=True, marker_counter_faults={"rx": 1350},
            )
            manifest = json.loads((result / "pairing.json").read_text())
            self.assertNotEqual(manifest["status"], "valid")
            self.assertEqual((len(captures), sends), (1, 1))
            proof = manifest["rows"][0]["marker_diagnostics"]["roles"]["rx"]["total_qa"]
            self.assertFalse(proof["valid"])
            self.assertEqual(proof["counter_anomaly_indices_guard"], [1350, 1351])
            self.assertIsNone(proof["energy_total_uJ"])

    def test_filter_replay_requires_delivery_and_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, captures, _, sends, _ = self.run_pilot(
                Path(temporary), integration_mode="radio_markers", marker_totals_only=True,
                filter_aware_totals=True, received=False,
            )
            manifest = json.loads((result / "pairing.json").read_text())
            self.assertNotEqual(manifest["status"], "valid")
            self.assertEqual((len(captures), sends), (1, 1))
            self.assertFalse(manifest["rows"][0]["packet_received"])
            self.assertIn("confirmed packet delivery", " ".join(manifest["rows"][0]["marker_diagnostics"]["reasons"]))

    def test_invalid_or_fragmented_batch_rejected_before_any_hardware_or_result_directory(self):
        invalid = [
            {"payload_bytes": 128}, {"payload_bytes": 512}, {"payload_bytes": 1024},
            {"payload_bytes": 16}, {"payload_bytes": True}, {"payload_bytes": 32.0},
            {"rf_profile": "unknown"}, {"rf_profile": "gfsk200"},
            {"tx_power_dbm": 1}, {"tx_power_dbm": True}, {"tx_power_dbm": 13.0},
            {"repetitions": 4},
            {"marker_totals_only": True},
            {"marker_totals_only": True, "integration_mode": "tx_marker"},
            {"marker_totals_only": "false", "integration_mode": "radio_markers"},
            {"filter_aware_totals": True},
            {"filter_aware_totals": True, "integration_mode": "radio_markers"},
            {"filter_aware_totals": "false", "integration_mode": "radio_markers", "marker_totals_only": True},
            {"filter_aware_totals": True, "integration_mode": "radio_markers", "marker_totals_only": True,
             "fragmented": True, "payload_bytes": 128},
            {"filter_history_policy": "energy_relative_v2"},
            {"filter_history_policy": "unknown", "filter_aware_totals": True,
             "integration_mode": "radio_markers", "marker_totals_only": True},
        ]
        for overrides in invalid:
            with (
                self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temp,
                patch.object(runner, "_usb_metadata") as usb,
                patch.object(runner, "Ppk2Sampler") as sampler,
                patch.object(runner, "SerialRadio") as radio,
            ):
                with self.assertRaises(ValueError):
                    runner.run_paired_pilot(
                        tx_radio_port="COM12", rx_radio_port="COM13", tx_ppk_port="COM10", rx_ppk_port="COM11",
                        tx_voltage_mv=3300, rx_voltage_mv=3300, output_root=Path(temp),
                        tx_identity="physical A", rx_identity="physical B", voltage_confirmed=True,
                        voltage_provenance="Operator measured external VIN", **overrides,
                    )
                usb.assert_not_called()
                sampler.assert_not_called()
                radio.assert_not_called()
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_cli_passes_single_condition_without_changing_default_pilot(self):
        required = ["--tx-radio-port", "COM12", "--rx-radio-port", "COM13", "--tx-ppk-port", "COM10",
                    "--rx-ppk-port", "COM11", "--tx-identity", "A", "--rx-identity", "B",
                    "--voltage-provenance", "Confirmed", "--tx-voltage-mv", "3300", "--rx-voltage-mv", "3300",
                    "--voltage-confirmed"]
        for extra, expected in (([], (32, "GFSK200", 13)),
                                (["--payload-bytes", "64", "--rf-profile", "SLR2K5", "--tx-power-dbm", "-20"],
                                 (64, "SLR2K5", -20))):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "pairing.json").write_text('{"status":"valid"}')
                with patch.object(runner, "run_paired_pilot", return_value=root) as run:
                    self.assertEqual(runner.main(required + ["--output", temp] + extra), 0)
                kwargs = run.call_args.kwargs
                self.assertEqual(tuple(kwargs[key] for key in ("payload_bytes", "rf_profile", "tx_power_dbm")), expected)
                self.assertEqual(kwargs["repetitions"], 5)

    def test_total_only_marker_batch_proves_totals_without_baseline_or_excess_and_passes_ui_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, analyses, sends, warms = self.run_pilot(
                Path(temp), integration_mode="radio_markers", marker_totals_only=True,
                marker_counter_faults={"tx": 400}, payload_bytes=64, rf_profile="SLR2K5", tx_power_dbm=-20,
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "valid", manifest["errors"])
            self.assertEqual((len(calls), sends, warms), (5, 5, 1))
            self.assertFalse(analyses)
            self.assertIs(manifest["marker_totals_only"], True)
            self.assertEqual(manifest["energy_policy"], TOTAL_ONLY_ENERGY_POLICY)
            self.assertTrue(manifest["warnings"])
            for pair in manifest["rows"]:
                diagnostic = pair["marker_diagnostics"]
                self.assertEqual(diagnostic["energy_policy"], TOTAL_ONLY_ENERGY_POLICY)
                self.assertEqual(diagnostic["roles"]["tx"]["counter_qa"]["status"], "review_required")
                self.assertTrue(all(diagnostic["roles"][role]["total_qa"]["valid"] for role in ("tx", "rx")))
            for role in ("tx", "rx"):
                with (output / role / "summary.csv").open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 5)
                for row in rows:
                    self.assertEqual(row["integration_method"], RADIO_TOTALS_INTEGRATION_METHOD)
                    for field in ("baseline_median_uA", "threshold_uA", "charge_excess_uC", "energy_excess_uJ"):
                        self.assertEqual(row[field], "")
                    self.assertAlmostEqual(float(row["energy_total_uJ"]), 116.16 if role == "tx" else 92.4)
                analysis = json.loads((output / role / "analysis/run_00001.json").read_text())
                self.assertEqual(analysis["diagnostics"]["energy_policy"], TOTAL_ONLY_ENERGY_POLICY)
            validation = validate_result(CommandStep(
                "totals", "totals", ["--integration-mode", "radio_markers", "--marker-totals-only",
                                     "--payload-bytes", "64", "--rf-profile", "SLR2K5", "--tx-power-dbm", "-20"], "paired", 5,
            ), output)
            self.assertTrue(validation["valid"], validation)

    def test_total_only_marker_proof_failure_retains_both_raw_and_stops_without_retry(self):
        for fault in (("tx", 1250, 1), ("rx", 1300, 1 << 14), ("tx", 1376, 1 << 17),
                      ("tx", 1197, 1 << 18)):
            self.setUp()
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                output, calls, analyses, sends, _ = self.run_pilot(
                    Path(temp), integration_mode="radio_markers", marker_totals_only=True, total_word_fault=fault,
                )
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "failed")
                self.assertEqual((len(calls), sends), (1, 1))
                self.assertFalse(analyses)
                self.assertFalse(manifest["rows"][0]["marker_diagnostics"]["roles"][fault[0]]["total_qa"]["valid"])
                for role in ("tx", "rx"):
                    self.assertTrue((output / role / "raw/run_00001.csv.gz").is_file())
                    with (output / role / "summary.csv").open(newline="") as stream:
                        row = next(csv.DictReader(stream))
                    self.assertEqual(row["status"], "analysis_review_required")
                    self.assertEqual(row["energy_total_uJ"], "")
                    self.assertEqual(row["integration_method"], RADIO_TOTALS_INTEGRATION_METHOD)

    def test_unconfirmed_voltage_opens_no_hardware(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, "Ppk2Sampler") as sampler:
            with self.assertRaisesRegex(ValueError, "Confirm"):
                runner.run_paired_pilot(tx_radio_port="COM12", rx_radio_port="COM13", tx_ppk_port="COM10",
                                        rx_ppk_port="COM11", tx_voltage_mv=3300, rx_voltage_mv=3300,
                                        output_root=Path(temp))
            sampler.assert_not_called()

    def test_fragmented_batch_records_all_frames_and_passes_ui_acceptance(self):
        for size in (128, 512, 1024):
            self.setUp()
            with self.subTest(size=size), tempfile.TemporaryDirectory() as temp:
                output, calls, analyses, sends, warms = self.run_pilot(
                    Path(temp), integration_mode="radio_markers", marker_totals_only=True,
                    fragmented=True, payload_bytes=size, rf_profile="SLR2K5",
                )
                manifest = json.loads((output / "pairing.json").read_text())
                self.assertEqual(manifest["status"], "valid", manifest["errors"])
                self.assertEqual((len(calls), sends, warms), (5, 5, 1))
                self.assertFalse(analyses)
                self.assertIs(manifest["fragmented"], True)
                self.assertEqual(manifest["frame_count"], size // 64)
                self.assertEqual(manifest["integration_method"], FRAGMENT_TOTALS_INTEGRATION_METHOD)
                for pair in manifest["rows"]:
                    self.assertEqual(pair["frame_payload_bytes"], [64] * (size // 64))
                    for role in ("tx", "rx"):
                        evidence = pair["marker_diagnostics"]["roles"][role]
                        self.assertEqual(len(evidence["frame_proofs"]), size // 64)
                        self.assertTrue(all(proof["valid"] for proof in evidence["frame_proofs"]))
                validation = validate_result(CommandStep(
                    "fragments", "fragments", ["--integration-mode", "radio_markers", "--marker-totals-only",
                       "--fragmented", "--payload-bytes", str(size), "--rf-profile", "SLR2K5", "--tx-power-dbm", "13"],
                    "paired", 5,
                ), output)
                self.assertTrue(validation["valid"], validation)

    def test_fragmented_missing_delivery_stops_after_first_measured_transfer(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, sends, _ = self.run_pilot(
                Path(temp), integration_mode="radio_markers", marker_totals_only=True,
                fragmented=True, payload_bytes=128, received=False,
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual((len(calls), sends), (1, 1))
            self.assertEqual(manifest["rows"][0]["rx_status"], "rx_missing")
            for role in ("tx", "rx"):
                self.assertTrue((output / role / "raw/run_00001.csv.gz").is_file())

    def test_fragmented_bad_later_frame_retains_raw_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            output, calls, _, sends, _ = self.run_pilot(
                Path(temp), integration_mode="radio_markers", marker_totals_only=True,
                fragmented=True, payload_bytes=1024, total_word_fault=("rx", 4000, 1 << 17),
            )
            manifest = json.loads((output / "pairing.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual((len(calls), sends), (1, 1))
            for role in ("tx", "rx"):
                self.assertTrue((output / role / "raw/run_00001.csv.gz").is_file())
                with (output / role / "summary.csv").open(newline="") as stream:
                    row = next(csv.DictReader(stream))
                self.assertEqual(row["status"], "analysis_review_required")
                self.assertEqual(row["energy_total_uJ"], "")

    def test_fragmented_invalid_mode_matrix_or_flag_opens_no_hardware(self):
        for overrides in ({"payload_bytes": 64}, {"tx_power_dbm": 0},
                          {"integration_mode": "modeled"}, {"marker_totals_only": False},
                          {"fragmented": "true"}):
            options = dict(payload_bytes=128, fragmented=True, integration_mode="radio_markers",
                           marker_totals_only=True)
            options.update(overrides)
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temp, \
                    patch.object(runner, "Ppk2Sampler") as sampler, patch.object(runner, "_usb_metadata") as usb:
                with self.assertRaises(ValueError):
                    runner.run_paired_pilot(
                        tx_radio_port="COM12", rx_radio_port="COM13", tx_ppk_port="COM10", rx_ppk_port="COM11",
                        tx_voltage_mv=3300, rx_voltage_mv=3300, output_root=Path(temp),
                        tx_identity="A", rx_identity="B", voltage_confirmed=True,
                        voltage_provenance="Operator confirmed external VIN", **options,
                    )
                sampler.assert_not_called()
                usb.assert_not_called()
                self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
