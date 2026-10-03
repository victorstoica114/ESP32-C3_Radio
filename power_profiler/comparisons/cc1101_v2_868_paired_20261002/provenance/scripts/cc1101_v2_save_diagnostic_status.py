"""Save a bounded no-delivery diagnostic summary; never accept energy points."""
import hashlib,json,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
session=Path((ROOT/'.tmp/cc1101_v2_active_session.txt').read_text().strip())
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def ref(p):return {'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
acq=read(session/'acquisition/report.json');review=read(session/'initial_attempts_review.json')
controls=read(session/'rf_controls_02.json');power=read(session/'acquisition_retry/status.json')
assert acq['candidate'] is None and controls['completed'] is True
attempts=[read(session/'acquisition'/v['path']/'report.json') for v in acq['attempts']]
runs=[r for a in attempts for r in a['runs']]
assert len(runs)==20 and all(r['tx_ok'] and r['rx_exact_count']==0 for r in runs)
probes=[r for b in controls['batches'] for r in b['runs']]
assert len(probes)==14 and all(r['tx_ok_count']==1 and r['rx_exact_count']==0 for r in probes)
assert power['state']=='waiting_for_start' and not power['hold_errors'] and not power['errors']
assert time.time()-power['time']<5 and power['ppk_handles_open']=={'tx':True,'rx':True}
archive=session/'diagnostic_provenance';archive.mkdir(exist_ok=False)
for name in ('cc1101_v2_prepare_probe.py','cc1101_v2_retry_capture_worker.py',
             'cc1101_v2_rf_controls.py','cc1101_v2_analyze_candidate.py',
             'cc1101_v2_save_diagnostic_status.py'):
    shutil.copyfile(ROOT/'.tmp'/name,archive/name)
(archive/'power_snapshot.json').write_text(json.dumps(power,indent=2),encoding='utf-8')
report={'status':'awaiting_physical_wiring_check','accepted_pairs':0,'accepted_energy_points':0,
    'module':'CC1101 V2 868 MHz','settings':acq['settings'],'physical_mapping':acq['ports'],
    'voltage_mv':3300,'voltage_provenance':acq['voltage_provenance'],'measured_rail':'Radio only, ESP32 excluded',
    'campaign_observations':{'attempts':len(attempts),'tx_completions':20,'rx_deliveries':0,
        'last_attempt_note':'Twenty transfers finished; explicit STOP prevented the fourth post-batch configuration check.'},
    'rf_controls':{'trials':14,'tx_completions':14,'rx_deliveries':0,
        'conditions':[{k:b[k] for k in ('rate_kbps','power_dbm','tx','rx','modulation')} for b in controls['batches']],
        'target_configuration_restored':True},
    'root_cause':'Undetermined. GPIO10 GDO0 wiring confirmation requested; no firmware edits or flash performed.',
    'uart_observation':'First RF control CFG response truncated at 512 bytes; subsequent controls used short per-field readbacks.',
    'legacy_note':'Historical TX had no peer reception observer; question mark was unknown delivery, not demonstrated loss.',
    'retention':'Failed initial RAW/WIRE follow explicit operator deletion policy; hashes and small reports retained.',
    'power_holder':{'pid':int((ROOT/'.tmp/cc1101_v2_retry_capture_worker.pid').read_text()),
        'state':'waiting_for_start','path':(session/'acquisition_retry').relative_to(ROOT).as_posix(),
        'both_dut_paths_on':True,'both_ports_open_and_continuously_drained':True,'automatic_transmission_pending':False},
    'evidence':[ref(session/n) for n in ('preparation.json','acquisition/report.json',
        'initial_attempts_review.json','rf_controls.json','rf_controls_02.json')],
    'software_provenance':[ref(p) for p in sorted(archive.iterdir())],
    'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
with (session/'diagnostic_summary.json').open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
print(json.dumps({'summary':str(session/'diagnostic_summary.json'),'accepted_pairs':0,'transfers':20,'rf_controls':14}))
