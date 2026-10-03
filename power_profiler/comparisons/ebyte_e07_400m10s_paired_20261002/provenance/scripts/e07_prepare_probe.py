"""Probe connected E07 radios while the existing persistent PPK holder stays open."""
import json
import sys
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'power_profiler'))
from radio_power_profiler.serial_radio import SerialRadio
from serial.tools import list_ports

out=ROOT/'power_profiler/web_sessions'/f'{datetime.now():%Y%m%d_%H%M%S_%f}_e07_400m10s_paired'
out.mkdir(exist_ok=False)
(ROOT/'.tmp/e07_active_session.txt').write_text(str(out),encoding='utf-8')
holder=ROOT/'power_profiler/web_sessions/20261002_135907_149907_nrf24_pa_paired_retries/status.json'
report={'kind':'configuration_and_current_mapping','commands':[],'power_snapshots':[],
    'voltage_mv':3300,'voltage_provenance':'External 3.3 V confirmed earlier by operator; no supply change reported',
    'ppk_owner':'Existing nRF acquisition worker holding both PPK open; no PPK release during this probe'}
def save():
    (out/'preparation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
def state(label):
    s=json.loads(holder.read_text())
    assert s['ppk_handles_open']=={'tx':True,'rx':True} and not s['errors'] and not s['hold_errors']
    assert time.time()-s['time']<5
    assert all(time.time()-v['time']<5 for v in s['samples_currents'].values())
    report['power_snapshots'].append({'label':label,'state':s})
    save()
    return s
def command(radio,text):
    response=radio.command(text,timeout_s=4,drain_before=False)
    report['commands'].append({'port':radio.port,'command':text,'lines':response.lines})
    save()
    print(json.dumps(report['commands'][-1]),flush=True)
    return response.lines
try:
    state('initial_both_powered')
    inventory={p.device:p for p in list_ports.comports()}
    expected={'COM27':'08:92:72:9A:C1:1C','COM28':'08:92:72:9A:C1:98'}
    for port,serial in expected.items():
        p=inventory[port]
        assert p.serial_number==serial and (p.vid,p.pid)==(0x303A,0x1001)
    report['radio_usb_identities']=expected
    with ExitStack() as stack:
        radios={p:stack.enter_context(SerialRadio(p,115200,dtr=True,rts=False,open_wait_s=.3)) for p in expected}
        for port,r in radios.items():
            cfg=command(r,'AT+CFG?')
            assert any('E07-400M10S' in line for line in cfg), (port,cfg)
            command(r,'AT+STATUS?')
        for r in radios.values(): command(r,'AT+RX=OFF')
        time.sleep(1.3);state('both_rx_off')
        for port,r in radios.items():
            command(r,'AT+RX=ON');time.sleep(1.3);state(f'{port}_rx_on_other_off')
            command(r,'AT+RX=OFF');time.sleep(.4)
        for r in radios.values(): command(r,'AT+RX=ON')
        time.sleep(1.3);state('both_rx_on_at_end')
        report['completed']=True
except BaseException as exc:
    report['error']=repr(exc)
    raise
finally:
    save()
    print('Saved '+str(out/'preparation.json'),flush=True)
