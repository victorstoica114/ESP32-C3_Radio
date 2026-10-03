import csv
from contextlib import redirect_stderr
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools.audit_fragment_marker_totals import METHOD, PAYLOAD, POLICY, audit_result, main


class AuditFragmentMarkerTotalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepare(128)

    def prepare(self, payload):
        self.frame_count = payload // 64
        coefficients = {key: {str(i): value for i in range(5)} for key, value in
                        {"R": 1, "O": 0, "GS": 0, "GI": 1, "S": 0, "I": 0, "UG": 1}.items()}
        self.metadata = {"endpoints": {role: {"voltage_mv": 3300,
                         "ppk_calibration_metadata": coefficients} for role in ("tx", "rx")}}
        self.manifest = {
            "sample_rate_hz": 100000, "session_id": "synthetic", "status": "valid", "errors": [],
            "expected_rows": 5, "profile_id": "RADIO_EBYTE_E79_CC1352P", "payload_bytes": payload,
            "frame_count": self.frame_count, "frame_payload_bytes": [64] * self.frame_count,
            "fragmented": True, "rf_profile": "GFSK200", "tx_power_dbm": 13,
            "integration_mode": "radio_markers", "marker_totals_only": True,
            "integration_method": METHOD, "energy_policy": POLICY,
            "rows": [{"run_id": "run_00001", "status": "valid", "tx_status": "ok", "rx_status": "ok",
                      "packet_received": True, "frame_payload_bytes": [64] * self.frame_count,
                      "capture_errors": {}, "marker_diagnostics": {"valid": True, "reasons": [],
                          "integration_method": METHOD, "expected_frame_count": self.frame_count, "roles": {}}}],
        }
        self.rows = {}
        (self.root / "wire" / "run_00001").mkdir(parents=True, exist_ok=True)
        for role, width, offset in (("tx", 10, 0), ("rx", 7, 20)):
            (self.root / role / "raw").mkdir(parents=True, exist_ok=True)
            (self.root / role / "metadata.json").write_text(json.dumps(self.metadata))
            windows = [[1800 + offset + 50 * i, 1800 + offset + 50 * i + width] for i in range(self.frame_count)]
            current = 4394.53125
            frame_charge = current * width / 100000
            charge = frame_charge * self.frame_count
            energy = charge * 3.3
            proof = {"valid": True, "reasons": [], "windows_samples": windows,
                     "duration_samples": width * self.frame_count,
                     "charge_total_uC": charge, "energy_total_uJ": energy,
                     "frame_proofs": [{"valid": True, "reasons": [], "window_samples": [a, b],
                                       "guard_window_samples": [a - 3, b], "charge_total_uC": frame_charge,
                                       "energy_total_uJ": frame_charge * 3.3} for a, b in windows]}
            self.manifest["rows"][0]["marker_diagnostics"]["roles"][role] = proof
            row = dict(run_id="run_00001", status="ok", measurement_direction=role,
                       integration_method=METHOD, analysis_error="", packet_received="True",
                       packet_lost="False", event_detected="True", payload_bytes=payload,
                       frame_count=self.frame_count, max_frame_payload_bytes=64, serial_content_bytes=payload,
                       baseline_median_uA="", threshold_uA="", charge_excess_uC="", energy_excess_uJ="",
                       parameters_json=json.dumps({"rf_profile": "GFSK200", "tx_power_dbm": 13}),
                       captured_samples=4000, sample_loss_percent=0, voltage_mv=3300,
                       charge_total_uC=charge, energy_total_uJ=energy,
                       event_start_ms=(windows[0][0] - 1500) / 100,
                       event_duration_ms=width * self.frame_count / 100,
                       tx_mean_uA=current, tx_peak_uA=current, event_mean_uA=current, event_peak_uA=current,
                       rx_mean_uA=current if role == "rx" else "", rx_peak_uA=current if role == "rx" else "",
                       integration_windows_ms=json.dumps([[(a - 1500) / 100, (b - 1500) / 100] for a, b in windows]),
                       receiver_response=" | ".join([PAYLOAD] * self.frame_count), transmitter_response="OK")
            self.rows[role] = row
            self.write_capture(role, windows)
            for index in range(2, 6):
                run_id = f"run_{index:05d}"
                (self.root / "wire" / run_id).mkdir(exist_ok=True)
                (self.root / "wire" / run_id / f"{role}.ppk2.bin").write_bytes(
                    (self.root / "wire" / "run_00001" / f"{role}.ppk2.bin").read_bytes())
                (self.root / role / "raw" / f"{run_id}.csv.gz").write_bytes(
                    (self.root / role / "raw" / "run_00001.csv.gz").read_bytes())
        self.persist()

    def persist(self):
        template = self.manifest["rows"][0]
        self.manifest["rows"] = [dict(json.loads(json.dumps(template)), run_id=f"run_{index:05d}")
                                 for index in range(1, 6)]
        (self.root / "pairing.json").write_text(json.dumps(self.manifest))
        for role, row in self.rows.items():
            with (self.root / role / "summary.csv").open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(dict(row, run_id=f"run_{index:05d}") for index in range(1, 6))

    def windows(self, role):
        return self.manifest["rows"][0]["marker_diagnostics"]["roles"][role]["windows_samples"]

    def write_capture(self, role, windows, *, delta_index=None, fault_index=None, range_index=None):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["sample_index", "current_uA", "logic_bits", "trigger"])
        words = []
        for i in range(4000):
            high = any(a <= i < b for a, b in windows)
            adc = 100 if high else 1000  # Tenfold current in gaps must NOT be integrated or counted in peak.
            word = adc | (3 << 14) | ((i % 64) << 18) | (int(high) << 24)
            if i == fault_index:
                word ^= 1 << 18
            if i == range_index:
                word = (word & ~(7 << 14)) | (2 << 14)
            words.append(word)
            current = adc * 4 * (1.8 / 163840) * 1e6 + (0.01 if i == delta_index else 0)
            writer.writerow([i, current, word >> 24, int(i == 1500)])
        (self.root / "wire" / "run_00001" / f"{role}.ppk2.bin").write_bytes(struct.pack(f"<{len(words)}I", *words))
        (self.root / role / "raw" / "run_00001.csv.gz").write_bytes(gzip.compress(stream.getvalue().encode()))

    def test_two_eight_sixteen_frames_sum_active_intervals_only_without_mutation(self):
        for payload in (128, 512, 1024):
            with self.subTest(payload=payload):
                self.prepare(payload)
                before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
                report = audit_result(self.root)
                self.assertTrue(report["accepted"], report["errors"])
                self.assertTrue(report["total_proven"])
                self.assertEqual(report["counts"]["proven_frames"], self.frame_count * 2 * 5)
                self.assertTrue(report["runs"][0]["delivery"]["all_frames_delivered"])
                tx = report["runs"][0]["roles"]["tx"]
                self.assertAlmostEqual(tx["total_energy_uJ"], 4394.53125 * 10 * self.frame_count / 100000 * 3.3)
                self.assertEqual(tx["peak_uA"], 4394.53125)
                self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_missing_extra_or_truncated_pulse_is_not_selected_away(self):
        for windows in (self.windows("rx")[:-1], self.windows("rx") + [[2200, 2210]], [[1800, 1810], [3990, 4000]]):
            with self.subTest(windows=windows):
                self.write_capture("rx", windows)
                report = audit_result(self.root)
                self.assertFalse(report["total_proven"])
                self.assertFalse(report["accepted"])

    def test_adc_counter_guard_and_range_faults_fail_entire_role(self):
        for mutation in ({"delta_index": 1801}, {"fault_index": 1797}, {"fault_index": 1810}, {"range_index": 1798}):
            with self.subTest(mutation=mutation):
                self.write_capture("tx", self.windows("tx"), **mutation)
                report = audit_result(self.root)
                self.assertFalse(report["accepted"])
                self.assertIsNone(report["runs"][0]["roles"]["tx"]["total_energy_uJ"])

    def test_baseline_counter_fault_is_diagnostic_and_not_part_of_total(self):
        self.write_capture("tx", self.windows("tx"), fault_index=600)
        report = audit_result(self.root)
        self.assertTrue(report["accepted"], report["errors"])
        self.assertFalse(report["runs"][0]["roles"]["tx"]["baseline_integrity_clean"])

    def test_delivery_requires_all_payload_lines_not_just_recorded_boolean(self):
        for role in ("tx", "rx"):
            self.rows[role]["receiver_response"] = PAYLOAD
        self.persist()
        report = audit_result(self.root)
        self.assertTrue(report["total_proven"])
        self.assertFalse(report["accepted"])
        self.assertFalse(report["runs"][0]["delivery"]["all_frames_delivered"])

    def test_csv_sum_gap_window_and_baseline_contract_are_checked(self):
        for field, value in (("energy_total_uJ", 999), ("event_duration_ms", 0.6),
                             ("integration_windows_ms", "[[3.0,3.6]]"), ("baseline_median_uA", 0)):
            with self.subTest(field=field):
                self.prepare(128)
                self.rows["tx"][field] = value
                self.persist()
                report = audit_result(self.root)
                self.assertTrue(report["total_proven"])
                self.assertFalse(report["accepted"])
                self.assertIn(field.replace("_ms", "").replace("_", " ") if field == "integration_windows_ms" else field,
                              " ".join(report["errors"]))

    def test_calibration_missing_and_failed_official_batch_cannot_be_accepted(self):
        path = self.root / "tx" / "metadata.json"
        metadata = json.loads(path.read_text())
        del metadata["endpoints"]["tx"]["ppk_calibration_metadata"]["R"]["4"]
        path.write_text(json.dumps(metadata))
        self.assertFalse(audit_result(self.root)["total_proven"])
        self.prepare(128)
        self.manifest["status"] = "failed"
        self.persist()
        report = audit_result(self.root)
        self.assertTrue(report["total_proven"])
        self.assertFalse(report["accepted"])

    def test_corrupt_gzip_and_nonfinite_guard_fail_closed(self):
        path = self.root / "tx" / "raw" / "run_00001.csv.gz"
        packed = bytearray(path.read_bytes())
        packed[-8] ^= 1  # CRC corruption with an otherwise complete stream.
        path.write_bytes(packed)
        self.assertFalse(audit_result(self.root)["accepted"])
        self.write_capture("tx", self.windows("tx"))
        rows = list(csv.reader(io.StringIO(gzip.decompress(path.read_bytes()).decode())))
        rows[1797 + 1][1] = "nan"
        stream = io.StringIO()
        csv.writer(stream).writerows(rows)
        path.write_bytes(gzip.compress(stream.getvalue().encode()))
        report = audit_result(self.root)
        self.assertFalse(report["total_proven"])
        self.assertFalse(report["accepted"])

    def test_refuses_nonfragmented_scope_and_output_overwrite(self):
        target = self.root / "audit.json"
        self.assertEqual(main([str(self.root), "--output", str(target)]), 0)
        before = target.read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([str(self.root), "--output", str(target)])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(before, target.read_bytes())
        self.manifest["fragmented"] = False
        self.persist()
        with self.assertRaisesRegex(ValueError, "explicit E79"):
            audit_result(self.root)

    def test_batch_cannot_redefine_the_required_five_transfers(self):
        self.manifest["expected_rows"] = 1
        self.persist()
        report = audit_result(self.root)
        self.assertTrue(report["total_proven"])
        self.assertFalse(report["accepted"])
        self.assertIn("exactly five", " ".join(report["errors"]))


if __name__ == "__main__":
    unittest.main()
