import csv
import hashlib
import json
import math
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
    AppServer,
    CommandStep,
    HTML,
    JobManager,
    PairedConfig,
    WebConfig,
    build_campaign_steps,
    build_continuous_rx_steps,
    build_quick_steps,
    build_paired_pilot_steps,
    build_paired_campaign_steps,
    build_paired_32b_campaign_steps,
    build_paired_fragmented_campaign_steps,
    run_web_server,
    validate_result,
)


class WebAppTests(unittest.TestCase):
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

    def write_fragmented_result(self, root, payload_bytes=128, rf_profile="GFSK200"):
        condition = {"payload_bytes": payload_bytes, "rf_profile": rf_profile, "tx_power_dbm": 13}
        manifest = self.write_paired_result(root, integration_mode="radio_markers", condition=condition,
                                            marker_totals_only=True)
        frames = payload_bytes // 64
        method = "independent_radio_fragment_marker_totals"
        manifest.update(fragmented=True, frame_count=frames, frame_payload_bytes=[64] * frames,
                        integration_method=method,
                        marker_contract={"expected_frame_count": frames, "inter_frame_energy": "excluded"})
        for transfer in manifest["rows"]:
            transfer.update(packet_received=True, frame_payload_bytes=[64] * frames)
            evidence = transfer["marker_diagnostics"]
            evidence.update(method=method, integration_method=method, expected_frame_count=frames)
            for detail in evidence["roles"].values():
                template = detail.pop("total_qa")
                start, end = detail.pop("window_samples")
                windows = [[start + frame * 1000, end + frame * 1000] for frame in range(frames)]
                proofs = [{**template, "window_samples": window, "guard_window_samples": [window[0] - 3, window[1]]}
                          for window in windows]
                detail.update(valid=True, reasons=[], warnings=[], sample_count=100_000,
                              software_trigger_index=20000, pulse_count=frames, windows_samples=windows,
                              frame_proofs=proofs, duration_samples=(end - start) * frames,
                              charge_total_uC=template["charge_total_uC"] * frames,
                              energy_total_uJ=template["energy_total_uJ"] * frames)
        for role in ("tx", "rx"):
            path = root / role / "summary.csv"
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            detail = manifest["rows"][0]["marker_diagnostics"]["roles"][role]
            for row in rows:
                row.update(integration_method=method, frame_count=frames, serial_content_bytes=payload_bytes,
                           receiver_response=" | ".join(["0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"] * frames),
                           charge_total_uC=detail["charge_total_uC"], energy_total_uJ=detail["energy_total_uJ"],
                           event_duration_ms=detail["duration_samples"] / 100,
                           integration_windows_ms=json.dumps([[(i - 20000) / 100 for i in window]
                                                              for window in detail["windows_samples"]]))
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0])
                writer.writeheader()
                writer.writerows(rows)
        (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_paired_config_requires_explicit_ports_voltages_identities_and_confirmation(self):
        required = ("tx_radio_port", "rx_radio_port", "tx_ppk_port", "rx_ppk_port",
                    "tx_voltage_mv", "rx_voltage_mv", "tx_identity", "rx_identity",
                    "voltage_confirmed", "voltage_provenance")
        for name in required:
            payload = self.paired_payload()
            del payload[name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                PairedConfig.from_mapping(payload)
        for key, value in (("voltage_confirmed", "true"), ("voltage_confirmed", 1),
                           ("tx_voltage_mv", True), ("tx_voltage_mv", 3300.5),
                           ("rx_voltage_mv", None), ("tx_voltage_mv", 5500),
                           ("rx_radio_port", "COM012"), ("tx_radio_port", "COM0"),
                           ("voltage_provenance", None), ("interface_label", "ESP32-C3"),
                           ("ppk_mode", "unknown"), ("integration_mode", "threshold"),
                           ("integration_mode", ""), ("integration_mode", None)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                PairedConfig.from_mapping({**self.paired_payload(), key: value})

    def test_paired_plan_runs_one_bounded_shared_runner_with_provenance(self):
        config = PairedConfig.from_mapping(self.paired_payload())
        with tempfile.TemporaryDirectory() as temporary:
            steps = build_paired_pilot_steps(config, Path(temporary))
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.result_kind, "paired")
        self.assertEqual(step.expected_rows, 5)
        self.assertIn("radio_power_profiler.paired_runner", step.command)
        self.assertIn("--voltage-confirmed", step.command)
        self.assertEqual(step.command[step.command.index("--repetitions") + 1], "5")
        self.assertEqual(step.command[step.command.index("--voltage-provenance") + 1], config.voltage_provenance)
        self.assertEqual(step.command[step.command.index("--ppk-mode") + 1], "ampere")
        self.assertEqual(config.integration_mode, "modeled")
        self.assertEqual(step.command[step.command.index("--integration-mode") + 1], "modeled")

    def test_paired_interfaces_build_only_the_explicit_five_transfer_pilot(self):
        for interface in ("CH340", "ESP32"):
            with self.subTest(interface=interface), tempfile.TemporaryDirectory() as temporary:
                payload = {**self.paired_payload(), "interface_label": interface,
                           "integration_mode": "radio_markers", "marker_totals_only": True}
                config = PairedConfig.from_mapping(payload)
                steps = build_paired_pilot_steps(config, Path(temporary))
                self.assertEqual(len(steps), 1)
                step = steps[0]
                self.assertEqual(step.step_id, "e79_paired_32b")
                self.assertEqual(step.expected_rows, 5)
                self.assertEqual(step.command[step.command.index("--interface-label") + 1], interface)
                self.assertEqual(step.command[step.command.index("--repetitions") + 1], "5")
                self.assertIn("--marker-totals-only", step.command)
                self.assertNotIn("--fragmented", step.command)
                for name in ("tx_identity", "rx_identity", "voltage_confirmed", "voltage_provenance"):
                    with self.subTest(missing=name), self.assertRaises(ValueError):
                        PairedConfig.from_mapping({key: value for key, value in payload.items() if key != name})
        for interface in ("", "CH9340C", "ESP32-C3", "esp32", "unknown", None):
            with self.subTest(invalid_interface=interface), self.assertRaisesRegex(ValueError, "CH340 or ESP32"):
                PairedConfig.from_mapping({**self.paired_payload(), "interface_label": interface})

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the UI confirmation handler")
    def test_interface_switch_clears_fixture_confirmation_in_both_directions(self):
        script = HTML.split("const pairedInterfaceHelp=", 1)[1].split("function pairedConfig()", 1)[0]
        script = "const pairedInterfaceHelp=" + script
        cleared = ["pairedTxRadio", "pairedRxRadio", "pairedTxIdentity", "pairedRxIdentity",
                   "pairedTxVoltage", "pairedRxVoltage", "pairedVoltageProvenance", "pairedResumeSession"]
        harness = """
const assert=require('node:assert/strict');
const cleared=CLEARED;
const fields=Object.fromEntries([...cleared,'pairedInterface','pairedInterfaceHelp','pairedVoltageConfirmed','pairedTxPpk','pairedRxPpk'].map(id=>[id,{value:'confirmed',checked:true}]));
const $=id=>fields[id];
fields.pairedInterface.value='CH340';
SCRIPT
assert.equal(fields.pairedVoltageConfirmed.checked,true);
for(const choice of ['ESP32','CH340']){
 for(const id of cleared) fields[id].value='previous fixture';
 fields.pairedVoltageConfirmed.checked=true;
 fields.pairedInterface.value=choice;
 fields.pairedInterface.onchange();
 for(const id of cleared) assert.equal(fields[id].value,'',id);
 assert.equal(fields.pairedVoltageConfirmed.checked,false);
 assert.equal(fields.pairedTxPpk.value,'confirmed');
 assert.equal(fields.pairedRxPpk.value,'confirmed');
 assert.ok(fields.pairedInterfaceHelp.textContent.includes(choice));
}
""".replace("CLEARED", json.dumps(cleared)).replace("SCRIPT", script)
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True,
                                text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_paired_marker_selection_is_explicit_in_runner_command_and_label(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "tx_marker"})
        with tempfile.TemporaryDirectory() as temporary:
            step = build_paired_pilot_steps(config, Path(temporary))[0]
        self.assertEqual(step.command[step.command.index("--integration-mode") + 1], "tx_marker")
        self.assertIn("common TX hardware marker", step.label)

    def test_local_radio_marker_selection_is_explicit_in_runner_command_and_label(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        with tempfile.TemporaryDirectory() as temporary:
            step = build_paired_pilot_steps(config, Path(temporary))[0]
        self.assertEqual(step.command[step.command.index("--integration-mode") + 1], "radio_markers")
        self.assertIn("local TX/RX hardware markers", step.label)

    def test_paired_campaign_matrix_is_bounded_ordered_unique_and_requires_local_markers(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steps = build_paired_campaign_steps(config, root)
            self.assertEqual(len(steps), 63)
            self.assertEqual(sum(step.expected_rows for step in steps), 315)
            self.assertEqual(len({step.step_id for step in steps}), 63)
            self.assertEqual(len({step.command[step.command.index("--output") + 1] for step in steps}), 63)
            conditions = [(int(s.command[s.command.index("--payload-bytes") + 1]),
                           s.command[s.command.index("--rf-profile") + 1],
                           int(s.command[s.command.index("--tx-power-dbm") + 1])) for s in steps]
            self.assertEqual(conditions[0], (32, "GFSK200", 13))
            self.assertEqual([value[0] for value in conditions], [32] * 21 + [8] * 21 + [64] * 21)
            phys = {"GFSK4K8", "GFSK50", "GFSK200", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50"}
            self.assertEqual(set(conditions), {(size, phy, power) for size in (8, 32, 64)
                                               for phy in phys for power in (-20, 0, 13)})
            self.assertEqual([s.command for s in steps],
                             [s.command for s in build_paired_campaign_steps(config, root)])
            for mode in ("modeled", "tx_marker"):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "radio_markers"):
                    build_paired_campaign_steps(PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": mode}), root)

    def test_32b_campaign_is_exact_canonical_subset_for_both_interfaces_with_explicit_totals(self):
        for interface in ("CH340", "ESP32"):
            with self.subTest(interface=interface), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                base = {**self.paired_payload(), "interface_label": interface,
                        "integration_mode": "radio_markers", "marker_totals_only": True}
                config = PairedConfig.from_mapping(base)
                before = asdict(config)
                steps = build_paired_32b_campaign_steps(config, root)
                full = build_paired_campaign_steps(config, root)
                self.assertEqual([s.public() for s in steps], [s.public() for s in full[:21]])
                self.assertEqual(asdict(config), before)
                self.assertEqual((len(steps), sum(s.expected_rows for s in steps)), (21, 105))
                self.assertEqual(len({s.step_id for s in steps}), 21)
                conditions = {(int(s.command[s.command.index("--payload-bytes") + 1]),
                               s.command[s.command.index("--rf-profile") + 1],
                               int(s.command[s.command.index("--tx-power-dbm") + 1])) for s in steps}
                phys = {"GFSK4K8", "GFSK50", "GFSK200", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50"}
                self.assertEqual(conditions, {(32, phy, power) for phy in phys for power in (-20, 0, 13)})
                self.assertEqual(steps[0].step_id, "paired_s32_GFSK200_p13")
                for step in steps:
                    self.assertEqual(step.command[step.command.index("--interface-label") + 1], interface)
                    self.assertIn("--marker-totals-only", step.command)
                    self.assertNotIn("--fragmented", step.command)
                for mode, totals in (("modeled", False), ("tx_marker", False), ("radio_markers", False)):
                    invalid = PairedConfig.from_mapping({**base, "integration_mode": mode, "marker_totals_only": totals})
                    with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "total-only"):
                        build_paired_32b_campaign_steps(invalid, root)
                    manager = JobManager(root)
                    with self.assertRaisesRegex(ValueError, "total-only"):
                        manager.start("paired_32b_campaign", invalid)
                    self.assertIsNone(manager._thread)
                    self.assertFalse(list(root.iterdir()))

    def test_fragmented_campaign_has_21_distinct_batches_and_requires_explicit_total_only(self):
        base = {**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steps = build_paired_fragmented_campaign_steps(PairedConfig.from_mapping(base), root)
            conditions = [(int(step.command[step.command.index("--payload-bytes") + 1]),
                           step.command[step.command.index("--rf-profile") + 1],
                           int(step.command[step.command.index("--tx-power-dbm") + 1])) for step in steps]
            self.assertEqual(len(steps), 21)
            self.assertEqual(sum(step.expected_rows for step in steps), 105)
            self.assertEqual(len({step.step_id for step in steps}), 21)
            self.assertEqual(len({step.command[step.command.index("--output") + 1] for step in steps}), 21)
            self.assertEqual([c[0] for c in conditions], [128] * 7 + [512] * 7 + [1024] * 7)
            for offset, size in ((0, 128), (7, 512), (14, 1024)):
                self.assertEqual(conditions[offset], (size, "GFSK200", 13))
            phys = {"GFSK4K8", "GFSK50", "GFSK200", "SLR2K5", "SLR5", "OOK4K8", "IEEE154G50"}
            self.assertEqual(set(conditions), {(size, phy, 13) for size in (128, 512, 1024) for phy in phys})
            self.assertTrue(all("--fragmented" in step.command and "--marker-totals-only" in step.command for step in steps))
            for mode, totals in (("modeled", False), ("tx_marker", False), ("radio_markers", False)):
                config = PairedConfig.from_mapping({**base, "integration_mode": mode, "marker_totals_only": totals})
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    build_paired_fragmented_campaign_steps(config, root)
                manager = JobManager(root)
                with self.assertRaises(ValueError):
                    manager.start("paired_fragmented_campaign", config)
                self.assertIsNone(manager._thread)
                self.assertFalse(list(root.iterdir()))

    def test_fragmented_validation_accepts_all_sizes_with_independent_durations_and_rejects_implicit_mode(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True})
        for size, offset in ((128, 0), (512, 7), (1024, 14)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_fragmented_result(root, size)
                step = build_paired_fragmented_campaign_steps(config, root)[offset]
                result = validate_result(step, root)
                self.assertTrue(result["valid"], result)
                step.command.remove("--fragmented")
                self.assertFalse(validate_result(step, root)["valid"])

    def test_fragmented_validation_rejects_any_missing_or_corrupt_frame_proof_and_contract(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.write_fragmented_result(root)
            step = build_paired_fragmented_campaign_steps(config, root)[0]
            mutations = {
                "no_opt_in": lambda m: m.update(fragmented=False),
                "count": lambda m: m.update(frame_count=8),
                "partition": lambda m: m.update(frame_payload_bytes=[63, 65]),
                "gaps": lambda m: m["marker_contract"].update(inter_frame_energy="included"),
                "method": lambda m: m.update(integration_method="independent_radio_hardware_marker_totals"),
                "delivery": lambda m: m["rows"][0].update(packet_received=False),
                "run_partition": lambda m: m["rows"][0].update(frame_payload_bytes=[64]),
                "diagnostic_count": lambda m: m["rows"][0]["marker_diagnostics"].update(expected_frame_count=8),
            }
            for name, mutation in mutations.items():
                with self.subTest(contract=name):
                    manifest = json.loads(json.dumps(original))
                    mutation(manifest)
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])
            proof_mutations = {"valid": False, "counter_anomaly_indices_guard": [26176],
                               "invalid_range_indices_guard": [26000], "bit17_indices_guard": [26000],
                               "guard_window_samples": [26000, 26176], "wire_logic_match_full_capture": False,
                               "direct_adc_max_difference_uA": 1.01e-6, "direct_adc_compared_samples": 1,
                               "energy_total_uJ": 999, "charge_total_uC": float("nan")}
            for role in ("tx", "rx"):
                for field, value in proof_mutations.items():
                    with self.subTest(role=role, proof=field):
                        manifest = json.loads(json.dumps(original))
                        manifest["rows"][0]["marker_diagnostics"]["roles"][role]["frame_proofs"][-1][field] = value
                        (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                        self.assertFalse(validate_result(step, root)["valid"])
                for field, value in (("pulse_count", 1), ("frame_proofs", []), ("valid", False),
                                     ("sample_count", 99999), ("software_trigger_index", 25000),
                                     ("windows_samples", [[25000, 25176], [25050, 25226]]),
                                     ("duration_samples", 1176), ("energy_total_uJ", 999)):
                    with self.subTest(role=role, detail=field):
                        manifest = json.loads(json.dumps(original))
                        manifest["rows"][0]["marker_diagnostics"]["roles"][role][field] = value
                        (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                        self.assertFalse(validate_result(step, root)["valid"])

    def test_fragmented_validation_requires_each_csv_receipt_and_exact_sum_excluding_gaps(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fragmented_result(root)
            step = build_paired_fragmented_campaign_steps(config, root)[0]
            for role in ("tx", "rx"):
                path = root / role / "summary.csv"
                with path.open(encoding="utf-8", newline="") as stream:
                    original = list(csv.DictReader(stream))
                mutations = [("receiver_response", "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"),
                             ("frame_count", "1"), ("serial_content_bytes", "64"), ("status", "rx_missing"),
                             ("charge_total_uC", "999"), ("energy_total_uJ", "999"), ("tx_mean_uA", "1000"),
                             ("event_duration_ms", "11.76"), ("integration_windows_ms", "[[50,61.76]]")]
                mutations += [(field, "0") for field in ("baseline_median_uA", "threshold_uA", "charge_excess_uC", "energy_excess_uJ")]
                for field, value in mutations:
                    with self.subTest(role=role, field=field):
                        rows = [dict(row) for row in original]
                        rows[0][field] = value
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=rows[0])
                            writer.writeheader()
                            writer.writerows(rows)
                        self.assertFalse(validate_result(step, root)["valid"])
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=original[0])
                    writer.writeheader()
                    writer.writerows(original)

    def test_marker_totals_only_is_strict_opt_in_and_propagates_to_pilot_and_campaign(self):
        base = {**self.paired_payload(), "integration_mode": "radio_markers"}
        self.assertIs(PairedConfig.from_mapping(base).marker_totals_only, False)
        for value in ("true", "false", 1, 0, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                PairedConfig.from_mapping({**base, "marker_totals_only": value})
        for mode in ("modeled", "tx_marker"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "radio_markers"):
                PairedConfig.from_mapping({**base, "integration_mode": mode, "marker_totals_only": True})
        config = PairedConfig.from_mapping({**base, "marker_totals_only": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for step in build_paired_pilot_steps(config, root) + build_paired_campaign_steps(config, root):
                self.assertIn("--marker-totals-only", step.command)
                self.assertIn("total energy only", step.label)
            self.assertNotIn("--marker-totals-only", build_paired_pilot_steps(PairedConfig.from_mapping(base), root)[0].command)

    def test_marker_total_proof_allows_disclosed_baseline_failure_only_after_explicit_opt_in(self):
        base = {**self.paired_payload(), "integration_mode": "radio_markers"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_paired_result(root, integration_mode="radio_markers",
                                                marker_totals_only=True, baseline_fault=True)
            step = build_paired_pilot_steps(PairedConfig.from_mapping({**base, "marker_totals_only": True}), root)[0]
            result = validate_result(step, root)
            self.assertTrue(result["valid"], result)
            self.assertTrue(any("baseline counter QA requires review" in w for w in result["warnings"]))
            self.assertTrue(any("excess metrics are unavailable" in w for w in result["warnings"]))
            self.assertEqual(manifest["rows"][0]["marker_diagnostics"]["roles"]["tx"]["counter_qa"]["status"], "review_required")
            implicit_step = build_paired_pilot_steps(PairedConfig.from_mapping(base), root)[0]
            self.assertFalse(validate_result(implicit_step, root)["valid"])

    def test_marker_total_policy_requires_complete_consistent_direct_adc_proof(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True})
        mutations = {
            "valid": False, "reasons": ["invalid"], "constant_range_guard": False,
            "method": "unchecked_total", "guard_qa_includes_stop": False,
            "sample_rate_hz": 1000, "captured_sample_count": 99999, "voltage_mv": 3000,
            "range_code": 5, "guard_window_samples": [25000, 25176], "window_samples": [25001, 25176],
            "counter_anomaly_indices_guard": [25176], "invalid_range_indices_guard": [24998],
            "bit17_indices_guard": [25001], "nonfinite_current_indices_guard": [25000],
            "wire_logic_match_full_capture": False, "wire_sample_count": 99999,
            "marker_window_complete": False, "calibration_valid": False,
            "direct_adc_tolerance_uA": 1e-3, "direct_adc_max_difference_uA": 1.01e-6,
            "direct_adc_compared_samples": 175, "direct_adc_match": False,
            "charge_total_uC": float("inf"), "energy_total_uJ": 50,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.write_paired_result(root, integration_mode="radio_markers", marker_totals_only=True, baseline_fault=True)
            step = build_paired_pilot_steps(config, root)[0]
            for key, value in mutations.items():
                with self.subTest(proof_field=key):
                    manifest = json.loads(json.dumps(original))
                    manifest["rows"][0]["marker_diagnostics"]["roles"]["tx"]["total_qa"][key] = value
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])
            for mutation in ("missing_proof", "wrong_policy", "missing_flag", "missing_warning", "wrong_diagnostic_policy"):
                with self.subTest(mutation=mutation):
                    manifest = json.loads(json.dumps(original))
                    diagnostic = manifest["rows"][0]["marker_diagnostics"]
                    if mutation == "missing_proof":
                        del diagnostic["roles"]["rx"]["total_qa"]
                    elif mutation == "wrong_policy":
                        manifest["energy_policy"] = "legacy_excess"
                    elif mutation == "missing_flag":
                        del manifest["marker_totals_only"]
                    elif mutation == "missing_warning":
                        diagnostic["warnings"] = []
                    else:
                        diagnostic["energy_policy"] = "legacy_excess"
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])

    def test_marker_totals_require_finite_matching_totals_and_unavailable_excess_fields_in_both_csv(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_paired_result(root, integration_mode="radio_markers", marker_totals_only=True)
            step = build_paired_pilot_steps(config, root)[0]
            for role in ("tx", "rx"):
                path = root / role / "summary.csv"
                with path.open(encoding="utf-8", newline="") as stream:
                    original = list(csv.DictReader(stream))
                mutations = [(name, "0") for name in ("baseline_median_uA", "threshold_uA", "charge_excess_uC", "energy_excess_uJ")]
                mutations += [(name, "NaN") for name in ("charge_total_uC", "energy_total_uJ", "tx_mean_uA", "tx_peak_uA")]
                mutations += [("energy_total_uJ", "999"), ("integration_method", "independent_radio_hardware_markers")]
                mutations += [("voltage_mv", "3400")]
                for key, value in mutations:
                    with self.subTest(role=role, field=key):
                        rows = [dict(row) for row in original]
                        rows[0][key] = value
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=original[0])
                            writer.writeheader()
                            writer.writerows(rows)
                        self.assertFalse(validate_result(step, root)["valid"])
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=original[0])
                    writer.writeheader()
                    writer.writerows(original)

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

    def test_filter_aware_opt_in_config_commands_and_fragment_rejection(self):
        base = {**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True}
        old = PairedConfig.from_mapping(base)
        config = PairedConfig.from_mapping({**base, "filter_aware_totals": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(old.filter_aware_totals)
            self.assertNotIn("--filter-aware-totals", build_paired_pilot_steps(old, root)[0].command)
            for builder, count in ((build_paired_pilot_steps, 1), (build_paired_32b_campaign_steps, 21),
                                   (build_paired_campaign_steps, 63)):
                steps = builder(config, root)
                self.assertEqual(len(steps), count)
                self.assertTrue(all(s.command.count("--filter-aware-totals") == 1 for s in steps))
            with self.assertRaisesRegex(ValueError, "fragmented"):
                build_paired_fragmented_campaign_steps(config, root)
            manager = JobManager(sessions_root=root / "sessions")
            with patch.object(manager, "_ensure_paired_guard") as guard:
                with self.assertRaisesRegex(ValueError, "filter-aware"):
                    manager.start("paired_fragmented_campaign", config)
                guard.assert_not_called()
        for changes in ({"filter_aware_totals": "true"}, {"filter_aware_totals": 1},
                        {"filter_aware_totals": True, "marker_totals_only": False},
                        {"filter_aware_totals": True, "integration_mode": "tx_marker"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PairedConfig.from_mapping({**base, **changes})
        self.assertIn('id="pairedFilterAwareTotals" type="checkbox"', HTML)
        self.assertIn("filter_aware_totals:$('pairedFilterAwareTotals').checked", HTML)

    @patch("radio_power_profiler.web_app._revalidate_filter_marker_files")
    def test_filter_proof_requires_explicit_matching_policy_and_retains_baseline_warning(self, replay):
        base = {**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True}
        config = PairedConfig.from_mapping({**base, "filter_aware_totals": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.write_paired_result(root, integration_mode="radio_markers", marker_totals_only=True,
                                                baseline_fault=True)
            step = build_paired_pilot_steps(config, root)[0]
            self.assertFalse(validate_result(step, root)["valid"])
            self.add_filter_proofs(root, manifest)
            result = validate_result(step, root)
            self.assertTrue(result["valid"], result)
            self.assertTrue(any("baseline" in text for text in result["warnings"]))
            self.assertFalse(validate_result(build_paired_pilot_steps(PairedConfig.from_mapping(base), root)[0], root)["valid"])
            for key, value in (("filter_aware_totals", False), ("filter_aware_totals", 1),
                               ("energy_policy", "total_only_with_direct_adc_proof")):
                bad = json.loads(json.dumps(manifest));bad[key] = value
                (root / "pairing.json").write_text(json.dumps(bad), encoding="utf-8")
                self.assertFalse(validate_result(step, root)["valid"])

    @patch("radio_power_profiler.web_app._revalidate_filter_marker_files")
    def test_filter_proof_rejects_missing_nonfinite_and_forged_bound_or_local_qa_fields(self, replay):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers",
                                            "marker_totals_only": True, "filter_aware_totals": True})
        mutations = {
            "filter_replay_match": False, "filter_replay_compared_samples": 176,
            "filter_replay_max_difference_uA": float("nan"), "history_interval_max_width_uA": float("inf"),
            "combined_error_bound_uA": 1e-5, "filter_tolerance_uA": 1,
            "global_adc_domain_values": 81919, "global_state_bounds_A": [float("nan"), 1],
            "global_adc_bounds_A": [2, 1], "global_state_invariant": False, "history_bound_valid": False,
            "history_clean_suffix_start": 25000, "history_last_suspect_index": 100,
            "history_state_converged_samples": {"fast": True, "slow": None},
            "filter_parameters": {"alpha": 0.1, "alpha5": 0.06, "samples": 3},
            "counter_anomaly_indices_guard": [25000], "bit17_indices_guard": [25176],
            "invalid_range_indices_guard": [24998], "nonfinite_current_indices_guard": [25001],
            "filter_replay_nonfinite_indices": [1], "wire_logic_match_full_capture": False,
            "wire_logic_mismatch_count": 1, "wire_sample_count": 99999, "calibration_valid": False,
            "wire_sha256": "bad", "calibration_sha256": "bad", "guard_qa_includes_stop": False,
            "guard_window_samples": [24998, 25176], "range_counts_guard": {"5": 179},
            "charge_interval_uC": [-1, 0], "energy_interval_uJ": [float("nan"), 2],
            "charge_interval_width_uC": -1, "energy_interval_width_uJ": 1,
            "charge_total_uC": float("nan"), "voltage_mv": 3400,
            "outside_counter_anomaly_count": -1,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.add_filter_proofs(root, self.write_paired_result(
                root, integration_mode="radio_markers", marker_totals_only=True))
            step = build_paired_pilot_steps(config, root)[0]
            for role in ("tx", "rx"):
                for name, value in mutations.items():
                    for missing in (False, True):
                        with self.subTest(role=role, field=name, missing=missing):
                            bad = json.loads(json.dumps(original))
                            proof = bad["rows"][0]["marker_diagnostics"]["roles"][role]["total_qa"]
                            if missing:
                                del proof[name]
                            else:
                                proof[name] = value
                            (root / "pairing.json").write_text(json.dumps(bad), encoding="utf-8")
                            self.assertFalse(validate_result(step, root)["valid"], name)

    def test_filter_file_replay_rejects_forged_bounds_and_changed_saved_sources(self):
        import struct
        from radio_power_profiler.filter_marker_totals import prove_filter_marker_total
        from radio_power_profiler.ppk import Capture
        from radio_power_profiler.results import save_raw_capture
        from radio_power_profiler.web_app import _revalidate_filter_marker_files, _validate_filter_marker_total_proof

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

    @patch("radio_power_profiler.web_app._revalidate_filter_marker_files")
    def test_filter_policy_requires_delivery_in_manifest_and_both_csv(self, replay):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers",
                                            "marker_totals_only": True, "filter_aware_totals": True})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.add_filter_proofs(root, self.write_paired_result(
                root, integration_mode="radio_markers", marker_totals_only=True))
            step = build_paired_pilot_steps(config, root)[0]
            for key, value in (("packet_received", False), ("tx_status", "rx_missing"), ("rx_status", "rx_missing")):
                with self.subTest(field=key):
                    bad = json.loads(json.dumps(original));bad["rows"][0][key] = value
                    (root / "pairing.json").write_text(json.dumps(bad), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])
            (root / "pairing.json").write_text(json.dumps(original), encoding="utf-8")
            for role in ("tx", "rx"):
                path = root / role / "summary.csv"
                with path.open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                rows[0]["packet_received"] = "False"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
                self.assertFalse(validate_result(step, root)["valid"])
                rows[0]["packet_received"] = "True"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)

    def test_filter_history_policy_is_versioned_and_v2_is_explicit_in_commands(self):
        base = {**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True,
                "filter_aware_totals": True}
        old = PairedConfig.from_mapping(base)
        current = PairedConfig.from_mapping({**base, "filter_history_policy": "current_equivalence_v1"})
        energy = PairedConfig.from_mapping({**base, "filter_history_policy": "energy_relative_v2"})
        self.assertEqual(old, current)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = build_paired_pilot_steps(old, root)[0].command
            self.assertEqual(legacy, build_paired_pilot_steps(current, root)[0].command)
            self.assertNotIn("--filter-history-policy", legacy)
            for step in build_paired_32b_campaign_steps(energy, root):
                index = step.command.index("--filter-history-policy")
                self.assertEqual(step.command[index + 1], "energy_relative_v2")
            with self.assertRaises(ValueError):
                build_paired_fragmented_campaign_steps(energy, root)
        for value in (None, True, 2, [], "unknown", " energy_relative_v2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PairedConfig.from_mapping({**base, "filter_history_policy": value})
        with self.assertRaises(ValueError):
            PairedConfig.from_mapping({**base, "filter_aware_totals": False,
                                      "filter_history_policy": "energy_relative_v2"})
        self.assertIn('<option value="energy_relative_v2" selected>', HTML)
        self.assertIn("filter_history_policy:$('pairedFilterAwareTotals').checked?$('pairedFilterHistoryPolicy').value:'current_equivalence_v1'", HTML)
        self.assertIn("not instrument accuracy", HTML)

    @patch("radio_power_profiler.web_app._revalidate_filter_marker_files")
    def test_v2_energy_history_accepts_wide_pointwise_bound_but_requires_new_policy(self, replay):
        base = {**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True,
                "filter_aware_totals": True}
        config = PairedConfig.from_mapping({**base, "filter_history_policy": "energy_relative_v2"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.add_filter_proofs(root, self.write_paired_result(
                root, integration_mode="radio_markers", marker_totals_only=True), "energy_relative_v2")
            step = build_paired_pilot_steps(config, root)[0]
            result = validate_result(step, root)
            self.assertTrue(result["valid"], result)
            self.assertEqual(replay.call_count, 10)
            self.assertFalse(validate_result(build_paired_pilot_steps(PairedConfig.from_mapping(base), root)[0], root)["valid"])
            for key, value in (("filter_history_policy", "current_equivalence_v1"),
                               ("filter_history_policy", "unknown"),
                               ("energy_policy", "total_only_with_bounded_filter_replay_proof")):
                with self.subTest(field=key, value=value):
                    bad = json.loads(json.dumps(original));bad[key] = value
                    (root / "pairing.json").write_text(json.dumps(bad), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])

    def test_filter_interval_outward_rounding_accepts_large_total_but_rejects_forged_width(self):
        from radio_power_profiler.web_app import _validate_filter_marker_total_proof

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
        from radio_power_profiler.web_app import _validate_filter_marker_total_proof

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

    @patch("radio_power_profiler.web_app._revalidate_filter_marker_files")
    def test_v2_energy_budget_rejects_missing_nan_forged_or_excessive_bounds(self, replay):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers",
                    "marker_totals_only": True, "filter_aware_totals": True, "filter_history_policy": "energy_relative_v2"})
        mutations = {"schema_version": 1, "history_policy": "current_equivalence_v1",
                     "energy_history_relative_tolerance": 0.1, "energy_history_relative_bound": float("nan"),
                     "energy_history_budget_valid": False, "history_bound_valid": False,
                     "filter_replay_max_difference_uA": 1.1e-6, "combined_error_bound_uA": float("inf")}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.add_filter_proofs(root, self.write_paired_result(
                root, integration_mode="radio_markers", marker_totals_only=True), "energy_relative_v2")
            step = build_paired_pilot_steps(config, root)[0]
            for role in ("tx", "rx"):
                for name, value in mutations.items():
                    for missing in (False, True):
                        with self.subTest(role=role, field=name, missing=missing):
                            bad = json.loads(json.dumps(original))
                            proof = bad["rows"][0]["marker_diagnostics"]["roles"][role]["total_qa"]
                            if missing:
                                del proof[name]
                            else:
                                proof[name] = value
                            (root / "pairing.json").write_text(json.dumps(bad), encoding="utf-8")
                            self.assertFalse(validate_result(step, root)["valid"])
                for half_width, forge_ratio in ((1e-5, False), (1e-5, True), (1e-3, False)):
                    with self.subTest(role=role, half_width=half_width, forged=forge_ratio):
                        bad = json.loads(json.dumps(original))
                        proof = bad["rows"][0]["marker_diagnostics"]["roles"][role]["total_qa"]
                        for quantity, unit in (("charge", "uC"), ("energy", "uJ")):
                            nominal = proof[f"{quantity}_total_{unit}"]
                            low, high = nominal * (1 - half_width), nominal * (1 + half_width)
                            proof[f"{quantity}_interval_{unit}"] = [low, high]
                            proof[f"{quantity}_interval_width_{unit}"] = high - low
                        low, high = proof["energy_interval_uJ"]
                        ratio = math.nextafter(proof["energy_interval_width_uJ"] / min(abs(low), abs(high)), math.inf)
                        proof["energy_history_relative_bound"] = 0.0 if forge_ratio else ratio
                        (root / "pairing.json").write_text(json.dumps(bad), encoding="utf-8")
                        result = validate_result(step, root)
                        self.assertEqual(result["valid"], half_width == 1e-5 and not forge_ratio, result)

    @patch("radio_power_profiler.web_app._revalidate_filter_marker_files")
    def test_resume_preserves_archived_explicit_filter_v1_and_rejects_version_change(self, replay):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(sessions_root=Path(temporary))
            config, session, manifest = self.write_halted_paired_campaign(manager.sessions_root,
                                                                         filter_aware_totals=True)
            manifest["config"].pop("filter_history_policy")
            path = session / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            before = path.read_bytes()
            v2 = PairedConfig.from_mapping({**asdict(config), "filter_history_policy": "energy_relative_v2"})
            with self.assertRaisesRegex(ValueError, "original confirmed"):
                manager.resume_paired_campaign(session.name, v2)
            self.assertEqual(path.read_bytes(), before)
            with patch("radio_power_profiler.web_app.threading.Thread") as worker:
                manager.resume_paired_campaign(session.name, config)
                worker.return_value.start.assert_called_once()
            self.assertEqual(manager.status()["completed_steps"], 1)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["steps"][0]["attempts"]), 1)
            self.assertNotIn("--filter-history-policy", saved["steps"][0]["command"])

    def test_resume_accepts_legacy_absent_filter_flag_but_rejects_opt_in_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(sessions_root=Path(temporary))
            config, session, manifest = self.write_halted_paired_campaign(manager.sessions_root)
            manifest["config"].pop("filter_aware_totals", None)
            manifest["config"].pop("filter_history_policy", None)
            path = session / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            before = path.read_bytes()
            changed = PairedConfig.from_mapping({**asdict(config), "filter_aware_totals": True})
            with self.assertRaisesRegex(ValueError, "original confirmed"):
                manager.resume_paired_campaign(session.name, changed)
            self.assertEqual(path.read_bytes(), before)
            with patch("radio_power_profiler.web_app.threading.Thread") as worker:
                manager.resume_paired_campaign(session.name, config)
                worker.return_value.start.assert_called_once()

    def test_paired_campaign_validation_binds_manifest_preflight_and_both_summaries_to_condition(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        condition = {"payload_bytes": 32, "rf_profile": "GFSK200", "tx_power_dbm": 13}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_campaign_steps(config, root)[0]
            original = self.write_paired_result(root, integration_mode="radio_markers", condition=condition)
            self.assertTrue(validate_result(step, root)["valid"])
            for field, wrong in (("payload_bytes", 8), ("rf_profile", "GFSK50"), ("tx_power_dbm", 0)):
                with self.subTest(field=field):
                    manifest = json.loads(json.dumps(original))
                    manifest[field] = wrong
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])
            for role in ("tx", "rx"):
                manifest = json.loads(json.dumps(original))
                manifest["endpoints"][role]["modem_preflight"]["config"]["PWR"] = "0"
                (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                self.assertFalse(validate_result(step, root)["valid"])
            (root / "pairing.json").write_text(json.dumps(original), encoding="utf-8")
            for role in ("tx", "rx"):
                path = root / role / "summary.csv"
                with path.open(encoding="utf-8", newline="") as stream:
                    original_rows = list(csv.DictReader(stream))
                for key, value in (("payload_bytes", "8"),
                                   ("parameters_json", json.dumps({"rf_profile": "GFSK50", "tx_power_dbm": 13}))):
                    with self.subTest(role=role, key=key):
                        rows = [dict(row) for row in original_rows]
                        rows[0][key] = value
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=original_rows[0])
                            writer.writeheader()
                            writer.writerows(rows)
                        self.assertFalse(validate_result(step, root)["valid"])
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=original_rows[0])
                    writer.writeheader()
                    writer.writerows(original_rows)

    def test_local_radio_markers_accept_distinct_durations_and_retained_rx_loss(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_paired_result(root, missing_packet=True, integration_mode="radio_markers")
            result = validate_result(build_paired_pilot_steps(config, root)[0], root)
            self.assertTrue(result["valid"], result)
            self.assertEqual(result["integration_mode"], "radio_markers")
            self.assertTrue(any("missing packet retained" in text for text in result["warnings"]))

    def test_local_radio_markers_require_firmware_roles_edges_and_conservative_qa(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        mutations = ("common_source", "wrong_local_source", "width_comparison", "old_tx_firmware", "old_rx_firmware",
                     "wrong_role", "missing_selection", "selection_error", "wrong_query", "query_without_ok",
                     "rx_rearmed", "missing_arming_policy", "missing_pulse", "unchecked_wire", "baseline_anomaly",
                     "malformed_role")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(config, root)[0]
            original = self.write_paired_result(root, integration_mode="radio_markers")
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    manifest = json.loads(json.dumps(original))
                    marker = manifest["rows"][0]["marker_diagnostics"]
                    preflight = manifest["endpoints"]["rx"]["modem_preflight"]
                    if mutation == "common_source":
                        marker["source"] = "TX DIO17 / RAT_GPO0 / active HIGH"
                    elif mutation == "wrong_local_source":
                        marker["roles"]["rx"]["source"] = "TX DIO17 / RAT_GPO0 / active HIGH"
                    elif mutation == "width_comparison":
                        marker["width_comparison"] = "equal_widths"
                    elif mutation == "old_tx_firmware":
                        manifest["endpoints"]["tx"]["modem_preflight"]["firmware_version"] = "0.3.1"
                    elif mutation == "old_rx_firmware":
                        preflight["firmware_version"] = "0.3.1"
                    elif mutation == "wrong_role":
                        preflight["radio_marker"]["role"] = "TX"
                    elif mutation == "missing_selection":
                        del preflight["marker_set_command"]
                    elif mutation == "selection_error":
                        preflight["marker_set_reply"] = ["#ERROR: failed", "OK"]
                    elif mutation == "wrong_query":
                        preflight["marker_reply"] = ["+MARKER:ROLE=TX,DIO=17,SOURCE=RAT_GPO0,ACTIVE=HIGH", "OK"]
                    elif mutation == "query_without_ok":
                        preflight["marker_reply"].pop()
                    elif mutation == "rx_rearmed":
                        manifest["rx_rearm_between_transfers"] = True
                    elif mutation == "missing_arming_policy":
                        del manifest["rx_arming_policy"]
                    elif mutation == "missing_pulse":
                        marker["roles"]["rx"]["pulse_count"] = 0
                    elif mutation == "unchecked_wire":
                        marker["roles"]["rx"]["counter_qa"] = {"status": "not_checked"}
                    elif mutation == "baseline_anomaly":
                        marker["roles"]["tx"]["counter_qa"]["relevant_anomaly_count"] = 1
                    elif mutation == "malformed_role":
                        marker["roles"]["rx"] = []
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])

    def test_local_radio_markers_reject_common_tx_or_modeled_fallback(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        for mode in ("modeled", "tx_marker"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_paired_result(root, integration_mode=mode)
                self.assertFalse(validate_result(build_paired_pilot_steps(config, root)[0], root)["valid"])

    def test_local_radio_markers_require_correct_method_and_local_csv_window(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_paired_result(root, integration_mode="radio_markers")
            step = build_paired_pilot_steps(config, root)[0]
            for role in ("tx", "rx"):
                path = root / role / "summary.csv"
                with path.open(encoding="utf-8", newline="") as stream:
                    original = list(csv.DictReader(stream))
                for key, value in (("integration_method", "common_tx_hardware_marker"),
                                   ("integration_windows_ms", "[[0,1.76]]")):
                    with self.subTest(role=role, key=key):
                        rows = [dict(row) for row in original]
                        rows[0][key] = value
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=original[0])
                            writer.writeheader()
                            writer.writerows(rows)
                        self.assertFalse(validate_result(step, root)["valid"])
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=original[0])
                    writer.writeheader()
                    writer.writerows(original)

    def test_paired_marker_accepts_consistent_measured_edges_and_keeps_packet_loss(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "tx_marker"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(config, root)[0]
            self.write_paired_result(root, missing_packet=True, integration_mode="tx_marker")
            result = validate_result(step, root)
            self.assertTrue(result["valid"], result)
            self.assertEqual(result["integration_mode"], "tx_marker")
            self.assertTrue(any("missing packet retained" in text for text in result["warnings"]))

    def test_paired_marker_rejects_legacy_results_without_silent_fallback(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "tx_marker"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_paired_result(root)
            result = validate_result(build_paired_pilot_steps(config, root)[0], root)
            self.assertFalse(result["valid"])
            self.assertTrue(any("integration mode" in error for error in result["errors"]))

    def test_paired_marker_requires_both_complete_consistent_d0_pulses(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "tx_marker"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(config, root)[0]
            original = self.write_paired_result(root, integration_mode="tx_marker")
            mutations = ("missing", "invalid", "wrong_bit", "wrong_source", "reason", "missing_rx", "multiple_pulses",
                         "empty_window", "fractional_sample", "outside_raw", "duration_mismatch",
                         "missing_timing", "wrong_rate", "missing_mode", "unchecked_wire", "wire_anomaly")
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    manifest = json.loads(json.dumps(original))
                    transfer = manifest["rows"][0]
                    evidence = transfer["marker_diagnostics"]
                    if mutation == "missing":
                        del transfer["marker_diagnostics"]
                    elif mutation == "invalid":
                        evidence["valid"] = False
                    elif mutation == "wrong_bit":
                        evidence["marker_bit"] = 1
                    elif mutation == "wrong_source":
                        evidence["source"] = "software host trigger"
                    elif mutation == "reason":
                        evidence["reasons"] = ["multiple pulses"]
                    elif mutation == "missing_rx":
                        del evidence["roles"]["rx"]
                    elif mutation == "multiple_pulses":
                        evidence["roles"]["rx"]["pulse_count"] = 2
                    elif mutation == "empty_window":
                        evidence["roles"]["rx"]["window_samples"] = [24910, 24910]
                    elif mutation == "fractional_sample":
                        evidence["roles"]["rx"]["window_samples"] = [24910.0, 25086]
                    elif mutation == "outside_raw":
                        evidence["roles"]["rx"]["window_samples"] = [99999, 100175]
                    elif mutation == "duration_mismatch":
                        evidence["roles"]["rx"]["duration_samples"] = 175
                    elif mutation == "missing_timing":
                        del transfer["timing"]
                    elif mutation == "wrong_rate":
                        manifest["sample_rate_hz"] = 1000
                    elif mutation == "missing_mode":
                        del manifest["integration_mode"]
                    elif mutation == "unchecked_wire":
                        evidence["roles"]["rx"]["counter_qa"] = {"status": "not_checked"}
                    elif mutation == "wire_anomaly":
                        evidence["roles"]["tx"]["counter_qa"]["relevant_anomaly_count"] = 1
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])

    def test_paired_marker_rejects_wrong_method_or_windows_in_either_summary(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "tx_marker"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(config, root)[0]
            self.write_paired_result(root, integration_mode="tx_marker")
            for role in ("tx", "rx"):
                path = root / role / "summary.csv"
                with path.open(encoding="utf-8", newline="") as stream:
                    original = list(csv.DictReader(stream))
                for key, value in (("integration_method", "fixed_modeled_airtime"),
                                   ("event_duration_ms", "4.76"),
                                   ("integration_windows_ms", "[[0,1.76]]"),
                                   ("integration_windows_ms", "[[0,1],[2,3]]")):
                    with self.subTest(role=role, key=key, value=value):
                        rows = [dict(row) for row in original]
                        rows[0][key] = value
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=original[0])
                            writer.writeheader()
                            writer.writerows(rows)
                        self.assertFalse(validate_result(step, root)["valid"])
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=original[0])
                    writer.writeheader()
                    writer.writerows(original)

    def test_paired_marker_accepts_two_sample_width_difference_but_rejects_three(self):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "tx_marker"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(config, root)[0]
            original = self.write_paired_result(root, integration_mode="tx_marker")
            path = root / "rx" / "summary.csv"
            with path.open(encoding="utf-8", newline="") as stream:
                original_rows = list(csv.DictReader(stream))
            for difference in (2, 3):
                with self.subTest(difference_samples=difference):
                    manifest = json.loads(json.dumps(original))
                    detail = manifest["rows"][0]["marker_diagnostics"]["roles"]["rx"]
                    detail["window_samples"][1] += difference
                    detail["duration_samples"] += difference
                    rows = [dict(row) for row in original_rows]
                    rows[0]["event_duration_ms"] = (176 + difference) / 100
                    rows[0]["integration_windows_ms"] = json.dumps([[49.1, (5086 + difference) / 100]])
                    with path.open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=original_rows[0])
                        writer.writeheader()
                        writer.writerows(rows)
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    result = validate_result(step, root)
                    self.assertEqual(result["valid"], difference == 2, result)

    def test_paired_validation_keeps_radio_loss_and_requires_matching_complete_pair(self):
        config = PairedConfig.from_mapping(self.paired_payload())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(config, root)[0]
            manifest = self.write_paired_result(root, missing_packet=True)
            valid = validate_result(step, root)
            self.assertTrue(valid["valid"], valid)
            self.assertIn("without retry", valid["warnings"][0])
            for mutation in ("duplicate", "partial", "failed", "identity", "analysis"):
                with self.subTest(mutation=mutation):
                    modified = json.loads(json.dumps(manifest))
                    if mutation == "duplicate":
                        modified["rows"][1] = modified["rows"][0]
                    elif mutation == "partial":
                        modified["rows"].pop()
                    elif mutation == "failed":
                        modified["status"] = "failed"
                    elif mutation == "identity":
                        modified["rows"][0]["paired_transfer_id"] = "different-session:run_00001"
                    else:
                        path = root / "rx" / "summary.csv"
                        path.write_text(path.read_text(encoding="utf-8").replace("run_00001,ok,", "run_00001,analysis_review_required,broken"), encoding="utf-8")
                    (root / "pairing.json").write_text(json.dumps(modified), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])

    def test_paired_job_preserves_root_logs_and_loss_without_guard_or_callback(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            def fake_process(command, attempt_log):
                attempt_log.parent.mkdir(parents=True)
                attempt_log.write_text("five synthetic paired transfers\n", encoding="utf-8")
                root = Path(command[command.index("--output") + 1]) / "pilot"
                self.write_paired_result(root, missing_packet=True)
                return 0, str(root)
            with (patch.object(manager, "_run_process", side_effect=fake_process) as process,
                  patch.object(manager, "_ensure_current_path_on") as guard,
                  patch.object(manager, "_ensure_paired_guard") as paired_guard,
                  patch.object(manager, "_release_current_path_guard") as release,
                  patch.object(manager, "_schedule_codex_callback") as callback):
                manager.start("paired_pilot", PairedConfig.from_mapping(self.paired_payload()))
                manager._thread.join(timeout=5)
                self.assertFalse(manager._thread.is_alive())
                status = manager.status()
                self.assertEqual(status["state"], "completed", status)
                process.assert_called_once()
                guard.assert_not_called()
                release.assert_not_called()
                callback.assert_not_called()
                paired_guard.assert_called_once()
            manifest = json.loads((Path(status["session_dir"]) / "manifest.json").read_text(encoding="utf-8"))
            step = manifest["steps"][0]
            self.assertEqual(len(step["attempts"]), 1)
            self.assertTrue((Path(step["accepted_result"]) / "pairing.json").is_file())
            self.assertTrue(Path(step["attempts"][0]["log_file"]).is_file())
            self.assertEqual(manifest["config"]["voltage_provenance"], self.paired_payload()["voltage_provenance"])

    def test_failed_paired_attempt_is_preserved_without_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            def failed_process(command, attempt_log):
                attempt_log.parent.mkdir(parents=True)
                attempt_log.write_text("synthetic capture failure\n", encoding="utf-8")
                root = Path(command[command.index("--output") + 1]) / "partial"
                root.mkdir(parents=True)
                (root / "pairing.json").write_text('{"status":"failed","rows":[]}', encoding="utf-8")
                return 1, ""
            with (patch.object(manager, "_run_process", side_effect=failed_process) as process,
                  patch.object(manager, "_ensure_paired_guard"),
                  patch.object(manager, "_ensure_current_path_on") as guard):
                manager.start("paired_pilot", PairedConfig.from_mapping(self.paired_payload()))
                manager._thread.join(timeout=5)
                status = manager.status()
                self.assertEqual(status["state"], "completed_with_errors", status)
                process.assert_called_once()
                guard.assert_not_called()
            step = status["steps"][0]
            self.assertEqual(step["accepted_result"], "")
            self.assertEqual(len(step["attempts"]), 1)
            self.assertTrue((Path(step["attempts"][0]["result_dir"]) / "pairing.json").is_file())

    def test_paired_campaign_halts_after_protocol_or_quality_failure_and_preserves_attempts(self):
        for failure in ("protocol", "quality"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                manager = JobManager(Path(temporary))
                config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers"})
                calls = []
                def fake_process(command, attempt_log):
                    calls.append(command)
                    attempt_log.parent.mkdir(parents=True, exist_ok=True)
                    attempt_log.write_text("synthetic paired campaign batch\n", encoding="utf-8")
                    root = Path(command[command.index("--output") + 1]) / "batch"
                    condition = {"payload_bytes": int(command[command.index("--payload-bytes") + 1]),
                                 "rf_profile": command[command.index("--rf-profile") + 1],
                                 "tx_power_dbm": int(command[command.index("--tx-power-dbm") + 1])}
                    manifest = self.write_paired_result(root, integration_mode="radio_markers", condition=condition)
                    if len(calls) == 2:
                        if failure == "protocol":
                            manifest["status"] = "failed"
                        else:
                            manifest["rows"][0]["marker_diagnostics"]["roles"]["tx"]["counter_qa"]["relevant_anomaly_count"] = 1
                        (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                    return (1 if len(calls) == 2 and failure == "protocol" else 0), str(root)
                with (patch.object(manager, "_run_process", side_effect=fake_process),
                      patch.object(manager, "_ensure_paired_guard") as paired_guard,
                      patch.object(manager, "_ensure_current_path_on") as single_guard,
                      patch.object(manager, "_schedule_codex_callback") as callback):
                    manager.start("paired_campaign", config)
                    manager._thread.join(timeout=5)
                    self.assertFalse(manager._thread.is_alive())
                    status = manager.status()
                    self.assertEqual(status["state"], "failed", status)
                    self.assertEqual(len(calls), 2, "Do not retry or start a later batch after failure")
                    self.assertEqual((status["completed_steps"], status["failed_steps"]), (1, 1))
                    self.assertEqual(status["halted_on_failure"], status["steps"][1]["step_id"])
                    self.assertTrue(all(step["status"] == "pending" for step in status["steps"][2:]))
                    self.assertEqual(len(status["steps"][1]["attempts"]), 1)
                    self.assertTrue((Path(status["steps"][1]["attempts"][0]["result_dir"]) / "pairing.json").is_file())
                    self.assertTrue(Path(status["steps"][1]["attempts"][0]["log_file"]).is_file())
                    paired_guard.assert_called_once_with(config)
                    single_guard.assert_not_called()
                    callback.assert_not_called()

    def test_32b_campaign_dispatch_completes_105_pairs_or_halts_on_first_fault_without_retry(self):
        for outcome in ("complete", "protocol", "proof"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                manager = JobManager(Path(temporary))
                config = PairedConfig.from_mapping({**self.paired_payload(), "interface_label": "ESP32",
                                                    "integration_mode": "radio_markers", "marker_totals_only": True})
                calls = []
                def process(command, log):
                    calls.append(command)
                    log.parent.mkdir(parents=True, exist_ok=True)
                    log.write_text("Synthetic 32 B batch\n", encoding="utf-8")
                    result = Path(command[command.index("--output") + 1]) / "batch"
                    condition = {"payload_bytes": int(command[command.index("--payload-bytes") + 1]),
                                 "rf_profile": command[command.index("--rf-profile") + 1],
                                 "tx_power_dbm": int(command[command.index("--tx-power-dbm") + 1])}
                    self.assertEqual(condition["payload_bytes"], 32)
                    pairing = self.write_paired_result(result, integration_mode="radio_markers",
                                                       marker_totals_only=True, condition=condition)
                    pairing["interface_label"] = "ESP32"
                    if len(calls) == 2 and outcome == "proof":
                        pairing["rows"][0]["marker_diagnostics"]["roles"]["rx"]["total_qa"]["direct_adc_match"] = False
                    (result / "pairing.json").write_text(json.dumps(pairing), encoding="utf-8")
                    return (1 if len(calls) == 2 and outcome == "protocol" else 0), str(result)
                with (patch.object(manager, "_run_process", side_effect=process),
                      patch.object(manager, "_ensure_paired_guard") as guard,
                      patch.object(manager, "_ensure_current_path_on") as single_guard,
                      patch.object(manager, "_schedule_codex_callback") as callback):
                    manager.start("paired_32b_campaign", config)
                    manager._thread.join(timeout=10)
                    self.assertFalse(manager._thread.is_alive())
                    status = manager.status()
                    self.assertEqual(status["kind"], "paired_32b_campaign")
                    self.assertEqual(status["config"], asdict(config))
                    self.assertEqual(status["total_steps"], 21)
                    expected_completed = 21 if outcome == "complete" else 1
                    self.assertEqual(status["completed_steps"], expected_completed)
                    self.assertEqual(len(calls), 21 if outcome == "complete" else 2)
                    self.assertEqual(status["state"], "completed" if outcome == "complete" else "failed")
                    if outcome == "complete":
                        self.assertEqual(sum(s["expected_rows"] for s in status["steps"] if s["accepted_result"]), 105)
                        self.assertEqual(status["failed_steps"], 0)
                    else:
                        failed = status["steps"][1]
                        self.assertEqual(status["halted_on_failure"], failed["step_id"])
                        self.assertEqual(len(failed["attempts"]), 1)
                        self.assertFalse(failed["accepted_result"])
                        self.assertTrue(Path(failed["attempts"][0]["result_dir"]).is_dir())
                        self.assertTrue(all(s["status"] == "pending" for s in status["steps"][2:]))
                    guard.assert_called_once_with(config)
                    single_guard.assert_not_called()
                    callback.assert_not_called()

    def test_paired_campaign_rejects_legacy_mode_before_creating_session_or_thread(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            with self.assertRaisesRegex(ValueError, "radio_markers"):
                manager.start("paired_campaign", PairedConfig.from_mapping(self.paired_payload()))
            self.assertIsNone(manager._thread)
            self.assertFalse(list(Path(temporary).iterdir()))

    def test_fragmented_campaign_halts_without_retry_and_restores_paired_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers", "marker_totals_only": True})
            calls = []
            def fake_process(command, attempt_log):
                calls.append(command)
                attempt_log.parent.mkdir(parents=True, exist_ok=True)
                attempt_log.write_text("fragmented batch\n", encoding="utf-8")
                root = Path(command[command.index("--output") + 1]) / "batch"
                manifest = self.write_fragmented_result(root, int(command[command.index("--payload-bytes") + 1]),
                                                        command[command.index("--rf-profile") + 1])
                if len(calls) == 2:
                    manifest["rows"][0]["marker_diagnostics"]["roles"]["rx"]["frame_proofs"][-1]["valid"] = False
                    (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
                return 0, str(root)
            with (patch.object(manager, "_run_process", side_effect=fake_process),
                  patch.object(manager, "_ensure_paired_guard") as guard,
                  patch.object(manager, "_ensure_current_path_on") as single_guard):
                manager.start("paired_fragmented_campaign", config)
                manager._thread.join(timeout=5)
                self.assertFalse(manager._thread.is_alive())
                status = manager.status()
                self.assertEqual(status["state"], "failed", status)
                self.assertEqual((status["total_steps"], status["completed_steps"], status["failed_steps"]), (21, 1, 1))
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(status["steps"][1]["attempts"]), 1)
                self.assertTrue(all(step["status"] == "pending" for step in status["steps"][2:]))
                self.assertTrue(Path(status["steps"][0]["accepted_result"]).is_dir())
                guard.assert_called_once_with(config)
                single_guard.assert_not_called()

    def write_halted_paired_campaign(self, sessions_root, *, kind="paired_campaign", interface="CH340",
                                    filter_aware_totals=False):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers",
                                            "marker_totals_only": True, "interface_label": interface,
                                            "filter_aware_totals": filter_aware_totals})
        session = sessions_root / f"halted_{kind}"
        session.mkdir()
        builder = build_paired_32b_campaign_steps if kind == "paired_32b_campaign" else build_paired_campaign_steps
        steps = builder(config, session)
        accepted = Path(steps[0].command[steps[0].command.index("--output") + 1]) / "accepted"
        pairing = self.write_paired_result(accepted, integration_mode="radio_markers", marker_totals_only=True,
            baseline_fault=True, condition={"payload_bytes": 32, "rf_profile": "GFSK200", "tx_power_dbm": 13})
        if filter_aware_totals:
            self.add_filter_proofs(accepted, pairing)
        for key in ("profile_id", "interface_label", "ppk_mode", "voltage_confirmed", "voltage_provenance"):
            pairing[key] = getattr(config, key)
        for role in ("tx", "rx"):
            for name in ("radio_port", "ppk_port", "voltage_mv", "identity"):
                pairing["endpoints"][role][name] = getattr(config, f"{role}_{name}")
            pairing["endpoints"][role]["ppk_usb"] = {"serial_number": f"PPK_{role.upper()}"}
        (accepted / "pairing.json").write_text(json.dumps(pairing), encoding="utf-8")
        steps[0].accepted_result = str(accepted)
        steps[0].status = "completed"
        steps[0].validation = validate_result(steps[0], accepted)
        self.assertTrue(steps[0].validation["valid"], steps[0].validation)
        partial = Path(steps[1].command[steps[1].command.index("--output") + 1]) / "preflight_failed"
        partial.mkdir(parents=True)
        (partial / "pairing.json").write_text('{"status":"failed","rows":[],"error":"write timeout"}', encoding="utf-8")
        steps[1].status = "failed"
        steps[1].validation = {"valid": False, "errors": ["Process exited with code 1"]}
        for step, result, code in ((steps[0], accepted, 0), (steps[1], partial, 1)):
            log = session / "logs" / f"{step.step_id}_attempt_01.log"
            log.parent.mkdir(exist_ok=True)
            log.write_text(f"Original attempt for {step.step_id}\n", encoding="utf-8")
            step.attempts = [{"attempt": 1, "result_dir": str(result), "return_code": code,
                              "log_file": str(log), "validation": step.validation.copy()}]
        manifest = {"state": "failed", "kind": kind, "config": asdict(config),
                    "session_dir": str(session), "steps": [step.public() for step in steps],
                    "started_utc": "original-start", "finished_utc": "original-finish", "total_steps": len(steps),
                    "current_step": 2, "current_label": "", "completed_steps": 1, "failed_steps": 1,
                    "quick_verdict": None, "message": "Halted", "halted_on_failure": steps[1].step_id}
        (session / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").replace("\n", "\r\n").encode("utf-8"))
        (session / "session.log").write_text("Original campaign log\n", encoding="utf-8")
        return config, session, manifest

    def write_halted_fragmented_campaign(self, sessions_root, accepted_count=15):
        config = PairedConfig.from_mapping({**self.paired_payload(), "integration_mode": "radio_markers",
                                            "marker_totals_only": True})
        session = sessions_root / "halted_fragmented_campaign"
        session.mkdir()
        steps = build_paired_fragmented_campaign_steps(config, session)
        for index, step in enumerate(steps[:accepted_count + 1]):
            result = Path(step.command[step.command.index("--output") + 1]) / "original_attempt"
            pairing = self.write_fragmented_result(result, int(step.command[step.command.index("--payload-bytes") + 1]),
                                                  step.command[step.command.index("--rf-profile") + 1])
            for key in ("profile_id", "interface_label", "ppk_mode", "voltage_confirmed", "voltage_provenance"):
                pairing[key] = getattr(config, key)
            for role in ("tx", "rx"):
                for name in ("radio_port", "ppk_port", "voltage_mv", "identity"):
                    pairing["endpoints"][role][name] = getattr(config, f"{role}_{name}")
                pairing["endpoints"][role]["ppk_usb"] = {"serial_number": f"PPK_{role.upper()}"}
            failed = index == accepted_count
            if failed:
                pairing.update(status="failed", rows=pairing["rows"][:3], errors=["RX marker has extra pulses"])
                pairing["rows"][-1]["status"] = "analysis_review_required"
                pairing["rows"][-1]["marker_diagnostics"]["roles"]["rx"]["pulse_count"] += 2
                for role in ("tx", "rx"):
                    path = result / role / "summary.csv"
                    with path.open(encoding="utf-8", newline="") as stream:
                        rows = list(csv.DictReader(stream))[:3]
                    with path.open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=rows[0])
                        writer.writeheader()
                        writer.writerows(rows)
                    for run in (4, 5):
                        (result / role / "raw" / f"run_{run:05d}.csv.gz").unlink()
            (result / "pairing.json").write_text(json.dumps(pairing), encoding="utf-8")
            step.status = "failed" if failed else "completed"
            step.accepted_result = "" if failed else str(result)
            step.validation = validate_result(step, result)
            self.assertEqual(step.validation["valid"], not failed, step.validation)
            log = session / "logs" / f"{step.step_id}_attempt_01.log"
            log.parent.mkdir(exist_ok=True)
            log.write_text("Original fragmented attempt\n", encoding="utf-8")
            step.attempts = [{"attempt": 1, "result_dir": str(result), "return_code": int(failed),
                              "log_file": str(log), "validation": step.validation.copy()}]
        manifest = {"state": "failed", "kind": "paired_fragmented_campaign", "config": asdict(config),
                    "session_dir": str(session), "steps": [step.public() for step in steps],
                    "started_utc": "original-start", "finished_utc": "original-finish", "total_steps": 21,
                    "current_step": accepted_count + 1, "current_label": "", "completed_steps": accepted_count,
                    "failed_steps": 1, "quick_verdict": None, "message": "Halted",
                    "halted_on_failure": steps[accepted_count].step_id}
        (session / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        (session / "session.log").write_text("Original fragmented campaign log\n", encoding="utf-8")
        return config, session, manifest

    def test_fragmented_resume_preserves_15_accepted_batches_and_three_partial_rows_then_runs_full_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            sessions = Path(temporary)
            config, session, previous = self.write_halted_fragmented_campaign(sessions)
            old_files = {path: path.read_bytes() for path in session.rglob("*") if path.is_file()}
            calls = []
            def process(command, attempt_log):
                calls.append(command)
                attempt_log.parent.mkdir(parents=True, exist_ok=True)
                attempt_log.write_text("Explicit fragmented resume\n", encoding="utf-8")
                self.assertEqual(command[command.index("--repetitions") + 1], "5")
                self.assertIn("--fragmented", command)
                result = Path(command[command.index("--output") + 1]) / "fresh_full_batch"
                self.write_fragmented_result(result, int(command[command.index("--payload-bytes") + 1]),
                                             command[command.index("--rf-profile") + 1])
                return (0 if len(calls) == 1 else 1), str(result)
            manager = JobManager(sessions)
            with (patch.object(manager, "_run_process", side_effect=process),
                  patch.object(manager, "_ensure_paired_guard") as guard,
                  patch.object(manager, "_ensure_current_path_on") as single_guard):
                manager.resume_paired_campaign(session.name, config)
                manager._thread.join(timeout=10)
                self.assertFalse(manager._thread.is_alive())
                status = manager.status()
                self.assertEqual(status["state"], "failed", status)
                self.assertEqual(status["kind"], "paired_fragmented_campaign")
                self.assertEqual((status["completed_steps"], status["failed_steps"]), (16, 1))
                self.assertEqual(calls, [previous["steps"][15]["command"], previous["steps"][16]["command"]])
                for before, after in zip(previous["steps"][:15], status["steps"][:15]):
                    self.assertEqual(after["accepted_result"], before["accepted_result"])
                    self.assertEqual(after["attempts"], before["attempts"])
                self.assertEqual(status["steps"][15]["attempts"][0], previous["steps"][15]["attempts"][0])
                self.assertEqual([a["attempt"] for a in status["steps"][15]["attempts"]], [1, 2])
                self.assertTrue(status["steps"][15]["attempts"][1]["log_file"].endswith("attempt_02.log"))
                self.assertTrue(all(step["status"] == "pending" for step in status["steps"][17:]))
                resumed = status["resumes"][0]
                self.assertEqual(len(resumed["revalidated_results"]), 15)
                self.assertEqual(len(resumed["scheduled_step_ids"]), 6)
                self.assertEqual(Path(resumed["previous_manifest"]).read_bytes(), old_files[session / "manifest.json"])
                new_pairing = json.loads((Path(status["steps"][15]["accepted_result"]) / "pairing.json").read_text())
                self.assertEqual(len(new_pairing["rows"]), 5)
                old_pairing = Path(previous["steps"][15]["attempts"][0]["result_dir"]) / "pairing.json"
                self.assertEqual(len(json.loads(old_pairing.read_text())["rows"]), 3)
                guard.assert_called_once_with(config)
                single_guard.assert_not_called()
            for path, data in old_files.items():
                if path not in {session / "manifest.json", session / "session.log"}:
                    self.assertEqual(path.read_bytes(), data, str(path))

    def test_fragmented_resume_rejects_forged_matrix_policy_proof_or_completed_session_without_writes(self):
        for mutation in ("config", "interface", "policy", "forged_policy", "matrix", "kind", "proof", "receipt", "completed", "running"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                sessions = Path(temporary)
                config, session, manifest = self.write_halted_fragmented_campaign(sessions, accepted_count=1)
                accepted = Path(manifest["steps"][0]["accepted_result"])
                request = config
                if mutation == "config":
                    request = PairedConfig.from_mapping({**asdict(config), "rx_identity": "another board"})
                elif mutation == "interface":
                    request = PairedConfig.from_mapping({**asdict(config), "interface_label": "ESP32"})
                elif mutation in {"policy", "forged_policy"}:
                    request = PairedConfig.from_mapping({**asdict(config), "marker_totals_only": False})
                    if mutation == "forged_policy":
                        manifest["config"] = asdict(request)
                elif mutation == "matrix":
                    manifest["steps"][1]["command"].remove("--fragmented")
                elif mutation == "kind":
                    manifest["kind"] = "paired_campaign"
                elif mutation == "proof":
                    path = accepted / "pairing.json"
                    pairing = json.loads(path.read_text())
                    pairing["rows"][0]["marker_diagnostics"]["roles"]["rx"]["frame_proofs"][-1]["direct_adc_match"] = False
                    path.write_text(json.dumps(pairing), encoding="utf-8")
                elif mutation == "receipt":
                    path = accepted / "rx" / "summary.csv"
                    path.write_text(path.read_text().replace("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_", "missing", 1), encoding="utf-8")
                else:
                    manifest["state"] = mutation
                manifest_path = session / "manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                before = manifest_path.read_bytes()
                manager = JobManager(sessions)
                with (patch.object(manager, "_run_process") as process,
                      patch.object(manager, "_release_paired_guard") as release):
                    with self.assertRaises(ValueError):
                        manager.resume_paired_campaign(session.name, request)
                    process.assert_not_called()
                    release.assert_not_called()
                    self.assertIsNone(manager._thread)
                self.assertEqual(before, manifest_path.read_bytes())
                self.assertFalse((session / "resume_history").exists())

    def test_fragmented_resume_respects_active_job_and_single_guard_before_any_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            sessions = Path(temporary)
            config, session, _ = self.write_halted_fragmented_campaign(sessions, accepted_count=1)
            manager = JobManager(sessions)
            manager._thread = types.SimpleNamespace(is_alive=lambda: True)
            with self.assertRaisesRegex(RuntimeError, "already running"):
                manager.resume_paired_campaign(session.name, config)
            manager._thread = None
            manager._ppk_guard = object()
            with self.assertRaisesRegex(RuntimeError, "single-PPK guard"):
                manager.resume_paired_campaign(session.name, config)
            self.assertFalse((session / "resume_history").exists())

    def test_paired_campaign_explicit_resume_skips_revalidated_batch_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            sessions = Path(temporary)
            config, session, previous = self.write_halted_paired_campaign(sessions)
            old_files = {path: path.read_bytes() for path in session.rglob("*") if path.is_file()}
            manager = JobManager(sessions)  # Resume works after a server restart.
            calls = []
            def process(command, attempt_log):
                calls.append(command)
                attempt_log.parent.mkdir(parents=True, exist_ok=True)
                attempt_log.write_text("New explicit resume attempt\n", encoding="utf-8")
                result = Path(command[command.index("--output") + 1]) / "resume_result"
                condition = {"payload_bytes": int(command[command.index("--payload-bytes") + 1]),
                             "rf_profile": command[command.index("--rf-profile") + 1],
                             "tx_power_dbm": int(command[command.index("--tx-power-dbm") + 1])}
                self.write_paired_result(result, integration_mode="radio_markers", marker_totals_only=True,
                                         condition=condition)
                return (0 if len(calls) == 1 else 1), str(result)
            with (patch.object(manager, "_run_process", side_effect=process),
                  patch.object(manager, "_ensure_paired_guard") as guard,
                  patch.object(manager, "_ensure_current_path_on") as single_guard):
                manager.resume_paired_campaign(session.name, config)
                manager._thread.join(timeout=10)
                self.assertFalse(manager._thread.is_alive())
                status = manager.status()
                self.assertEqual(status["state"], "failed", status)
                self.assertEqual(len(calls), 2, "No automatic retry after the next failed batch")
                self.assertEqual(calls[0], previous["steps"][1]["command"])
                self.assertEqual(calls[1], previous["steps"][2]["command"])
                self.assertEqual(status["steps"][0]["accepted_result"], previous["steps"][0]["accepted_result"])
                self.assertEqual(status["steps"][0]["attempts"], previous["steps"][0]["attempts"])
                self.assertEqual(status["steps"][1]["attempts"][0], previous["steps"][1]["attempts"][0])
                self.assertEqual([a["attempt"] for a in status["steps"][1]["attempts"]], [1, 2])
                self.assertTrue(status["steps"][1]["attempts"][1]["log_file"].endswith("attempt_02.log"))
                self.assertEqual((status["completed_steps"], status["failed_steps"]), (2, 1))
                self.assertTrue(all(s["status"] == "pending" for s in status["steps"][3:]))
                self.assertEqual(status["started_utc"], "original-start")
                self.assertEqual(status["session_dir"], str(session))
                resume = status["resumes"][0]
                self.assertEqual(len(resume["revalidated_results"]), 1)
                self.assertEqual(len(resume["scheduled_step_ids"]), 62)
                self.assertEqual(Path(resume["previous_manifest"]).read_bytes(), old_files[session / "manifest.json"])
                guard.assert_called_once_with(config)
                single_guard.assert_not_called()
            for path, contents in old_files.items():
                if path.name not in {"manifest.json", "session.log"}:
                    self.assertEqual(path.read_bytes(), contents, str(path))
            self.assertTrue((session / "session.log").read_text(encoding="utf-8").startswith("Original campaign log\n"))

    def test_32b_resume_preserves_accepted_results_and_restarts_only_failed_or_pending_whole_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            sessions = Path(temporary)
            config, session, previous = self.write_halted_paired_campaign(
                sessions, kind="paired_32b_campaign", interface="ESP32")
            original = {path: path.read_bytes() for path in session.rglob("*") if path.is_file()}
            manager = JobManager(sessions)
            calls = []
            def process(command, log):
                calls.append(command)
                self.assertEqual(command[command.index("--repetitions") + 1], "5")
                self.assertEqual(command[command.index("--payload-bytes") + 1], "32")
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("Explicit resumed batch\n", encoding="utf-8")
                result = Path(command[command.index("--output") + 1]) / "new_attempt"
                condition = {"payload_bytes": 32, "rf_profile": command[command.index("--rf-profile") + 1],
                             "tx_power_dbm": int(command[command.index("--tx-power-dbm") + 1])}
                self.write_paired_result(result, integration_mode="radio_markers", marker_totals_only=True,
                                         condition=condition)
                return (0 if len(calls) == 1 else 1), str(result)
            with (patch.object(manager, "_run_process", side_effect=process),
                  patch.object(manager, "_ensure_paired_guard") as guard,
                  patch.object(manager, "_ensure_current_path_on") as single_guard):
                manager.resume_paired_campaign(session.name, config)
                manager._thread.join(timeout=10)
                self.assertFalse(manager._thread.is_alive())
                status = manager.status()
                self.assertEqual(status["state"], "failed")
                self.assertEqual(status["kind"], "paired_32b_campaign")
                self.assertEqual(status["total_steps"], 21)
                self.assertEqual(calls, [previous["steps"][i]["command"] for i in (1, 2)])
                self.assertEqual(status["steps"][0]["accepted_result"], previous["steps"][0]["accepted_result"])
                self.assertEqual(status["steps"][0]["attempts"], previous["steps"][0]["attempts"])
                self.assertEqual(status["steps"][1]["attempts"][0], previous["steps"][1]["attempts"][0])
                self.assertEqual([a["attempt"] for a in status["steps"][1]["attempts"]], [1, 2])
                self.assertEqual((status["completed_steps"], status["failed_steps"]), (2, 1))
                self.assertTrue(all(s["status"] == "pending" for s in status["steps"][3:]))
                resume = status["resumes"][0]
                self.assertEqual(len(resume["revalidated_results"]), 1)
                self.assertEqual(len(resume["scheduled_step_ids"]), 20)
                self.assertEqual(Path(resume["previous_manifest"]).read_bytes(), original[session / "manifest.json"])
                guard.assert_called_once_with(config)
                single_guard.assert_not_called()
            for path, content in original.items():
                if path.name not in {"manifest.json", "session.log"}:
                    self.assertEqual(path.read_bytes(), content, str(path))

    def test_32b_resume_rejects_changed_scope_config_or_accepted_proof_before_writes(self):
        for mutation in ("as_full", "full_as_32b", "payload", "power", "missing_condition", "duplicate_condition",
                         "interface", "mode", "proof", "completed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                sessions = Path(temporary)
                kind = "paired_campaign" if mutation == "full_as_32b" else "paired_32b_campaign"
                config, session, manifest = self.write_halted_paired_campaign(sessions, kind=kind, interface="ESP32")
                request = config
                if mutation in {"as_full", "full_as_32b"}:
                    manifest["kind"] = "paired_campaign" if mutation == "as_full" else "paired_32b_campaign"
                elif mutation in {"payload", "power"}:
                    flag = "--payload-bytes" if mutation == "payload" else "--tx-power-dbm"
                    command = manifest["steps"][1]["command"]
                    command[command.index(flag) + 1] = "64" if mutation == "payload" else "13"
                elif mutation == "missing_condition":
                    manifest["steps"].pop()
                elif mutation == "duplicate_condition":
                    manifest["steps"][-1] = manifest["steps"][-2]
                elif mutation == "interface":
                    request = PairedConfig.from_mapping({**asdict(config), "interface_label": "CH340"})
                elif mutation == "mode":
                    request = PairedConfig.from_mapping({**asdict(config), "marker_totals_only": False})
                elif mutation == "proof":
                    path = Path(manifest["steps"][0]["accepted_result"]) / "pairing.json"
                    pairing = json.loads(path.read_text())
                    pairing["rows"][0]["marker_diagnostics"]["roles"]["tx"]["total_qa"]["direct_adc_match"] = False
                    path.write_text(json.dumps(pairing), encoding="utf-8")
                else:
                    manifest["state"] = "completed"
                path = session / "manifest.json"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                before = path.read_bytes()
                manager = JobManager(sessions)
                with (patch.object(manager, "_run_process") as process,
                      patch.object(manager, "_release_paired_guard") as release):
                    with self.assertRaises(ValueError):
                        manager.resume_paired_campaign(session.name, request)
                    process.assert_not_called()
                    release.assert_not_called()
                    self.assertIsNone(manager._thread)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((session / "resume_history").exists())

    def test_paired_campaign_resume_rejects_changed_config_or_invalid_accepted_evidence_without_writes(self):
        mutations = ("config", "interface", "mode", "matrix", "raw_missing", "condition", "proof", "fixture", "voltage",
                     "provenance", "accepted_outside", "no_successful_attempt", "running", "wrong_kind")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                sessions = Path(temporary)
                config, session, manifest = self.write_halted_paired_campaign(sessions)
                accepted = Path(manifest["steps"][0]["accepted_result"])
                pairing_path = accepted / "pairing.json"
                pairing = json.loads(pairing_path.read_text(encoding="utf-8"))
                request = config
                if mutation == "config":
                    request = PairedConfig.from_mapping({**vars(config), "tx_identity": "different board"})
                elif mutation == "interface":
                    request = PairedConfig.from_mapping({**vars(config), "interface_label": "ESP32"})
                elif mutation == "mode":
                    request = PairedConfig.from_mapping({**vars(config), "marker_totals_only": False})
                elif mutation == "matrix":
                    manifest["steps"][1]["command"].extend(["--arbitrary-command", "not allowed"])
                elif mutation == "raw_missing":
                    (accepted / "tx" / "raw" / "run_00001.csv.gz").unlink()
                elif mutation == "condition":
                    pairing["rf_profile"] = "GFSK4K8"
                elif mutation == "proof":
                    pairing["rows"][0]["marker_diagnostics"]["roles"]["tx"]["total_qa"]["guard_qa_includes_stop"] = False
                elif mutation == "fixture":
                    pairing["endpoints"]["tx"]["identity"] = "different board"
                elif mutation == "voltage":
                    pairing["endpoints"]["rx"]["voltage_mv"] = 3000
                elif mutation == "provenance":
                    pairing["voltage_provenance"] = "different supply"
                elif mutation == "accepted_outside":
                    manifest["steps"][0]["accepted_result"] = str(sessions / "elsewhere")
                elif mutation == "no_successful_attempt":
                    manifest["steps"][0]["attempts"][0]["validation"]["valid"] = False
                elif mutation == "running":
                    manifest["state"] = "running"
                else:
                    manifest["kind"] = "paired_pilot"
                pairing_path.write_text(json.dumps(pairing), encoding="utf-8")
                manifest_path = session / "manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                before = manifest_path.read_bytes()
                manager = JobManager(sessions)
                with (patch.object(manager, "_run_process") as process,
                      patch.object(manager, "_release_paired_guard") as release):
                    with self.assertRaises(ValueError):
                        manager.resume_paired_campaign(str(session), request)
                    self.assertIsNone(manager._thread)
                    process.assert_not_called()
                    release.assert_not_called()
                self.assertEqual(manifest_path.read_bytes(), before)
                self.assertFalse((session / "resume_history").exists())

    def test_paired_campaign_resume_respects_job_lock_session_boundary_and_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            sessions = Path(temporary)
            config, session, _ = self.write_halted_paired_campaign(sessions)
            manager = JobManager(sessions)
            for invalid in ("", "..", str(sessions.parent), str(session / "nested")):
                with self.subTest(session=invalid), self.assertRaises(ValueError):
                    manager.resume_paired_campaign(invalid, config)
            manager._thread = types.SimpleNamespace(is_alive=lambda: True)
            with self.assertRaisesRegex(RuntimeError, "already running"):
                manager.resume_paired_campaign(str(session), config)
            manager._thread = None
            manager._ppk_guard = object()
            with self.assertRaisesRegex(RuntimeError, "single-PPK guard"):
                manager.resume_paired_campaign(str(session), config)
            self.assertFalse((session / "resume_history").exists())

    def write_uart_mapping_evidence(self, path, config, ports):
        evidence = {"schema": "e79_uart_port_mapping_v1", "same_physical_fixture_confirmed": True,
                    "confirmed_by": "Operator and independent bench review",
                    "verification_method": "Independent RX toggles and current steps on unchanged PPK branches",
                    "roles": {role: {"previous_radio_port": getattr(config, f"{role}_radio_port"),
                                      "radio_port": ports[role], "ppk_port": getattr(config, f"{role}_ppk_port"),
                                      "ppk_serial_number": f"PPK_{role.upper()}",
                                      "identity": getattr(config, f"{role}_identity")} for role in ("tx", "rx")}}
        path.write_bytes(json.dumps(evidence, indent=2).encode("utf-8"))
        return evidence

    def test_uart_remap_preserves_original_batches_and_supports_future_resume_with_mixed_port_history(self):
        for ports in ({"tx": "COM16", "rx": "COM14"}, {"tx": "COM12", "rx": "COM14"}):
            with self.subTest(ports=ports), tempfile.TemporaryDirectory() as temporary:
                sessions = Path(temporary)
                config, session, original = self.write_halted_paired_campaign(sessions)
                evidence_path = sessions / "confirmed_mapping.json"
                self.write_uart_mapping_evidence(evidence_path, config, ports)
                old_files = {path: path.read_bytes() for path in session.rglob("*") if path.is_file()}
                calls = []
                def process(command, attempt_log):
                    calls.append(command)
                    self.assertEqual(command[command.index("--tx-radio-port") + 1], ports["tx"])
                    self.assertEqual(command[command.index("--rx-radio-port") + 1], ports["rx"])
                    attempt_log.parent.mkdir(exist_ok=True)
                    attempt_log.write_text("Mapped UART attempt\n", encoding="utf-8")
                    result = Path(command[command.index("--output") + 1]) / f"resume_{len(calls)}"
                    condition = {"payload_bytes": int(command[command.index("--payload-bytes") + 1]),
                                 "rf_profile": command[command.index("--rf-profile") + 1],
                                 "tx_power_dbm": int(command[command.index("--tx-power-dbm") + 1])}
                    pairing = self.write_paired_result(result, integration_mode="radio_markers",
                                                      marker_totals_only=True, condition=condition)
                    for key in ("profile_id", "interface_label", "ppk_mode", "voltage_confirmed", "voltage_provenance"):
                        pairing[key] = getattr(config, key)
                    for role in ("tx", "rx"):
                        for name in ("radio_port", "ppk_port", "voltage_mv", "identity"):
                            pairing["endpoints"][role][name] = ports[role] if name == "radio_port" else getattr(config, f"{role}_{name}")
                        pairing["endpoints"][role]["ppk_usb"] = {"serial_number": f"PPK_{role.upper()}"}
                    (result / "pairing.json").write_text(json.dumps(pairing), encoding="utf-8")
                    return (0 if len(calls) == 1 else 1), str(result)
                manager = JobManager(sessions)
                with (patch.object(manager, "_run_process", side_effect=process),
                      patch.object(manager, "_ensure_paired_guard") as guard):
                    manager.resume_paired_campaign(str(session), config, radio_port_overrides=ports,
                                                   port_mapping_evidence=str(evidence_path))
                    manager._thread.join(timeout=5)
                    self.assertFalse(manager._thread.is_alive())
                    status = manager.status()
                    self.assertEqual(status["state"], "failed", status)
                    self.assertEqual(status["completed_steps"], 2)
                    self.assertEqual(status["config"], original["config"])
                    self.assertEqual(status["active_radio_ports"], ports)
                    self.assertEqual(len(status["radio_port_history"]), 1)
                    mapping = status["radio_port_history"][0]
                    self.assertEqual(Path(mapping["evidence_path"]).read_bytes(), evidence_path.read_bytes())
                    self.assertEqual(mapping["evidence_sha256"], hashlib.sha256(evidence_path.read_bytes()).hexdigest())
                    self.assertEqual(status["steps"][0]["command"], original["steps"][0]["command"])
                    self.assertEqual(status["steps"][0]["attempts"], original["steps"][0]["attempts"])
                    self.assertEqual(status["steps"][1]["attempts"][0], original["steps"][1]["attempts"][0])
                    self.assertEqual(status["steps"][1]["attempts"][1]["radio_ports"], ports)
                    self.assertEqual(guard.call_args.args[0].tx_radio_port, ports["tx"])
                    self.assertEqual(guard.call_args.args[0].rx_radio_port, ports["rx"])
                # An ordinary explicit resume after another failure uses the saved mapping.
                # Deleting the external source proves the immutable session copy is sufficient.
                evidence_path.unlink()
                restarted = JobManager(sessions)
                with (patch.object(restarted, "_run_process", side_effect=process),
                      patch.object(restarted, "_ensure_paired_guard")):
                    restarted.resume_paired_campaign(session.name, config)
                    restarted._thread.join(timeout=5)
                    status = restarted.status()
                    self.assertEqual(status["state"], "failed", status)
                    self.assertEqual(len(calls), 3, "Only the failed third batch is repeated explicitly")
                    self.assertEqual(status["completed_steps"], 2)
                    self.assertEqual(len(status["resumes"]), 2)
                    self.assertEqual(len(status["radio_port_history"]), 1)
                    self.assertEqual(len(status["resumes"][-1]["revalidated_results"]), 2)
                    self.assertEqual([a["attempt"] for a in status["steps"][2]["attempts"]], [1, 2])
                    self.assertEqual(status["active_radio_ports"], ports)
                for path, data in old_files.items():
                    if path.name not in {"manifest.json", "session.log"}:
                        self.assertEqual(path.read_bytes(), data, str(path))
                # A modified historical proof cannot silently authorize a later resume.
                proof = Path(status["radio_port_history"][0]["evidence_path"])
                proof.write_bytes(proof.read_bytes() + b" ")
                final = JobManager(sessions)
                before = (session / "manifest.json").read_bytes()
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    final.resume_paired_campaign(session.name, config)
                self.assertIsNone(final._thread)
                self.assertEqual((session / "manifest.json").read_bytes(), before)

    def test_uart_remap_requires_confirmed_same_fixture_evidence_and_only_uart_overrides(self):
        cases = ("missing_evidence", "missing_file", "not_confirmed", "identity", "ppk_port", "ppk_serial",
                 "previous_port", "new_port", "schema", "no_verifier", "extra_override", "same_ppk_port",
                 "unknown_saved_ports", "tampered_active_ports")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                sessions = Path(temporary)
                config, session, manifest = self.write_halted_paired_campaign(sessions)
                ports = {"tx": "COM16", "rx": "COM14"}
                evidence_path = sessions / "mapping.json"
                evidence = self.write_uart_mapping_evidence(evidence_path, config, ports)
                if case == "not_confirmed":
                    evidence["same_physical_fixture_confirmed"] = "true"
                elif case in {"identity", "ppk_port", "ppk_serial", "previous_port", "new_port"}:
                    key = {"ppk_serial": "ppk_serial_number", "previous_port": "previous_radio_port", "new_port": "radio_port"}.get(case, case)
                    evidence["roles"]["tx"][key] = "different"
                elif case == "schema":
                    evidence["schema"] = "unknown"
                elif case == "no_verifier":
                    evidence["confirmed_by"] = ""
                elif case == "extra_override":
                    ports["tx_ppk_port"] = "COM20"
                elif case == "same_ppk_port":
                    ports["tx"] = "COM10"
                elif case == "unknown_saved_ports":
                    command = manifest["steps"][0]["command"]
                    command[command.index("--tx-radio-port") + 1] = "COM99"
                elif case == "tampered_active_ports":
                    manifest["active_radio_ports"] = ports
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
                manifest_path = session / "manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                proof_arg = str(evidence_path)
                if case == "missing_evidence":
                    proof_arg = None
                elif case == "missing_file":
                    evidence_path.unlink()
                before = manifest_path.read_bytes()
                manager = JobManager(sessions)
                with (patch.object(manager, "_run_process") as process,
                      patch.object(manager, "_release_paired_guard") as release):
                    with self.assertRaises(ValueError):
                        manager.resume_paired_campaign(session.name, config, radio_port_overrides=ports,
                                                       port_mapping_evidence=proof_arg)
                    self.assertIsNone(manager._thread)
                    process.assert_not_called()
                    release.assert_not_called()
                self.assertFalse((session / "resume_history").exists())
                self.assertEqual(manifest_path.read_bytes(), before)

    def test_paired_resume_api_requires_explicit_config_and_routes_session_to_resume_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with (patch.object(manager, "resume_paired_campaign", return_value={"state": "running"}) as resume,
                      patch.object(manager, "start") as start):
                    payload = {**self.paired_payload(), "integration_mode": "radio_markers",
                               "marker_totals_only": True, "session_dir": "halted_paired_campaign",
                               "radio_port_overrides": {"tx": "COM16", "rx": "COM14"},
                               "port_mapping_evidence": "confirmed.json"}
                    for confirmed in (False, True):
                        request = urllib.request.Request(f"http://{host}:{port}/api/paired-campaign/resume",
                            data=json.dumps({**payload, "voltage_confirmed": confirmed}).encode("utf-8"),
                            headers={"Content-Type": "application/json"}, method="POST")
                        if confirmed:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                self.assertEqual(response.status, 202)
                        else:
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(raised.exception.code, 400)
                            resume.assert_not_called()
                    resume.assert_called_once()
                    self.assertEqual(resume.call_args.args[0], payload["session_dir"])
                    self.assertTrue(resume.call_args.args[1].marker_totals_only)
                    self.assertEqual(resume.call_args.kwargs["radio_port_overrides"], payload["radio_port_overrides"])
                    self.assertEqual(resume.call_args.kwargs["port_mapping_evidence"], payload["port_mapping_evidence"])
                    start.assert_not_called()
                    with urllib.request.urlopen(f"http://{host}:{port}/", timeout=3) as response:
                        html = response.read().decode("utf-8")
                    self.assertIn('id="pairedResume"', html)
                    self.assertIn("/api/paired-campaign/resume", html)
                    self.assertIn("Accepted batches are freshly validated and retained", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

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

    def test_paired_quality_rejects_missing_raw_and_invalid_sample_counts_or_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            step = build_paired_pilot_steps(PairedConfig.from_mapping(self.paired_payload()), root)[0]
            manifest = self.write_paired_result(root)
            path = root / "rx" / "summary.csv"
            original = path.read_text(encoding="utf-8")
            for value in ("", "NaN", "inf", "1.01", "-1"):
                with self.subTest(sample_loss=value):
                    path.write_text(original.replace(",ok,,0,100000", f",ok,,{value},100000"), encoding="utf-8")
                    self.assertFalse(validate_result(step, root)["valid"])
            path.write_text(original.replace(",100000", ",0"), encoding="utf-8")
            self.assertFalse(validate_result(step, root)["valid"])
            path.write_text(original, encoding="utf-8")
            manifest["rows"][0]["rx_raw"] = "../outside.csv.gz"
            (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(validate_result(step, root)["valid"])
            manifest["rows"][0]["rx_raw"] = "rx/raw/run_00001.csv.gz"
            (root / "pairing.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "rx/raw/run_00001.csv.gz").write_bytes(b"")
            self.assertFalse(validate_result(step, root)["valid"])

    def test_paired_hold_owns_and_drains_both_ports_and_releases_without_power_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PairedConfig.from_mapping(self.paired_payload())
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
            config = PairedConfig.from_mapping(self.paired_payload())
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
            config = PairedConfig.from_mapping(self.paired_payload())
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
            config = PairedConfig.from_mapping(self.paired_payload())
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

    def test_paired_guard_enable_api_requires_confirmed_fixture_without_starting_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with (patch.object(manager, "enable_paired_guard", return_value={"ok": True}) as enable,
                      patch.object(manager, "start") as start):
                    for payload in ({}, {**self.paired_payload(), "voltage_confirmed": False}, self.paired_payload()):
                        request = urllib.request.Request(f"http://{host}:{port}/api/paired-guard/enable",
                            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                        if payload.get("voltage_confirmed") is True:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                self.assertEqual(response.status, 202)
                        else:
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(raised.exception.code, 400)
                            enable.assert_not_called()
                    enable.assert_called_once()
                    start.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_paired_start_respects_single_job_lock_and_existing_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            config = PairedConfig.from_mapping(self.paired_payload())
            manager._thread = types.SimpleNamespace(is_alive=lambda: True)
            with self.assertRaisesRegex(RuntimeError, "already running"):
                manager.start("paired_pilot", config)
            manager._thread = None
            manager._ppk_guard = object()
            with self.assertRaisesRegex(RuntimeError, "Release the single-PPK guard explicitly"):
                manager.start("paired_pilot", config)

    def test_paired_api_requires_voltage_confirmation_before_scheduling_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with patch.object(manager, "start", return_value={"state": "running"}) as start:
                    for confirmed in (False, "true", True):
                        payload = {**self.paired_payload(), "voltage_confirmed": confirmed}
                        request = urllib.request.Request(f"http://{host}:{port}/api/paired-pilot",
                            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                        if confirmed is True:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                self.assertEqual(response.status, 202)
                        else:
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(raised.exception.code, 400)
                            start.assert_not_called()
                    start.assert_called_once()
                    self.assertEqual(start.call_args.args[0], "paired_pilot")
                    self.assertIsInstance(start.call_args.args[1], PairedConfig)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_paired_campaign_api_only_schedules_confirmed_local_marker_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with patch.object(manager, "start", return_value={"state": "running"}) as start:
                    for mode, confirmed in (("modeled", True), ("tx_marker", True), ("radio_markers", False)):
                        payload = {**self.paired_payload(), "integration_mode": mode, "voltage_confirmed": confirmed}
                        request = urllib.request.Request(f"http://{host}:{port}/api/paired-campaign",
                            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=3)
                        self.assertEqual(raised.exception.code, 400)
                        start.assert_not_called()
                    request = urllib.request.Request(f"http://{host}:{port}/api/paired-campaign",
                        data=json.dumps({**self.paired_payload(), "integration_mode": "radio_markers"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(request, timeout=3) as response:
                        self.assertEqual(response.status, 202)
                    start.assert_called_once()
                    self.assertEqual(start.call_args.args[0], "paired_campaign")
                    self.assertEqual(start.call_args.args[1].integration_mode, "radio_markers")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_32b_api_requires_confirmed_local_totals_and_dispatches_only_the_selected_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                base = {**self.paired_payload(), "interface_label": "ESP32",
                        "integration_mode": "radio_markers", "marker_totals_only": True}
                with patch.object(manager, "start", return_value={"state": "running"}) as start:
                    for overrides in ({"integration_mode": "modeled", "marker_totals_only": False},
                                      {"integration_mode": "tx_marker", "marker_totals_only": False},
                                      {"marker_totals_only": False}, {"voltage_confirmed": False},
                                      {"tx_identity": ""}, {}):
                        request = urllib.request.Request(f"http://{host}:{port}/api/paired-32b-campaign",
                            data=json.dumps({**base, **overrides}).encode("utf-8"),
                            headers={"Content-Type": "application/json"}, method="POST")
                        if overrides:
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(raised.exception.code, 400)
                            start.assert_not_called()
                        else:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                self.assertEqual(response.status, 202)
                    start.assert_called_once_with("paired_32b_campaign", PairedConfig.from_mapping(base))
                with urllib.request.urlopen(f"http://{host}:{port}/", timeout=3) as response:
                    html = response.read().decode("utf-8")
                self.assertIn('id="paired32bCampaign"', html)
                self.assertIn("/api/paired-32b-campaign", html)
                self.assertIn("32 B only: 105 TX/RX pairs = 21 batches", html)
                self.assertIn("does not reuse pilot results or continue to other payload sizes", html)
                self.assertIn("$('paired32bCampaign').disabled=s.running", html)
                self.assertIn("['paired_campaign','paired_32b_campaign','paired_fragmented_campaign'].includes(s.kind)", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_fragmented_api_requires_explicit_total_only_before_scheduling_and_ui_exposes_separate_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with patch.object(manager, "start", return_value={"state": "running"}) as start:
                    for mode, totals in (("modeled", False), ("tx_marker", False), ("radio_markers", False), ("radio_markers", True)):
                        payload = {**self.paired_payload(), "integration_mode": mode, "marker_totals_only": totals}
                        request = urllib.request.Request(f"http://{host}:{port}/api/paired-fragmented-campaign",
                            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                        if totals:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                self.assertEqual(response.status, 202)
                        else:
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(raised.exception.code, 400)
                            start.assert_not_called()
                    start.assert_called_once()
                    self.assertEqual(start.call_args.args[0], "paired_fragmented_campaign")
                    self.assertTrue(start.call_args.args[1].marker_totals_only)
                with urllib.request.urlopen(f"http://{host}:{port}/", timeout=3) as response:
                    html = response.read().decode("utf-8")
                self.assertIn('id="pairedFragmentedCampaign"', html)
                self.assertIn("/api/paired-fragmented-campaign", html)
                self.assertIn("Energy excludes the gaps between frames", html)
                self.assertIn("['paired_campaign','paired_32b_campaign','paired_fragmented_campaign'].includes(s.kind)", html)
                self.assertIn("Each failed batch restarts all five transfers", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

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

    def test_http_ui_and_status_are_available_without_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = JobManager(Path(temporary))
            server = AppServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with urllib.request.urlopen(
                    f"http://{host}:{port}/", timeout=3
                ) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Run quick check", html)
                self.assertIn("Test Codex callback", html)
                self.assertIn("currentSession!==s.session_dir", html)
                self.assertIn("/api/status?after=0", html)
                self.assertIn("Opening this interface does not access hardware", html)
                self.assertIn('id="pairedIntegration"', html)
                self.assertIn('<select id="pairedInterface">', html)
                self.assertIn('<option value="CH340" selected>CH340</option>', html)
                self.assertIn('<option value="ESP32">ESP32 bridge</option>', html)
                self.assertIn("0.3.0 has no marker support", html)
                self.assertIn('<option value="modeled" selected>Modeled windows (legacy)</option>', html)
                self.assertIn('value="tx_marker">Common TX hardware marker', html)
                self.assertIn('value="radio_markers">Local TX/RX hardware markers (recommended)', html)
                self.assertIn('id="pairedIntegrationHelp"', html)
                self.assertIn('id="pairedCampaign"', html)
                self.assertIn('id="pairedMarkerTotalsOnly" type="checkbox">', html)
                self.assertIn("selected wire proof", html)
                self.assertIn("Baseline, threshold and excess energy are unavailable", html)
                self.assertIn("marker_totals_only:$('pairedMarkerTotalsOnly').checked", html)
                self.assertIn("/api/paired-campaign", html)
                self.assertIn("315 TX/RX pairs = 63 batches", html)
                self.assertIn("Separate fragmented phase: 105 TX/RX pairs", html)
                self.assertIn("This creates a new session and preserves the 8/32/64 B campaign", html)
                self.assertIn("same E79 firmware 0.3.2 binary on both radios", html)
                self.assertIn("each radio's DIO17 only to its own PPK2 D0", html)
                self.assertIn("Never connect the radio output pins together", html)
                self.assertIn("sync detection to packet end/abort; it excludes preamble and listening", html)
                self.assertIn("integration_mode:$('pairedIntegration').value", html)
                self.assertIn("requires TX firmware 0.3.1", html)
                self.assertIn("common GND and a 3.3 V logic reference", html)
                self.assertIn("Both energies cover the TX interval, not the receiver's own RF interval", html)
                for field in ("measured", "peer", "ppk"):
                    self.assertIn(f'id="{field}" value=""', html)
                with urllib.request.urlopen(
                    f"http://{host}:{port}/api/status", timeout=3
                ) as response:
                    status = json.loads(response.read().decode("utf-8"))
                self.assertEqual(status["state"], "idle")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

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
