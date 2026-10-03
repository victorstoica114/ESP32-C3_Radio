"""Summarize accepted E79 fragmented batches in a terminal campaign; no hardware access.

Usage: python -B summarize_fragmented_campaign.py --manifest <manifest.json> --output <NEW directory>
Only completed steps.accepted_result is read. Failed attempts are never scanned.
This is a consistency/aggregation helper, not an independent RAW acceptance audit.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_power_profiler.storage import resolve_measurement_path

PHYS = ('GFSK4K8', 'GFSK50', 'GFSK200', 'SLR2K5', 'SLR5', 'OOK4K8', 'IEEE154G50')
EXPECTED = set(itertools.product((128, 512, 1024), PHYS, (13,)))
RUN_IDS = {f'run_{i:05d}' for i in range(1, 6)}
METRICS = {'energy_total_uJ': 'energy_total_uJ', 'charge_total_uC': 'charge_total_uC',
           'duration_ms': 'event_duration_ms', 'mean_current_uA': 'event_mean_uA'}
METHOD = 'independent_radio_fragment_marker_totals'
POLICY = 'total_only_with_direct_adc_proof'
SAMPLE_RATE_HZ = 100_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def summarize(manifest_path: Path):
    inputs = {}

    def read(path, as_csv=False):
        path = path.resolve()
        raw = path.read_bytes()
        inputs[str(path)] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        text = raw.decode('utf-8-sig')
        return list(csv.DictReader(io.StringIO(text))) if as_csv else json.loads(text)

    manifest_path = resolve_measurement_path(manifest_path).resolve()
    manifest = read(manifest_path)
    require(manifest.get('kind') == 'paired_fragmented_campaign', 'Not a fragmented campaign manifest')
    require(manifest.get('state') in ('completed', 'passed', 'stopped', 'failed', 'completed_with_errors'),
            'Manifest must be terminal; running/idle campaigns are refused')
    config = manifest.get('config', {})
    require(config.get('integration_mode') == 'radio_markers' and config.get('marker_totals_only') is True,
            'This helper requires explicitly selected independent marker totals only')
    planned, covered, result_paths, transfer_ids = set(), set(), set(), set()
    aggregates, sources, excluded = [], [], []
    steps = manifest.get('steps', [])
    for step in steps:
        command = step.get('command', [])

        def flag(name):
            require(command.count(name) == 1, f'{step.get("step_id")}: missing/duplicate {name}')
            return command[command.index(name) + 1]

        condition = (int(flag('--payload-bytes')), flag('--rf-profile'), int(flag('--tx-power-dbm')))
        require(condition in EXPECTED and condition not in planned, f'Invalid/duplicate condition: {condition}')
        planned.add(condition)
        require(int(flag('--repetitions')) == 5 and step.get('expected_rows') == 5, 'Expected five repetitions')
        require(flag('--integration-mode') == 'radio_markers' and '--marker-totals-only' in command and command.count('--fragmented') == 1,
                'Batch does not request independent marker totals only')
        if step.get('status') != 'completed':
            require(not step.get('accepted_result'), 'Noncompleted step unexpectedly has accepted_result')
            excluded.append({'step_id': step.get('step_id'), 'status': step.get('status')})
            continue
        require(step.get('accepted_result') and step.get('validation', {}).get('valid') is True,
                'Completed step lacks accepted_result/valid acceptance')
        result = resolve_measurement_path(step['accepted_result'])
        result = (result if result.is_absolute() else manifest_path.parent / result).resolve()
        require(result not in result_paths, 'Accepted result reused by multiple conditions')
        result_paths.add(result)
        pairing = read(result / 'pairing.json')
        require(pairing.get('status') == 'valid' and pairing.get('expected_rows') == 5, 'Pairing not valid/five rows')
        require(tuple(pairing.get(k) for k in ('payload_bytes', 'rf_profile', 'tx_power_dbm')) == condition,
                f'{result}: pairing condition differs from planned CLI condition')
        require(pairing.get('profile_id') == 'RADIO_EBYTE_E79_CC1352P' and pairing.get('frame_count') == condition[0] // 64 and pairing.get('fragmented') is True,
                'Unexpected device profile or fragmentation')
        require(pairing.get('integration_mode') == 'radio_markers' and pairing.get('marker_totals_only') is True
                and pairing.get('energy_policy') == POLICY, 'Pairing energy policy differs')
        require(pairing.get('sample_rate_hz') == SAMPLE_RATE_HZ, 'Unexpected pairing sample rate')
        pairs = pairing.get('rows', [])
        require(len(pairs) == 5 and {p.get('run_id') for p in pairs} == RUN_IDS, 'Pairing IDs missing/duplicate')
        by_id = {p['run_id']: p for p in pairs}
        for pair in pairs:
            require(pair.get('status') == 'valid' and pair.get('packet_received') is True
                    and pair.get('tx_status') == pair.get('rx_status') == 'ok', 'Invalid/undelivered pair')
            identifier = pair.get('paired_transfer_id')
            require(identifier == pairing.get('session_id', '') + ':' + pair['run_id']
                    and identifier not in transfer_ids, 'Missing/duplicate paired transfer ID')
            transfer_ids.add(identifier)
            require(pair.get('marker_diagnostics', {}).get('valid') is True, 'Marker diagnostics not valid')
        for role in ('tx', 'rx'):
            rows = read(result / role / 'summary.csv', as_csv=True)
            require(len(rows) == 5 and {r.get('run_id') for r in rows} == RUN_IDS, 'Summary IDs missing/duplicate')
            require({int(r['repetition']) for r in rows} == set(range(1, 6)), 'Repetitions missing/duplicate')
            for row in rows:
                require(int(row['repetition']) == int(row['run_id'].removeprefix('run_')), 'Run/repetition mismatch')
                require(row.get('status') == 'ok' and row.get('packet_received') == 'True'
                        and row.get('packet_lost') == 'False' and not row.get('analysis_error'), 'Summary row not accepted')
                require(row.get('measurement_direction') == role and row.get('integration_method') == METHOD,
                        'Summary direction/method mismatch')
                require(row.get('profile_id') == 'RADIO_EBYTE_E79_CC1352P' and int(row['payload_bytes']) == condition[0]
                        and json.loads(row['parameters_json']) == {'rf_profile': condition[1], 'tx_power_dbm': condition[2]},
                        'Summary condition mismatch')
                require(all(key in row and row[key] == '' for key in
                            ('baseline_median_uA', 'threshold_uA', 'charge_excess_uC', 'energy_excess_uJ')),
                        'Total-only summary contains baseline/excess metrics')
                role_diagnostics = by_id[row['run_id']]['marker_diagnostics']['roles'][role]
                proofs = role_diagnostics['frame_proofs']
                require(len(proofs) == condition[0] // 64 and all(p.get('valid') is True for p in proofs), 'Every frame requires a valid direct ADC proof')
                require(int(row['frame_count']) == len(proofs) and int(row['serial_content_bytes']) == condition[0], 'Fragment layout differs')
                for key in METRICS.values():
                    value = float(row[key])
                    require(math.isfinite(value) and value >= 0, f'Invalid {key}')
                require(float(row['event_duration_ms']) > 0, 'Nonpositive marker duration')
                require(float(row['voltage_mv']) == float(pairing['endpoints'][role]['voltage_mv']) > 0,
                        'Summary voltage differs from measured endpoint metadata')
                windows = [proof.get('window_samples') for proof in proofs]
                require(role_diagnostics.get('windows_samples') == windows, 'Role windows differ from frame proofs')
                trigger = role_diagnostics.get('software_trigger_index')
                count = int(row['captured_samples'])
                require(type(trigger) is int and 0 <= trigger < count, 'Invalid local software trigger')
                previous_stop = trigger
                active_samples = 0
                expected_windows_ms = []
                for proof, window in zip(proofs, windows):
                    require(proof.get('sample_rate_hz') == SAMPLE_RATE_HZ, 'Unexpected frame proof sample rate')
                    require(isinstance(window, list) and len(window) == 2
                            and all(type(index) is int for index in window), 'Invalid frame proof window')
                    start, stop = window
                    require(previous_stop < start < stop < count and stop - start >= 3,
                            'Frame windows must be complete, ordered and separated after the trigger')
                    require(proof.get('captured_sample_count') == count, 'Frame proof sample count differs from CSV')
                    require(float(proof['voltage_mv']) == float(row['voltage_mv']), 'Frame proof voltage differs from CSV')
                    active_samples += stop - start
                    previous_stop = stop
                    expected_windows_ms.append([(index - trigger) * 1000 / SAMPLE_RATE_HZ for index in window])
                csv_windows = json.loads(row['integration_windows_ms'])
                require(isinstance(csv_windows, list) and len(csv_windows) == len(expected_windows_ms)
                        and all(isinstance(actual, list) and len(actual) == 2
                                and all(math.isclose(float(a), expected, rel_tol=1e-10, abs_tol=1e-10)
                                        for a, expected in zip(actual, expected_window))
                                for actual, expected_window in zip(csv_windows, expected_windows_ms)),
                        'CSV integration windows differ from the active frame proofs')
                require(math.isclose(float(row['event_duration_ms']), active_samples * 1000 / SAMPLE_RATE_HZ,
                                     rel_tol=1e-10, abs_tol=1e-10), 'Duration includes gaps or differs from frame proofs')
                require(math.isclose(float(row['event_mean_uA']), float(row['charge_total_uC']) * SAMPLE_RATE_HZ / active_samples,
                                     rel_tol=1e-10, abs_tol=1e-10), 'Mean current differs from charge over active duration')
                for key in ('energy_total_uJ', 'charge_total_uC'):
                    require(math.isclose(float(row[key]), math.fsum(float(p[key]) for p in proofs), rel_tol=1e-10, abs_tol=1e-10),
                            f'{key} differs from accepted direct ADC proof')
                require(math.isclose(float(row['energy_total_uJ']), float(row['charge_total_uC']) * float(row['voltage_mv']) / 1000,
                                     rel_tol=1e-10, abs_tol=1e-10), 'Energy differs from charge times measured voltage')
            aggregate = dict(zip(('payload_bytes', 'rf_profile', 'tx_power_dbm'), condition))
            aggregate.update(role=role, repetitions=5, voltage_mv=pairing['endpoints'][role]['voltage_mv'],
                             integration_method=METHOD, energy_policy=POLICY)
            for name, key in METRICS.items():
                values = [float(row[key]) for row in rows]
                aggregate[name + '_mean'] = statistics.fmean(values)
                aggregate[name + '_sd'] = statistics.stdev(values)
            aggregates.append(aggregate)
        covered.add(condition)
        sources.append({'step_id': step['step_id'], 'accepted_result': str(result),
                        'paired_transfer_ids': [pair['paired_transfer_id'] for pair in pairs]})
    require(planned == EXPECTED, 'Manifest plan is not exactly 7 PHY x +13 dBm x 3 fragmented sizes (21 batches)')
    require(manifest.get('completed_steps') == len(covered), 'Manifest completed_steps disagrees with accepted steps')
    if manifest['state'] in ('completed', 'passed'):
        require(covered == EXPECTED, 'Completed campaign lacks full accepted coverage')
    for path, recorded in inputs.items():
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == recorded['sha256'], f'Input changed while reading: {path}')
    return {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'manifest': str(manifest_path), 'campaign_state': manifest['state'],
            'coverage_status': 'complete' if covered == EXPECTED else 'partial',
            'expected_conditions': 21, 'accepted_conditions': len(covered),
            'expected_pairs': 105, 'accepted_pairs': len(covered) * 5,
            'accepted_role_rows': len(covered) * 10,
            'missing_conditions': [dict(zip(('payload_bytes', 'rf_profile', 'tx_power_dbm'), c)) for c in sorted(EXPECTED - covered)],
            'standard_deviation': 'Sample standard deviation, ddof=1, five accepted repetitions per condition/role',
            'scope': 'Whole powered module summed over all 2/8/16 local markers; inter-frame gaps excluded. RX: sync detected to packet end/abort; excludes preamble and listening. Independent clocks; TX/RX durations differ.',
            'limitations': ['Only accepted total energy and charge; no baseline/excess inference.',
                            'Consistency checks do not replace the independent RAW/wire audit.',
                            'Failed/unaccepted attempts excluded; accepted-only statistics do not estimate campaign packet loss.'],
            'inputs': inputs, 'accepted_sources': sources, 'excluded_steps': excluded, 'aggregates': aggregates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New, exclusive output directory')
    args = parser.parse_args()
    require(not args.output.exists(), 'Output directory already exists; choose a new directory')
    report = summarize(args.manifest)
    args.output.mkdir(parents=True, exist_ok=False)
    fields = ['payload_bytes', 'rf_profile', 'tx_power_dbm', 'role', 'repetitions', 'voltage_mv', 'integration_method', 'energy_policy']
    fields += [name + suffix for name in METRICS for suffix in ('_mean', '_sd')]
    with (args.output / 'aggregates.csv').open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report['aggregates'])
    with (args.output / 'summary.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'coverage_status': report['coverage_status'], 'accepted_pairs': report['accepted_pairs'],
                      'expected_pairs': 105, 'output': str(args.output.resolve())}))


if __name__ == '__main__':
    main()
