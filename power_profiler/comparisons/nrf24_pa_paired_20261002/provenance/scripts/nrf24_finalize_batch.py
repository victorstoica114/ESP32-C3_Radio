"""Archive an independently audited, complete nRF batch without changing its evidence."""
import csv
import hashlib
import importlib.metadata
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
campaign = Path((ROOT / '.tmp/nrf24_retry_campaign_path.txt').read_text().strip())
analysis = campaign / 'analysis'
export = ROOT / 'power_profiler/comparisons/nrf24_pa_paired_20261002'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)

def evidence(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

audit = read(analysis / 'audit.json')
history = read(analysis / 'window_history_audit.json')
assert audit['valid_complete_five_trial_numeric_batch'] is True and audit['errors'] == []
assert history['all_history_budgets_passed'] is True
source = Path(audit['source']['path'])
assert evidence(source)['sha256'] == audit['source']['sha256']
assert evidence(analysis / 'audit.json')['sha256'] == history['audit']['sha256']
candidate = read(source)
assert candidate['completed'] is True and candidate['status'] == 'candidate'
expected = {'RF_CH': 80, 'RF_SETUP': 15, 'EN_AA': 0, 'FEATURE': 4, 'DYNPD': 63}
assert candidate['hardware_before'] == candidate['hardware_after'] == {'tx': expected, 'rx': expected}
for capture in audit['captures']:
    for kind in ('raw', 'wire'):
        assert evidence(Path(capture[kind]['path']))['sha256'] == capture[kind]['sha256']

root_bytes = (campaign / 'report.json').read_bytes()
root_report = json.loads(root_bytes)
status_bytes = (campaign / 'status.json').read_bytes()
status = json.loads(status_bytes)
assert root_report['candidate'] == source.parent.name
assert not root_report['errors'] and not status['errors'] and not status['hold_errors']
assert status['state'] == 'candidate_holding' and status['ppk_handles_open'] == {'tx': True, 'rx': True}
assert time.time() - status['time'] < 5
assert all(time.time() - x['time'] < 5 for x in status['samples_currents'].values())

archive = campaign / 'provenance'
archive.mkdir(exist_ok=False)
(archive / 'acquisition_snapshot.json').write_bytes(root_bytes)
(archive / 'power_hold_snapshot.json').write_bytes(status_bytes)
scripts = archive / 'scripts'
scripts.mkdir()
names = ('nrf24_retry_capture_worker.py', 'nrf24_analyze_candidate.py',
         'nrf24_window_history_audit.py', 'nrf24_finalize_batch.py')
for name in names:
    shutil.copyfile(ROOT / '.tmp' / name, scripts / name)
assert evidence(scripts / names[0])['sha256'] == root_report['script_sha256']
assert evidence(scripts / names[1])['sha256'] == audit['helper']['sha256']
assert evidence(scripts / names[2])['sha256'] == history['helper']['sha256']
dependencies = ('radio_power_profiler/ppk.py', 'radio_power_profiler/serial_radio.py',
                'radio_power_profiler/paired_ppk.py', 'radio_power_profiler/results.py',
                'radio_power_profiler/analysis.py', 'radio_power_profiler/profiles.py',
                'radio_power_profiler/profiles.json', 'radio_power_profiler/planning.py',
                'radio_power_profiler/filter_marker_totals.py', 'tools/audit_filter_marker_totals.py')
for relative in dependencies:
    destination = archive / 'dependencies' / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'power_profiler' / relative, destination)
versions = {dist.metadata['Name']: dist.version for dist in importlib.metadata.distributions()
            if dist.metadata['Name'].lower() in ('ppk2-api', 'pyserial')}
write(archive / 'environment.json', {'python': __import__('sys').version,
    'packages': versions, 'source_script_location': '.tmp/',
    'reproduction': 'Restore the archived helper scripts under repository .tmp/ and run the analyzer with --candidate <campaign>/attempt_002 --output <NEW directory>. Then run the history audit with --audit <NEW directory>/audit.json --output <NEW history JSON>.'})

attempts = []
for item in root_report['attempts']:
    attempt = read(campaign / item['path'] / 'report.json')
    attempts.append({'path': item['path'], 'status': attempt['status'],
        'completed': attempt['completed'], 'transfers': len(attempt['runs']),
        'exact_receipts': sum(r['rx_exact_count'] == 1 for r in attempt['runs']),
        'included_in_energy_aggregates': item['path'] == root_report['candidate']})
inputs = sorted(p for folder in [analysis, archive] + [campaign / a['path'] for a in attempts]
                for p in folder.rglob('*') if p.is_file())
write(campaign / 'source_manifest.json', {'algorithm': 'sha256',
    'scope': 'Both complete attempts, all RAW/WIRE, immutable analysis and software snapshot. Live root report/status are represented only by immutable snapshots.',
    'files': [evidence(p) for p in inputs]})

summary = {'schema_version': 1, 'completed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'status': 'complete_five_trial_numeric_batch', 'module': 'nRF24L01 PA/LNA',
    'condition': {'payload_bytes': 32, 'data_rate_kbps': 2000, 'chip_drive_dbm': 0,
                  'channel': 80, 'auto_ack': False, 'external_voltage_V': 3.3},
    'measured_rail': 'Radio module; ESP32 excluded',
    'voltage_provenance': candidate['voltage_provenance'],
    'voltage_simultaneously_recorded': False,
    'accepted_attempt': root_report['candidate'], 'accepted_pairs': 5, 'accepted_captures': 10,
    'accepted_energy_conditions': 2, 'attempts': attempts,
    'all_new_attempts_receipts': sum(a['exact_receipts'] for a in attempts),
    'all_new_attempts_transfers': sum(a['transfers'] for a in attempts),
    'batch_selection': 'First whole five-transfer batch with exact delivery and subsequent independent numeric QA; no merging of successful packets from different batches.',
    'intermittent_delivery_problem_resolved': False,
    'link_reliability_claim': 'None: 5/5 is conditional on selection after retry. All attempts remain archived.',
    'hardware_synchronized': False, 'sample_rate_hz_per_ppk': 100000,
    'ports': root_report['ports'], 'radio_usb_identities': root_report['radio_usb_identities'],
    'power_hold': {'worker_pid': int((ROOT / '.tmp/nrf24_retry_capture_worker.pid').read_text()),
        'status_path': (campaign / 'status.json').relative_to(ROOT).as_posix(),
        'stop_file': (campaign / 'STOP').relative_to(ROOT).as_posix(),
        'snapshot': evidence(archive / 'power_hold_snapshot.json'),
        'note': 'PPK handles remain open and both streams are drained; do not create STOP until intentional ownership handoff.'},
    'numeric_audit': evidence(analysis / 'audit.json'),
    'initial_history_audit': evidence(analysis / 'window_history_audit.json'),
    'source_manifest': evidence(campaign / 'source_manifest.json'),
    'audit_summary': audit['summary'], 'aggregates': audit['aggregates'],
    'max_initial_history_relative_bound': history['max_energy_history_relative_bound'],
    'definitions': {'TX': audit['tx_window_definition'], 'RX': audit['rx_window_definition'],
                    'energy_total': audit['legacy_total_definition'],
                    'sd': 'Sample standard deviation, ddof=1, n=5; not absolute instrument uncertainty.'},
    'limitations': ['RX is listening energy in a modeled 1.16 ms interval, not exclusive RF reception.',
        'TX threshold interval includes radio activity; no independent RF boundary marker.',
        'Unknown-history audit bounds total energy only in the selected fixed software windows, not alternate threshold-window selection.',
        'Chip drive setting 0 dBm does not specify the PA module output power.',
        'No simultaneous voltage measurement, no analog accuracy calibration claim; modulo64 continuity cannot detect all multiple64 losses.'],
    'calculation_files': {name: evidence(analysis / name) for name in ('trials.csv', 'aggregates.csv')},
    'historical_diagnostics': 'power_profiler/web_sessions/20261002_130611_934700_nrf24_pa_diagnostic/diagnostic_summary.json'}
write(campaign / 'final_result.json', summary)
export.mkdir(exist_ok=False)
for name in ('audit.json', 'window_history_audit.json', 'trials.csv', 'aggregates.csv'):
    shutil.copyfile(analysis / name, export / name)
shutil.copyfile(campaign / 'source_manifest.json', export / 'source_manifest.json')
shutil.copyfile(campaign / 'final_result.json', export / 'summary.json')
shutil.copytree(archive, export / 'provenance')
for attempt in attempts:
    shutil.copyfile(campaign / attempt['path'] / 'report.json', export / f"{attempt['path']}_report.json")
print(json.dumps({'export': str(export), 'accepted_pairs': 5, 'all_attempts': attempts,
                  'immutable_source_files': len(inputs)}, ensure_ascii=False))
