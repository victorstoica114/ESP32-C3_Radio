"""Finalize a complete E07 point after independent numeric and history audits."""
import hashlib,json,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
session=Path((ROOT/'.tmp/e07_active_session.txt').read_text().strip())
acquisition=session/'acquisition'
analysis=session/'analysis'
export=ROOT/'power_profiler/comparisons/ebyte_e07_400m10s_paired_20261002'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def evidence(p):return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
def write(p,d):
    with p.open('x',encoding='utf-8') as f:json.dump(d,f,indent=2,ensure_ascii=False,allow_nan=False)

audit=read(analysis/'audit.json');history=read(analysis/'window_history_audit.json')
assert audit['valid_complete_five_trial_numeric_batch'] is True and audit['errors']==[]
assert history['all_history_budgets_passed'] is True
assert sha(analysis/'audit.json')==history['audit']['sha256']
source=Path(audit['source']['path']);assert sha(source)==audit['source']['sha256']
candidate=read(source);assert candidate['completed'] is True and candidate['status']=='candidate'
for role in ('tx','rx'):
    before,after=candidate['hardware_before'][role],candidate['hardware_after'][role]
    assert before['configuration_queries']==after['configuration_queries']
    for meta in (before,after):
        assert int(meta['status']['CHIP_VERSION'],0)==0x14
        assert meta['status']['RX']==('OFF' if role=='tx' else 'ON')
        assert meta['status']['SLEEP']=='NO' and meta['status']['BRIDGE']=='ON'
for cap in audit['captures']:
    for kind in ('raw','wire'):assert sha(Path(cap[kind]['path']))==cap[kind]['sha256']
status_bytes=(acquisition/'status.json').read_bytes();status=json.loads(status_bytes)
assert status['state']=='candidate_holding' and not status['errors'] and not status['hold_errors']
assert status['ppk_handles_open']=={'tx':True,'rx':True}
assert time.time()-status['time']<5 and all(time.time()-v['time']<5 for v in status['samples_currents'].values())
root_bytes=(acquisition/'report.json').read_bytes();root_report=json.loads(root_bytes)
assert not root_report['errors'] and root_report['candidate']==source.parent.name
assert len(root_report['attempts'])==1 and root_report['attempts'][0]['status']=='candidate'

archive=session/'provenance';archive.mkdir(exist_ok=False)
(archive/'acquisition_snapshot.json').write_bytes(root_bytes)
(archive/'power_hold_snapshot.json').write_bytes(status_bytes)
for name in ('preparation.json','rf_preflight.json','rf_controls.json','uart_after_controls.json'):
    shutil.copyfile(session/name,archive/name)
scripts=archive/'scripts';scripts.mkdir()
names=('e07_prepare_probe.py','e07_rf_preflight.py','e07_rf_controls.py',
       'e07_retry_capture_worker.py','e07_analyze_candidate.py','nrf24_window_history_audit.py','e07_finalize_batch.py')
for name in names:shutil.copyfile(ROOT/'.tmp'/name,scripts/name)
assert sha(scripts/'e07_retry_capture_worker.py')==root_report['script_sha256']
assert sha(scripts/'e07_analyze_candidate.py')==audit['helper']['sha256']
assert sha(scripts/'nrf24_window_history_audit.py')==history['helper']['sha256']
for path in ('radio_power_profiler/ppk.py','radio_power_profiler/serial_radio.py',
    'radio_power_profiler/paired_ppk.py','radio_power_profiler/results.py',
    'radio_power_profiler/analysis.py','radio_power_profiler/profiles.py',
    'radio_power_profiler/profiles.json','radio_power_profiler/planning.py',
    'radio_power_profiler/filter_marker_totals.py','tools/audit_filter_marker_totals.py'):
    dest=archive/'dependencies'/path;dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'power_profiler'/path,dest)
write(archive/'reproduction.json',{'original_helper_location':'.tmp/',
    'analysis_command':'power_profiler/.venv/Scripts/python.exe -B .tmp/e07_analyze_candidate.py --candidate <session>/acquisition/attempt_001 --output <NEW output directory>',
    'history_command':'power_profiler/.venv/Scripts/python.exe -B .tmp/nrf24_window_history_audit.py --audit <NEW output directory>/audit.json --output <NEW history JSON>',
    'archive_note':'Restore archived helpers under repository .tmp/; hardware worker is recorded for provenance and must not be launched while existing PPK holder owns the ports.'})
files=sorted(p for folder in (source.parent,analysis,archive) for p in folder.rglob('*') if p.is_file())
write(session/'source_manifest.json',{'algorithm':'sha256','files':[evidence(p) for p in files],
    'scope':'Complete accepted five-transfer batch, numeric audits, software and configuration snapshots. Live acquisition report/status represented by immutable snapshots.'})
summary={'schema_version':1,'completed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
    'status':'complete_five_trial_numeric_batch','module':'Ebyte E07-400M10S',
    'profile_id':'RADIO_EBYTE_E07_400M10S','condition':candidate['settings'],
    'accepted_attempt':source.parent.name,'accepted_pairs':5,'accepted_captures':10,
    'accepted_energy_conditions':2,'acquisition_attempts':1,
    'retention':'Only complete accepted RAW/WIRE present. Preliminary RF controls produced small transcripts without energy captures.',
    'voltage_mv':candidate['voltage_mv_for_decoder'],'voltage_provenance':candidate['voltage_provenance'],
    'voltage_simultaneously_recorded':False,'measured_rail':'E07 module; ESP32 host excluded',
    'ports':root_report['ports'],'radio_usb_identities':root_report['radio_usb_identities'],
    'mapping_evidence':evidence(archive/'preparation.json'),
    'configuration_verification':'SPI chip version0x14 before/after and explicit firmware parameter readbacks; no full hardware RF-register dump.',
    'hardware_synchronized':False,'sample_rate_hz_per_ppk':100000,
    'numeric_audit':evidence(analysis/'audit.json'),'initial_history_audit':evidence(analysis/'window_history_audit.json'),
    'source_manifest':evidence(session/'source_manifest.json'),'audit_summary':audit['summary'],
    'aggregates':audit['aggregates'],'max_initial_history_relative_bound':history['max_energy_history_relative_bound'],
    'transmit_protocol':audit['transmit_protocol'],
    'definitions':{'TX':audit['tx_window_definition'],'RX':audit['rx_window_definition'],
        'energy':audit['legacy_total_definition'],'sd':'Sample SD, ddof=1, n=5; not instrument absolute uncertainty.'},
    'limitations':['RX is listening energy in a modeled4.44ms interval, not exclusive RF reception.',
        'TX is a current-threshold event; no hardware RF marker.',
        'Initial-history interval applies to selected software windows; it does not establish invariance of TX threshold selection.',
        'No simultaneous voltage measurement or analog-accuracy calibration claim.',
        'Five successful transfers do not prove a general100percent delivery probability or a unique cause for earlier losses.'],
    'power_hold':{'worker_pid':int((ROOT/'.tmp/e07_retry_capture_worker.pid').read_text()),
        'status_path':(acquisition/'status.json').relative_to(ROOT).as_posix(),
        'stop_file':(acquisition/'STOP').relative_to(ROOT).as_posix(),
        'state_at_finalization':'Both PPK ports open, DUT paths ON, measurement streams drained continuously.'},
    'calculation_files':{name:evidence(analysis/name) for name in ('trials.csv','aggregates.csv')}}
write(session/'final_result.json',summary)
export.mkdir(exist_ok=False)
for name in ('audit.json','window_history_audit.json','trials.csv','aggregates.csv'):
    shutil.copyfile(analysis/name,export/name)
for source_path,name in ((session/'final_result.json','summary.json'),(session/'source_manifest.json','source_manifest.json'),(source,'attempt_001_report.json')):
    shutil.copyfile(source_path,export/name)
shutil.copytree(archive,export/'provenance')
print(json.dumps({'export':str(export),'accepted_pairs':5,'manifest_files':len(files),'aggregates':summary['aggregates']}))
