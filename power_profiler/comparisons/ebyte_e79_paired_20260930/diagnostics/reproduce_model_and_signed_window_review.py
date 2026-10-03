"""Preserved inline calculations, concatenated in their original execution order.

Run from the repository root using Python 3 (standard library only).
Reads the captured pilot and Maxwell's wire_counter_review.json. Writes only
diagnostics/tx_review/model_and_signed_window_review.json. No hardware access.
The counter interpolation is a hypothetical sensitivity test, NOT a correction.

The source wire-counter report subsequently gained additional diagnostics; its
hash may therefore differ from the hash in the originally generated report.
The original input paths and calculation expressions below are preserved.
"""

# First inline calculation: model, original-window interpretation and signed
# integration using the full and split pretrigger baseline windows.
from pathlib import Path
import csv, gzip, json, statistics, hashlib

r = Path('power_profiler/web_sessions/20260930_213239_043901_paired_pilot_radio_ebyte_e79_cc1352p/paired_result/20260930_213239_188258_e79_paired_pilot')
manifest = json.loads((r / 'pairing.json').read_text())
report = {
    'schema_version': 1,
    'scope': 'Independent read-only model and signed-window review; original metrics unchanged',
    'model': {
        'payload_bytes': 32, 'frame_count': 1, 'modeled_overhead_bytes': 12,
        'bitrate_bps': 200000, 'modeled_bit_duration_ms': 1.76,
        'modeled_ramp_ms': 3.0, 'modeled_integration_ms': 4.76,
        'interpretation': 'A modeled current-integration window; not independently measured RF duration or full transaction energy.',
    },
    'signed_metric': {
        'definition': 'V/fs * sum(I - mean(pretrigger -180..-20 ms)), retaining negative values',
        'baseline_state': {'tx': 'RX disabled', 'rx': 'RX listening'},
        'primary_window_ms': [0, 200],
        'sensitivity_window_ends_ms': [100, 150, 200, 300, 500],
        'sensitivity_baseline_windows_ms': [[-180, -100], [-100, -20]],
        'clock': 'Each PPK local sample axis; host-coordinated marker, no hardware synchronization',
    },
    'rows': [], 'inputs': {},
    'limits': [
        'No physical RF-start/end timestamp recorded.',
        'TX alignment maximizes clipped charge in a fixed model-length window; observed energy does not establish RF duration.',
        'RX fixed window starts at the host marker and precedes UART drain/write latency; not a detected packet event.',
        'Host sample_loss_percent is an acquisition-volume estimator, not a wire-continuity certificate.',
        'The five physical transfers are the replicate unit; ADC samples are autocorrelated.',
        'TX and RX baselines have different radio states; never describe both as standby.',
        'Recorded calibration coefficients do not provide an independent instrument/voltage accuracy verification.',
    ],
}


def addhash(p):
    report['inputs'][str(p.relative_to(r)).replace('\\', '/')] = hashlib.sha256(p.read_bytes()).hexdigest()


addhash(r / 'pairing.json')
for role in ['tx', 'rx']:
    p = r / role / 'summary.csv'
    addhash(p)
    rows = list(csv.DictReader(p.open(newline='', encoding='utf-8-sig')))
    for s, pair in zip(rows, manifest['rows']):
        run = s['run_id']
        p = r / role / 'raw' / f'{run}.csv.gz'
        addhash(p)
        with gzip.open(p, 'rt', newline='') as f:
            raw = list(csv.DictReader(f))
        x = [float(a['current_uA']) for a in raw]
        markers = [i for i, a in enumerate(raw) if a['trigger'] == '1']
        assert len(markers) == 1
        m = markers[0]
        assert m == pair['timing']['devices'][role]['trigger_index']
        fs = 100000
        v = 3.3

        def mean_ms(a, b):
            return statistics.fmean(x[m + round(a * 100):m + round(b * 100)])

        baseline = mean_ms(-180, -20)
        bases = [{'window_ms': [a, b], 'mean_uA': mean_ms(a, b)} for a, b in [(-180, -100), (-100, -20)]]
        a, b = json.loads(s['integration_windows_ms'])[0]
        lo = m + round(a * 100)
        hi = m + round(b * 100)
        assert hi - lo == 476
        item = {
            'role': role, 'run_id': run, 'paired_transfer_id': pair['paired_transfer_id'],
            'sample_count': len(x), 'trigger_index': m, 'posttrigger_ms': (len(x) - m) / 100,
            'reported_sample_loss_percent': float(s['sample_loss_percent']),
            'baseline_mean_uA': baseline, 'baseline_split_means': bases,
            'legacy': {
                'window_ms': [a, b], 'baseline_median_uA': float(s['baseline_median_uA']),
                'energy_total_uJ': float(s['energy_total_uJ']),
                'energy_clipped_excess_uJ': float(s['energy_excess_uJ']),
                'signed_increment_using_mean_baseline_uJ': v / fs * sum(z - baseline for z in x[lo:hi]),
                'baseline_energy_using_mean_uJ': v / fs * baseline * (hi - lo),
            },
            'signed_windows': [],
            'host_timing': {
                'marker_skew_ms': pair['timing']['host_marker_skew_ms'],
                'callback_duration_ms': (pair['timing']['trigger_callback_finished_host_ns'] - pair['timing']['trigger_callback_started_host_ns']) / 1e6,
                'host_trigger_to_send_entry_ms': (pair['radio_send_entry_host_ns'] - pair['timing']['host_trigger_ns']) / 1e6,
            },
        }
        for end in [100, 150, 200, 300, 500]:
            segment = x[m:m + round(end * 100)]
            assert len(segment) == round(end * 100)
            total = v / fs * sum(segment)
            item['signed_windows'].append({
                'end_ms': end, 'energy_total_uJ': total,
                'baseline_energy_uJ': v / fs * len(segment) * baseline,
                'signed_increment_uJ': v / fs * sum(z - baseline for z in segment),
                'split_baseline_signed_increment_uJ': [v / fs * sum(z - bb['mean_uA'] for z in segment) for bb in bases],
            })
        report['rows'].append(item)

report['aggregates'] = {}
for role in ['tx', 'rx']:
    rows = [a for a in report['rows'] if a['role'] == role]
    agg = {
        'replicates': 5,
        'baseline_mean_uA': statistics.fmean(a['baseline_mean_uA'] for a in rows),
        'legacy_signed_increment_uJ_mean': statistics.fmean(a['legacy']['signed_increment_using_mean_baseline_uJ'] for a in rows),
        'legacy_signed_increment_uJ_sd': statistics.stdev(a['legacy']['signed_increment_using_mean_baseline_uJ'] for a in rows),
        'windows': [],
    }
    for idx, end in enumerate([100, 150, 200, 300, 500]):
        es = [a['signed_windows'][idx]['signed_increment_uJ'] for a in rows]
        split = [statistics.fmean(a['signed_windows'][idx]['split_baseline_signed_increment_uJ'][j] for a in rows) for j in range(2)]
        agg['windows'].append({
            'end_ms': end, 'signed_increment_uJ_mean': statistics.fmean(es),
            'signed_increment_uJ_sd': statistics.stdev(es),
            'split_baseline_aggregate_means_uJ': split,
        })
    report['aggregates'][role] = agg
out = r / 'diagnostics/tx_review/model_and_signed_window_review.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report['aggregates'], indent=2))
print('Report:', out)
print('Rows200:', [(a['role'], a['run_id'], a['baseline_mean_uA'], a['signed_windows'][2]['signed_increment_uJ']) for a in report['rows']])

# Second inline calculation: hypothetical sensitivity to the isolated counter
# outliers identified independently by Maxwell. RAW values are never rewritten.
a = json.loads(out.read_text())
wp = r / 'diagnostics/rx_review/wire_counter_review.json'
wire = json.loads(wp.read_text())
a['inputs'][str(wp.relative_to(r)).replace('\\', '/')] = hashlib.sha256(wp.read_bytes()).hexdigest()
a['wire_counter_review'] = {
    'source_report': '../rx_review/wire_counter_review.json',
    'protocol_source': wire['source'],
    'interpretation': 'Counter anomalies are observed, but their cause and corresponding ADC error are not identified. No missing-count correction or reindexing is applied. Persistent startup phase changes precede the -180 ms baseline start. A modulo-64 counter cannot rule out losses divisible by 64.',
    'hypothetical_sensitivity_definition': 'Replace only dominant-phase isolated outlier current values by the average of their immediate neighbors, preserving sample indices and recomputing mean baseline; this is a diagnostic perturbation, NOT a corrected measurement or error bound.',
    'rows': [],
}
for w in wire['rows']:
    role = w['role']
    run = w['run_id']
    saved = next(z for z in a['rows'] if z['role'] == role and z['run_id'] == run)
    with gzip.open(r / role / 'raw' / f'{run}.csv.gz', 'rt', newline='') as f:
        x = [float(z['current_uA']) for z in csv.DictReader(f)]
    m = saved['trigger_index']
    idx = [z['index'] for z in w.get('outliers', [])]
    y = list(x)
    for i in idx:
        y[i] = (x[i - 1] + x[i + 1]) / 2
    bm = statistics.fmean(y[m - 18000:m - 2000])
    delta_b = bm - saved['baseline_mean_uA']
    lo = m + round(saved['legacy']['window_ms'][0] * 100)
    hi = lo + 476
    entry = {
        'role': role, 'run_id': run,
        'counter_transition_anomalies': w['counter_transition_anomalies'],
        'phase_outliers_after_index1000': len(idx),
        'baseline_outlier_count': sum(m - 18000 <= i < m - 2000 for i in idx),
        'legacy_window_outlier_count': sum(lo <= i < hi for i in idx),
        'legacy_window_outlier_local_ms': [(i - m) / 100 for i in idx if lo <= i < hi],
        'legacy_window_outlier_recorded_energy_uJ': 3.3 / 100000 * sum(x[i] for i in idx if lo <= i < hi),
        'hypothetical_neighbor_replacement_baseline_change_uA': delta_b,
        'hypothetical_legacy_total_energy_change_uJ': 3.3 / 100000 * sum(y[i] - x[i] for i in range(lo, hi)),
        'window_sensitivity': [],
    }
    for end in [100, 150, 200, 300, 500]:
        n = end * 100
        correction = 3.3 / 100000 * (sum(y[i] - x[i] for i in range(m, m + n)) - n * delta_b)
        entry['window_sensitivity'].append({
            'end_ms': end, 'phase_outlier_count': sum(m <= i < m + n for i in idx),
            'hypothetical_signed_increment_change_uJ': correction,
        })
    a['wire_counter_review']['rows'].append(entry)
a['limits'].append('TX wire counter anomalies exist in all five captures; acquisition validity is qualified pending identification of their cause. They do not justify inventing missing samples or rejecting only run 3.')
out.write_text(json.dumps(a, indent=2) + '\n')
for z in a['wire_counter_review']['rows']:
    print(z['role'], z['run_id'], 'baseline_outliers', z['baseline_outlier_count'],
          'legacy_outliers', z['legacy_window_outlier_count'], 'legacy_total_delta',
          round(z['hypothetical_legacy_total_energy_change_uJ'], 6), 'signed200_delta',
          round(z['window_sensitivity'][2]['hypothetical_signed_increment_change_uJ'], 6))
print('tx primary mean delta', statistics.fmean(z['window_sensitivity'][2]['hypothetical_signed_increment_change_uJ'] for z in a['wire_counter_review']['rows'] if z['role'] == 'tx'))

# Final inline addition: source/model facts and the specific run-3 limitation.
a = json.loads(out.read_text())
a['model'].update({
    'generated_payload_ascii': '0123456789abcdefghijklmnopqrstuv',
    'host_uart_command_ascii': 'AT+SEND=0123456789abcdefghijklmnopqrstuv\\r\\n',
    'host_uart_command_bytes_including_CRLF': 42, 'uart_baud': 1000000,
    'uart_command_drain_before_write_ms': 20,
    'source_references': [
        'radio_power_profiler/profiles.json:552-554',
        'radio_power_profiler/planning.py:49-61',
        'radio_power_profiler/serial_radio.py:467-470',
        'radio_power_profiler/serial_radio.py:161-170',
        'radio_power_profiler/paired_runner.py:272-279',
        'radio_power_profiler/analysis.py:153-180',
    ],
})
a['run3_acquisition_qualification'] = {
    'role': 'tx', 'samples': 97280, 'marker': 22528,
    'nominal_expected_samples': 97528, 'nominal_deficit_samples': 248,
    'reported_deficit_percent': 0.2542859486506439,
    'interpretation': '248 is a deficit against requested duration and queue-count marker, not a confirmed count of missing wire samples. No rescaling, padding, or selective exclusion is justified by this number alone.',
    'local_posttrigger_ms': 747.52, 'all_requested_sensitivity_windows_fit': True,
}
out.write_text(json.dumps(a, indent=2) + '\n')
print('report_complete', out)
