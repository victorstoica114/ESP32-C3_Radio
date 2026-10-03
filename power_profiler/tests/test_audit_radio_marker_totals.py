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

from tools.audit_radio_marker_totals import audit_result, main


class AuditRadioMarkerTotalsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        coefficients = {name: {str(i): value for i in range(5)}
                        for name, value in {"R": 1, "O": 0, "GS": 0, "GI": 1,
                                           "S": 0, "I": 0, "UG": 1}.items()}
        coefficients["Calibrated"] = "0"
        self.metadata = {"session_id": "offline-fixture", "endpoints": {
            role: {"voltage_mv": 3300, "ppk_calibration_metadata": coefficients}
            for role in ("tx", "rx")}}
        self.manifest = {"session_id": "offline-fixture", "status": "failed",
                         "sample_rate_hz": 100000, "integration_mode": "radio_markers",
                         "rows": [{"run_id": "run_00001", "status": "failed",
                                   "packet_received": True, "tx_status": "analysis_review_required",
                                   "rx_status": "analysis_review_required"}]}
        (self.root / "pairing.json").write_text(json.dumps(self.manifest))
        for role in ("tx", "rx"):
            (self.root / role / "raw").mkdir(parents=True)
            (self.root / role / "metadata.json").write_text(json.dumps(self.metadata))
        (self.root / "wire" / "run_00001").mkdir(parents=True)
        self.write_role("tx", ((1800, 1978),))
        self.write_role("rx", ((1850, 1990),))

    def wire_path(self, role):
        return self.root / "wire" / "run_00001" / f"{role}.ppk2.bin"

    def csv_path(self, role):
        return self.root / role / "raw" / "run_00001.csv.gz"

    def write_role(self, role, pulses, *, mutations=None, csv_delta_index=None,
                   csv_delta=0, logic_mismatch_index=None):
        words = [100 | (3 << 14) | ((i % 64) << 18)
                 | (int(any(a <= i < b for a, b in pulses)) << 24) for i in range(3000)]
        for index, change in (mutations or {}).items():
            words[index] = change(words[index])
        self.wire_path(role).write_bytes(b"".join(struct.pack("<I", word) for word in words))
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["sample_index", "current_uA", "logic_bits", "trigger"])
        for i, word in enumerate(words):
            # Deliberately simple, analytic calibration; no production decoder.
            current = (word & 0x3FFF) * 4 * (1.8 / 163840) * 1e6
            if i == csv_delta_index:
                current += csv_delta
            logic = word >> 24
            if i == logic_mismatch_index:
                logic ^= 1
            writer.writerow([i, current, logic, int(i == 1500)])
        self.csv_path(role).write_bytes(gzip.compress(stream.getvalue().encode()))

    def tx(self):
        return audit_result(self.root)["runs"][0]["roles"]["tx"]

    def test_independent_unequal_intervals_and_failed_acceptance_are_preserved(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob("*") if p.is_file()}
        report = audit_result(self.root)
        self.assertEqual(report["official_status_unchanged"], "failed")
        self.assertFalse(report["acceptance_changed"])
        run = report["runs"][0]
        self.assertTrue(run["delivery"]["packet_received_recorded"])
        for role, samples in (("tx", 178), ("rx", 140)):
            detail = run["roles"][role]
            self.assertTrue(detail["total_proven"], detail)
            self.assertAlmostEqual(detail["total_energy_uJ"], 4394.53125 * samples / 100000 * 3.3)
            self.assertTrue(detail["pulses"][0]["adc_csv_exact_match"])
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_baseline_anomaly_does_not_enter_stable_range_total(self):
        self.write_role("tx", ((1800, 1978),), mutations={600: lambda word: word ^ (1 << 18)})
        detail = self.tx()
        self.assertFalse(detail["baseline_integrity_clean"])
        self.assertEqual(detail["baseline_qa"]["counter_anomaly_indices"], [600, 601])
        self.assertTrue(detail["total_proven"])
        self.assertEqual(detail["pulses"][0]["range_counts_guard"], {3: 181})

    def test_fault_in_guard_pulse_or_falling_boundary_prevents_total(self):
        for index in (1797, 1799, 1800, 1900, 1978):
            with self.subTest(index=index):
                self.write_role("tx", ((1800, 1978),), mutations={index: lambda word: word ^ (1 << 18)})
                detail = self.tx()
                self.assertFalse(detail["total_proven"])
                self.assertIsNone(detail["total_energy_uJ"])

    def test_range_change_can_reintroduce_iir_memory_despite_matching_direct_adc(self):
        self.write_role("tx", ((1800, 1978),), mutations={
            600: lambda word: word ^ (1 << 18),
            1798: lambda word: (word & ~(7 << 14)) | (2 << 14),
        })
        detail = self.tx()
        self.assertFalse(detail["total_proven"])
        pulse = detail["pulses"][0]
        self.assertTrue(pulse["adc_csv_exact_match"])
        self.assertFalse(pulse["direct_adc_dependency_proven"])
        self.assertIn("stateful decoder", " ".join(detail["reasons"]))

    def test_invalid_range_and_reserved_bit_are_not_clamped_or_repaired(self):
        for mutate in (lambda word: (word & ~(7 << 14)) | (7 << 14),
                       lambda word: word | (1 << 17)):
            with self.subTest(mutate=mutate):
                self.write_role("tx", ((1800, 1978),), mutations={1805: mutate})
                self.assertFalse(self.tx()["total_proven"])

    def test_csv_current_tolerance_is_explicit_and_mismatch_prevents_total(self):
        self.write_role("tx", ((1800, 1978),), csv_delta_index=1820, csv_delta=0.01)
        self.assertFalse(self.tx()["total_proven"])
        self.write_role("tx", ((1800, 1978),), csv_delta_index=1820, csv_delta=1e-7)
        detail = self.tx()
        self.assertTrue(detail["total_proven"])
        self.assertFalse(detail["pulses"][0]["adc_csv_exact_match"])
        self.assertTrue(detail["pulses"][0]["adc_csv_within_tolerance"])

    def test_absent_rx_pulse_does_not_discard_diagnostic_tx_total_or_change_delivery(self):
        self.write_role("rx", ())
        run = audit_result(self.root)["runs"][0]
        self.assertTrue(run["roles"]["tx"]["total_proven"])
        self.assertIsNone(run["roles"]["rx"]["total_energy_uJ"])
        self.assertEqual(run["roles"]["rx"]["pulse_count"], 0)
        self.assertTrue(run["delivery"]["packet_received_recorded"])

    def test_multiple_and_truncated_pulses_are_not_selected_or_summed(self):
        for pulses in (((1800, 1810), (1850, 1860)), ((2990, 3000),), ((0, 15),)):
            with self.subTest(pulses=pulses):
                self.write_role("tx", pulses)
                self.assertFalse(self.tx()["total_proven"])
                self.assertIsNone(self.tx()["total_energy_uJ"])

    def test_digital_mismatch_and_gzip_corruption_fail_closed(self):
        self.write_role("tx", ((1800, 1978),), logic_mismatch_index=1800)
        self.assertFalse(self.tx()["total_proven"])
        self.write_role("tx", ((1800, 1978),))
        self.csv_path("tx").write_bytes(self.csv_path("tx").read_bytes()[:-6])
        self.assertFalse(self.tx()["total_proven"])

    def test_calibration_is_required_and_unsafe_run_ids_are_rejected(self):
        metadata = json.loads((self.root / "tx" / "metadata.json").read_text())
        del metadata["endpoints"]["tx"]["ppk_calibration_metadata"]["R"]
        (self.root / "tx" / "metadata.json").write_text(json.dumps(metadata))
        self.assertFalse(self.tx()["total_proven"])
        self.manifest["rows"][0]["run_id"] = "../outside"
        (self.root / "pairing.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            audit_result(self.root)

    def test_report_output_cannot_overwrite_any_existing_file(self):
        target = self.root / "pairing.json"
        before = target.read_bytes()
        error_output = io.StringIO()
        with redirect_stderr(error_output), self.assertRaises(SystemExit) as caught:
            main([str(self.root), "--output", str(target)])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("Audit failed:", error_output.getvalue())
        self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
