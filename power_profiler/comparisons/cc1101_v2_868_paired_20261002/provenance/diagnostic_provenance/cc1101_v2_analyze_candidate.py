"""Offline CC1101 V2 868 MHz 32B/250kbps/+10dBm legacy analysis; never changes acceptance."""
from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'power_profiler'))
from radio_power_profiler.analysis import analyze_capture
from radio_power_profiler.profiles import load_profile
from radio_power_profiler.planning import build_cases, estimate_airtime_s
from tools.audit_filter_marker_totals import read_capture, normalize, replay, evidence

RATE = 100000
PARAMETERS = {'bit_rate_kbps': 250, 'tx_power_dbm': 10}
CONTENT_BYTES = 30
PROFILE_ID = 'RADIO_CC1101_V2_868'
TOLERANCE = 1e-6


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def write_csv(path, rows):
    if rows:
        with path.open('x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def radio_ports(source):
    explicit = source.get('radio_ports')
    if explicit is not None:
        if (not isinstance(explicit, dict) or set(explicit) != {'tx', 'rx'}
                or any(not isinstance(v, str) or not v for v in explicit.values())
                or explicit['tx'].upper() == explicit['rx'].upper()):
            raise ValueError('Invalid explicit radio_ports mapping')
        return explicit, 'explicit radio_ports'
    # Old diagnostic reports lacked explicit endpoint metadata. Their final
    # recorded RX=ON/OFF configuration uniquely identifies the two roles.
    states = {}
    for command in source.get('commands', []):
        if command.get('command') in ('AT+RX=ON', 'AT+RX=OFF') and 'OK' in command.get('lines', []):
            states[command['port']] = command['command']
    tx = [p for p, c in states.items() if c == 'AT+RX=OFF']
    rx = [p for p, c in states.items() if c == 'AT+RX=ON']
    if len(tx) != 1 or len(rx) != 1 or tx[0].upper() == rx[0].upper():
        raise ValueError('UART roles cannot be identified from recorded evidence')
    return {'tx': tx[0], 'rx': rx[0]}, 'legacy final successful AT+RX configuration'


def uart_delivery(run, ports, final_tail=None):
    phases = [run.get(name, {}) for name in ('during_uart', 'after_uart', 'tail_uart')]
    if final_tail is not None:
        phases.append(final_tail)
    by_role = {role: [] for role in ports}
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get('lines', {}), dict):
            raise ValueError('Malformed persistent UART transcript')
        for role, port in ports.items():
            lines = phase.get('lines', {}).get(port, [])
            if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
                raise ValueError('Malformed UART lines')
            by_role[role].extend(lines)
    tx_state_lines = [line for line in by_role['tx'] if line.startswith('[TX] ') and ' bytes, state: ' in line]
    tx_ok_count = tx_state_lines.count('[TX] 32 bytes, state: 0')
    tx_complete_count = by_role['tx'].count('[TX] 32 bytes')
    received = by_role['rx'].count(run['payload'])
    failures = [line for lines in by_role.values() for line in lines
                if 'failed' in line.lower() or line.upper().startswith(('#ERROR', 'ERROR'))]
    return {'tx_ok_line_count': tx_ok_count, 'rx_exact_payload_line_count': received,
            'tx_complete_line_count': tx_complete_count, 'tx_state_lines': tx_state_lines,
            'failure_lines': failures, 'passed': tx_ok_count == 1 and tx_complete_count == 1
                and len(tx_state_lines) == 1 and received == 1 and not failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True, help='Candidate report.json or its parent directory')
    parser.add_argument('--output', type=Path, required=True, help='NEW output directory, created exclusively')
    args = parser.parse_args()
    source_path = args.candidate / 'report.json' if args.candidate.is_dir() else args.candidate
    source_path = source_path.resolve()
    root = source_path.parent
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    profile = load_profile(PROFILE_ID)
    profile = dataclasses.replace(profile, payload_sizes=(32,), repetitions=5,
        axes=tuple(dataclasses.replace(axis, values=(PARAMETERS[axis.name],)) for axis in profile.axes))
    cases = {role: build_cases(profile, role)[0] for role in ('tx', 'rx')}
    voltage_mv = source['voltage_mv_for_decoder']
    if not finite(voltage_mv) or voltage_mv <= 0:
        raise ValueError('Recorded decoder voltage must be positive and finite')
    airtime = estimate_airtime_s(profile, 32, PARAMETERS)
    if int(airtime * RATE) != 469:
        raise ValueError('Profile changed: expected complementary CC1101 RX window of469samples')
    report = {
        'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'source': evidence(source_path), 'helper': evidence(Path(__file__)),
        'sources': [evidence(REPO / path) for path in (
            'power_profiler/radio_power_profiler/analysis.py',
            'power_profiler/radio_power_profiler/profiles.json',
            'power_profiler/radio_power_profiler/planning.py',
            'power_profiler/tools/audit_filter_marker_totals.py')],
        'acceptance_changed': False, 'hardware_synchronized': False,
        'scope': 'Legacy-compatible TX threshold metric plus a new complementary RX listening metric on a declared software window, with independent full-stream decoder replay. Not E79 hardware-marker proof.',
        'profile_id': PROFILE_ID,
        'parameters': PARAMETERS,
        'historical_comparison': {'tx_delivery': 'Unknown: historical source had receiver_port=null and packets_attempted=0; this was not evidence of failed RF delivery.', 'tx_energy_total_uJ_mean': 200.89440048232663, 'tx_energy_total_uJ_sd': 0.9234120568222898, 'rx_delivery': 'Historical source received5/5.', 'rx_energy_total_uJ_mean': 5989.537946269249, 'rx_duration_ms_mean': 112.74600000000001, 'rx_direct_numeric_comparability': False, 'reason': 'Historical RX used threshold-selected enable/receive/restore behavior; new RX stays in listening state and uses469samples at the software trigger.'},
        'tx_window_definition': 'Largest rectified-excess threshold group; threshold=pretrigger median+max(500uA,8*1.4826*MAD); merge gap20ms; minimum0.05ms; padding0.1ms each side.',
        'rx_window_definition': 'Complementary listening energy in a fixed modeled4.696ms interval quantized to469samples(4.69ms), beginning at the local software trigger. Not an independently delimited RF reception and not numerically comparable to historical controlled RX enable/restore windows(112.746ms mean at this condition).',
        'transmit_protocol': 'Bridge sends a unique30-byte ASCII identifier plus CRLF as one32-byte RF frame. Historical TXBURST=32,32 used a fixed payload pattern. RF length and TX threshold integration are preserved; new PHY is explicitly read back as2FSK/NONE/NRZ. Historical setup did not archive MOD/SHAPE readback, so identical historical PHY is not independently certified.',
        'estimated_airtime_s': airtime, 'rx_window_samples': int(airtime * RATE),
        'voltage_mv_for_decoder': voltage_mv, 'voltage_provenance': source.get('voltage_provenance'),
        'legacy_total_definition': 'V * sum(max(0,I_uA))/100000; ordinary Python sum to reproduce existing analysis.py.',
        'legacy_excess_definition': 'V * sum(max(0,I_uA-baseline_median_uA))/100000; rectified, not signed baseline subtraction.',
        'signed_diagnostic_definition': 'V * math.fsum(I_uA)/100000 over the same selected window; kept separate from legacy totals.',
        'history_validation': {
            'replay_initialization': 'Known host decoder reset: fast/slow/previous=None, after_spike=consecutive=0.',
            'scope': 'Reconstructs this declared reset convention from full WIRE; does not bound unknown pre-capture physical/filter history.',
            'unknown_initial_history_bound_performed': False,
            'window_boundary_uncertainty_bound_performed': False,
            'e79_marker_proof_applied': False,
        },
        'limitations': ['Modulo64 continuity cannot exclude missing blocks of64 samples.',
            'Replay agreement does not establish analog accuracy or actual VIN.',
            'TX threshold selection is not proved invariant under unknown history; RX software trigger is not an RF edge.',
            'All five trials are retained; failed transfers or QA prevent a valid five-trial numeric batch.'],
        'errors': [], 'captures': [],
    }
    runs = source.get('runs', [])
    expected_settings = {'rate_kbps': 250, 'tx_power_dbm': 10, 'payload_bytes': 32,
                         'content_bytes': CONTENT_BYTES, 'frequency_mhz': 868.0, 'modulation': '2FSK', 'shaping': 'NONE', 'encoding': 'NRZ',
                         'deviation_khz': 127, 'bandwidth_khz': 541.67, 'preamble_bits': 128,
                         'sync_word': 'D391', 'sync_error_bits': 1, 'crc': True}
    if source.get('sample_rate_hz') != RATE: report['errors'].append('Wrong sample rate')
    if source.get('completed') is not True: report['errors'].append('Source is not completed')
    if 'error' in source: report['errors'].append('Source contains an error field')
    if len(runs) != 5 or len({r['run_id'] for r in runs}) != 5: report['errors'].append('Exactly five unique transfers required')
    if any(source.get('settings', {}).get(k) != v for k, v in expected_settings.items()): report['errors'].append('Unexpected RF settings')
    if source.get('settings', {}).get('crc') is not True:
        report['errors'].append('CRC must be explicitly enabled')
    if source.get('profile_id', source.get('settings', {}).get('profile_id')) != PROFILE_ID:
        report['errors'].append('Explicit CC1101 V2 868 MHz profile identity required')
    payloads = [r.get('payload') for r in runs]
    if (any(not isinstance(p, str) or not p.isascii() or len(p.encode('ascii')) != CONTENT_BYTES
            or any(ord(c) < 33 or ord(c) > 126 for c in p) for p in payloads)
            or len(set(p for p in payloads if isinstance(p, str))) != 5):
        report['errors'].append('Five unique printable ASCII payloads of exactly30bytes required; CRLF yields32RFbytes')
    try:
        ports, port_provenance = radio_ports(source)
        report.update(radio_ports=ports, radio_port_provenance=port_provenance)
    except ValueError as exc:
        ports = None
        report['errors'].append(str(exc))
    evidence_inputs = [report['source']]
    used_paths = {}
    used_hashes = {'raw': {}, 'wire': {}}
    report['independent_delivery'] = []
    rows = []
    for run_index, run in enumerate(runs):
        delivery_ok = False
        try:
            if ports is None:
                raise ValueError('Cannot independently verify delivery without UART role mapping')
            if bytes.fromhex(run['sent_rf_hex']) != run['payload'].encode('ascii') + b'\r\n':
                raise ValueError('Recorded sent RF bytes do not equal30-byte identifier plus CRLF')
            final_tail = source.get('tail_uart') if run_index == len(runs)-1 else None
            delivery = uart_delivery(run, ports, final_tail)
            delivery.update(run_id=run['run_id'], payload=run.get('payload'))
            report['independent_delivery'].append(delivery)
            delivery_ok = delivery['passed']
            if (run.get('tx_ok') is not (delivery['tx_ok_line_count'] > 0)
                    or type(run.get('rx_exact_count')) is not int
                    or run.get('rx_exact_count') != delivery['rx_exact_payload_line_count']):
                raise ValueError('Recorded delivery flags disagree with persistent UART transcript')
            if (type(run.get('tx_state_ok_count')) is not int
                    or run['tx_state_ok_count'] != delivery['tx_ok_line_count']):
                raise ValueError('Recorded TX state0 count disagrees with persistent UART transcript')
            if (type(run.get('tx_bridge_ack_count')) is not int
                    or run['tx_bridge_ack_count'] != delivery['tx_complete_line_count']):
                raise ValueError('Recorded TX completion count disagrees with persistent UART transcript')
        except (ValueError, KeyError, TypeError) as exc:
            report['errors'].append(f"{run['run_id']}: delivery evidence: {exc}")
        if not delivery_ok: report['errors'].append(f"{run['run_id']}: exactly one TX32/state0, one TX32 completion and one RX payload required from UART evidence")
        if run.get('capture_errors'): report['errors'].append(f"{run['run_id']}: acquisition errors")
        for role in ('tx', 'rx'):
            label = f"{run['run_id']}/{role}"
            detail = {'run_id': run['run_id'], 'role': role, 'errors': []}
            report['captures'].append(detail)
            try:
                capture_meta = run['captures'][role]
                loss = capture_meta.get('sample_loss_percent')
                if not finite(loss) or not 0 <= loss <= 1.0:
                    raise ValueError('Recorded sample-loss estimator must be finite and between0and1percent')
                raw_path, wire_path = (root / capture_meta['raw_path']).resolve(), (root / run['wire_paths'][role]).resolve()
                for kind, path in (('raw', raw_path), ('wire', wire_path)):
                    if not path.is_relative_to(root): raise ValueError('Capture evidence is outside candidate directory')
                    key = str(path).casefold()
                    if key in used_paths: raise ValueError(f'Duplicate evidence path: {used_paths[key]} and {label}/{kind}')
                    used_paths[key] = f'{label}/{kind}'
                detail.update(raw=evidence(raw_path), wire=evidence(wire_path))
                evidence_inputs.extend((detail['raw'], detail['wire']))
                for kind in ('raw', 'wire'):
                    digest = detail[kind]['sha256']
                    if digest in used_hashes[kind]: raise ValueError(f'Duplicate {kind}SHA256: {used_hashes[kind][digest]} and {label}')
                    used_hashes[kind][digest] = label
                words, currents, logic, trigger = read_capture(raw_path, wire_path)
                n = len(words)
                if not n or not n == len(currents) == len(logic) == capture_meta['samples']: raise ValueError('Capture lengths disagree')
                if trigger != capture_meta['trigger_index']: raise ValueError('Trigger metadata mismatch')
                if any(not finite(v) for v in currents): raise ValueError('Nonfinite RAW current')
                coefficients, voltage_v = normalize(source['calibrations'][role], voltage_mv)
                decoded, filtered = replay(words, coefficients, voltage_v)
                if len(decoded) != n or any(not finite(v) for v in decoded): raise ValueError('Invalid replay output')
                faults = [i for i in range(1, n) if ((words[i] >> 18) & 63) != (((words[i-1] >> 18) & 63) + 1) % 64]
                invalid = [i for i, w in enumerate(words) if ((w >> 14) & 7) > 4]
                bit17 = [i for i, w in enumerate(words) if w & (1 << 17)]
                mismatches = sum(v != w >> 24 for v, w in zip(logic, words))
                difference = max(abs(a-b) for a, b in zip(currents, decoded))
                detail.update(sample_count=n, software_trigger_index=trigger,
                    replay_max_difference_uA=difference, replay_exact_samples=sum(a == b for a, b in zip(currents, decoded)),
                    filtered_samples=len(filtered), counter_transition_fault_indices=faults,
                    invalid_range_indices=invalid, bit17_indices=bit17, logic_mismatch_count=mismatches,
                    mean_current_full_capture_uA=statistics.fmean(currents), min_current_full_capture_uA=min(currents),
                    max_current_full_capture_uA=max(currents), range_counts=dict(collections.Counter((w >> 14) & 7 for w in words)),
                    sample_loss_percent_recorded_estimator=capture_meta.get('sample_loss_percent'),
                    calibration_sha256=hashlib.sha256(json.dumps(source['calibrations'][role], sort_keys=True, allow_nan=False).encode()).hexdigest())
                if faults or invalid or bit17 or mismatches or difference > TOLERANCE: raise ValueError('Full-stream integrity/replay QA failed')
                case = cases[role]
                metrics = analyze_capture(currents, trigger_index=trigger, sample_rate_hz=RATE, voltage_mv=voltage_mv,
                    capture_spec=profile.capture, expected_event_count=1,
                    search_window_s=min(case.capture_after_trigger_s, case.estimated_event_s*1.5 + profile.capture.search_window_margin_s),
                    fallback_window_s=max(.001, case.estimated_event_s-profile.receive.post_receive_s) if role == 'rx' and delivery_ok else None,
                    integration_window_s=case.estimated_airtime_s if role == 'rx' else None,
                    align_integration_window=False)
                if not metrics.event_detected or metrics.analysis_error: raise ValueError('Legacy analysis did not yield an event')
                windows = [(trigger+round(a*RATE/1000), trigger+round(b*RATE/1000)) for a, b in metrics.integration_windows_ms]
                if len(windows) != 1 or any(not 0 <= a < b <= n for a, b in windows): raise ValueError('Invalid software integration window')
                if role == 'rx' and windows != [(trigger, trigger+int(airtime*RATE))]: raise ValueError('Unexpected RX listening window')
                selected = [v for a, b in windows for v in currents[a:b]]
                replay_selected = [v for a, b in windows for v in decoded[a:b]]
                legacy_q = sum(max(0., v) for v in replay_selected)/RATE
                legacy_e = legacy_q*voltage_v
                signed_q = math.fsum(replay_selected)/RATE
                signed_e = signed_q*voltage_v
                legacy_error = abs(legacy_e-metrics.energy_total_uJ)
                allowed_error = math.nextafter(len(selected)*difference/RATE*voltage_v, math.inf) if difference else 0.
                if legacy_error > max(allowed_error, 1e-9): raise ValueError('Legacy integration differs from independent replay')
                detail.update(metrics=dataclasses.asdict(metrics), window_samples=windows,
                    independent_legacy_charge_uC=legacy_q, independent_legacy_energy_uJ=legacy_e,
                    independent_legacy_energy_difference_uJ=legacy_error,
                    signed_charge_diagnostic_uC=signed_q, signed_energy_diagnostic_uJ=signed_e,
                    legacy_minus_signed_energy_uJ=legacy_e-signed_e,
                    negative_current_samples_in_window=sum(v < 0 for v in selected),
                    signed_vs_legacy_note='Difference includes zero-clipping and ordinary-sum versus fsum rounding; this does not replace the legacy metric.')
                rows.append({'run_id': run['run_id'], 'role': role, 'profile_id': PROFILE_ID,
                    'payload_bytes': 32, 'content_bytes': CONTENT_BYTES, 'bit_rate_kbps': 250,
                    'tx_power_dbm': 10, 'frequency_mhz': 868.0, 'modulation': '2FSK', 'shaping': 'NONE', 'encoding': 'NRZ',
                    'voltage_mv': voltage_mv, 'tx_ok': run.get('tx_ok'), 'rx_exact_count': run.get('rx_exact_count'),
                    'method': metrics.integration_method, 'window_start_sample': windows[0][0], 'window_stop_sample': windows[0][1],
                    'duration_ms': metrics.event_duration_ms, 'mean_current_uA': metrics.tx_mean_uA,
                    'baseline_median_uA': metrics.baseline_median_uA, 'threshold_uA': metrics.threshold_uA,
                    'charge_total_uC': metrics.charge_total_uC, 'energy_total_uJ': metrics.energy_total_uJ,
                    'energy_excess_uJ': metrics.energy_excess_uJ, 'signed_energy_diagnostic_uJ': signed_e,
                    'legacy_minus_signed_energy_uJ': legacy_e-signed_e})
            except (ValueError, KeyError, OSError, TypeError, OverflowError) as exc:
                detail['errors'].append(f'{type(exc).__name__}: {exc}')
                report['errors'].append(f'{label}: {type(exc).__name__}: {exc}')
    unchanged = all(evidence(item['path'])['sha256'] == item['sha256'] for item in evidence_inputs)
    if not unchanged: report['errors'].append('Source evidence changed during audit')
    valid = not report['errors'] and len(rows) == 10
    aggregates = []
    for role in ('tx', 'rx'):
        group = [r for r in rows if r['role'] == role]
        aggregate = {'role': role, 'trial_count': len(group), 'valid_complete_five_trial_numeric_batch': valid,
                     'scope': 'TX threshold event' if role == 'tx' else 'RX listening, complementary fixed modeled4.69ms; not historical RX controlled-window', 'sample_sd_ddof': 1}
        for name in ('energy_total_uJ', 'charge_total_uC', 'duration_ms', 'mean_current_uA', 'energy_excess_uJ'):
            values = [r[name] for r in group]
            aggregate[name+'_mean'] = statistics.fmean(values) if len(values) == 5 else None
            aggregate[name+'_sd'] = statistics.stdev(values) if len(values) == 5 else None
        aggregates.append(aggregate)
    report.update(aggregates=aggregates, valid_complete_five_trial_numeric_batch=valid, source_files_unchanged=unchanged)
    report['unique_evidence_counts'] = {'paths': len(used_paths), 'raw_sha256': len(used_hashes['raw']), 'wire_sha256': len(used_hashes['wire'])}
    report['summary'] = {'captures': len(report['captures']), 'computed_trials': len(rows),
        'total_samples': sum(c.get('sample_count', 0) for c in report['captures']),
        'counter_transition_faults': sum(len(c.get('counter_transition_fault_indices', [])) for c in report['captures']),
        'maximum_replay_difference_uA': max((c.get('replay_max_difference_uA', 0) for c in report['captures']), default=0),
        'valid_complete_five_trial_numeric_batch': valid}
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / 'trials.csv', rows)
    write_csv(output / 'aggregates.csv', aggregates)
    with (output / 'audit.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(report['summary'], indent=2))
    print(json.dumps(report['errors'], indent=2))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
