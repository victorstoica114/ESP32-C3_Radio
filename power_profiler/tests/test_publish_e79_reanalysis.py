import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import publish_e79_reanalysis as publisher


class E79PublicationValidationTests(unittest.TestCase):
    def record(self):
        original = {field: "" for field in publisher.FIELDS}
        original.update(
            run_id="run_00001", profile_id="RADIO_EBYTE_E79_CC1352P",
            measurement_direction="tx", payload_bytes="32", frame_count="1",
            repetition="1", parameters_json='{"rf_profile":"GFSK200","tx_power_dbm":13}',
            voltage_mv="1000", packet_received="True", status="ok",
            event_start_ms="1", event_duration_ms="10", tx_mean_uA="10000",
            tx_peak_uA="12000", event_mean_uA="10000", event_peak_uA="12000",
            charge_total_uC="100", charge_excess_uC="80",
            energy_total_uJ="100", energy_excess_uJ="80",
        )
        corrected = dict(original)
        corrected.update(analysis_error="", integration_method="original_single_frame_window_verified", integration_windows_ms="[[1, 11]]")
        record = {
            "step_id": "tx_p13_rf_profile-GFSK200_s32", "run_id": "run_00001",
            "quality": "model_window_reanalysis", "reasons": [],
            "original_energy_total_uJ": 100, "original_energy_excess_uJ": 80,
            "recalculated_energy_total_uJ": 100, "recalculated_energy_excess_uJ": 80,
            "frame_windows_ms": [[1, 11]], "corrected_summary": corrected,
        }
        return record, original

    def test_verified_single_frame_keeps_original_values(self):
        record, original = self.record()
        result = publisher.validate_corrected(record, original)
        self.assertEqual(result["energy_total_uJ"], original["energy_total_uJ"])

    def test_review_required_cannot_be_published(self):
        record, original = self.record()
        record["quality"] = "review_required"
        with self.assertRaisesRegex(ValueError, "requires review"):
            publisher.validate_corrected(record, original)

    def test_receiver_loss_cannot_be_rewritten_as_success(self):
        record, original = self.record()
        original["packet_received"] = "False"
        original["status"] = "rx_missing"
        with self.assertRaisesRegex(ValueError, "configuration/telemetry"):
            publisher.validate_corrected(record, original)

    def test_energy_must_match_integrated_mean_and_duration(self):
        record, original = self.record()
        record["recalculated_energy_total_uJ"] = 120
        record["corrected_summary"]["energy_total_uJ"] = 120
        with self.assertRaisesRegex(ValueError, "mean current, duration and energy"):
            publisher.validate_corrected(record, original)

    def test_single_frame_cannot_be_silently_reintegrated(self):
        record, original = self.record()
        record["recalculated_energy_total_uJ"] = 200
        record["corrected_summary"].update(energy_total_uJ=200, event_mean_uA=20000, tx_mean_uA=20000)
        with self.assertRaisesRegex(ValueError, "retain their original metrics"):
            publisher.validate_corrected(record, original)

    def test_archive_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in ("../outside.csv.gz", "C:/other/raw.csv.gz", "/other/raw.csv.gz"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    publisher.contained_path(root, value)

    def test_raw_hash_mismatch_rejected_without_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "run.csv.gz"
            raw.write_bytes(b"changed archive content")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                publisher.verify_raw(raw, raw.name, "0" * 64, {}, None)

    def test_newer_source_rechecks_cache_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "run.csv.gz"
            raw.write_bytes(b"new")
            old_hash = hashlib.sha256(b"old").hexdigest()
            cache = {raw.name: {"valid": True, "sha256_compressed": old_hash, "compressed_bytes": 3}}
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                publisher.verify_raw(raw, raw.name, old_hash, cache, 0)

    def test_partial_input_is_rejected_before_any_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "runs.json").write_text(json.dumps([self.record()[0]]), encoding="utf-8")
            destination = root / "published"
            with self.assertRaisesRegex(ValueError, "exactly 630"):
                publisher.publish(root, inputs, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
