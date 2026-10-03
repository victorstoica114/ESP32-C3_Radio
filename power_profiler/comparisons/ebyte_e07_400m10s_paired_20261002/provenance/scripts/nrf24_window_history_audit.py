"""Bound unknown initial decoder history for already selected software windows."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'power_profiler'))
from tools.audit_filter_marker_totals import read_capture, normalize, evidence
from radio_power_profiler.filter_marker_totals import _COEFFICIENTS, _global_bounds, _replay, _total_interval, _upper_difference

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audit',required=True,type=Path)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
if args.output.exists():raise FileExistsError(args.output)
audit=json.loads(args.audit.read_text(encoding='utf-8'))
if audit.get('valid_complete_five_trial_numeric_batch') is not True or audit.get('errors') != []:
    raise ValueError('A valid independently audited five-transfer batch is required')
source_path=Path(audit['source']['path'])
source_bytes=source_path.read_bytes()
source_sha256=hashlib.sha256(source_bytes).hexdigest()
if source_sha256!=audit['source']['sha256']:
    raise ValueError('Source metadata changed since prerequisite audit')
source=json.loads(source_bytes)
source_evidence={'path':str(source_path.resolve()),'bytes':len(source_bytes),'sha256':source_sha256}
imported_modules=[evidence(Path(sys.modules[name].__file__).resolve()) for name in (
    read_capture.__module__,_replay.__module__)]
report={'audit':evidence(args.audit),'source':source_evidence,'helper':evidence(Path(__file__)),
        'imported_modules':imported_modules,
        'method':'Conservative initial-history enclosure in fixed, already selected software windows',
        'unknown_state_seed_sample':0,'unknown_seed_is_recorded_counter_fault':False,
        'energy_history_relative_tolerance':1e-4,'captures':[],
        'scope':'Clipped-current total integrated with fsum. Legacy ordinary-sum total is retained separately, with its rounding difference.',
        'limitations':['Does not validate physical packet boundaries, analog accuracy, or TX threshold-window invariance under alternate filter histories.',
                       'No D0 marker is asserted or synthesized. RX remains a conventional listening interval.',
                       'All prior filter states are assumed bounded by the calibrated ADC-domain invariant.'],
        'accepted_energy_points_changed':False}
for cap in audit['captures']:
    if cap.get('errors')!=[]:raise ValueError('Invalid capture in prerequisite audit')
    for field in ('counter_transition_fault_indices','bit17_indices','invalid_range_indices'):
        if cap.get(field)!=[]:
            raise ValueError(f'Prerequisite capture must have an explicit empty {field}')
    raw,wire=cap['raw']['path'],cap['wire']['path']
    if evidence(raw)['sha256']!=cap['raw']['sha256'] or evidence(wire)['sha256']!=cap['wire']['sha256']:
        raise ValueError('Capture changed since prerequisite audit')
    words,currents,logic,trigger=read_capture(raw,wire)
    if len(cap['window_samples'])!=1:raise ValueError('Expected one selected software window')
    start,stop=cap['window_samples'][0]
    normalized,voltage=normalize(source['calibrations'][cap['role']],source['voltage_mv_for_decoder'])
    coefficients=tuple(tuple(normalized[name][str(i)] for i in range(5)) for name in _COEFFICIENTS)
    adc_min,adc_max,low,high,expansions=_global_bounds(coefficients,voltage)
    nominal,intervals,converged=_replay(words,coefficients,voltage,{0},(start,stop),(low,high))
    if len(nominal)!=len(currents) or max(abs(a-b) for a,b in zip(nominal,currents))>1e-6:
        raise ValueError('Full replay does not match archived currents')
    if len(intervals)!=stop-start or any(not a<=v<=b for (a,b),v in zip(intervals,nominal[start:stop])):
        raise ValueError('Nominal values escape initial-history enclosure')
    clipped=[(max(0.,a),max(0.,b)) for a,b in intervals]
    charge_interval,energy_interval=_total_interval(clipped,100000,voltage)
    reference=math.fsum(max(0.,v) for v in nominal[start:stop])/100000*voltage
    width=_upper_difference(energy_interval[1],energy_interval[0])
    if not 0<energy_interval[0]<=reference<=energy_interval[1]:
        raise ValueError('Unsafe or inconsistent energy enclosure')
    relative=math.nextafter(width/energy_interval[0],math.inf) if width else 0.
    report['captures'].append({'run_id':cap['run_id'],'role':cap['role'],'window_samples':[start,stop],
        'raw_sha256':cap['raw']['sha256'],'wire_sha256':cap['wire']['sha256'],
        'global_adc_bounds_A':[adc_min,adc_max],'initial_state_invariant_A':[low,high],
        'converged_samples':converged,'max_current_interval_width_uA':max(_upper_difference(b,a) for a,b in intervals),
        'charge_interval_uC':charge_interval,'energy_interval_uJ':energy_interval,
        'energy_interval_width_uJ':width,'energy_history_relative_bound':relative,
        'fsum_reference_energy_uJ':reference,'legacy_energy_uJ':cap['independent_legacy_energy_uJ'],
        'legacy_ordinary_sum_minus_fsum_uJ':cap['independent_legacy_energy_uJ']-reference,
        'history_budget_passed':relative<=1e-4})
report['all_history_budgets_passed']=len(report['captures'])==10 and all(c['history_budget_passed'] for c in report['captures'])
report['max_energy_history_relative_bound']=max(c['energy_history_relative_bound'] for c in report['captures'])
args.output.parent.mkdir(parents=True,exist_ok=True)
with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,allow_nan=False)
print(json.dumps({'all_history_budgets_passed':report['all_history_budgets_passed'],'max_energy_history_relative_bound':report['max_energy_history_relative_bound']}))
raise SystemExit(0 if report['all_history_budgets_passed'] else 1)
