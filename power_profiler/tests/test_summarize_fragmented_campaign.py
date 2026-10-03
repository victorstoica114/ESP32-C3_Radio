import csv
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from tools.summarize_fragmented_campaign import METHOD, POLICY, summarize


class FragmentedCampaignSummaryTests(unittest.TestCase):
    """Accepted synthetic records have known current; long gaps carry no energy."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest_path = self.root / 'manifest.json'
        phys = ('GFSK4K8', 'GFSK50', 'GFSK200', 'SLR2K5', 'SLR5', 'OOK4K8', 'IEEE154G50')
        self.conditions = [(size, phy, 13) for size in (128, 512, 1024) for phy in phys]
        self.manifest = {
            'kind': 'paired_fragmented_campaign', 'state': 'failed', 'completed_steps': 0,
            'config': {'integration_mode': 'radio_markers', 'marker_totals_only': True},
            'steps': [
                {'step_id': f'fragment_{size}_{phy}', 'status': 'pending', 'expected_rows': 5,
                 'command': ['python', '-m', 'radio_power_profiler.paired_runner',
                             '--payload-bytes', str(size), '--rf-profile', phy, '--tx-power-dbm', str(power),
                             '--repetitions', '5', '--integration-mode', 'radio_markers',
                             '--marker-totals-only', '--fragmented']}
                for size, phy, power in self.conditions
            ],
        }

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    @staticmethod
    def write_csv(path, rows):
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def accept(self, index=0):
        size, phy, power = self.conditions[index]
        result = self.root / self.manifest['steps'][index]['step_id']
        result.mkdir()
        pairing = {
            'status': 'valid', 'expected_rows': 5, 'session_id': result.name,
            'payload_bytes': size, 'rf_profile': phy, 'tx_power_dbm': power,
            'profile_id': 'RADIO_EBYTE_E79_CC1352P', 'frame_count': size // 64, 'fragmented': True,
            'integration_mode': 'radio_markers', 'marker_totals_only': True, 'energy_policy': POLICY,
            'sample_rate_hz': 100_000, 'endpoints': {role: {'voltage_mv': 3300} for role in ('tx', 'rx')},
            'rows': [],
        }
        summaries = {'tx': [], 'rx': []}
        for repetition in range(1, 6):
            run_id = f'run_{repetition:05d}'
            pair = {'run_id': run_id, 'paired_transfer_id': f'{result.name}:{run_id}',
                    'status': 'valid', 'packet_received': True, 'tx_status': 'ok', 'rx_status': 'ok',
                    'marker_diagnostics': {'valid': True, 'roles': {}}}
            for role in ('tx', 'rx'):
                # Deliberately unequal TX/RX widths, with 1000 samples between rising edges.
                width = 10 if role == 'tx' else 5
                current = repetition * (1000 if role == 'tx' else 2000)
                windows = [[100 + 1000 * frame, 100 + 1000 * frame + width]
                           for frame in range(size // 64)]
                count = windows[-1][1] + 100
                proofs = [{'valid': True, 'sample_rate_hz': 100_000, 'window_samples': window,
                           'captured_sample_count': count, 'voltage_mv': 3300,
                           'charge_total_uC': current * width / 100_000,
                           'energy_total_uJ': current * width / 100_000 * 3.3}
                          for window in windows]
                pair['marker_diagnostics']['roles'][role] = {
                    'valid': True, 'windows_samples': windows, 'software_trigger_index': 50,
                    'frame_proofs': proofs,
                }
                charge = current * width * len(windows) / 100_000
                summaries[role].append({
                    'run_id': run_id, 'repetition': repetition, 'status': 'ok',
                    'packet_received': True, 'packet_lost': False, 'analysis_error': '',
                    'measurement_direction': role, 'integration_method': METHOD,
                    'profile_id': pairing['profile_id'], 'payload_bytes': size,
                    'parameters_json': json.dumps({'rf_profile': phy, 'tx_power_dbm': power}),
                    'baseline_median_uA': '', 'threshold_uA': '', 'charge_excess_uC': '', 'energy_excess_uJ': '',
                    'frame_count': len(windows), 'serial_content_bytes': size, 'voltage_mv': 3300,
                    'captured_samples': count, 'energy_total_uJ': charge * 3.3, 'charge_total_uC': charge,
                    'event_duration_ms': width * len(windows) / 100,
                    'event_mean_uA': current,
                    'integration_windows_ms': json.dumps([[(start - 50) / 100, (stop - 50) / 100]
                                                         for start, stop in windows]),
                })
            pairing['rows'].append(pair)
        self.write_json(result / 'pairing.json', pairing)
        for role, rows in summaries.items():
            (result / role).mkdir()
            self.write_csv(result / role / 'summary.csv', rows)
        self.manifest['steps'][index].update(status='completed', accepted_result=result.name,
                                             validation={'valid': True})
        self.manifest['completed_steps'] += 1
        return result, pairing, summaries

    def summarize(self):
        self.write_json(self.manifest_path, self.manifest)
        return summarize(self.manifest_path)

    def test_partial_report_uses_only_accepted_attempt_and_sample_sd(self):
        result, _, _ = self.accept()
        failed = self.root / 'failed_attempt'
        failed.mkdir()
        (failed / 'pairing.json').write_text('deliberately invalid unaccepted JSON', encoding='utf-8')
        self.manifest['steps'][1].update(status='failed', attempts=[{'result': str(failed)}])
        report = self.summarize()
        self.assertEqual((report['coverage_status'], report['accepted_pairs'], report['accepted_role_rows']),
                         ('partial', 5, 10))
        self.assertEqual(len(report['missing_conditions']), 20)
        self.assertEqual(len(report['excluded_steps']), 20)
        self.assertEqual(len(report['inputs']), 4)  # manifest, pairing and two role CSVs only
        self.assertNotIn(str(failed / 'pairing.json'), report['inputs'])
        for aggregate in report['aggregates']:
            # Five energies 0.66, 1.32, 1.98, 2.64, 3.30 uJ in both roles.
            self.assertAlmostEqual(aggregate['energy_total_uJ_mean'], 1.98)
            self.assertAlmostEqual(aggregate['energy_total_uJ_sd'], .66 * math.sqrt(2.5))
            self.assertAlmostEqual(aggregate['charge_total_uC_mean'], .6)
            self.assertAlmostEqual(aggregate['charge_total_uC_sd'], .2 * math.sqrt(2.5))
            self.assertEqual(aggregate['duration_ms_mean'], .2 if aggregate['role'] == 'tx' else .1)
            self.assertEqual(aggregate['duration_ms_sd'], 0)
            self.assertEqual(aggregate['mean_current_uA_mean'], 3000 if aggregate['role'] == 'tx' else 6000)
        source = str((result / 'pairing.json').resolve())
        self.assertEqual(report['inputs'][source]['sha256'], hashlib.sha256(Path(source).read_bytes()).hexdigest())

    def test_complete_grid_has_105_pairs_210_role_rows_and_all_three_fragment_counts(self):
        for index in range(21):
            self.accept(index)
        self.manifest['state'] = 'completed'
        report = self.summarize()
        self.assertEqual(report['coverage_status'], 'complete')
        self.assertEqual(report['accepted_conditions'], 21)
        self.assertEqual(report['accepted_pairs'], 105)
        self.assertEqual(report['accepted_role_rows'], 210)
        self.assertEqual(len(report['aggregates']), 42)
        self.assertEqual(report['missing_conditions'], [])
        self.assertEqual(len({identifier for source in report['accepted_sources']
                              for identifier in source['paired_transfer_ids']}), 105)

    def test_duration_cannot_include_inter_frame_gaps(self):
        result, pairing, rows = self.accept()
        windows = pairing['rows'][0]['marker_diagnostics']['roles']['tx']['windows_samples']
        rows['tx'][0]['event_duration_ms'] = (windows[-1][1] - windows[0][0]) / 100
        self.write_csv(result / 'tx' / 'summary.csv', rows['tx'])
        with self.assertRaisesRegex(ValueError, 'Duration includes gaps'):
            self.summarize()

    def test_mean_current_cannot_use_elapsed_duration_including_gaps(self):
        result, pairing, rows = self.accept()
        windows = pairing['rows'][0]['marker_diagnostics']['roles']['rx']['windows_samples']
        rows['rx'][0]['event_mean_uA'] = rows['rx'][0]['charge_total_uC'] * 100_000 / (windows[-1][1] - windows[0][0])
        self.write_csv(result / 'rx' / 'summary.csv', rows['rx'])
        with self.assertRaisesRegex(ValueError, 'Mean current differs'):
            self.summarize()

    def test_csv_windows_must_match_frame_proofs_even_when_widths_match(self):
        result, _, rows = self.accept()
        windows = json.loads(rows['tx'][0]['integration_windows_ms'])
        windows[1] = [edge + 1 for edge in windows[1]]
        rows['tx'][0]['integration_windows_ms'] = json.dumps(windows)
        self.write_csv(result / 'tx' / 'summary.csv', rows['tx'])
        with self.assertRaisesRegex(ValueError, 'CSV integration windows differ'):
            self.summarize()

    def test_each_frame_sample_rate_and_voltage_are_checked(self):
        result, pairing, _ = self.accept()
        proof = pairing['rows'][4]['marker_diagnostics']['roles']['rx']['frame_proofs'][1]
        for field, invalid, message in (('sample_rate_hz', 50_000, 'sample rate'),
                                        ('voltage_mv', 3000, 'voltage differs'),
                                        ('captured_sample_count', 1, 'sample count differs')):
            original = proof[field]
            with self.subTest(field=field):
                proof[field] = invalid
                self.write_json(result / 'pairing.json', pairing)
                with self.assertRaisesRegex(ValueError, message):
                    self.summarize()
            proof[field] = original

    def test_charge_energy_must_agree_with_each_frame_and_voltage(self):
        result, pairing, rows = self.accept()
        rows['tx'][0]['energy_total_uJ'] *= 2
        self.write_csv(result / 'tx' / 'summary.csv', rows['tx'])
        with self.assertRaisesRegex(ValueError, 'energy_total_uJ differs'):
            self.summarize()
        for proof in pairing['rows'][0]['marker_diagnostics']['roles']['tx']['frame_proofs']:
            proof['energy_total_uJ'] *= 2
        self.write_json(result / 'pairing.json', pairing)
        with self.assertRaisesRegex(ValueError, 'Energy differs from charge'):
            self.summarize()

    def test_later_failed_proof_or_missing_delivery_rejects_whole_accepted_batch(self):
        result, pairing, _ = self.accept(14)  # 1024 B, sixteen frames
        proof = pairing['rows'][4]['marker_diagnostics']['roles']['rx']['frame_proofs'][-1]
        proof['valid'] = False
        self.write_json(result / 'pairing.json', pairing)
        with self.assertRaisesRegex(ValueError, 'Every frame requires'):
            self.summarize()
        proof['valid'] = True
        pairing['rows'][4]['packet_received'] = False
        self.write_json(result / 'pairing.json', pairing)
        with self.assertRaisesRegex(ValueError, 'undelivered pair'):
            self.summarize()

    def test_nonfinite_metrics_and_baseline_excess_are_rejected(self):
        result, _, rows = self.accept()
        row = rows['rx'][2]
        for key, invalid, message in (('energy_total_uJ', 'nan', 'Invalid energy'),
                                      ('event_mean_uA', 'inf', 'Invalid event_mean'),
                                      ('energy_excess_uJ', '0', 'baseline/excess')):
            original = row[key]
            with self.subTest(key=key):
                row[key] = invalid
                self.write_csv(result / 'rx' / 'summary.csv', rows['rx'])
                with self.assertRaisesRegex(ValueError, message):
                    self.summarize()
            row[key] = original

    def test_running_manifest_or_false_complete_coverage_cannot_be_published(self):
        self.accept()
        for state, message in (('running', 'must be terminal'), ('completed', 'lacks full accepted coverage')):
            with self.subTest(state=state):
                self.manifest['state'] = state
                with self.assertRaisesRegex(ValueError, message):
                    self.summarize()

    def test_duplicate_condition_and_accepted_result_on_failed_step_are_rejected(self):
        self.accept()
        original = self.manifest['steps'][1]['command']
        self.manifest['steps'][1]['command'] = self.manifest['steps'][0]['command'][:]
        with self.assertRaisesRegex(ValueError, 'duplicate condition'):
            self.summarize()
        self.manifest['steps'][1]['command'] = original
        self.manifest['steps'][1].update(status='failed', accepted_result='unaccepted')
        with self.assertRaisesRegex(ValueError, 'Noncompleted step'):
            self.summarize()


if __name__ == '__main__':
    unittest.main()
