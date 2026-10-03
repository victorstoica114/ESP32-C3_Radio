import csv
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools.audit_filter_marker_totals import (COEFFICIENTS, CURRENT_POLICY, ENERGY_POLICY, TOLERANCE_UA,
    advance_states, audit_result, energy_budget, normalize, prove, replay)


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.cal = {name: {str(i): 0.0 for i in range(5)} for name in COEFFICIENTS}
        for i in range(5):
            self.cal['R'][str(i)] = 10.0/(i+1)
            self.cal['GI'][str(i)] = self.cal['UG'][str(i)] = 1.0

    def fixture(self, fault=None, start=450, switch=True, range4=False):
        words = []
        for i in range(550):
            g = 3 if switch and 460 <= i < 467 else 2
            if range4 and 459 <= i < 466: g = 4
            counter = (i + (3 if i == fault else 0)) % 64
            words.append(800 | g << 14 | counter << 18 | (int(start <= i < 480) << 24))
        c, v = normalize(self.cal, 3300)
        values, _ = replay(words, c, v)
        return words, values, [w >> 24 for w in words], 100

    def test_clean_range_change(self):
        r = prove(*self.fixture(), self.cal, 3300)
        self.assertTrue(r['valid_candidate_not_acceptance']); self.assertEqual(r['history_max_bound_uA'], 0)

    def test_distant_fault_converges(self):
        self.assertTrue(prove(*self.fixture(fault=20), self.cal, 3300)['valid_candidate_not_acceptance'])

    def test_local_counter_rejected(self):
        self.assertFalse(prove(*self.fixture(fault=470), self.cal, 3300)['valid_candidate_not_acceptance'])

    def test_recent_fault_cannot_be_ignored(self):
        r = prove(*self.fixture(fault=440), self.cal, 3300)
        self.assertFalse(r['valid_candidate_not_acceptance']); self.assertGreater(r['history_max_bound_uA'], TOLERANCE_UA)

    def test_range4_freeze_and_uncertainty(self):
        clean = prove(*self.fixture(range4=True), self.cal, 3300)
        dirty = prove(*self.fixture(fault=440, range4=True), self.cal, 3300)
        self.assertTrue(clean['valid_candidate_not_acceptance']); self.assertFalse(dirty['valid_candidate_not_acceptance'])

    def test_boundary_high_rejected(self):
        args = self.fixture(); words = [w | (1 << 24) for w in args[0]]
        self.assertFalse(prove(words, args[1], [w >> 24 for w in words], 100, self.cal, 3300)['valid_candidate_not_acceptance'])

    def test_raw_mismatch_rejected(self):
        args = self.fixture(); args[1][461] += 1
        self.assertFalse(prove(*args, self.cal, 3300)['valid_candidate_not_acceptance'])

    def test_invalid_calibration(self):
        self.cal['R']['3'] = 0
        with self.assertRaises(ValueError): prove(*self.fixture(switch=False), self.cal, 3300)

    def test_range4_freezes_both_states_for_exactly_two_samples(self):
        states = {(3, 0, 0): (1.0, 2.0, 3.0, 4.0)}
        states, output = advance_states(states, 4, 10.0)
        self.assertEqual(states, {(4, 2, 0): (1.0, 2.0, 3.0, 4.0)})
        self.assertEqual(output, (3.0, 4.0))
        states, output = advance_states(states, 4, 10.0)
        self.assertEqual(states, {(4, 1, 1): (1.0, 2.0, 3.0, 4.0)})
        states, output = advance_states(states, 4, 10.0)
        self.assertEqual(output, (.06 * 10 + (1-.06) * 3, .06 * 10 + (1-.06) * 4))
        self.assertEqual(states[(4, 0, 2)][:2],
                         (.18 * 10 + (1-.18) * 1, .18 * 10 + (1-.18) * 2))

    def test_fault_after_falling_boundary_implicates_boundary_word(self):
        result = prove(*self.fixture(fault=481), self.cal, 3300)
        self.assertFalse(result['valid_candidate_not_acceptance'])
        self.assertIn(480, result['suspect_indices_guard'])

    def test_bit17_in_marker_rejected_even_with_matching_replay(self):
        args = self.fixture()
        args[0][465] |= 1 << 17
        result = prove(*args, self.cal, 3300)
        self.assertFalse(result['valid_candidate_not_acceptance'])
        self.assertEqual(result['replay_max_difference_uA'], 0)

    def test_nonfinite_current_anywhere_cannot_be_hidden(self):
        args = self.fixture()
        args[1][500] = float('nan')
        with self.assertRaisesRegex(ValueError, 'Nonfinite RAW'):
            prove(*args, self.cal, 3300)

    def test_v2_bounds_integrated_energy_separately_from_pointwise_error(self):
        args = self.fixture(fault=390)
        old = prove(*args, self.cal, 3300)
        new = prove(*args, self.cal, 3300, history_policy=ENERGY_POLICY)
        self.assertEqual(old['history_policy'], CURRENT_POLICY)
        self.assertFalse(old['valid_candidate_not_acceptance'])
        self.assertTrue(new['valid_candidate_not_acceptance'])
        self.assertGreater(new['combined_error_bound_uA'], TOLERANCE_UA)
        self.assertGreater(new['energy_history_relative_bound'], 0)
        self.assertLessEqual(new['energy_history_relative_bound'], 1e-4)
        self.assertGreater(new['energy_interval_uJ'][0], 0)
        self.assertLessEqual(new['energy_interval_uJ'][0], new['diagnostic_energy_uJ'])
        self.assertGreaterEqual(new['energy_interval_uJ'][1], new['diagnostic_energy_uJ'])

    def test_energy_budget_rejects_large_uncertainty_and_nonpositive_interval(self):
        self.assertTrue(energy_budget([100, 100.005], 100.002)[0])
        self.assertFalse(energy_budget([100, 100.02], 100.01)[0])
        for interval, nominal in [([0, 1], .5), ([-1, 2], 1), ([1, 2], 3),
                                  ([1, float('inf')], 1.5)]:
            self.assertFalse(energy_budget(interval, nominal)[0])

    def test_v2_preserves_local_fault_and_full_replay_gates(self):
        self.assertFalse(prove(*self.fixture(fault=470), self.cal, 3300,
                               history_policy=ENERGY_POLICY)['valid_candidate_not_acceptance'])
        args = self.fixture()
        args[1][500] += 2e-6
        self.assertFalse(prove(*args, self.cal, 3300,
                               history_policy=ENERGY_POLICY)['valid_candidate_not_acceptance'])

    def test_unknown_history_policy_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, 'Unknown history policy'):
            prove(*self.fixture(), self.cal, 3300, history_policy='unbounded')

    def test_generic_audit_selects_metadata_policy_without_accepting_failed_result(self):
        words, currents, logic, trigger = self.fixture(fault=390)
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp)
            row = {'run_id': 'run_00001', 'status': 'failed', 'packet_received': True,
                   'tx_raw': 'tx.csv.gz', 'rx_raw': 'rx.csv.gz',
                   'wire_paths': {'tx': 'tx.bin', 'rx': 'rx.bin'}}
            manifest = {'status': 'failed', 'sample_rate_hz': 100000, 'expected_rows': 5,
                        'filter_history_policy': ENERGY_POLICY, 'rows': [row],
                        'endpoints': {role: {'voltage_mv': 3300, 'ppk_calibration_metadata': self.cal}
                                      for role in ('tx', 'rx')}}
            (result/'pairing.json').write_text(json.dumps(manifest), encoding='utf-8')
            before = (result/'pairing.json').read_bytes()
            for role in ('tx', 'rx'):
                (result/(role+'.bin')).write_bytes(b''.join(struct.pack('<I', word) for word in words))
                stream = io.StringIO(); writer = csv.writer(stream)
                writer.writerow(['sample_index', 'current_uA', 'logic_bits', 'trigger'])
                writer.writerows((i, current, logic[i], int(i == trigger)) for i, current in enumerate(currents))
                (result/(role+'.csv.gz')).write_bytes(gzip.compress(stream.getvalue().encode()))
            report = audit_result(result)
            self.assertTrue(all(r['valid_candidate_not_acceptance'] for r in report['captures']))
            self.assertTrue(all(r['history_policy'] == ENERGY_POLICY for r in report['captures']))
            self.assertFalse(report['complete_recorded_batch_independently_consistent'])
            self.assertFalse(report['acceptance_changed'])
            self.assertEqual(before, (result/'pairing.json').read_bytes())
            old = audit_result(result, history_policy=CURRENT_POLICY)
            self.assertFalse(any(r['valid_candidate_not_acceptance'] for r in old['captures']))



if __name__ == "__main__":
    unittest.main()
