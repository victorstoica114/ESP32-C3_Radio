"""Verify finalized CC1101 package and preserved source data without hardware access."""
import hashlib,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
session=Path((ROOT/'.tmp/cc1101_v2_active_session.txt').read_text().strip())
export=ROOT/'power_profiler/comparisons/cc1101_v2_868_paired_20261002'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=read(session/'source_manifest.json')
for row in manifest['files']:
    p=ROOT/row['path']
    assert p.is_file() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],row['path']
assert sha(session/'final_result.json')==sha(export/'summary.json')
assert sha(session/'source_manifest.json')==sha(export/'source_manifest.json')
for name in ('audit.json','window_history_audit.json','trials.csv','aggregates.csv'):
    assert sha(session/'analysis'/name)==sha(export/name),name
for p in (session/'provenance').rglob('*'):
    if p.is_file():assert sha(p)==sha(export/'provenance'/p.relative_to(session/'provenance')),str(p)
remaining=[p for folder in ('acquisition','acquisition_retry','acquisition_retry_more')
           for p in (session/folder).rglob('*') if p.name.endswith(('.csv.gz','.ppk2.bin'))]
assert len(remaining)==20 and all('acquisition_retry_more/attempt_001' in p.as_posix() for p in remaining)
summary=read(session/'final_result.json');assert summary['accepted_pairs']==5 and summary['accepted_captures']==10
status=read(session/'acquisition_retry_more/status.json')
assert status['state']=='candidate_holding' and not status['errors'] and not status['hold_errors']
assert status['ppk_handles_open']=={'tx':True,'rx':True} and time.time()-status['time']<5
assert all(time.time()-v['time']<5 for v in status['samples_currents'].values())
report={'passed':True,'manifest_files_verified':len(manifest['files']),'export_copies_identical':True,
        'accepted_pairs':5,'accepted_captures':10,'remaining_raw_wire_files':len(remaining),
        'failed_raw_wire_remaining':0,'final_result_sha256':sha(session/'final_result.json'),
        'source_manifest_sha256':sha(session/'source_manifest.json'),'power_status_at_verification':status,
        'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
with (session/'final_verification.json').open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
print(json.dumps({k:v for k,v in report.items() if k!='power_status_at_verification'}))
