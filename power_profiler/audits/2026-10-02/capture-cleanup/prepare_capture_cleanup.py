"""Prepare exact, independently classified capture deletion paths; no deletion here."""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'power_profiler/audits/2026-10-02/capture-cleanup'
OUTPUT.mkdir(parents=True, exist_ok=True)
if (OUTPUT / 'deletion_manifest.json').exists() or (OUTPUT / 'execution.json').exists():
    raise FileExistsError('A sealed deletion plan already exists; do not overwrite it')
ALLOWED = [ROOT / 'power_profiler', ROOT / 'module radio', ROOT / '.tmp']

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def key(path):
    return str(path).casefold()

def resolve(value, *, protected=False):
    path = Path(value)
    if not path.is_absolute(): path = ROOT / path
    path = path.resolve(strict=True)
    if not any(path.is_relative_to(parent) for parent in ALLOWED):
        raise ValueError(f'Outside measurement roots: {path}')
    if not protected and any(part in ('.git', '.venv', 'node_modules') for part in path.parts):
        raise ValueError(f'Excluded program/history path: {path}')
    if not path.is_file(): raise ValueError(f'Not a regular file: {path}')
    return path

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(8 * 1024 * 1024): h.update(chunk)
    return h.hexdigest()

plans, protected, proposed, unknowns = [], {}, {}, []
for name in ('root', 'faraday', 'maxwell', 'tesla'):
    source = ROOT / f'.tmp/cleanup_{name}.json'
    data = read(source)
    plans.append({'agent': name, 'path': source.relative_to(ROOT).as_posix(), 'sha256': digest(source)})
    # Keep exact classification evidence, small compared with the deleted traces.
    (OUTPUT / f'classification_{name}.json').write_bytes(source.read_bytes())
    for item in data.get('protected_files', []):
        path = resolve(item if isinstance(item, str) else item['path'], protected=True)
        stat = path.stat()
        protected[key(path)] = {'path': path.relative_to(ROOT).as_posix(), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    for item in data['delete_files']:
        path = resolve(item['path'])
        verified_duplicate_zip = (item.get('status') == 'verified_redundant_archive' and
            path == ROOT / '.tmp/e79-ch340-release/e79_ch340_tx_recapture_20260929_full_session.zip' and
            item.get('sha256') == 'fe09b18b6332ba34362133ab4ca97297633f2f786a21d0af6377544787e6068a')
        if not (path.name.endswith('.csv.gz') or path.name.endswith('.ppk2.bin') or verified_duplicate_zip):
            raise ValueError(f'Unexpected capture extension requires explicit review: {path}')
        if path.stat().st_size != item['bytes']:
            raise ValueError(f'Capture changed since classification: {path}')
        entry = dict(item, path=str(path), relative_path=path.relative_to(ROOT).as_posix(), classifier=name)
        if key(path) in proposed and proposed[key(path)]['bytes'] != entry['bytes']:
            raise ValueError(f'Conflicting evidence: {path}')
        proposed[key(path)] = entry
    unresolved = data.get('unknowns', [])
    if isinstance(unresolved, dict): unresolved = unresolved.get('files', [])
    unknowns.extend(unresolved)
conflicts = set(protected) & set(proposed)
if conflicts: raise ValueError(f'Deletion intersects protected evidence: {sorted(conflicts)[:10]}')
entries = []
for number, entry in enumerate(sorted(proposed.values(), key=lambda x:x['path'])):
    path = Path(entry['path'])
    entry['sha256'] = digest(path)
    evidence_path = entry.get('evidence_path')
    if evidence_path:
        p = resolve(evidence_path)
        entry['evidence_sha256'] = digest(p)
    entries.append(entry)
    if number % 100 == 0: print(json.dumps({'hashed_deletion_candidates':number+1,'total':len(proposed)}), flush=True)
manifest = {'schema_version':1, 'created_utc':datetime.now(timezone.utc).isoformat(),
    'workspace_root':str(ROOT), 'authorization':'User requested keeping only complete data and deleting failed attempts, including historic captures.',
    'policy':'Delete exact RAW/WIRE files proved rejected or incomplete and the one local ZIP verified identical to its extracted copies. Keep accepted measurements and small summaries. No hardware operations.',
    'plans':plans, 'delete_files':entries, 'protected_files':list(protected.values()), 'unknowns':unknowns,
    'delete_file_count':len(entries), 'delete_bytes':sum(e['bytes'] for e in entries),
    'protected_file_count':len(protected), 'protected_bytes':sum(e['bytes'] for e in protected.values())}
for name in ('cleanup_tesla_zip_verification.json','prepare_capture_cleanup.py','remove_failed_capture_files.ps1','finalize_capture_cleanup.py'):
    (OUTPUT/name).write_bytes((ROOT/'.tmp'/name).read_bytes())
(OUTPUT / 'deletion_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({k:manifest[k] for k in ('delete_file_count','delete_bytes','protected_file_count','protected_bytes')}) )
