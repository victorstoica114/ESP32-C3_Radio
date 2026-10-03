import json
from pathlib import Path
import tempfile
import unittest

from radio_power_profiler.cli import make_parser
from radio_power_profiler.storage import (
    CONTINUOUS_RESULTS_ROOT, PACKET_RESULTS_ROOT, SESSIONS_ROOT,
    resolve_capture_command, resolve_measurement_path,
)


class StorageTests(unittest.TestCase):
    def test_old_windows_manifest_path_resolves_without_changing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = root / 'measurements/raw/sessions/campaign/tx/raw/run_00001.csv.gz'
            capture.parent.mkdir(parents=True)
            capture.write_bytes(b'original compressed bytes')
            old = r'D:\old-pc\ESP32-C3_Radio\power_profiler\web_sessions\campaign\tx\raw\run_00001.csv.gz'
            resolved = resolve_measurement_path(old, root=root)
            self.assertEqual(resolved, capture)
            self.assertEqual(resolved.read_bytes(), b'original compressed bytes')

    def test_archive_path_from_other_computer_resolves(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = 'E:/radio/module radio/ESP32-C3_Radio/power_profiler/web_sessions/old/raw/run.csv.gz'
            self.assertEqual(resolve_measurement_path(old, root=root),
                             root / 'measurements/raw/archive/web_sessions/old/raw/run.csv.gz')

    def test_existing_custom_output_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'custom.ppk2.bin'
            path.write_bytes(b'custom')
            self.assertEqual(resolve_measurement_path(path), path)

    def test_duplicate_alias_points_to_verified_canonical_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'measurements').mkdir()
            (root / 'measurements/relocation.json').write_text(json.dumps({'captures': [
                {'path': '.tmp/staging/run.csv.gz', 'new_path': 'measurements/raw/archive/run.csv.gz'}
            ]}))
            self.assertEqual(resolve_measurement_path('.tmp/staging/run.csv.gz', root=root),
                             root / 'measurements/raw/archive/run.csv.gz')

    def test_missing_capture_is_not_replaced_with_an_unrelated_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = resolve_measurement_path('power_profiler/web_sessions/missing.csv.gz', root=Path(temporary))
            self.assertFalse(path.exists())
            self.assertTrue(str(path).endswith('missing.csv.gz'))
            unrelated = Path(temporary) / 'elsewhere/missing.csv.gz'
            self.assertEqual(resolve_measurement_path(unrelated, root=Path(temporary)), unrelated)

    def test_path_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                resolve_measurement_path('power_profiler/web_sessions/../../../../outside.bin', root=Path(temporary))

    def test_saved_command_relocates_output_without_changing_fixture_or_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = 'PPK serial; power_profiler/web_sessions is only descriptive text'
            command = ['python', '-m', 'runner', '--output', 'power_profiler/web_sessions/campaign/result',
                       '--tx-identity', identity, '--tx-voltage-mv', '3300']
            rewritten = resolve_capture_command(command, root=root)
            self.assertEqual(rewritten[4], str(root / 'measurements/raw/sessions/campaign/result'))
            self.assertEqual(rewritten[5:], command[5:])
            self.assertEqual(command[4], 'power_profiler/web_sessions/campaign/result')

    def test_all_capture_commands_default_to_central_storage(self):
        parser = make_parser()
        self.assertEqual(parser.parse_args(['web']).sessions_root, SESSIONS_ROOT)
        self.assertEqual(parser.parse_args(['run', '--module', 'RADIO_NRF24L01', '--radio-port', 'COM1']).output,
                         PACKET_RESULTS_ROOT)
        self.assertEqual(parser.parse_args(['continuous', '--module', 'RADIO_NRF24L01', '--radio-port', 'COM1', '--direction', 'tx']).output,
                         CONTINUOUS_RESULTS_ROOT)


if __name__ == '__main__':
    unittest.main()
