"""Identify E07-900MM10S and map radio rails while staged worker owns PPKs."""
import json,sys,time
from contextlib import ExitStack
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'power_profiler'))
from radio_power_profiler.serial_radio import SerialRadio
from serial.tools import list_ports
out=Path((ROOT/'.tmp/e07_900_active_session.txt').read_text().strip())
holder=out/'acquisition/status.json'
assert not (out/'preparation.json').exists()
report={'kind':'configuration_and_current_mapping','commands':[],'power_snapshots':[],
    'voltage_mv':3300,'voltage_provenance':'External 3.3 V confirmed earlier by operator; no supply change reported',
    'ppk_owner':'E07-900 staged acquisition worker; both PPK handles remain open during preparation and acquisition'}
def save(): (out/'preparation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
def state(label):
    s=json.loads(holder.read_text())
    assert s['state']=='waiting_for_start',s['state']
    assert s['ppk_handles_open']=={'tx':True,'rx':True} and not s['errors'] and not s['hold_errors']
    assert time.time()-s['time']<5
    assert all(time.time()-v['time']<5 for v in s['samples_currents'].values())
    report['power_snapshots'].append({'label':label,'state':s});save();return s
def command(r,text):
    a=r.command(text,timeout_s=4,drain_before=False)
    row={'port':r.port,'command':text,'lines':a.lines};report['commands'].append(row);save()
    print(json.dumps(row),flush=True);return a.lines
try:
    state('initial_power_hold')
    ports={p.device:p for p in list_ports.comports()}
    expected={'COM29':'08:92:72:9A:C2:8C','COM30':'08:92:72:9A:CC:88'}
    for port,serial in expected.items():assert ports[port].serial_number==serial and (ports[port].vid,ports[port].pid)==(0x303A,0x1001)
    report['radio_usb_identities']=expected
    with ExitStack() as stack:
        radios={p:stack.enter_context(SerialRadio(p,115200,dtr=True,rts=False,open_wait_s=.3)) for p in expected}
        for port,r in radios.items():
            cfg=command(r,'AT+CFG?');assert any('E07-900MM10S' in line for line in cfg),(port,cfg)
            command(r,'AT+DEFAULT')
            status=command(r,'AT+STATUS?');assert 'CHIP_VERSION=0x14' in status,(port,status)
        for r in radios.values():command(r,'AT+RX=OFF')
        time.sleep(1.3);baseline=state('both_rx_off')
        mapping={}
        for port,r in radios.items():
            command(r,'AT+RX=ON');time.sleep(1.3);s=state(f'{port}_rx_on_other_off')
            delta={role:s['samples_currents'][role]['last_chunk_mean_current_uA']-baseline['samples_currents'][role]['last_chunk_mean_current_uA'] for role in ('tx','rx')}
            role=max(delta,key=delta.get);other='rx' if role=='tx' else 'tx'
            assert delta[role]>8000 and abs(delta[other])<2000,(port,delta)
            assert role not in mapping,(mapping,port,delta)
            mapping[role]=port
            report.setdefault('mapping_deltas_uA',{})[port]=delta
            command(r,'AT+RX=OFF');time.sleep(.4)
        for r in radios.values():command(r,'AT+RX=ON')
        time.sleep(1.3);state('both_rx_on_at_end')
        assert set(mapping)=={'tx','rx'}
        report.update(completed=True,radio_ports=mapping,ppk_ports={'tx':'COM10','rx':'COM11'})
except BaseException as exc:
    report['error']=repr(exc);raise
finally:
    save();print('Saved '+str(out/'preparation.json'),flush=True)
