import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from unittest.mock import call, patch

from radio_power_profiler.web_app import (
    AppHandler,
    AppServer,
    CommandStep,
    HTML,
    JobManager,
    PowerPathConfig,
    WebConfig,
    build_campaign_steps,
    build_continuous_rx_steps,
    build_quick_steps,
    run_web_server,
    validate_result,
)


class WebAppTests(unittest.TestCase):
    def test_retired_e79_controls_and_routes_are_removed_without_hardware_access(self):
        self.assertNotIn('E79 paired 32 B', HTML)
        html_ids = set(re.findall(r'id="([^"]+)"', HTML))
        js_ids = set(re.findall(r"\$\('([^']+)'\)", HTML))
        self.assertFalse(js_ids - html_ids, f'Dangling DOM references: {js_ids - html_ids}')
        self.assertIn('referenceCampaign', html_ids)
        self.assertIn('enablePowerPaths', html_ids)
        self.assertIn('campaign', html_ids)
        retired_routes = ('paired-pilot', 'paired-campaign', 'paired-32b-campaign',
                          'paired-fragmented-campaign', 'paired-campaign/resume', 'paired-guard/enable')
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            handler = AppHandler.__new__(AppHandler)
            handler.server = types.SimpleNamespace(manager=manager)
            with (patch.object(handler, '_json') as response, patch.object(manager, 'start') as start,
                  patch('radio_power_profiler.ppk.Ppk2Sampler') as sampler):
                for route in retired_routes:
                    handler.path = '/api/' + route
                    handler.do_POST()
                    response.assert_called_with({'error': 'Not found'}, 404)
                start.assert_not_called()
                sampler.assert_not_called()
            for kind in ('paired_pilot', 'paired_campaign', 'paired_32b_campaign', 'paired_fragmented_campaign'):
                with self.assertRaisesRegex(ValueError, 'Unknown job type'):
                    manager.start(kind, WebConfig())
            self.assertFalse(list(Path(temporary).iterdir()))

    @staticmethod
    def paired_payload():
        return {
            "tx_radio_port": "COM12", "rx_radio_port": "COM13",
            "tx_ppk_port": "COM10", "rx_ppk_port": "COM11",
            "tx_voltage_mv": 3300, "rx_voltage_mv": 3300,
            "tx_identity": "TX fixture / serial TX", "rx_identity": "RX fixture / serial RX",
            "interface_label": "CH340", "ppk_mode": "ampere",
            "voltage_confirmed": True,
            "voltage_provenance": "User confirmed external 3.3 V at both VIN inputs",
        }

    @staticmethod
    def write_paired_result(root, *, missing_packet=False, integration_mode="modeled", condition=None,
                            marker_totals_only=False, baseline_fault=False):
        root.mkdir(parents=True, exist_ok=True)
        rows = []
        for index in range(1, 6):
            run_id = f"run_{index:05d}"
            status = "rx_missing" if missing_packet and index == 2 else "ok"
            rows.append({"run_id": run_id, "paired_transfer_id": f"pilot:{run_id}",
                         "status": "valid", "tx_status": status, "rx_status": status,
                         "tx_raw": f"tx/raw/{run_id}.csv.gz", "rx_raw": f"rx/raw/{run_id}.csv.gz"})
            if integration_mode in {"tx_marker", "radio_markers"}:
                rows[-1]["timing"] = {"devices": {role: {"trigger_index": 20000} for role in ("tx", "rx")}}
                rows[-1]["marker_diagnostics"] = {
                    "valid": True, "marker_bit": 0,
                    "source": "TX DIO17 / RAT_GPO0 / active HIGH",
                    "width_tolerance_samples": 2, "reasons": [],
                    "roles": {
                        "tx": {"window_samples": [25000, 25176], "duration_samples": 176, "pulse_count": 1},
                        "rx": {"window_samples": [24910, 25086], "duration_samples": 176, "pulse_count": 1},
                    },
                }
                for evidence in rows[-1]["marker_diagnostics"]["roles"].values():
                    evidence["counter_qa"] = {"status": "passed_relevant_intervals", "relevant_anomaly_count": 0}
                if integration_mode == "radio_markers":
                    evidence = rows[-1]["marker_diagnostics"]
                    evidence.update(source="Local TX and RX DIO17 / active HIGH", width_tolerance_samples=None,
                                    width_comparison="not_applicable_independent_radio_intervals")
                    evidence["roles"]["tx"]["source"] = "TX DIO17 / RAT_GPO0 / active HIGH"
                    evidence["roles"]["rx"].update(source="RX DIO17 / RAT_GPO1 / active HIGH",
                                                  window_samples=[24910, 25054], duration_samples=144)
                    if marker_totals_only:
                        evidence.update(energy_policy="total_only_with_direct_adc_proof", warnings=[])
                        for role, detail in evidence["roles"].items():
                            start, stop = detail["window_samples"]
                            charge = (stop - start) * 2000.0 / 100_000
                            detail["total_qa"] = {
                                "valid": True, "reasons": [], "warnings": [],
                                "method": "direct_adc_constant_range_marker_total", "guard_qa_includes_stop": True,
                                "window_samples": [start, stop], "guard_window_samples": [start - 3, stop],
                                "range_code": 3, "constant_range_guard": True,
                                "counter_anomaly_indices_guard": [], "invalid_range_indices_guard": [],
                                "bit17_indices_guard": [], "nonfinite_current_indices_guard": [],
                                "outside_counter_anomaly_count": 2 if baseline_fault and role == "tx" else 0,
                                "wire_sample_count": 100_000, "captured_sample_count": 100_000,
                                "sample_rate_hz": 100_000, "voltage_mv": 3300, "wire_logic_match_full_capture": True,
                                "marker_window_complete": True, "calibration_valid": True,
                                "direct_adc_tolerance_uA": 1e-6, "direct_adc_max_difference_uA": 0.0,
                                "direct_adc_compared_samples": stop - start, "direct_adc_match": True,
                                "charge_total_uC": charge, "energy_total_uJ": charge * 3.3,
                            }
                        if baseline_fault:
                            evidence["roles"]["tx"]["counter_qa"].update(status="review_required", relevant_anomaly_count=2)
                            evidence["warnings"].append("tx: original baseline counter QA requires review; only direct ADC totals are available")
        for role in ("tx", "rx"):
            (root / role).mkdir()
            (root / role / "raw").mkdir()
            for row in rows:
                (root / row[f"{role}_raw"]).write_bytes(b"synthetic RAW placeholder; CRC checked separately")
            with (root / role / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
                fields = ["run_id", "status", "analysis_error", "sample_loss_percent", "captured_samples"]
                extra = {}
                if integration_mode in {"tx_marker", "radio_markers"}:
                    extra = {"integration_method": "common_tx_hardware_marker", "event_duration_ms": 1.76,
                             "integration_windows_ms": json.dumps([[50, 51.76]] if role == "tx" else [[49.1, 50.86]])}
                    if integration_mode == "radio_markers":
                        extra["integration_method"] = "independent_radio_hardware_markers"
                        if role == "rx":
                            extra.update(event_duration_ms=1.44, integration_windows_ms=json.dumps([[49.1, 50.54]]))
                    fields.extend(extra)
                if marker_totals_only:
                    charge = rows[0]["marker_diagnostics"]["roles"][role]["total_qa"]["charge_total_uC"]
                    extra["integration_method"] = "independent_radio_hardware_marker_totals"
                    totals = {"baseline_median_uA": "", "threshold_uA": "", "charge_excess_uC": "", "energy_excess_uJ": "",
                              "charge_total_uC": charge, "energy_total_uJ": charge * 3.3,
                              "tx_mean_uA": 2000.0, "tx_peak_uA": 2000.0, "voltage_mv": 3300}
                    extra.update(totals)
                    fields.extend(totals)
                if condition is not None:
                    extra.update(payload_bytes=condition["payload_bytes"], parameters_json=json.dumps({
                        "rf_profile": condition["rf_profile"], "tx_power_dbm": condition["tx_power_dbm"],
                    }))
                    fields.extend(("payload_bytes", "parameters_json"))
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows({"run_id": row["run_id"], "status": row[f"{role}_status"],
                                  "analysis_error": "", "sample_loss_percent": 0,
                                  "captured_samples": 100_000, **extra} for row in rows)
        manifest = {"status": "valid", "session_id": "pilot", "rows": rows,
                    "voltage_confirmed": True, "voltage_provenance": "User confirmed 3.3 V"}
        if integration_mode in {"tx_marker", "radio_markers"}:
            manifest.update(integration_mode=integration_mode, sample_rate_hz=100_000)
        if integration_mode == "radio_markers":
            manifest.update(rx_arming_policy="continuous_across_warmup_and_five_transfers",
                            rx_rearm_between_transfers=False, endpoints={})
            for role, signal in (("tx", "RAT_GPO0"), ("rx", "RAT_GPO1")):
                manifest["endpoints"][role] = {"modem_preflight": {
                    "firmware_version": "0.3.2",
                    "radio_marker": {"role": role.upper(), "dio": 17, "source": signal,
                                     "active": "HIGH", "ppk_input": "D0"},
                    "marker_set_command": f"AT+MARKER={role.upper()}", "marker_set_reply": ["OK"],
                    "marker_reply": [f"+MARKER:ROLE={role.upper()},DIO=17,SOURCE={signal},ACTIVE=HIGH", "OK"],
                }}
        if condition is not None:
            manifest.update(condition)
            for role in ("tx", "rx"):
                manifest["endpoints"][role]["modem_preflight"]["config"] = {
                    "PROFILE": condition["rf_profile"], "PWR": str(condition["tx_power_dbm"]),
                }
        if marker_totals_only:
            manifest.update(marker_totals_only=True, energy_policy="total_only_with_direct_adc_proof")
        (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest


    @staticmethod
    def add_filter_proofs(root, manifest, history_policy="current_equivalence_v1"):
        policy = "total_only_with_bounded_filter_replay_proof"
        method = "independent_radio_hardware_filter_marker_totals"
        if history_policy == "energy_relative_v2":
            policy = "total_only_with_bounded_filter_energy_proof_v2"
            method = "independent_radio_hardware_filter_energy_totals_v2"
            manifest["filter_history_policy"] = history_policy
        manifest.update(filter_aware_totals=True, energy_policy=policy, expected_rows=5)
        for transfer in manifest["rows"]:
            transfer["packet_received"] = transfer["rx_status"] == "ok"
            evidence = transfer["marker_diagnostics"]
            evidence["energy_policy"] = policy
            for detail in evidence["roles"].values():
                old = detail["total_qa"]
                start, stop = detail["window_samples"]
                proof = {k: v for k, v in old.items() if not k.startswith("direct_adc_")}
                proof.update(schema_version=1, method="bounded_filter_replay_marker_total",
                             constant_range_guard=False, range_code=None,
                             range_counts_guard={"3": stop - start + 2, "4": 1},
                             wire_sha256="a" * 64, calibration_sha256="b" * 64,
                             wire_logic_mismatch_count=0, outside_invalid_range_count=0, outside_bit17_count=0,
                             filter_parameters={"alpha": 0.18, "alpha5": 0.06, "samples": 3},
                             filter_tolerance_uA=1e-6, filter_replay_match=True,
                             filter_replay_compared_samples=100_000, filter_replay_max_difference_uA=2e-9,
                             filter_replay_nonfinite_indices=[], global_adc_domain_values=81920,
                             global_adc_bounds_A=[-0.1, 1.0], global_state_bounds_A=[-0.1, 1.0],
                             global_state_invariant=True, history_bound_valid=True,
                             history_interval_max_width_uA=3e-9, combined_error_bound_uA=5e-9,
                             history_clean_suffix_start=100, history_last_suspect_index=99,
                             history_state_converged_samples={"fast": None, "slow": None})
                for quantity, unit in (("charge", "uC"), ("energy", "uJ")):
                    nominal = proof[f"{quantity}_total_{unit}"]
                    proof[f"{quantity}_interval_{unit}"] = [nominal, nominal]
                    proof[f"{quantity}_interval_width_{unit}"] = 0.0
                if history_policy == "energy_relative_v2":
                    proof.update(schema_version=2, history_policy=history_policy,
                                 history_interval_max_width_uA=100.0,
                                 combined_error_bound_uA=100.0 + proof["filter_replay_max_difference_uA"],
                                 energy_history_relative_tolerance=1e-4,
                                 energy_history_relative_bound=0.0, energy_history_budget_valid=True)
                detail["total_qa"] = proof
        for role in ("tx", "rx"):
            path = root / role / "summary.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                row["integration_method"] = method
                row["packet_received"] = str(row["status"] == "ok")
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0])
                writer.writeheader()
                writer.writerows(rows)
        (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_filter_file_replay_rejects_forged_bounds_and_changed_saved_sources(self):
        import struct
        from radio_power_profiler.filter_marker_totals import prove_filter_marker_total
        from radio_power_profiler.ppk import Capture
        from radio_power_profiler.results import save_raw_capture
        from radio_power_profiler.paired_validation import _revalidate_filter_marker_files, _validate_filter_marker_total_proof

        count, start, stop, trigger = 300, 200, 230, 100
        current = (1000 * 4) * ((1.8 / 163840) / 10) * 1e6
        bits = [int(start <= i < stop) for i in range(count)]
        words = [(1000 | 3 << 14 | (i % 64) << 18 | bits[i] << 24) for i in range(count)]
        calibration = {name: {str(i): value for i in range(5)} for name, value in
                       (("R", 10.0), ("O", 0.0), ("GS", 0.0), ("GI", 1.0),
                        ("S", 0.0), ("I", 0.0), ("UG", 1.0))}
        capture = Capture([current] * count, bits, trigger, count / 100_000, count)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wire = root / "wire" / "run_00001" / "tx.ppk2.bin"
            wire.parent.mkdir(parents=True)
            original_wire = struct.pack(f"<{count}I", *words)
            wire.write_bytes(original_wire)
            raw = root / "tx" / "raw" / "run_00001.csv.gz"
            save_raw_capture(raw, capture)
            proof = prove_filter_marker_total(capture, wire, (start, stop), calibration, 3300)
            self.assertTrue(proof["valid"], proof["reasons"])
            detail = {"window_samples": [start, stop], "total_qa": proof}
            transfer = {"run_id": "run_00001", "wire_paths": {"tx": "wire/run_00001/tx.ppk2.bin"},
                        "timing": {"devices": {"tx": {"trigger_index": trigger}}}}
            pairing = {"endpoints": {"tx": {"ppk_calibration_metadata": calibration, "voltage_mv": 3300}}}
            _revalidate_filter_marker_files(root, pairing, transfer, "tx", detail, count)
            for mutation in ("bounds", "interval", "wire", "raw_current", "raw_logic", "calibration", "path"):
                with self.subTest(mutation=mutation):
                    changed = json.loads(json.dumps(detail))
                    changed_pairing = json.loads(json.dumps(pairing))
                    changed_transfer = json.loads(json.dumps(transfer))
                    wire.write_bytes(original_wire)
                    save_raw_capture(raw, capture)
                    if mutation == "bounds":
                        changed["total_qa"].update(global_adc_bounds_A=[0.0, 1.0], global_state_bounds_A=[0.0, 1.0])
                    elif mutation == "interval":
                        forged = changed["total_qa"]
                        q = forged["charge_total_uC"]
                        forged["charge_interval_uC"] = [q - 1e-9, q + 1e-9]
                        forged["energy_interval_uJ"] = [
                            math.nextafter((q - 1e-9) * 3.3, -math.inf),
                            math.nextafter((q + 1e-9) * 3.3, math.inf)]
                        for quantity, unit in (("charge", "uC"), ("energy", "uJ")):
                            lo, hi = forged[f"{quantity}_interval_{unit}"]
                            forged[f"{quantity}_interval_width_{unit}"] = math.nextafter(hi - lo, math.inf)
                        row = {key: "" for key in ("baseline_median_uA", "threshold_uA",
                                                    "charge_excess_uC", "energy_excess_uJ")}
                        row.update(voltage_mv=3300, charge_total_uC=q, energy_total_uJ=forged["energy_total_uJ"],
                                   tx_mean_uA=q * 100_000 / (stop - start), tx_peak_uA=current)
                        # Coherent endpoint/width algebra cannot establish that
                        # these bounds came from the saved samples. Replay must.
                        _validate_filter_marker_total_proof(changed, row, start, stop, count)
                        with self.assertRaisesRegex(ValueError, "differs from replay"):
                            _revalidate_filter_marker_files(root, changed_pairing, changed_transfer, "tx", changed, count)
                        continue
                    elif mutation == "wire":
                        corrupted = list(words);corrupted[5] ^= 1
                        wire.write_bytes(struct.pack(f"<{count}I", *corrupted))
                    elif mutation == "raw_current":
                        currents = list(capture.samples_uA);currents[5] += 1.0
                        save_raw_capture(raw, Capture(currents, bits, trigger, .003, count))
                    elif mutation == "raw_logic":
                        extra_pulse = list(bits);extra_pulse[150] = 1
                        save_raw_capture(raw, Capture(capture.samples_uA, extra_pulse, trigger, .003, count))
                    elif mutation == "calibration":
                        changed_pairing["endpoints"]["tx"]["ppk_calibration_metadata"]["R"]["3"] = 11.0
                    else:
                        changed_transfer["wire_paths"]["tx"] = "../foreign.ppk2.bin"
                    with self.assertRaises(ValueError):
                        _revalidate_filter_marker_files(root, changed_pairing, changed_transfer, "tx", changed, count)

    def test_filter_interval_outward_rounding_accepts_large_total_but_rejects_forged_width(self):
        from radio_power_profiler.paired_validation import _validate_filter_marker_total_proof

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.add_filter_proofs(root, self.write_paired_result(
                root, integration_mode="radio_markers", marker_totals_only=True), "energy_relative_v2")
            detail = manifest["rows"][0]["marker_diagnostics"]["roles"]["tx"]
            proof = detail["total_qa"]
            with (root / "tx" / "summary.csv").open(newline="", encoding="utf-8") as stream:
                row = next(csv.DictReader(stream))
            start, stop = 25281, 32581
            # Recorded GFSK4K8-scale total: energy endpoints each gain an outward
            # ULP, so scaling the separately rounded charge width is not exact.
            charge = 741.9900202727614
            charge_bounds = [741.9900202727612, 741.9900202727617]
            energy_bounds = [math.nextafter(charge_bounds[0] * 3.3, -math.inf),
                             math.nextafter(charge_bounds[1] * 3.3, math.inf)]
            charge_width = math.nextafter(charge_bounds[1] - charge_bounds[0], math.inf)
            energy_width = math.nextafter(energy_bounds[1] - energy_bounds[0], math.inf)
            self.assertGreater(abs(energy_width - charge_width * 3.3), 1e-12)
            proof.update(window_samples=[start, stop], guard_window_samples=[start - 3, stop],
                         range_counts_guard={"3": stop - start + 3},
                         history_interval_max_width_uA=0.0, filter_replay_max_difference_uA=0.0,
                         combined_error_bound_uA=0.0, charge_total_uC=charge, energy_total_uJ=charge * 3.3,
                         charge_interval_uC=charge_bounds, energy_interval_uJ=energy_bounds,
                         charge_interval_width_uC=charge_width, energy_interval_width_uJ=energy_width,
                         energy_history_relative_bound=math.nextafter(energy_width / energy_bounds[0], math.inf))
            row.update(charge_total_uC=str(charge), energy_total_uJ=str(charge * 3.3),
                       tx_mean_uA=str(charge * 100_000 / (stop - start)))
            _validate_filter_marker_total_proof(detail, row, start, stop, 100_000, "energy_relative_v2")
            for key in ("charge_interval_width_uC", "energy_interval_width_uJ"):
                for forged in (0.0, 1e-4):
                    with self.subTest(field=key, forged=forged):
                        original = proof[key]
                        proof[key] = forged
                        with self.assertRaisesRegex(ValueError, "bounded interval is inconsistent"):
                            _validate_filter_marker_total_proof(
                                detail, row, start, stop, 100_000, "energy_relative_v2")
                        proof[key] = original

    def test_filter_total_interval_includes_rounding_with_zero_history_uncertainty(self):
        from radio_power_profiler.filter_marker_totals import _total_interval
        from radio_power_profiler.paired_validation import _validate_filter_marker_total_proof

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.add_filter_proofs(root, self.write_paired_result(
                root, integration_mode="radio_markers", marker_totals_only=True), "energy_relative_v2")
            detail = manifest["rows"][0]["marker_diagnostics"]["roles"]["tx"]
            proof = detail["total_qa"]
            with (root / "tx" / "summary.csv").open(newline="", encoding="utf-8") as stream:
                row = next(csv.DictReader(stream))
            start, stop = 25000, 65000
            charge, energy = _total_interval([(10000.0, 10000.0)] * (stop - start), 100_000, 3.3)
            charge_width = math.nextafter(charge[1] - charge[0], math.inf)
            energy_width = math.nextafter(energy[1] - energy[0], math.inf)
            self.assertGreater(charge_width, 1e-12)
            proof.update(window_samples=[start, stop], guard_window_samples=[start - 3, stop],
                         range_counts_guard={"3": stop - start + 3},
                         history_interval_max_width_uA=0.0, filter_replay_max_difference_uA=0.0,
                         combined_error_bound_uA=0.0, charge_total_uC=4000.0, energy_total_uJ=13200.0,
                         charge_interval_uC=charge, energy_interval_uJ=energy,
                         charge_interval_width_uC=charge_width, energy_interval_width_uJ=energy_width,
                         energy_history_relative_bound=math.nextafter(energy_width / energy[0], math.inf))
            row.update(charge_total_uC="4000.0", energy_total_uJ="13200.0", tx_mean_uA="10000.0")
            _validate_filter_marker_total_proof(detail, row, start, stop, 100_000, "energy_relative_v2")


    def test_legacy_campaign_still_continues_after_failed_batch(self):
        steps = [CommandStep("first", "First", [], "packet", 1),
                 CommandStep("second", "Second", [], "packet", 1)]
        config = WebConfig(measured_port="COM12", peer_port="COM13", ppk_port="COM10", notify_codex=False)
        def run_step(step, _config):
            step.status = "failed" if step.step_id == "first" else "completed"
            return step.status == "completed"
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            with (patch("radio_power_profiler.web_app.build_campaign_steps", return_value=steps),
                  patch.object(manager, "_run_step", side_effect=run_step) as run,
                  patch.object(manager, "_ensure_current_path_on")):
                manager.start("campaign", config)
                manager._thread.join(timeout=5)
                self.assertFalse(manager._thread.is_alive())
                self.assertEqual(run.call_count, 2)
                self.assertEqual(manager.status()["state"], "completed_with_errors")


    def test_paired_hold_owns_and_drains_both_ports_and_releases_without_power_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PowerPathConfig.from_mapping(self.paired_payload())
            with (patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type,
                  patch("radio_power_profiler.paired_ppk.ContinuousDrain") as drain_type):
                from unittest.mock import MagicMock
                tx, rx = MagicMock(), MagicMock()
                for sampler in (tx, rx):
                    sampler.api.ser.is_open = True
                    sampler.close.side_effect = lambda sampler=sampler, **_: setattr(sampler.api.ser, "is_open", False)
                sampler_type.side_effect = [tx, rx]
                drain_type.return_value.errors = []
                manager._ensure_paired_guard(config)
                self.assertTrue(manager.status()["paired_guard_active"])
                self.assertEqual(manager.status()["paired_guard_ports"], {"tx": "COM10", "rx": "COM11"})
                self.assertEqual(sampler_type.call_args_list, [call("COM10", voltage_mv=3300), call("COM11", voltage_mv=3300)])
                tx.start_continuous.assert_called_once()
                rx.start_continuous.assert_called_once()
                drain_type.assert_called_once_with({"tx": tx, "rx": rx})
                drain_type.return_value.start.assert_called_once()
                with self.assertRaisesRegex(RuntimeError, "Release the paired"):
                    manager.start("quick", WebConfig())
                manager.release_paired_guard_for_diagnostics()
                drain_type.return_value.pause.assert_called_once()
                tx.close.assert_called_once_with(keep_power_on=True)
                rx.close.assert_called_once_with(keep_power_on=True)
                tx.power_off.assert_not_called()
                rx.power_off.assert_not_called()
                self.assertFalse(manager.status()["paired_guard_active"])

    def test_paired_hold_retries_usb_reenumeration_without_reopening_owned_port(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PowerPathConfig.from_mapping(self.paired_payload())
            tx, rx = MagicMock(), MagicMock()
            for sampler in (tx, rx):
                sampler.api.ser.is_open = True
                sampler.close.side_effect = lambda sampler=sampler, **_: setattr(sampler.api.ser, "is_open", False)
            attempts = {"COM10": 0, "COM11": 0}
            elapsed = [0.0]
            def open_sampler(port, **_kwargs):
                attempts[port] += 1
                if port == "COM11" and attempts[port] <= 12:
                    raise FileNotFoundError("USB port is re-enumerating")
                return tx if port == "COM10" else rx
            with (patch("radio_power_profiler.ppk.Ppk2Sampler", side_effect=open_sampler),
                  patch("radio_power_profiler.paired_ppk.ContinuousDrain") as drain_type,
                  patch("radio_power_profiler.web_app.time.monotonic", side_effect=lambda: elapsed[0]),
                  patch("radio_power_profiler.web_app.time.sleep", side_effect=lambda value: elapsed.__setitem__(0, elapsed[0] + value))):
                drain_type.return_value.errors = []
                result = manager.enable_paired_guard(config)
                self.assertTrue(result["paired_guard_active"])
                self.assertEqual(attempts, {"COM10": 1, "COM11": 13})
                self.assertEqual(elapsed[0], 6.0)
                tx.start_continuous.assert_called_once()
                rx.start_continuous.assert_called_once()
                tx.close.assert_not_called()
                rx.close.assert_not_called()
                self.assertEqual(manager.status()["paired_guard_error"], "")
                manager.release_paired_guard_for_diagnostics()

    def test_paired_hold_recovery_has_deadline_and_respects_job_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PowerPathConfig.from_mapping(self.paired_payload())
            manager._thread = types.SimpleNamespace(is_alive=lambda: True)
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type:
                with self.assertRaisesRegex(RuntimeError, "while a test is running"):
                    manager.enable_paired_guard(config)
                sampler_type.assert_not_called()
            manager._thread = None
            elapsed = [0.0]
            with (patch("radio_power_profiler.ppk.Ppk2Sampler", side_effect=FileNotFoundError("port absent")) as sampler_type,
                  patch("radio_power_profiler.paired_ppk.ContinuousDrain") as drain_type,
                  patch("radio_power_profiler.web_app.time.monotonic", side_effect=lambda: elapsed[0]),
                  patch("radio_power_profiler.web_app.time.sleep", side_effect=lambda value: elapsed.__setitem__(0, elapsed[0] + value))):
                drain_type.return_value.errors = []
                with self.assertRaisesRegex(RuntimeError, "port absent"):
                    manager.enable_paired_guard(config)
                self.assertEqual(elapsed[0], 12.0)
                self.assertEqual(sampler_type.call_count, 50)
                self.assertFalse(manager.status()["paired_guard_active"])
                self.assertEqual(manager.status()["paired_guard_ports"], {})

    def test_stale_guard_releases_confirmed_closed_handles_but_retains_power_warning_until_explicit_enable(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PowerPathConfig.from_mapping(self.paired_payload())
            tx, rx, drain = MagicMock(), MagicMock(), MagicMock()
            drain.errors = ["rx: stale USB handle"]
            for sampler in (tx, rx):
                sampler.api.ser.is_open = True
            def stale_close(**_):
                tx.api.ser.is_open = False
                raise PermissionError(13, "power flush failed on disconnected device")
            tx.close.side_effect = stale_close
            rx.close.side_effect = lambda **_: setattr(rx.api.ser, "is_open", False)
            manager._paired_guards = {"tx": tx, "rx": rx}
            manager._paired_guard_ports = {"tx": "COM10", "rx": "COM11"}
            manager._paired_drain = drain
            with patch.object(manager, "_ensure_paired_guard") as enable:
                with self.assertRaisesRegex(RuntimeError, "DUT power state could not be reasserted"):
                    manager.release_paired_guard_for_diagnostics()
                enable.assert_not_called()
            drain.pause.assert_called_once()
            self.assertIsNone(manager._paired_drain)
            self.assertEqual(manager._paired_guards, {})
            self.assertEqual(manager.status()["paired_guard_ports"], {})
            self.assertFalse(manager.status()["paired_guard_active"])
            self.assertIn("power flush failed", manager.status()["paired_guard_error"])
            self.assertTrue(any("could not be reasserted" in entry["message"] for entry in manager.status()["logs"]))
            # Explicit re-enable can now take new handles; release did not do it.
            def enable_new(_config):
                manager._paired_guards = {"tx": MagicMock(), "rx": MagicMock()}
                manager._paired_guard_ports = {"tx": "COM10", "rx": "COM11"}
                manager._paired_guard_error = ""
            with patch.object(manager, "_ensure_paired_guard", side_effect=enable_new) as enable:
                self.assertTrue(manager.enable_paired_guard(config)["paired_guard_active"])
                enable.assert_called_once_with(config)

    def test_guard_release_retains_ownership_if_reader_or_serial_closure_is_unconfirmed(self):
        from unittest.mock import MagicMock
        for failure in ("reader", "serial", "unknown"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                manager = JobManager(Path(temporary))
                sampler, drain = MagicMock(), MagicMock()
                drain.errors = []
                sampler.api.ser.is_open = None if failure == "unknown" else True
                manager._paired_guards = {"rx": sampler}
                manager._paired_guard_ports = {"rx": "COM11"}
                manager._paired_drain = drain
                if failure == "reader":
                    drain.pause.side_effect = RuntimeError("reader still alive")
                elif failure == "serial":
                    sampler.close.side_effect = OSError("close failed")
                with self.assertRaises(RuntimeError):
                    manager.release_paired_guard_for_diagnostics()
                self.assertEqual(manager._paired_guards, {"rx": sampler})
                self.assertEqual(manager.status()["paired_guard_ports"], {"rx": "COM11"})
                self.assertTrue(manager.status()["paired_guard_error"])
                if failure == "reader":
                    sampler.close.assert_not_called()
                    self.assertIs(manager._paired_drain, drain)

    def test_already_closed_guard_is_removed_without_claiming_power_state(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            sampler = MagicMock()
            sampler.api.ser.is_open = False
            manager._paired_guards = {"rx": sampler}
            manager._paired_guard_ports = {"rx": "COM11"}
            with self.assertRaisesRegex(RuntimeError, "already closed"):
                manager.release_paired_guard_for_diagnostics()
            self.assertFalse(manager._paired_guards)
            # A second release remains idempotent but does not erase uncertainty.
            result = manager.release_paired_guard_for_diagnostics()
            self.assertTrue(result["ok"])
            self.assertTrue(result["warnings"])

    def test_http_configuration_requires_explicit_hardware_ports(self):
        for missing in ("measured_port", "peer_port", "ppk_port"):
            config = {"measured_port": "COM3", "peer_port": "COM4", "ppk_port": "COM10"}
            del config[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                WebConfig.from_mapping(config)

    def test_device_inventory_reports_both_ppks_without_opening_serial_ports(self):
        ports = [types.SimpleNamespace(device=device, description="USB Serial Device", serial_number=serial)
                 for device, serial in (("COM10", "PPK_TX"), ("COM11", "PPK_RX"))]
        with tempfile.TemporaryDirectory() as temporary:
            server = AppServer(("127.0.0.1", 0), JobManager(Path(temporary)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with (
                    patch("serial.tools.list_ports.comports", return_value=ports),
                    patch("radio_power_profiler.ppk.Ppk2Sampler.list_devices", return_value=[("COM10", "PPK_TX"), ("COM11", "PPK_RX")]),
                    patch("serial.Serial") as serial_type,
                ):
                    with urllib.request.urlopen(f"http://{host}:{port}/api/ports", timeout=3) as response:
                        result = json.load(response)
                    self.assertEqual([item["kind"] for item in result["ports"]], ["PPK2", "PPK2"])
                    self.assertEqual([item["serial_number"] for item in result["ports"]], ["PPK_TX", "PPK_RX"])
                    serial_type.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_server_startup_and_shutdown_do_not_access_hardware(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type,
            patch("radio_power_profiler.web_app.AppServer") as server_type,
        ):
            server_type.return_value.serve_forever.side_effect = KeyboardInterrupt

            run_web_server(sessions_root=Path(temporary), open_browser=False)

            sampler_type.assert_not_called()
            server_type.return_value.serve_forever.assert_called_once()
            server_type.return_value.server_close.assert_called_once()

    def test_server_bind_failure_does_not_acquire_a_ppk_port(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type,
            patch("radio_power_profiler.web_app.AppServer", side_effect=OSError("port in use")),
        ):
            with self.assertRaisesRegex(OSError, "port in use"):
                run_web_server(sessions_root=Path(temporary), open_browser=False)
            sampler_type.assert_not_called()

    def test_guard_enable_requires_explicit_port_and_voltage(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type:
                    for payload in ({}, {"ppk_port": "COM9"}, {"voltage_mv": 3300}):
                        request = urllib.request.Request(
                            f"http://{host}:{port}/api/ppk-guard/enable",
                            data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"}, method="POST",
                        )
                        with self.subTest(payload=payload), self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=3)
                        self.assertEqual(raised.exception.code, 400)
                        self.assertIn("Explicit ppk_port and voltage_mv", raised.exception.read().decode("utf-8"))
                    sampler_type.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_logging_survives_an_archived_session_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = JobManager(root, codex_thread_id="thread-id")
            manager._log_path = root / "archived-session" / "session.log"

            manager._log("PPK guard remains available")

            self.assertIsNone(manager._log_path)
            self.assertEqual(
                manager.status()["logs"][-1]["message"],
                "PPK guard remains available",
            )

    def test_codex_callback_resumes_the_captured_thread(self):
        thread_id = "12345678-1234-1234-1234-123456789abc"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            session.mkdir()
            manager = JobManager(root, codex_thread_id=thread_id)
            manager.codex_executable = "codex.exe"
            manager.vscode_process_id = ""
            manager._session_dir = session
            manager._log_path = session / "session.log"

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch.object(manager, "_open_vscode_uri") as open_uri,
            ):
                run.return_value.returncode = 0
                manager._schedule_codex_callback("campaign")
                manager._callback_thread.join(timeout=3)

            self.assertFalse(manager._callback_thread.is_alive())
            self.assertEqual(run.call_count, 2)
            notification_command = run.call_args_list[0].args[0]
            command = run.call_args_list[1].args[0]
            self.assertEqual(notification_command[:7], command[:7])
            self.assertIn("immediate visible completion notification", notification_command[7])
            self.assertIn("Măsurătorile s-au încheiat", notification_command[7])
            self.assertEqual(
                command[:7],
                [
                    "codex.exe",
                    "exec",
                    "--sandbox",
                    "workspace-write",
                    "resume",
                    "--json",
                    thread_id,
                ],
            )
            self.assertIn(str(session), command[7])
            self.assertIn("/api/ppk-guard/release", command[7])
            self.assertIn("Never stop, kill, or restart", command[7])
            self.assertIn("do not create a temporary repository", command[7])
            self.assertIn("commit/push remains pending", command[7])
            self.assertEqual(
                open_uri.call_args_list,
                [
                    call(f"vscode://openai.chatgpt/local/{thread_id}"),
                    call(f"vscode://openai.chatgpt/local/{thread_id}"),
                ],
            )
            callback_log = (session / "codex_callback.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("visible notification exited with code 0", callback_log)
            self.assertIn("result analysis exited with code 0", callback_log)
            self.assertIn("Displayed immediate completion notification", callback_log)
            self.assertIn("conversation foreground", callback_log)

    def test_codex_callback_test_is_hardware_free_and_uses_a_dedicated_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary), codex_thread_id="thread-id")
            manager.codex_executable = "codex.exe"

            with patch.object(
                manager,
                "_schedule_codex_callback",
                return_value=True,
            ) as schedule:
                status = manager.start_codex_callback_test()

            self.assertEqual(status["state"], "running")
            self.assertEqual(status["kind"], "callback_test")
            self.assertEqual(status["config"], {"hardware_access": False})
            self.assertTrue(status["session_dir"].endswith("_codex_callback_test"))
            _, call_kwargs = schedule.call_args
            self.assertTrue(call_kwargs["update_test_state"])
            self.assertIn("Do not access hardware", call_kwargs["prompt"])

    def test_codex_callback_test_uses_the_immediate_visible_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            session.mkdir()
            manager = JobManager(root, codex_thread_id="thread-id")
            manager.codex_executable = "codex.exe"
            manager.vscode_process_id = ""
            manager._session_dir = session
            manager._log_path = session / "session.log"
            prompt = "Hardware-free callback analysis test."

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch.object(manager, "_open_vscode_uri"),
            ):
                run.return_value.returncode = 0
                manager._schedule_codex_callback(
                    "callback-test",
                    prompt=prompt,
                    update_test_state=True,
                )
                manager._callback_thread.join(timeout=3)

            self.assertFalse(manager._callback_thread.is_alive())
            self.assertEqual(run.call_count, 2)
            self.assertIn(
                "immediate visible completion notification",
                run.call_args_list[0].args[0][7],
            )
            self.assertIn(
                "Testul callback Codex a ajuns în conversație",
                run.call_args_list[0].args[0][7],
            )
            self.assertEqual(run.call_args_list[1].args[0][7], prompt)

    def test_codex_focus_reloads_webviews_before_reopening_the_thread(self):
        thread_id = "12345678-1234-1234-1234-123456789abc"
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary), codex_thread_id=thread_id)
            manager.vscode_process_id = "18572"

            with (
                patch("radio_power_profiler.web_app.subprocess.run") as run,
                patch.object(manager, "_open_vscode_uri") as open_uri,
                patch("radio_power_profiler.web_app.time.sleep"),
            ):
                run.return_value.returncode = 0
                manager._focus_codex_thread()

            uri = f"vscode://openai.chatgpt/local/{thread_id}"
            self.assertEqual(
                open_uri.call_args_list,
                [call(uri), call(uri), call(uri)],
            )
            self.assertEqual(run.call_count, 2)
            reload_command = run.call_args_list[0].args[0]
            self.assertIn("Developer: Reload Webviews", reload_command[-1])
            self.assertIn("Get-Process -Id 18572", reload_command[-1])
            self.assertIn("Get-Process -Name Code", reload_command[-1])
            self.assertIn("MainWindowTitle -like '*ESP32-C3_Radio*'", reload_command[-1])
            self.assertNotIn("Sort-Object StartTime", reload_command[-1])
            activate_command = run.call_args_list[1].args[0]
            self.assertIn("AppActivate($target.Id)", activate_command[-1])

    def test_vscode_uri_uses_internal_cli_with_electron_node_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            install_root = Path(temporary) / "Microsoft VS Code"
            executable = install_root / "Code.exe"
            cli = install_root / "version" / "resources" / "app" / "out" / "cli.js"
            cli.parent.mkdir(parents=True)
            executable.touch()
            cli.touch()
            manager = JobManager(Path(temporary) / "sessions")

            with (
                patch.dict(
                    "radio_power_profiler.web_app.os.environ",
                    {"VSCODE_CWD": str(install_root)},
                    clear=False,
                ),
                patch("radio_power_profiler.web_app.shutil.which", return_value=None),
                patch("radio_power_profiler.web_app.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                manager._open_vscode_uri("vscode://openai.chatgpt/local/thread-id")

            command = run.call_args.args[0]
            self.assertEqual(
                command,
                [
                    str(executable),
                    str(cli),
                    "--open-url",
                    "--",
                    "vscode://openai.chatgpt/local/thread-id",
                ],
            )
            self.assertEqual(
                run.call_args.kwargs["env"]["ELECTRON_RUN_AS_NODE"],
                "1",
            )

    def test_codex_executable_is_rediscovered_after_extension_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            executable = (
                home
                / ".vscode"
                / "extensions"
                / "openai.chatgpt-99.1.2-win32-x64"
                / "bin"
                / "windows-x86_64"
                / "codex.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.touch()
            manager = JobManager(home, codex_thread_id="thread-id")
            manager.codex_executable = str(home / "removed-extension" / "codex.exe")

            with (
                patch("radio_power_profiler.web_app.shutil.which", return_value=None),
                patch("radio_power_profiler.web_app.Path.home", return_value=home),
                patch("radio_power_profiler.web_app.os.name", "nt"),
            ):
                resolved = manager._resolve_codex_executable()

            self.assertEqual(resolved, str(executable))

    def test_quick_and_campaign_plans_cover_expected_work(self):
        config = WebConfig(
            profile_id="RADIO_EBYTE_E32_868T30D",
            measured_port="COM18",
            peer_port="COM17",
            save_raw_campaign=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick = build_quick_steps(config, root / "quick")
            campaign = build_campaign_steps(config, root / "campaign")
            continuous_rx = build_continuous_rx_steps(config, root / "continuous-rx")

        self.assertEqual(len(quick), 4)
        self.assertTrue(all("--save-raw" in step.command for step in quick))
        self.assertTrue(all("--keep-power-on" in step.command for step in quick))
        self.assertTrue(all(step.expected_rows == 2 for step in quick))
        self.assertTrue(
            all(
                step.command[step.command.index("--repetitions") + 1] == "2"
                for step in quick
            )
        )
        self.assertEqual(len(campaign), 76)
        self.assertEqual(
            sum(step.result_kind == "packet" for step in campaign),
            72,
        )
        self.assertEqual(
            sum(step.result_kind == "continuous" for step in campaign),
            4,
        )
        self.assertEqual(len(continuous_rx), 3)
        self.assertTrue(
            all(step.step_id.startswith("continuous_rx_") for step in continuous_rx)
        )
        self.assertTrue(
            all("--keep-power-on" in step.command for step in continuous_rx)
        )
        self.assertTrue(all("--save-raw" in step.command for step in campaign))
        self.assertTrue(all("--keep-power-on" in step.command for step in campaign))

    def test_power_guard_holds_ppk2_open_and_reasserts_on_when_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type:
                sampler = sampler_type.return_value

                manager._ensure_current_path_on("COM11", 3300)
                manager._release_current_path_guard()

            sampler_type.assert_called_once_with("COM11", voltage_mv=3300)
            sampler.power_on.assert_called_once_with()
            sampler.close.assert_called_once_with(keep_power_on=True)

    def test_ppk_guard_handoff_api_keeps_the_server_alive(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            with patch("radio_power_profiler.ppk.Ppk2Sampler") as sampler_type:
                sampler = sampler_type.return_value
                manager._ensure_current_path_on("COM11", 3300)
                thread.start()
                try:
                    host, port = server.server_address
                    release_request = urllib.request.Request(
                        f"http://{host}:{port}/api/ppk-guard/release",
                        data=b"",
                        method="POST",
                    )
                    with urllib.request.urlopen(
                        release_request,
                        timeout=3,
                    ) as response:
                        released = json.loads(response.read().decode("utf-8"))

                    enable_request = urllib.request.Request(
                        f"http://{host}:{port}/api/ppk-guard/enable",
                        data=json.dumps(
                            {"ppk_port": "COM11", "voltage_mv": 3300}
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(
                        enable_request,
                        timeout=3,
                    ) as response:
                        enabled = json.loads(response.read().decode("utf-8"))

                    self.assertFalse(released["guarded"])
                    self.assertTrue(released["was_guarded"])
                    self.assertTrue(enabled["guarded"])
                    self.assertTrue(manager.status()["ppk_guard_active"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)

            self.assertEqual(sampler_type.call_count, 2)
            self.assertEqual(sampler.power_on.call_count, 2)
            sampler.close.assert_called_once_with(keep_power_on=True)

    def test_lora_profile_uses_sf_and_bandwidth_in_web_campaign(self):
        config = WebConfig(
            profile_id="RADIO_SX1278_SHIELDED",
            measured_port="COM22",
            peer_port="COM21",
            ppk_port="COM11",
            save_raw_campaign=True,
        )
        config.validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick = build_quick_steps(config, root / "quick")
            campaign = build_campaign_steps(config, root / "campaign")

        self.assertEqual(len(quick), 4)
        self.assertIn("spreading_factor=7", quick[0].command)
        self.assertIn("spreading_factor=12", quick[2].command)
        self.assertEqual(
            sum(step.result_kind == "packet" for step in campaign),
            36,
        )
        self.assertEqual(
            sum(step.result_kind == "continuous" for step in campaign),
            4,
        )
        continuous = [step for step in campaign if step.result_kind == "continuous"]
        self.assertTrue(
            all("--powers=-4,10,20" in step.command for step in continuous)
        )
        self.assertTrue(
            all(any(item.startswith("spreading_factor=") for item in step.command) for step in continuous)
        )
        self.assertTrue(
            all("bandwidth_khz=125" in step.command for step in continuous)
        )

    def test_e22_campaign_uses_firmware_valid_front_stage_power(self):
        config = WebConfig(
            profile_id="RADIO_EBYTE_E22_SX1268",
            measured_port="COM52",
            peer_port="COM51",
            ppk_port="COM11",
        )
        config.validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick = build_quick_steps(config, root / "quick")
            campaign = build_campaign_steps(config, root / "campaign")

        self.assertTrue(
            any("tx_power_dbm=18" in step.command for step in quick)
        )
        self.assertFalse(
            any("tx_power_dbm=22" in step.command for step in quick)
        )
        continuous = [step for step in campaign if step.result_kind == "continuous"]
        self.assertTrue(
            all("--powers=-9,10,18" in step.command for step in continuous)
        )

    def test_hc12_campaign_uses_datasheet_safe_continuous_gaps(self):
        config = WebConfig(
            profile_id="RADIO_HC12",
            measured_port="COM39",
            peer_port="COM40",
            ppk_port="COM11",
        )
        config.validate()
        with tempfile.TemporaryDirectory() as temporary:
            campaign = build_campaign_steps(config, Path(temporary) / "campaign")

        self.assertEqual(len(campaign), 40)
        continuous_rx = {
            next(item for item in step.command if item.startswith("bit_rate_kbps=")):
            step.command[step.command.index("--gap-ms") + 1]
            for step in campaign
            if step.step_id.startswith("continuous_rx_")
        }
        self.assertEqual(
            continuous_rx,
            {
                "bit_rate_kbps=0.5": "2100",
                "bit_rate_kbps=15": "100",
                "bit_rate_kbps=250": "100",
            },
        )

    def test_nrf24l01_campaign_covers_all_rates_and_controlled_rx(self):
        for profile_id, measured_port, peer_port in (
            ("RADIO_NRF24L01", "COM41", "COM42"),
            ("RADIO_NRF24L01_PA", "COM43", "COM44"),
        ):
            with self.subTest(profile_id=profile_id):
                config = WebConfig(
                    profile_id=profile_id,
                    measured_port=measured_port,
                    peer_port=peer_port,
                    ppk_port="COM11",
                )
                config.validate()
                with tempfile.TemporaryDirectory() as temporary:
                    quick = build_quick_steps(config, Path(temporary) / "quick")
                    campaign = build_campaign_steps(config, Path(temporary) / "campaign")

                self.assertEqual(len(quick), 6)
                high_power_slow = {
                    step.step_id: step
                    for step in quick
                    if step.step_id.endswith("slow_high_power")
                }
                self.assertEqual(
                    set(high_power_slow),
                    {"tx_slow_high_power", "rx_slow_high_power"},
                )
                self.assertTrue(
                    all("tx_power_dbm=0" in step.command for step in high_power_slow.values())
                )
                self.assertTrue(
                    all("data_rate_kbps=250" in step.command for step in high_power_slow.values())
                )
                self.assertTrue(
                    all(
                        "--sizes" in step.command and "32" in step.command
                        for step in high_power_slow.values()
                    )
                )
                self.assertEqual(len(campaign), 40)
                self.assertEqual(
                    sum(step.result_kind == "packet" for step in campaign),
                    36,
                )
                continuous_rx = [
                    step
                    for step in campaign
                    if step.step_id.startswith("continuous_rx_")
                ]
                self.assertEqual(len(continuous_rx), 3)
                self.assertTrue(
                    all(
                        step.command[step.command.index("--gap-ms") + 1] == "15"
                        for step in continuous_rx
                    )
                )

    def test_e280_quick_check_covers_late_low_power_fast_tx(self):
        config = WebConfig(
            profile_id="RADIO_EBYTE_E280_SX1280",
            measured_port="COM45",
            peer_port="COM46",
            ppk_port="COM11",
        )
        with tempfile.TemporaryDirectory() as temporary:
            quick = build_quick_steps(config, Path(temporary) / "quick")

        self.assertEqual(len(quick), 5)
        metrology = next(
            step
            for step in quick
            if step.step_id == "tx_fast_low_power_full_frame"
        )
        self.assertEqual(metrology.expected_rows, 2)
        self.assertIn("tx_power_dbm=4", metrology.command)
        self.assertIn("air_rate=2M", metrology.command)
        self.assertIn("64", metrology.command)

    def test_e280_continuous_rx_runs_each_power_in_a_fresh_process(self):
        config = WebConfig(
            profile_id="RADIO_EBYTE_E280_SX1280",
            measured_port="COM45",
            peer_port="COM46",
            ppk_port="COM11",
        )
        with tempfile.TemporaryDirectory() as temporary:
            campaign = build_campaign_steps(config, Path(temporary) / "campaign")
            continuous_rx = [
                step
                for step in campaign
                if step.step_id.startswith("continuous_rx_")
            ]

        self.assertEqual(len(campaign), 46)
        self.assertEqual(len(continuous_rx), 9)
        self.assertTrue(all(step.expected_rows == 1 for step in continuous_rx))
        self.assertEqual(
            {
                item.split("=", 1)[1]
                for step in continuous_rx
                for item in step.command
                if item.startswith("--powers=")
            },
            {"4", "7", "12"},
        )

    def test_current_web_defaults_target_e79_pair(self):
        config = WebConfig()
        self.assertEqual(config.profile_id, "RADIO_EBYTE_E79_CC1352P")
        self.assertEqual(config.measured_port, "COM5")
        self.assertEqual(config.peer_port, "COM13")

    def test_e79_quick_check_includes_low_power_metrology_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            quick = build_quick_steps(WebConfig(), Path(temporary) / "quick")

        self.assertEqual(len(quick), 5)
        metrology = next(
            step for step in quick if step.step_id == "tx_low_power_metrology"
        )
        self.assertEqual(metrology.expected_rows, 5)
        self.assertIn("tx_power_dbm=-20", metrology.command)
        self.assertIn("rf_profile=GFSK4K8", metrology.command)
        self.assertEqual(
            metrology.command[metrology.command.index("--repetitions") + 1],
            "5",
        )

    def test_e79_campaign_covers_all_seven_rf_profiles(self):
        config = WebConfig()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = build_campaign_steps(config, root / "campaign")
            continuous_rx = build_continuous_rx_steps(config, root / "continuous-rx")

        self.assertEqual(len(campaign), 176)
        self.assertEqual(
            sum(step.result_kind == "packet" for step in campaign),
            168,
        )
        self.assertEqual(
            sum(step.result_kind == "continuous" for step in campaign),
            8,
        )
        self.assertEqual(len(continuous_rx), 7)
        profile_tokens = {
            item.split("=", 1)[1]
            for step in continuous_rx
            for item in step.command
            if item.startswith("rf_profile=")
        }
        self.assertEqual(
            profile_tokens,
            {
                "GFSK4K8",
                "GFSK50",
                "GFSK200",
                "SLR2K5",
                "SLR5",
                "OOK4K8",
                "IEEE154G50",
            },
        )

    def test_config_rejects_duplicate_ports(self):
        with self.assertRaisesRegex(ValueError, "must be different"):
            WebConfig.from_mapping(
                {
                    "measured_port": "COM18",
                    "peer_port": "COM18",
                    "ppk_port": "COM11",
                }
            )

    def test_result_validation_retries_hardware_failures_but_keeps_loss(self):
        step = CommandStep(
            step_id="packet",
            label="packet",
            command=[],
            result_kind="packet",
            expected_rows=1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            fields = ["status", "sample_loss_percent", "transmitter_response"]
            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"status": "rx_missing", "sample_loss_percent": 0})
            loss = validate_result(step, result_dir)
            self.assertTrue(loss["valid"])
            self.assertTrue(loss["warnings"])

            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {"status": "no_event_detected", "sample_loss_percent": 0}
                )
            invalid = validate_result(step, result_dir)
            self.assertFalse(invalid["valid"])

            continuous_step = CommandStep(
                step_id="continuous",
                label="continuous",
                command=[],
                result_kind="continuous",
                expected_rows=1,
            )
            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {"status": "no_rx_data", "sample_loss_percent": 0}
                )
            continuous_loss = validate_result(continuous_step, result_dir)
            self.assertTrue(continuous_loss["valid"])
            self.assertTrue(continuous_loss["warnings"])

            with (result_dir / "summary.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "status": "ok",
                        "sample_loss_percent": 0,
                        "transmitter_response": "SERIAL_ERRORS=3",
                    }
                )
            serial_failure = validate_result(continuous_step, result_dir)
            self.assertFalse(serial_failure["valid"])

    def test_result_validation_rejects_analysis_failures_even_with_rx_loss(self):
        step = CommandStep(
            step_id="packet", label="packet", command=[],
            result_kind="packet", expected_rows=1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            for status, analysis_error in (
                ("analysis_review_required", ""),
                ("ok", "detected_frame_count_mismatch"),
                ("rx_missing", "energy_sensitivity_above_1_percent"),
            ):
                with self.subTest(status=status, analysis_error=analysis_error):
                    with (result_dir / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=["status", "analysis_error"])
                        writer.writeheader()
                        writer.writerow({"status": status, "analysis_error": analysis_error})
                    result = validate_result(step, result_dir)
                    self.assertFalse(result["valid"])
                    self.assertTrue(result["errors"])


    def test_quick_job_persists_manifest_logs_and_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = JobManager(root)
            counter = 0

            def fake_process(command, attempt_log):
                nonlocal counter
                counter += 1
                attempt_log.parent.mkdir(parents=True, exist_ok=True)
                attempt_log.write_text("synthetic hardware log\n", encoding="utf-8")
                result_dir = root / f"synthetic_{counter}"
                result_dir.mkdir()
                fields = [
                    "status",
                    "sample_loss_percent",
                    "event_peak_uA",
                    "tx_peak_uA",
                ]
                with (result_dir / "summary.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    repetitions = int(
                        command[command.index("--repetitions") + 1]
                    )
                    for _ in range(repetitions):
                        writer.writerow(
                            {
                                "status": "ok",
                                "sample_loss_percent": 0,
                                "event_peak_uA": 500_000,
                                "tx_peak_uA": 500_000,
                            }
                        )
                return 0, str(result_dir)

            manager._run_process = fake_process
            manager._ensure_current_path_on = lambda *_args: None
            manager.start("quick", WebConfig())
            manager._thread.join(timeout=5)
            status = manager.status()

            self.assertEqual(status["state"], "completed")
            self.assertTrue(status["quick_verdict"]["ready_for_campaign"])
            session = Path(status["session_dir"])
            manifest = json.loads(
                (session / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["completed_steps"], 5)
            self.assertTrue(all(step["attempts"] for step in manifest["steps"]))
            self.assertTrue(
                all(
                    Path(step["attempts"][0]["log_file"]).is_file()
                    for step in manifest["steps"]
                )
            )


if __name__ == "__main__":
    unittest.main()
