"""Local capture storage and resolution of unchanged historical source paths."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPOSITORY_ROOT / 'measurements' / 'raw'
SESSIONS_ROOT = RAW_ROOT / 'sessions'
PACKET_RESULTS_ROOT = RAW_ROOT / 'packet'
CONTINUOUS_RESULTS_ROOT = RAW_ROOT / 'continuous'

# Keep source manifests byte-identical: only translate paths when opening them.
_PREFIXES = (
    ('module radio/ESP32-C3_Radio/power_profiler', 'measurements/raw/archive'),
    ('module radio/IMPORT_INFO', 'measurements/raw/archive/import-info'),
    ('power_profiler/web_sessions', 'measurements/raw/sessions'),
    ('power_profiler/firmware/e79_tx_marker_dio17', 'power_profiler/audits/2026-10-01/e79-markers'),
    ('power_profiler/results', 'measurements/raw/packet'),
    ('power_profiler/continuous_results', 'measurements/raw/archive/continuous_results'),
    ('power_profiler/loss_results', 'measurements/raw/archive/loss_results'),
    ('continuous_results', 'measurements/raw/archive/continuous_results'),
    ('loss_results', 'measurements/raw/archive/loss_results'),
)


@lru_cache(maxsize=4)
def _mappings(root: Path) -> tuple[tuple[str, str], ...]:
    manifest = root / 'measurements' / 'relocation.json'
    if not manifest.is_file():
        return tuple(sorted(_PREFIXES, key=lambda pair: len(pair[0]), reverse=True))
    data = json.loads(manifest.read_text(encoding='utf-8'))
    aliases = {row['path']: row['new_path'] for row in data.get('captures', [])}
    mappings = dict(_PREFIXES)
    mappings.update(data.get('prefixes', []))
    mappings.update(aliases)
    return tuple(sorted(mappings.items(), key=lambda pair: len(pair[0]), reverse=True))


def resolve_measurement_path(value: str | Path, *, root: Path = REPOSITORY_ROOT) -> Path:
    """Resolve a local path or a recorded old path, without editing evidence.

    Existing explicit paths take precedence. Unrelated external paths are
    returned unchanged; missing captures stay missing and are not synthesized.
    """
    path = Path(value)
    try:
        if path.exists():
            return path
    except OSError:
        # A drive recorded on another PC may be inaccessible on this one.
        pass
    text = str(value).replace('\\', '/')
    for old, new in _mappings(root):
        if text == old or text.startswith(old + '/'):
            suffix = text[len(old):].lstrip('/')
        elif '/' + old + '/' in text:
            suffix = text.split('/' + old + '/', 1)[1]
        elif text.endswith('/' + old):
            suffix = ''
        else:
            continue
        target = root / new / suffix
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('Recorded capture path escapes the repository')
        return target
    return path


def resolve_capture_command(command: list[str], *, root: Path = REPOSITORY_ROOT) -> list[str]:
    """Translate the output path only; preserve recorded fixture arguments."""
    result = list(command)
    if result.count('--output') == 1:
        index = result.index('--output') + 1
        if index < len(result):
            result[index] = str(resolve_measurement_path(result[index], root=root))
    return result
