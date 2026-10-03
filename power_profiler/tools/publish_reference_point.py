"""Export a validated reference point without copying its local RAW/WIRE."""
import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_power_profiler.reference_runner import REFERENCE_POINTS, validate_reference_result, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    session, output = args.session.resolve(), args.output.resolve()
    root = session / 'reference_result'
    validation = validate_reference_result(root)
    if not validation['valid']:
        raise ValueError(validation['errors'])
    source = root / 'reference.json'
    report = json.loads(source.read_text(encoding='utf-8'))
    point = REFERENCE_POINTS[report['profile_id']]
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for pair in report['accepted_batch']['pairs']:
        for role, detail in pair['roles'].items():
            for kind in ('raw', 'wire'):
                evidence = detail[kind]
                files.append({**evidence, 'path': str((root / evidence['path']).relative_to(repo)),
                              'run_id': pair['run_id'], 'role': role, 'kind': kind})
    summary = {key: report[key] for key in ('profile_id', 'parameters', 'payload_bytes', 'voltage_mv', 'frequency_mhz',
        'voltage_provenance', 'physical_voltage_measured', 'measured_rail', 'ppk_mode', 'synchronization',
        'rx_scope', 'tx_scope', 'estimated_airtime_s', 'endpoints', 'usb', 'aggregates')}
    summary.update(status='complete_five_trial_numeric_batch', accepted_pairs=5, accepted_captures=10,
        acquisition_attempts=len(report['attempts']), source_session=str(session.relative_to(repo)),
        validation=validation, captured_samples_verified=sum(d['qa']['sample_count']
            for pair in report['accepted_batch']['pairs'] for d in pair['roles'].values()),
        source_report_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        serial_content_bytes=report.get('serial_content_bytes', 32),
        line_overhead_bytes=report.get('line_overhead_bytes', 0),
        coding_rate_denominator=report.get('coding_rate_denominator'),
        preamble_symbols=report.get('preamble_symbols'),
        tx_confirmation=report.get('tx_confirmation'),
        replacement_scope='Only the agreed 32-byte reference point; not other historical energy curves.',
        rf_reliability_scope='Five accepted transfers, not a statistical RF reliability estimate.')
    write_json(output / 'summary.json', summary)
    write_json(output / 'source_manifest.json', {'files': files, 'source_report': str(source.relative_to(repo)),
               'source_report_sha256': summary['source_report_sha256']})
    shutil.copyfile(source, output / 'source_report.json')
    with (output / 'aggregates.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report['aggregates'][0]))
        writer.writeheader()
        writer.writerows(report['aggregates'])
    audit = root / 'tx_window_audit.json'
    if audit.exists():
        shutil.copyfile(audit, output / 'tx_window_audit.json')
    provenance = root / 'provenance'
    source_files = []
    for name in ('reference_runner.py', 'analysis.py', 'paired_ppk.py', 'ppk.py', 'planning.py',
                 'profiles.json', 'profiles.py', 'models.py', 'results.py', 'serial_radio.py'):
        source_path = repo / 'power_profiler/radio_power_profiler' / name
        target = provenance / 'radio_power_profiler' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # An existing acquisition snapshot is never overwritten by later code.
        if not target.exists():
            shutil.copyfile(source_path, target)
        source_files.append({'path': str(target.relative_to(repo)),
                             'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    source_path = repo / 'power_profiler/tools/audit_filter_marker_totals.py'
    target = provenance / 'tools/audit_filter_marker_totals.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(source_path, target)
    source_files.append({'path': str(target.relative_to(repo)), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    write_json(output / 'acquisition_sources.json', {'source_files': source_files})
    tx, rx = report['aggregates']
    frame_note = ('Modemul transparent nu dovedește numărul cadrelor PHY interne.'
                  if point['tx_success_line'] is None else
                  'Firmware-ul SPI confirmă finalizarea transmisiei; receptorul confirmă payloadul exact.')
    display_name = (point.get('manufacturer_prefix', 'Ebyte') + ' ' + point['label']).strip()
    (output / 'README.md').write_text(f'''# {display_name} — punct de referință la 5 V

**5/5 perechi TX/RX, 10 capturi**, {len(report['attempts'])} încercare/încercări.
32 B, {point['description']}; frecvență {point['frequency_mhz']} MHz.
PPK în serie numai cu radioul, cu decodare și calcul la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul convenit la 5 V; operatorul a
confirmat conectarea după instrucțiunea de alimentare. Nu a fost măsurată independent.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, evenimentul principal detectat în curent | {tx['energy_total_uJ_mean']/1000:.6f} ± {tx['energy_total_uJ_sd']/1000:.6f} | {tx['event_duration_ms_mean']:.3f} | {tx['tx_mean_uA_mean']/1000:.6f} |
| RX, ascultare în fereastră modelată | {rx['energy_total_uJ_mean']/1000:.6f} ± {rx['energy_total_uJ_sd']/1000:.6f} | {rx['event_duration_ms_mean']:.3f} | {rx['tx_mean_uA_mean']/1000:.6f} |

TX folosește evenimentul cu cea mai mare sarcină peste curentul de repaus,
conform definiției istorice. Nu este energia întregii tranzacții UART–RF.
RX nu este energia exclusivă a recepției RF; fereastra începe la triggerul
hostului, pe ceasul propriu al PPK. Ceasurile PPK nu sunt sincronizate hardware.
SD folosește cinci repetări și numitorul n−1. În CSV, câmpul istoric
`tx_mean_uA` reprezintă curentul mediu pentru rolul indicat pe rând.

Au fost trimiși {summary['serial_content_bytes']} octeți ASCII plus
{summary['line_overhead_bytes']} octeți adăugați de firmware. Fiecare payload a
fost primit exact o dată. Confirmarea TX: {summary['tx_confirmation']}.
{frame_note}

Toate fluxurile WIRE au trecut verificarea formatului, continuitatea modulo-64
și replay-ul independent al conversiei, cu diferență de cel mult 0,000001 µA.
Modulo-64 nu poate exclude pierderi de multipli de 64 de eșantioane. Hashurile
celor 20 de fișiere RAW/WIRE au fost reverificate după lot. Controalele
intenționate de asociere rămân local. Acest punct înlocuiește doar condiția
de 32 B convenită, fără a valida alte curbe istorice sau fiabilitatea RF.

[Agregate CSV](aggregates.csv) · [Rezumat](summary.json) · [Manifest surse](source_manifest.json).
Capturile rămân locale, excluse din Git, în
`{session.relative_to(repo).as_posix()}/reference_result/`.
''', encoding='utf-8')
    print(json.dumps({'output': str(output), 'accepted_pairs': 5,
        'samples_verified': summary['captured_samples_verified'],
        'tx_energy_mJ': tx['energy_total_uJ_mean']/1000, 'rx_listening_energy_mJ': rx['energy_total_uJ_mean']/1000}))


if __name__ == '__main__':
    main()
