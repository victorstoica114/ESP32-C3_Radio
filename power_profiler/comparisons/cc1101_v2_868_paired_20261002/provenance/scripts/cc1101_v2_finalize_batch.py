"""Finalize a whole CC1101 V2 batch; preserve all earlier attempt metadata."""
import hashlib,json,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
session=Path((ROOT/'.tmp/cc1101_v2_active_session.txt').read_text().strip()).resolve()
assert session.is_relative_to(ROOT.resolve())
acquisition_names=('acquisition','acquisition_retry','acquisition_retry_more')
analysis=session/'analysis'
export=ROOT/'power_profiler/comparisons/cc1101_v2_868_paired_20261002'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def evidence(p):return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
def write(p,d):
    with p.open('x',encoding='utf-8') as f:json.dump(d,f,indent=2,ensure_ascii=False,allow_nan=False)

audit=read(analysis/'audit.json');history=read(analysis/'window_history_audit.json')
assert audit['valid_complete_five_trial_numeric_batch'] is True and audit['errors']==[]
assert history['all_history_budgets_passed'] is True
assert sha(analysis/'audit.json')==history['audit']['sha256']
source=Path(audit['source']['path']).resolve();assert sha(source)==audit['source']['sha256']
acquisition=source.parent.parent
candidate_name=source.parent.name
assert source.name=='report.json' and source.is_relative_to(session)
assert acquisition.parent==session and acquisition.name in acquisition_names
assert candidate_name.startswith('attempt_') and candidate_name[8:].isdigit()
candidate=read(source);assert candidate['completed'] is True and candidate['status']=='candidate'
assert len(candidate['runs'])==5 and len({r['run_id'] for r in candidate['runs']})==5
assert all(r['candidate'] is True for r in candidate['runs'])
assert len(audit['captures'])==10
independent_path=session/'independent_evidence_review.json'
independent=read(independent_path)
assert independent['valid'] is True and independent['verdict']=='passed' and independent['errors']==[]
assert Path(independent['candidate_result_root']).resolve()==source.parent
assert Path(independent['candidate_report']['path']).resolve()==source
assert independent['candidate_report']['sha256']==sha(source)
assert all(independent['checks'].get(k) is True for k in (
    'raw_uart_reconstruction_match','delivery_valid','complete_lot','configuration_valid',
    'mapping_valid','identities_valid','capture_association_valid','all_source_hashes_recorded'))
assert all(independent['summary'].get(k)==v for k,v in {
    'transfers':5,'tx_success_both_ack_lines':5,'rx_exact_deliveries':5,'raw_files':10,'wire_files':10}.items())
for role in ('tx','rx'):
    before,after=candidate['hardware_before'][role],candidate['hardware_after'][role]
    assert before['configuration_queries']==after['configuration_queries']
    for meta in (before,after):
        assert int(meta['status']['CHIP_VERSION'],0)==0x14
        assert meta['status']['RX']==('OFF' if role=='tx' else 'ON')
        assert meta['status']['SLEEP']=='NO' and meta['status']['BRIDGE']=='ON'
accepted_capture_paths=set()
for cap in audit['captures']:
    for kind in ('raw','wire'):
        p=Path(cap[kind]['path']).resolve()
        assert p.is_relative_to(source.parent) and p not in accepted_capture_paths
        assert sha(p)==cap[kind]['sha256']
        accepted_capture_paths.add(p)
status_bytes=(acquisition/'status.json').read_bytes();status=json.loads(status_bytes)
assert status['state']=='candidate_holding' and not status['errors'] and not status['hold_errors']
assert status['ppk_handles_open']=={'tx':True,'rx':True}
assert time.time()-status['time']<5 and all(time.time()-v['time']<5 for v in status['samples_currents'].values())
root_bytes=(acquisition/'report.json').read_bytes();root_report=json.loads(root_bytes)
assert not root_report['errors'] and root_report['candidate']==source.parent.name
assert root_report['attempts'][-1]=={'path':candidate_name,'status':'candidate'}

# Reject selective prefixes: one entire candidate is accepted; every preceding
# incomplete/failed lot remains represented by its unchanged report and receipt.
attempt_rows=[]; acquisition_roots=[]; rejected_capture_paths=set()
def observations(runs, *, energy):
    tx_key='tx_state_ok_count' if energy else 'tx_ok_count'
    return {'transfers_recorded':len(runs),
        'tx_successes_observed':sum(r.get(tx_key)==1 and
            (not energy or r.get('tx_bridge_ack_count')==1) for r in runs),
        'rx_transfers_observed':sum(type(r.get('rx_exact_count')) is int and r['rx_exact_count']>0 for r in runs),
        'rx_payload_observations':sum(r['rx_exact_count'] for r in runs if type(r.get('rx_exact_count')) is int),
        'missing_tx_telemetry':sum(type(r.get(tx_key)) is not int for r in runs),
        'missing_rx_telemetry':sum(type(r.get('rx_exact_count')) is not int for r in runs)}
for acquisition_name in acquisition_names:
    subtree=session/acquisition_name
    if not subtree.exists():continue
    assert subtree.resolve().parent==session
    acquisition_roots.append(subtree)
    report=read(subtree/'report.json')
    assert report.get('candidate')==(candidate_name if subtree==acquisition else None)
    declared=report['attempts']
    assert len({a['path'] for a in declared})==len(declared)
    assert {p.parent.name for p in subtree.glob('attempt_*/report.json')}=={a['path'] for a in declared}
    for item in declared:
        name=item['path'];assert Path(name).name==name and name.startswith('attempt_') and name[8:].isdigit()
        p=subtree/name/'report.json';data=read(p);accepted=p.resolve()==source
        assert data['status']==item['status']
        if accepted:
            assert data['status']=='candidate' and subtree==acquisition
        else:
            assert data['status'] in ('incomplete_delivery','failed')
            assert acquisition_names.index(acquisition_name)<=acquisition_names.index(acquisition.name)
            if subtree==acquisition:assert int(name[8:])<int(candidate_name[8:])
            for run in data.get('runs',[]):
                paths=[cap['raw_path'] for cap in run.get('captures',{}).values()]
                paths.extend(run.get('wire_paths',{}).values())
                for relative in paths:
                    capture=(p.parent/relative).resolve()
                    assert capture.is_relative_to(p.parent.resolve()) and capture not in accepted_capture_paths
                    rejected_capture_paths.add(capture)
        attempt_rows.append({'acquisition':acquisition_name,'attempt':name,'status':data['status'],
            'completed':data.get('completed') is True,'accepted_energy_batch':accepted,
            'report':evidence(p),'observations':observations(data.get('runs',[]),energy=True)})
assert sum(a['accepted_energy_batch'] for a in attempt_rows)==1
energy_observations={k:sum(a['observations'][k] for a in attempt_rows) for k in attempt_rows[0]['observations']}
energy_by_acquisition={name:{k:sum(a['observations'][k] for a in attempt_rows if a['acquisition']==name)
    for k in energy_observations} for name in acquisition_names if any(a['acquisition']==name for a in attempt_rows)}

cleanup_receipts=[]; deleted_paths=set()
for receipt_path in sorted(session.glob('*cleanup_execution.json')):
    receipt=read(receipt_path)
    plan_path=receipt_path.with_name(receipt_path.name.replace('_execution.json','_plan.json'))
    assert plan_path.is_file() and sha(plan_path)==receipt['plan_sha256']
    deleted=receipt['deleted_files']
    assert receipt['deleted_count']==len(deleted)
    assert receipt['deleted_bytes']==sum(item['bytes'] for item in deleted)
    for item in deleted:
        p=Path(item['path']).resolve()
        assert p.is_relative_to(session) and p not in accepted_capture_paths
        assert p.name.endswith(('.csv.gz','.ppk2.bin')) and not p.exists()
        assert len(item['sha256'])==64
        deleted_paths.add(p)
    cleanup_receipts.append({'receipt':evidence(receipt_path),'plan':evidence(plan_path),
        'deleted_files':len(deleted),'deleted_bytes':receipt['deleted_bytes']})
assert rejected_capture_paths<=deleted_paths, 'Rejected capture cleanup receipts are incomplete'
present_capture_paths={p.resolve() for tree in acquisition_roots for p in tree.rglob('*')
    if p.is_file() and p.name.endswith(('.csv.gz','.ppk2.bin'))}
assert present_capture_paths==accepted_capture_paths, 'Only accepted RAW/WIRE may remain'

rf_observations=[]
for p in sorted(session.glob('rf_*.json')):
    data=read(p)
    if 'batches' not in data:continue
    runs=[r for batch in data['batches'] for r in batch.get('runs',[])]
    rf_observations.append({'report':evidence(p),'completed':data.get('completed') is True,
        'batch_count':len(data['batches']),'observations':observations(runs,energy=False)})
rf_totals={k:sum(r['observations'][k] for r in rf_observations) for k in energy_observations}

archive=session/'provenance';archive.mkdir(exist_ok=False)
(archive/'acquisition_snapshot.json').write_bytes(root_bytes)
(archive/'power_hold_snapshot.json').write_bytes(status_bytes)
assert sha(acquisition/'START.json')==root_report['staged_start']['sha256']
shutil.copyfile(acquisition/'START.json',archive/'START.json')
for name in ('preparation.json',):
    shutil.copyfile(session/name,archive/name)
metadata=archive/'session_metadata';metadata.mkdir()
for p in sorted(session.glob('*.json')):
    assert p.name not in ('final_result.json','source_manifest.json'), 'Finalizer has already run'
    shutil.copyfile(p,metadata/p.name)
for tree in acquisition_roots:
    for p in sorted(tree.rglob('*')):
        if not p.is_file() or p.suffix.lower()=='.tmp' or p.name.endswith(('.csv.gz','.ppk2.bin')):continue
        assert p.suffix.lower() in ('.json','.log','.txt','.md','.py') or p.name=='STOP'
        destination=archive/'acquisition_metadata'/p.relative_to(session)
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,destination)
diagnostic_provenance=session/'diagnostic_provenance'
if diagnostic_provenance.exists():
    for p in diagnostic_provenance.rglob('*'):
        if p.is_file():assert p.suffix.lower() in ('.json','.log','.txt','.md','.py')
    shutil.copytree(diagnostic_provenance,archive/'diagnostic_provenance')
scripts=archive/'scripts';scripts.mkdir()
names=sorted({p.name for p in (ROOT/'.tmp').glob('cc1101_v2_*.py')}|{'nrf24_window_history_audit.py'})
for name in names:shutil.copyfile(ROOT/'.tmp'/name,scripts/name)
assert sha(scripts/'cc1101_v2_retry_capture_worker.py')==root_report['script_sha256']
assert sha(scripts/'cc1101_v2_analyze_candidate.py')==audit['helper']['sha256']
assert sha(scripts/'nrf24_window_history_audit.py')==history['helper']['sha256']
for path in ('radio_power_profiler/ppk.py','radio_power_profiler/serial_radio.py',
    'radio_power_profiler/paired_ppk.py','radio_power_profiler/results.py',
    'radio_power_profiler/analysis.py','radio_power_profiler/profiles.py',
    'radio_power_profiler/profiles.json','radio_power_profiler/planning.py',
    'radio_power_profiler/filter_marker_totals.py','tools/audit_filter_marker_totals.py'):
    dest=archive/'dependencies'/path;dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'power_profiler'/path,dest)
write(archive/'reproduction.json',{'original_helper_location':'.tmp/',
    'analysis_command':f'power_profiler/.venv/Scripts/python.exe -B .tmp/cc1101_v2_analyze_candidate.py --candidate <session>/{acquisition.name}/{candidate_name} --output <NEW output directory>',
    'history_command':'power_profiler/.venv/Scripts/python.exe -B .tmp/nrf24_window_history_audit.py --audit <NEW output directory>/audit.json --output <NEW history JSON>',
    'archive_note':'Restore archived helpers under repository .tmp/; hardware worker is recorded for provenance and must not be launched while existing PPK holder owns the ports.'})
files=sorted(p for folder in (source.parent,analysis,archive) for p in folder.rglob('*') if p.is_file())
write(session/'source_manifest.json',{'algorithm':'sha256','files':[evidence(p) for p in files],
    'scope':'Complete accepted five-transfer batch, numeric/independent/history audits, software/configuration snapshots and all previous attempt/RF diagnostic metadata plus cleanup receipts. Only accepted RAW/WIRE are retained; live reports/status have immutable snapshots.'})
summary={'schema_version':1,'completed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
    'status':'complete_five_trial_numeric_batch','module':'CC1101 V2 868 MHz',
    'profile_id':'RADIO_CC1101_V2_868','condition':candidate['settings'],
    'accepted_acquisition':acquisition.name,'accepted_attempt':candidate_name,'accepted_pairs':5,'accepted_captures':10,
    'accepted_energy_conditions':2,'acquisition_attempts':len(attempt_rows),
    'all_energy_attempts':attempt_rows,'all_energy_observations':energy_observations,
    'energy_observations_by_acquisition':energy_by_acquisition,
    'rf_only_diagnostics':rf_observations,'rf_only_observations':rf_totals,
    'cleanup_receipts':cleanup_receipts,
    'retention':'Only the entire accepted five-transfer RAW/WIRE set remains. All preceding rejected attempts, successful prefixes, RF-only observations and cleanup receipts remain as archived metadata; no selected transfers were merged.',
    'voltage_mv':candidate['voltage_mv_for_decoder'],'voltage_provenance':candidate['voltage_provenance'],
    'voltage_simultaneously_recorded':False,'measured_rail':'CC1101 module; ESP32 host excluded',
    'ports':root_report['ports'],'radio_usb_identities':root_report['radio_usb_identities'],
    'mapping_evidence':evidence(archive/'preparation.json'),
    'staged_start':evidence(archive/'START.json'),
    'configuration_verification':'SPI chip version0x14 before/after and explicit firmware parameter readbacks; no full hardware RF-register dump.',
    'hardware_synchronized':False,'sample_rate_hz_per_ppk':100000,
    'numeric_audit':evidence(analysis/'audit.json'),'initial_history_audit':evidence(analysis/'window_history_audit.json'),
    'independent_evidence_review':evidence(independent_path),
    'source_manifest':evidence(session/'source_manifest.json'),'audit_summary':audit['summary'],
    'aggregates':audit['aggregates'],'max_initial_history_relative_bound':history['max_energy_history_relative_bound'],
    'transmit_protocol':audit['transmit_protocol'],
    'definitions':{'TX':audit['tx_window_definition'],'RX':audit['rx_window_definition'],
        'energy':audit['legacy_total_definition'],'sd':'Sample SD, ddof=1, n=5; not instrument absolute uncertainty.'},
    'limitations':['RX is complementary listening energy in a modeled4.69ms interval (469 samples), not exclusive RF reception. The historical RX metric used a different controlled interval and is not directly comparable.',
        'TX is a current-threshold event; no hardware RF marker.',
        'Initial-history interval applies to selected software windows; it does not establish invariance of TX threshold selection.',
        'No simultaneous voltage measurement or analog-accuracy calibration claim.',
        'This is the complete passing batch selected after earlier failed/incomplete batches, not an unbiased delivery-rate estimate. All observed trial counts are reported separately; no causal remedy is inferred.',
        'RF-only controls used multiple settings and are separate from the energy cohort; their observations are not a single-condition reliability estimate.',
        'Five successful transfers do not prove a general100percent delivery probability. Historical TX receipt telemetry was absent, not evidence of failed delivery.'],
    'power_hold':{'worker_pid':int((ROOT/'.tmp/cc1101_v2_retry_capture_worker.pid').read_text()),
        'status_path':(acquisition/'status.json').relative_to(ROOT).as_posix(),
        'stop_file':(acquisition/'STOP').relative_to(ROOT).as_posix(),
        'state_at_finalization':'Both PPK ports open, DUT paths ON, measurement streams drained continuously.'},
    'calculation_files':{name:evidence(analysis/name) for name in ('trials.csv','aggregates.csv')}}
write(session/'final_result.json',summary)
export.mkdir(exist_ok=False)
for name in ('audit.json','window_history_audit.json','trials.csv','aggregates.csv'):
    shutil.copyfile(analysis/name,export/name)
for source_path,name in ((session/'final_result.json','summary.json'),(session/'source_manifest.json','source_manifest.json'),(source,candidate_name+'_report.json'),(independent_path,'independent_evidence_review.json')):
    shutil.copyfile(source_path,export/name)
shutil.copytree(archive,export/'provenance')
print(json.dumps({'export':str(export),'accepted_pairs':5,'manifest_files':len(files),'aggregates':summary['aggregates']}))
