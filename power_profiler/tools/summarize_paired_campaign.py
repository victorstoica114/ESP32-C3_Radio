"""Summarize accepted E79 batches in a terminal campaign; no hardware access.

Usage: python -B summarize_paired_campaign.py --manifest <manifest.json> --output <NEW directory>
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
PLANS = {'paired_campaign': (8, 32, 64), 'paired_32b_campaign': (32,)}
PROVENANCE = ('profile_id', 'interface_label', 'ppk_mode', 'voltage_confirmed', 'voltage_provenance')
RUN_IDS = {f'run_{i:05d}' for i in range(1, 6)}
METRICS = {'energy_total_uJ': 'energy_total_uJ', 'charge_total_uC': 'charge_total_uC',
           'duration_ms': 'event_duration_ms', 'mean_current_uA': 'event_mean_uA'}
POLICIES = {
    False: ('independent_radio_hardware_marker_totals', 'total_only_with_direct_adc_proof',
            'direct_adc_constant_range_marker_total'),
    True: ('independent_radio_hardware_filter_marker_totals', 'total_only_with_bounded_filter_replay_proof',
           'bounded_filter_replay_marker_total'),
}
ENERGY_POLICY_V2 = ('independent_radio_hardware_filter_energy_totals_v2',
                    'total_only_with_bounded_filter_energy_proof_v2', 'bounded_filter_replay_marker_total')


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
    kind = manifest.get('kind')
    require(kind in PLANS, 'Unsupported paired campaign kind')
    expected = set(itertools.product(PLANS[kind], PHYS, (-20, 0, 13)))
    require(manifest.get('state') in ('completed', 'passed', 'stopped', 'failed', 'completed_with_errors'),
            'Manifest must be terminal; running/idle campaigns are refused')
    config = manifest.get('config', {})
    filter_aware = config.get('filter_aware_totals', False)
    require(type(filter_aware) is bool, 'Filter-aware opt-in must be boolean')
    method, policy, proof_method = POLICIES[filter_aware]
    history_policy = config.get('filter_history_policy', 'current_equivalence_v1')
    require(isinstance(history_policy, str) and history_policy in ('current_equivalence_v1', 'energy_relative_v2'),
            'Unsupported filter history policy')
    energy_budget = history_policy == 'energy_relative_v2'
    require(not energy_budget or filter_aware, 'Energy history policy requires filter-aware totals')
    if energy_budget:
        method, policy, proof_method = ENERGY_POLICY_V2
    require(config.get('interface_label') in ('CH340', 'ESP32'), 'Missing/unsupported interface label')
    require(config.get('profile_id') == 'RADIO_EBYTE_E79_CC1352P'
            and config.get('ppk_mode') in ('ampere', 'source')
            and config.get('voltage_confirmed') is True
            and isinstance(config.get('voltage_provenance'), str) and config['voltage_provenance'].strip(),
            'Missing explicit fixture profile, power mode or voltage provenance')
    for role in ('tx', 'rx'):
        require(isinstance(config.get(f'{role}_identity'), str) and config[f'{role}_identity'].strip()
                and type(config.get(f'{role}_voltage_mv')) is int
                and 2500 <= config[f'{role}_voltage_mv'] <= 5000, 'Invalid fixture identity/voltage')
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
        require(condition in expected and condition not in planned, f'Invalid/duplicate condition: {condition}')
        planned.add(condition)
        for name in ('interface_label', 'ppk_mode', 'voltage_provenance', 'tx_identity', 'rx_identity',
                     'tx_radio_port', 'rx_radio_port', 'tx_ppk_port', 'rx_ppk_port', 'tx_voltage_mv', 'rx_voltage_mv'):
            require(flag('--' + name.replace('_', '-')) == str(config.get(name)),
                    f'CLI {name} differs from confirmed campaign fixture')
        require('--voltage-confirmed' in command, 'CLI voltage confirmation is missing')
        require(int(flag('--repetitions')) == 5 and step.get('expected_rows') == 5, 'Expected five repetitions')
        require(flag('--integration-mode') == 'radio_markers' and '--marker-totals-only' in command,
                'Batch does not request independent marker totals only')
        require(command.count('--filter-aware-totals') == int(filter_aware),
                'Batch filter-aware opt-in differs from campaign config')
        if energy_budget:
            require(flag('--filter-history-policy') == history_policy, 'Batch history policy differs from config')
        else:
            require('--filter-history-policy' not in command, 'Unexpected history policy in legacy batch')
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
        require(all(pairing.get(k) == config.get(k) for k in PROVENANCE),
                'Pairing interface/fixture provenance differs from confirmed campaign config')
        for role in ('tx', 'rx'):
            endpoint = pairing.get('endpoints', {}).get(role, {})
            require(all(endpoint.get(name) == config.get(f'{role}_{name}')
                        for name in ('radio_port', 'ppk_port', 'identity', 'voltage_mv')),
                    f'{role.upper()} pairing endpoint differs from confirmed campaign fixture')
        require(pairing.get('status') == 'valid' and pairing.get('expected_rows') == 5, 'Pairing not valid/five rows')
        require(tuple(pairing.get(k) for k in ('payload_bytes', 'rf_profile', 'tx_power_dbm')) == condition,
                f'{result}: pairing condition differs from planned CLI condition')
        require(pairing.get('profile_id') == 'RADIO_EBYTE_E79_CC1352P' and pairing.get('frame_count') == 1,
                'Unexpected device profile or fragmentation')
        require(pairing.get('integration_mode') == 'radio_markers' and pairing.get('marker_totals_only') is True
                and pairing.get('energy_policy') == policy
                and pairing.get('filter_aware_totals', False) is filter_aware, 'Pairing energy policy differs')
        require(pairing.get('filter_history_policy', 'current_equivalence_v1') == history_policy,
                'Pairing history policy differs')
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
            metadata = read(result / role / 'metadata.json')
            require(all(metadata.get(k) == pairing.get(k) for k in (*PROVENANCE, 'session_id'))
                    and metadata.get('measurement_direction') == role,
                    f'{role.upper()} metadata interface/provenance/session differs from pairing')
            endpoint = pairing['endpoints'][role]
            require(all(metadata.get('endpoints', {}).get(role, {}).get(k) == endpoint.get(k)
                        for k in ('radio_port', 'ppk_port', 'identity', 'voltage_mv')),
                    f'{role.upper()} metadata endpoint differs from pairing')
            ports = {'measured_port': endpoint['radio_port'],
                     'peer_port': pairing['endpoints']['rx' if role == 'tx' else 'tx']['radio_port'],
                     'transmitter_port': pairing['endpoints']['tx']['radio_port'],
                     'receiver_port': pairing['endpoints']['rx']['radio_port']}
            require(all(metadata.get(k) == v for k, v in ports.items())
                    and metadata.get('ppk_port') == endpoint['ppk_port']
                    and metadata.get('voltage_mv') == endpoint['voltage_mv'],
                    f'{role.upper()} metadata wiring/voltage differs from pairing')
            rows = read(result / role / 'summary.csv', as_csv=True)
            require(len(rows) == 5 and {r.get('run_id') for r in rows} == RUN_IDS, 'Summary IDs missing/duplicate')
            require({int(r['repetition']) for r in rows} == set(range(1, 6)), 'Repetitions missing/duplicate')
            for row in rows:
                # CSV has no interface column: bind its wiring/mode/voltage to this role's metadata.
                require(all(row.get(k) == v for k, v in ports.items())
                        and row.get('ppk_mode') == config['ppk_mode'],
                        f'{role.upper()} summary wiring/power provenance differs from metadata')
                require(int(row['repetition']) == int(row['run_id'].removeprefix('run_')), 'Run/repetition mismatch')
                require(row.get('status') == 'ok' and row.get('packet_received') == 'True'
                        and row.get('packet_lost') == 'False' and not row.get('analysis_error'), 'Summary row not accepted')
                require(row.get('measurement_direction') == role and row.get('integration_method') == method,
                        'Summary direction/method mismatch')
                require(row.get('profile_id') == 'RADIO_EBYTE_E79_CC1352P' and int(row['payload_bytes']) == condition[0]
                        and json.loads(row['parameters_json']) == {'rf_profile': condition[1], 'tx_power_dbm': condition[2]},
                        'Summary condition mismatch')
                require(all(key in row and row[key] == '' for key in
                            ('baseline_median_uA', 'threshold_uA', 'charge_excess_uC', 'energy_excess_uJ')),
                        'Total-only summary contains baseline/excess metrics')
                proof = by_id[row['run_id']]['marker_diagnostics']['roles'][role]['total_qa']
                require(proof.get('valid') is True and not proof.get('reasons')
                        and proof.get('method') == proof_method, 'Selected wire proof not valid')
                require(proof.get('schema_version') == (2 if energy_budget else 1), 'Proof schema differs')
                if energy_budget:
                    require(proof.get('history_policy') == history_policy
                            and proof.get('energy_history_relative_tolerance') == 1e-4
                            and proof.get('energy_history_budget_valid') is True,
                            'Energy history proof has the wrong policy or budget')
                    bound = proof.get('energy_history_relative_bound')
                    require(type(bound) in (int, float) and math.isfinite(bound) and 0 <= bound <= 1e-4,
                            'Energy history proof exceeds the fixed relative bound')
                for key in METRICS.values():
                    value = float(row[key])
                    require(math.isfinite(value) and value >= 0, f'Invalid {key}')
                require(float(row['event_duration_ms']) > 0, 'Nonpositive marker duration')
                require(float(row['voltage_mv']) == float(pairing['endpoints'][role]['voltage_mv']) > 0,
                        'Summary voltage differs from measured endpoint metadata')
                for key in ('energy_total_uJ', 'charge_total_uC'):
                    require(math.isclose(float(row[key]), float(proof[key]), rel_tol=1e-10, abs_tol=1e-10),
                            f'{key} differs from accepted wire proof')
            aggregate = dict(zip(('payload_bytes', 'rf_profile', 'tx_power_dbm'), condition))
            aggregate.update(interface_label=config['interface_label'], role=role, repetitions=5,
                             voltage_mv=pairing['endpoints'][role]['voltage_mv'],
                             integration_method=method, energy_policy=policy)
            aggregate['history_energy_interval_width_uJ_max'] = None
            aggregate['history_energy_relative_bound_percent_max'] = None
            if energy_budget:
                proofs = [pair['marker_diagnostics']['roles'][role]['total_qa'] for pair in pairs]
                aggregate['history_energy_interval_width_uJ_max'] = max(q['energy_interval_width_uJ'] for q in proofs)
                aggregate['history_energy_relative_bound_percent_max'] = 100 * max(q['energy_history_relative_bound'] for q in proofs)
            for name, key in METRICS.items():
                values = [float(row[key]) for row in rows]
                aggregate[name + '_mean'] = statistics.fmean(values)
                aggregate[name + '_sd'] = statistics.stdev(values)
            aggregates.append(aggregate)
        covered.add(condition)
        sources.append({'step_id': step['step_id'], 'accepted_result': str(result),
                        'paired_transfer_ids': [pair['paired_transfer_id'] for pair in pairs]})
    require(planned == expected, f'Manifest plan differs from explicit {kind} matrix ({len(expected)} batches)')
    require(manifest.get('completed_steps') == len(covered), 'Manifest completed_steps disagrees with accepted steps')
    if manifest['state'] in ('completed', 'passed'):
        require(covered == expected, 'Completed campaign lacks full accepted coverage')
    for path, recorded in inputs.items():
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == recorded['sha256'], f'Input changed while reading: {path}')
    return {'schema_version': 2, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'manifest': str(manifest_path), 'campaign_kind': kind, 'campaign_state': manifest['state'],
            'interface_label': config['interface_label'], 'fixture_config': config,
            'planned_payload_bytes': list(PLANS[kind]),
            'coverage_status': 'complete' if covered == expected else 'partial',
            'expected_conditions': len(expected), 'accepted_conditions': len(covered),
            'expected_pairs': len(expected) * 5, 'accepted_pairs': len(covered) * 5,
            'accepted_role_rows': len(covered) * 10,
            'missing_conditions': [dict(zip(('payload_bytes', 'rf_profile', 'tx_power_dbm'), c)) for c in sorted(expected - covered)],
            'standard_deviation': 'Sample standard deviation, ddof=1, five accepted repetitions per condition/role',
            'scope': 'Whole powered module over each local marker. RX: sync detected to packet end/abort; excludes preamble and listening. Independent clocks; TX/RX durations differ.',
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
    fields = ['interface_label', 'payload_bytes', 'rf_profile', 'tx_power_dbm', 'role', 'repetitions', 'voltage_mv', 'integration_method', 'energy_policy']
    fields += [name + suffix for name in METRICS for suffix in ('_mean', '_sd')]
    fields += ['history_energy_interval_width_uJ_max', 'history_energy_relative_bound_percent_max']
    with (args.output / 'aggregates.csv').open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report['aggregates'])
    with (args.output / 'summary.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'coverage_status': report['coverage_status'], 'accepted_pairs': report['accepted_pairs'],
                      'expected_pairs': report['expected_pairs'], 'output': str(args.output.resolve())}))


if __name__ == '__main__':
    main()
