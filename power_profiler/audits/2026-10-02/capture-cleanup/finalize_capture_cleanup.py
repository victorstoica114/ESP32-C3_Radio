"""Verify deletion, retained evidence, and document the current data-retention state."""
import collections
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'power_profiler/audits/2026-10-02/capture-cleanup'

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p, data): p.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p): return p.relative_to(ROOT).as_posix()

manifest = read(AUDIT / 'deletion_manifest.json')
execution = read(AUDIT / 'execution.json')
assert execution['completed'] is True
assert execution['deleted_file_count'] == manifest['delete_file_count']
assert execution['deleted_bytes'] == manifest['delete_bytes']
assert all(not Path(e['path']).exists() for e in manifest['delete_files'])
for entry in manifest['protected_files']:
    p = ROOT / entry['path']
    stat = p.stat()
    assert stat.st_size == entry['bytes'] and stat.st_mtime_ns == entry['mtime_ns'], str(p)

campaign = ROOT / 'power_profiler/web_sessions/20261002_135907_149907_nrf24_pa_paired_retries'
export = ROOT / 'power_profiler/comparisons/nrf24_pa_paired_20261002'
nrf_audit = read(campaign / 'analysis/audit.json')
for cap in nrf_audit['captures']:
    for kind in ('raw', 'wire'):
        assert sha(Path(cap[kind]['path'])) == cap[kind]['sha256']

deleted_paths = {e['relative_path'] for e in manifest['delete_files']}
by_scope = collections.defaultdict(lambda: {'files':0, 'bytes':0})
for entry in manifest['delete_files']:
    by_scope[entry['classifier']]['files'] += 1
    by_scope[entry['classifier']]['bytes'] += entry['bytes']
summary = {'schema_version':1, 'completed_utc':datetime.now(timezone.utc).isoformat(),
    'user_request':'Keep complete data; remove unsuccessful captures, including historic attempts.',
    'deleted_file_count':execution['deleted_file_count'], 'deleted_bytes':execution['deleted_bytes'],
    'by_classification_scope':dict(by_scope), 'all_deleted_paths_absent':True,
    'protected_file_count':len(manifest['protected_files']), 'protected_sizes_and_mtimes_unchanged':True,
    'nrf24_complete_batch_sha256_verified_captures':10,
    'retained':'Accepted/complete data, later-revalidated measurements, successful diagnostics, small logs/reports and interpreted results. No invented success status for deleted failures.',
    'historical_manifest_note':'Original audit reports and hashes describe evidence available at their creation. The deletion manifest records subsequent intentional removal of rejected/incomplete RAW/WIRE.',
    'deletion_manifest': {'path':rel(AUDIT/'deletion_manifest.json'),'sha256':sha(AUDIT/'deletion_manifest.json')},
    'unknown_classifications_retained':manifest['unknowns']}
write(AUDIT / 'summary.json', summary)

retention = {'updated_utc':summary['completed_utc'], 'policy':'Keep complete/accepted capture data; remove proved failed/incomplete RAW/WIRE after classification.',
    'historical_raw_availability':'Failed RAW/WIRE listed in the linked deletion manifest were intentionally deleted at the operator request. Historical reports remain as records, not claims that those files still exist.',
    'cleanup_summary':rel(AUDIT/'summary.json')}
groups = collections.defaultdict(list)
for entry in manifest['delete_files']:
    if entry.get('evidence_path'): groups[Path(entry['evidence_path']).parent].append(entry)
for folder, entries in groups.items():
    write(folder / 'capture_retention.json', dict(retention,
        removed_file_count=len(entries), removed_bytes=sum(e['bytes'] for e in entries),
        removed_paths=[e['relative_path'] for e in entries]))

# Keep the former complete source list as historical provenance; current source
# manifests must not claim that deleted failed-attempt traces remain available.
source_manifest_path = campaign / 'source_manifest.json'
prior_bytes = source_manifest_path.read_bytes()
(AUDIT / 'nrf24_source_manifest_at_acceptance.json').write_bytes(prior_bytes)
prior = json.loads(prior_bytes)
removed = [e for e in prior['files'] if e['path'] in deleted_paths]
retained = [e for e in prior['files'] if e['path'] not in deleted_paths]
for entry in retained: assert sha(ROOT/entry['path']) == entry['sha256']
updated = dict(prior, scope='Retained complete batch, small attempt summaries, calculation results and software snapshots.',
    files=retained, retention=dict(retention, removed_files_from_original_manifest=len(removed),
        original_manifest={'path':rel(AUDIT/'nrf24_source_manifest_at_acceptance.json'), 'sha256':hashlib.sha256(prior_bytes).hexdigest()}))
write(source_manifest_path, updated)
(export/'source_manifest.json').write_bytes(source_manifest_path.read_bytes())
for p in (campaign/'final_result.json', export/'summary.json'):
    data = read(p)
    data['capture_retention'] = retention
    data['source_manifest'] = {'path':rel(source_manifest_path), 'bytes':source_manifest_path.stat().st_size, 'sha256':sha(source_manifest_path)}
    write(p, data)
assert (campaign/'final_result.json').read_bytes() == (export/'summary.json').read_bytes()
write(campaign/'capture_retention.json', retention)
write(export/'capture_retention.json', retention)
print(json.dumps({k:summary[k] for k in ('deleted_file_count','deleted_bytes','protected_file_count','nrf24_complete_batch_sha256_verified_captures')}))
