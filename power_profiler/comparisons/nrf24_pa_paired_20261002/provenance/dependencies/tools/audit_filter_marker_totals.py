"""Independent stdlib proof audit. Reads evidence; never changes acceptance.

The interval implementation enumerates uncertain decoder control states. It is
independent of production proof code; optional production calls are comparisons.
"""
from __future__ import annotations

import collections
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import struct
from types import SimpleNamespace

RATE = 100_000
TOLERANCE_UA = 1e-6
CURRENT_POLICY = 'current_equivalence_v1'
ENERGY_POLICY = 'energy_relative_v2'
HISTORY_POLICIES = (CURRENT_POLICY, ENERGY_POLICY)
ENERGY_RELATIVE_LIMIT = 1e-4
COEFFICIENTS = ('R', 'O', 'GS', 'GI', 'S', 'I', 'UG')
BOUND_CACHE = {}


def evidence(path):
    data = Path(path).read_bytes()
    return {'path': str(Path(path).resolve()), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}


def normalize(calibration, voltage_mv):
    c = {name: {str(i): float(calibration[name][str(i)]) for i in range(5)}
         for name in COEFFICIENTS}
    voltage = float(voltage_mv) / 1000
    if not math.isfinite(voltage) or voltage <= 0:
        raise ValueError('Voltage must be finite and positive')
    if any(not math.isfinite(v) for column in c.values() for v in column.values()):
        raise ValueError('Calibration must be finite')
    if any(v <= 0 for v in c['R'].values()):
        raise ValueError('Calibration resistance must be positive')
    return c, voltage


def adc_a(code, range_code, c, voltage):
    k = str(range_code)
    u = (code * 4 - c['O'][k]) * ((1.8 / 163840) / c['R'][k])
    value = c['UG'][k] * (u * (c['GS'][k] * u + c['GI'][k])
                         + (c['S'][k] * voltage + c['I'][k]))
    if not math.isfinite(value):
        raise ValueError('Calibrated ADC overflow or nonfinite value')
    return value


def invariant_bounds(c, voltage):
    key = json.dumps([c, voltage], sort_keys=True, allow_nan=False)
    if key in BOUND_CACHE:
        return BOUND_CACHE[key]
    low, high = math.inf, -math.inf
    for g in range(5):
        for code in range(16384):
            value = adc_a(code, g, c, voltage)
            low, high = min(low, value), max(high, value)
    adc_bounds = (low, high)
    for count in range(1000):
        image_low = min(a * adc_bounds[0] + (1 - a) * low for a in (.18, .06))
        image_high = max(a * adc_bounds[1] + (1 - a) * high for a in (.18, .06))
        if image_low >= low and image_high <= high:
            result = (low, high, adc_bounds, count)
            BOUND_CACHE[key] = result
            return result
        low = min(low, math.nextafter(image_low, -math.inf))
        high = max(high, math.nextafter(image_high, math.inf))
    raise ValueError('Unable to establish invariant float bounds')


def replay(words, c, voltage):
    fast = slow = previous = None
    after = consecutive = 0
    outputs, filtered = [], []
    for i, word in enumerate(words):
        g = min((word >> 14) & 7, 4)  # Exact archived decoder convention.
        value = adc_a(word & 0x3fff, g, c, voltage)
        old_fast, old_slow = fast, slow
        fast = value if fast is None else .18 * value + (1 - .18) * fast
        slow = value if slow is None else .06 * value + (1 - .06) * slow
        if previous is None:
            previous = g
        active = previous != g or after > 0
        if active:
            if previous != g:
                consecutive, after = 0, 3
            else:
                consecutive += 1
            if g == 4:
                if consecutive < 2:
                    fast, slow = old_fast, old_slow
                value = slow
            else:
                value = fast
            after -= 1
            filtered.append(i)
        previous = g
        outputs.append(value * 1e6)
    return outputs, filtered


def uncertain_states(low, high):
    return {(g, after, consecutive): (low, high, low, high)
            for g, after, consecutive in itertools.product(range(5), range(3), range(3))}


def advance_states(states, g, adc):
    result = {}
    output_low, output_high = math.inf, -math.inf
    for (previous, after, consecutive), bounds in states.items():
        fl, fh, sl, sh = bounds
        updated = (.18 * adc + (1 - .18) * fl, .18 * adc + (1 - .18) * fh,
                   .06 * adc + (1 - .06) * sl, .06 * adc + (1 - .06) * sh)
        active = previous != g or after > 0
        if active:
            if previous != g:
                consecutive, after = 0, 3
            else:
                consecutive = min(2, consecutive + 1)
            if g == 4:
                if consecutive < 2:
                    updated = bounds
                out_low, out_high = updated[2:4]
            else:
                out_low, out_high = updated[:2]
            after -= 1
        else:
            out_low = out_high = adc
        key = (g, after, consecutive)
        if key in result:
            old = result[key]
            updated = (min(old[0], updated[0]), max(old[1], updated[1]),
                       min(old[2], updated[2]), max(old[3], updated[3]))
        result[key] = updated
        output_low, output_high = min(output_low, out_low), max(output_high, out_high)
    return result, (output_low, output_high)


def pulses(words):
    found, start = [], None
    for i, word in enumerate(words):
        high = bool(word & (1 << 24))
        if high and start is None:
            start = i
        elif not high and start is not None:
            found.append((start, i)); start = None
    if start is not None:
        found.append((start, len(words)))
    return found


def outward_totals(intervals_uA, voltage):
    """Enclose the integrated history intervals, including float operations."""
    low_sum = math.nextafter(math.fsum(pair[0] for pair in intervals_uA), -math.inf)
    high_sum = math.nextafter(math.fsum(pair[1] for pair in intervals_uA), math.inf)
    charge = [math.nextafter(low_sum/RATE, -math.inf), math.nextafter(high_sum/RATE, math.inf)]
    energy = [math.nextafter(charge[0]*voltage, -math.inf), math.nextafter(charge[1]*voltage, math.inf)]
    if not all(math.isfinite(value) for value in charge + energy):
        raise ValueError('Nonfinite integrated interval')
    return charge, energy


def energy_budget(energy_interval, nominal):
    low, high = energy_interval
    if not all(math.isfinite(value) for value in (low, high, nominal)):
        return False, None
    if not 0 < low <= nominal <= high or nominal <= 0:
        return False, None
    width = 0.0 if high == low else math.nextafter(high-low, math.inf)
    ratio = width/min(abs(low), abs(high))
    if ratio > 0:
        ratio = math.nextafter(ratio, math.inf)
    return math.isfinite(ratio) and ratio <= ENERGY_RELATIVE_LIMIT, ratio


def prove(words, currents, logic, trigger, calibration, voltage_mv, *, history_policy=CURRENT_POLICY):
    if history_policy not in HISTORY_POLICIES:
        raise ValueError('Unknown history policy; no fallback permitted')
    c, voltage = normalize(calibration, voltage_mv)
    count = len(words)
    if not count or len(currents) != count or len(logic) != count:
        raise ValueError('Empty or inconsistent capture lengths')
    if isinstance(trigger, bool) or not isinstance(trigger, int) or not 0 <= trigger < count:
        raise ValueError('Software trigger outside capture')
    if any(not math.isfinite(v) for v in currents):
        raise ValueError('Nonfinite RAW current')
    windows = pulses(words)
    reasons = []
    if any(v != w >> 24 for v, w in zip(logic, words)):
        reasons.append('RAW/wire digital mismatch')
    decoded, filtered = replay(words, c, voltage)
    replay_error = max(abs(x - y) for x, y in zip(decoded, currents))
    if replay_error > TOLERANCE_UA:
        reasons.append('Full-history replay does not reproduce RAW current')
    counter_faults = [i for i in range(1, count)
                      if ((words[i] >> 18) & 63) != (((words[i-1] >> 18) & 63) + 1) % 64]
    bit17 = [i for i, w in enumerate(words) if w & (1 << 17)]
    invalid = [i for i, w in enumerate(words) if ((w >> 14) & 7) > 4]
    if invalid:
        reasons.append('Invalid range code anywhere in full capture')
    suspects = set(counter_faults + [i-1 for i in counter_faults] + bit17 + invalid)
    info = {'valid_candidate_not_acceptance': False, 'reasons': reasons, 'history_policy': history_policy,
            'pulse_windows': windows, 'sample_count': count,
            'replay_max_difference_uA': replay_error,
            'replay_exact_samples': sum(x == y for x, y in zip(decoded, currents)),
            'counter_transition_faults': counter_faults, 'bit17_indices': bit17,
            'invalid_range_indices': invalid, 'diagnostic_energy_uJ': None}
    if len(windows) != 1:
        reasons.append('Exactly one complete local pulse is required')
        return info
    start, stop = windows[0]
    if not 3 <= start < stop < count or start <= trigger or stop-start < 3:
        reasons.append('Incomplete, too short, or pretrigger marker')
        return info
    guard = start-3
    faults_local = sorted(i for i in suspects if guard <= i <= stop)
    if faults_local:
        reasons.append('Suspect word touches decoder guard, marker, or falling boundary')
    low, high, adc_bounds, iterations = invariant_bounds(c, voltage)
    states = None
    interval_rows = []
    intervals_uA = []
    last_fault = None
    for i in range(stop):
        w = words[i]; g = (w >> 14) & 7
        if i in suspects:
            states = uncertain_states(low, high)
            last_fault = i
            interval = (low, high)
        else:
            d = adc_a(w & 0x3fff, g, c, voltage)
            if states is None:
                states = {(g, 0, 0): (d, d, d, d)}
                interval = (d, d)
            else:
                states, interval = advance_states(states, g, d)
        if start <= i < stop:
            lo_uA, hi_uA = (v * 1e6 for v in interval)
            intervals_uA.append((lo_uA, hi_uA))
            if not lo_uA <= decoded[i] <= hi_uA:
                reasons.append('Nominal replay outside independent history enclosure')
            width = hi_uA - lo_uA
            error = math.nextafter(width, math.inf) if width > 0 else 0.0
            interval_rows.append({'sample_index': i, 'filtered': i in filtered,
                                  'last_suspect_index': last_fault,
                                  'history_bound_uA': error,
                                  'state_control_cases': len(states)})
    bound = max(r['history_bound_uA'] for r in interval_rows)
    combined = replay_error + bound
    if combined > 0:
        combined = math.nextafter(combined, math.inf)
    charge_interval, energy_interval = outward_totals(intervals_uA, voltage)
    nominal_charge = math.fsum(decoded[start:stop])/RATE
    nominal_energy = nominal_charge*voltage
    if not (charge_interval[0] <= nominal_charge <= charge_interval[1]
            and energy_interval[0] <= nominal_energy <= energy_interval[1]):
        reasons.append('Nominal total outside integrated history enclosure')
    energy_ok, energy_relative = energy_budget(energy_interval, nominal_energy)
    if history_policy == CURRENT_POLICY and combined > TOLERANCE_UA:
        reasons.append('Replay plus historical uncertainty exceeds fixed 1e-6 uA proof bound')
    if history_policy == ENERGY_POLICY and not energy_ok:
        reasons.append('Positive energy history interval exceeds fixed relative 1e-4 budget or excludes nominal')
    info.update(window_samples=[start, stop], duration_ms=(stop-start)/100,
                guard_window_samples=[guard, stop], suspect_indices_guard=faults_local,
                adc_bounds_A=adc_bounds, invariant_state_bounds_A=[low, high],
                bound_iterations=iterations, history_max_bound_uA=bound,
                combined_error_bound_uA=combined,
                charge_interval_uC=charge_interval, energy_interval_uJ=energy_interval,
                energy_history_relative_tolerance=ENERGY_RELATIVE_LIMIT,
                energy_history_relative_bound=energy_relative,
                energy_history_budget_valid=energy_ok,
                filtered_samples=[r for r in interval_rows if r['filtered']],
                filtered_sample_count=sum(r['filtered'] for r in interval_rows),
                history_energy_bound_uJ=math.fsum(r['history_bound_uA'] for r in interval_rows)/RATE*voltage,
                valid_candidate_not_acceptance=not reasons)
    if not reasons:
        info['diagnostic_energy_uJ'] = nominal_energy
        info['diagnostic_charge_uC'] = nominal_charge
    return info


def read_capture(raw_path, wire_path):
    blob = Path(wire_path).read_bytes()
    if not blob or len(blob) % 4:
        raise ValueError('Incomplete wire word')
    words = [v[0] for v in struct.iter_unpack('<I', blob)]
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(Path(raw_path).read_bytes()).decode('utf-8-sig'))))
    if any(int(r['sample_index']) != i for i, r in enumerate(rows)):
        raise ValueError('Noncontiguous RAW sample indices')
    triggers = [i for i, r in enumerate(rows) if int(r['trigger']) == 1]
    if len(triggers) != 1 or any(int(r['trigger']) not in (0, 1) for r in rows):
        raise ValueError('Expected one software trigger')
    return words, [float(r['current_uA']) for r in rows], [int(r['logic_bits']) for r in rows], triggers[0]


def audit_sources(sources, production_function=None, *, history_policy=None):
    if history_policy is not None and history_policy not in HISTORY_POLICIES:
        raise ValueError('Unknown history policy override')
    report = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
              'method': 'Independent binary64 control-state interval replay; no production proof imports except optional comparison',
              'acceptance_changed': False, 'fixed_tolerance_uA': TOLERANCE_UA,
              'energy_history_relative_tolerance': ENERGY_RELATIVE_LIMIT,
              'explicit_history_policy_override': history_policy,
              'limitations': ['Numerical decoder proof, not independent physical current calibration.',
                             'Modulo64 counters cannot exclude invisible block losses.',
                             'Old failed/incomplete campaigns remain failed; candidate is not acceptance.'],
              'helper': evidence(Path(__file__)), 'captures': [], 'sources': {}, 'production_differences': [],
              'dataset_contexts': []}
    for label, source, manifest, diagnostic in sources:
        recorded_policy = manifest.get('filter_history_policy', CURRENT_POLICY)
        selected_policy = recorded_policy if history_policy is None else history_policy
        if selected_policy not in HISTORY_POLICIES:
            raise ValueError('Unknown recorded history policy')
        report['sources'][str(source)] = evidence(source)
        if not manifest.get('runs' if diagnostic else 'rows'):
            raise ValueError('No recorded transfers in result')
        if not diagnostic and manifest.get('sample_rate_hz') != RATE:
            raise ValueError('Expected sample_rate_hz=100000')
        report['dataset_contexts'].append({'dataset': label, 'status': manifest.get('status'),
                                          'recorded_expected_rows': manifest.get('expected_rows'),
                                          'recorded_history_policy': recorded_policy,
                                          'audited_history_policy': selected_policy,
                                          'source': str(source)})
        run_ids = set()
        for row in manifest['runs' if diagnostic else 'rows']:
            if row['run_id'] in run_ids:
                raise ValueError('Duplicate transfer ID')
            run_ids.add(row['run_id'])
            for role in ('tx', 'rx'):
                base = source.parent
                if diagnostic:
                    raw_path = base/row['sources'][role]['raw']; wire_path = base/row['sources'][role]['wire']
                    calibration = manifest['endpoints'][role]['calibration']; voltage = manifest['voltage_mv']
                else:
                    raw_path = base/row[role+'_raw']; wire_path = base/row['wire_paths'][role]
                    calibration = manifest['endpoints'][role]['ppk_calibration_metadata']; voltage = manifest['endpoints'][role]['voltage_mv']
                if not all(path.resolve().is_relative_to(base.resolve()) for path in (raw_path, wire_path)):
                    raise ValueError('RAW/wire path escapes result directory')
                args = read_capture(raw_path, wire_path)
                if row.get('timing'):
                    timing = row['timing']
                    if timing['sample_rate_hz'] != RATE or args[3] != timing['devices'][role]['trigger_index']:
                        raise ValueError('RAW trigger/rate differs from capture timing metadata')
                info = prove(*args, calibration, voltage, history_policy=selected_policy)
                info.update(dataset=label, run_id=row['run_id'], role=role,
                            packet_received_recorded=row['packet_received'],
                            raw=evidence(raw_path), wire=evidence(wire_path))
                summary_path = base/role/'summary.csv'
                if not diagnostic and summary_path.exists():
                    report['sources'][str(summary_path)] = evidence(summary_path)
                    with summary_path.open(encoding='utf-8', newline='') as f:
                        summaries = [item for item in csv.DictReader(f) if item['run_id'] == row['run_id']]
                    if len(summaries) != 1:
                        raise ValueError('Missing or duplicate summary row')
                    info['recorded_summary'] = {k: summaries[0].get(k) for k in
                                                ('status', 'energy_total_uJ', 'charge_total_uC',
                                                 'event_duration_ms', 'integration_method',
                                                 'baseline_median_uA', 'energy_excess_uJ', 'charge_excess_uC')}
                    recorded = summaries[0].get('energy_total_uJ')
                    if recorded and info['diagnostic_energy_uJ'] is not None:
                        energy = float(recorded)
                        if not math.isfinite(energy):
                            raise ValueError('Nonfinite recorded energy')
                        info['absolute_recorded_energy_difference_uJ'] = abs(energy-info['diagnostic_energy_uJ'])
                        info['recorded_energy_matches_exactly'] = energy == info['diagnostic_energy_uJ']
                        info['recorded_charge_matches_exactly'] = float(summaries[0]['charge_total_uC']) == info['diagnostic_charge_uC']
                        info['recorded_baseline_excess_absent'] = all(summaries[0].get(key, '') == '' for key in
                            ('baseline_median_uA', 'threshold_uA', 'charge_excess_uC', 'energy_excess_uJ'))
                if production_function and len(info['pulse_windows']) == 1:
                    capture = SimpleNamespace(samples_uA=args[1], logic_bits=args[2], trigger_index=args[3])
                    prod = production_function(capture, wire_path, tuple(info['pulse_windows'][0]),
                                               calibration, voltage, RATE, history_policy=selected_policy)
                    info['production_comparison'] = {'valid': prod['valid'], 'reasons': prod['reasons'],
                                                     'energy_total_uJ': prod.get('energy_total_uJ')}
                    info['production_comparison']['energy_interval_uJ'] = prod.get('energy_interval_uJ')
                    info['production_comparison']['energy_history_relative_bound'] = prod.get('energy_history_relative_bound')
                    difference = prod['valid'] != info['valid_candidate_not_acceptance']
                    if prod['valid'] and info['valid_candidate_not_acceptance']:
                        delta = abs(prod['energy_total_uJ']-info['diagnostic_energy_uJ'])
                        info['production_comparison']['absolute_energy_difference_uJ'] = delta
                        difference |= delta > 1e-10
                    if difference:
                        report['production_differences'].append({'dataset': label, 'run_id': row['run_id'], 'role': role})
                report['captures'].append(info)
    report['summary'] = {label: {'captures': sum(r['dataset'] == label for r in report['captures']),
                                'candidate_proofs': sum(r['dataset'] == label and r['valid_candidate_not_acceptance'] for r in report['captures']),
                                'recorded_energies_present': sum(r['dataset'] == label and 'recorded_energy_matches_exactly' in r for r in report['captures']),
                                'recorded_energies_match_exactly': all(r.get('recorded_energy_matches_exactly', True) for r in report['captures'] if r['dataset'] == label)}
                         for label in sorted({r['dataset'] for r in report['captures']})}
    return report


def audit_result(result_root, production_function=None, *, history_policy=None):
    """Audit one arbitrary paired result, without changing its acceptance."""
    path = Path(result_root).resolve()/'pairing.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('sample_rate_hz') != RATE:
        raise ValueError('Expected sample_rate_hz=100000 in pairing manifest')
    result = audit_sources([('paired_result', path, manifest, False)], production_function, history_policy=history_policy)
    result['recorded_result_complete'] = (manifest.get('status') == 'valid'
        and len(manifest.get('rows', [])) == manifest.get('expected_rows')
        and all(row.get('status') == 'valid' and row.get('packet_received') is True for row in manifest.get('rows', [])))
    result['complete_recorded_batch_independently_consistent'] = (result['recorded_result_complete']
        and len(result['captures']) == 2*manifest['expected_rows']
        and all(row['valid_candidate_not_acceptance'] and row.get('recorded_energy_matches_exactly') is True
                and row.get('recorded_charge_matches_exactly') is True
                and row.get('recorded_baseline_excess_absent') is True for row in result['captures']))
    return result



def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument('--history-policy', choices=HISTORY_POLICIES,
                        help='Explicit diagnostic override; otherwise use pairing metadata, default v1')
    args = parser.parse_args(argv)
    report = audit_result(args.result_root, history_policy=args.history_policy)
    content = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as f:
            f.write(content)
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
