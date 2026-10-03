"""One RF transfer, with both PPK paths held open by the existing process."""
import json,sys,time,uuid
from pathlib import Path
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'power_profiler'))
from radio_power_profiler.serial_radio import SerialRadio
out=Path((ROOT/'.tmp/e07_active_session.txt').read_text())
report={'energy_capture':False,'commands':[],'uart_raw':[]}
assert not (out/'rf_preflight.json').exists()
def save(): (out/'rf_preflight.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
try:
    state=json.loads((ROOT/'power_profiler/web_sessions/20261002_135907_149907_nrf24_pa_paired_retries/status.json').read_text())
    assert time.time()-state['time']<5 and not state['errors'] and not state['hold_errors']
    assert state['ppk_handles_open']=={'tx':True,'rx':True}
    with ExitStack() as stack:
        radios={p:stack.enter_context(SerialRadio(p,115200,dtr=True,rts=False,open_wait_s=.3)) for p in ('COM28','COM27')}
        for port,commands in {'COM28':['AT+DEBUG=ON','AT+RX=OFF'],'COM27':['AT+DEBUG=OFF','AT+RX=ON']}.items():
            for command in commands:
                result=radios[port].command(command,drain_before=False)
                report['commands'].append({'port':port,'command':command,'lines':result.lines})
        body=('E07_PILOT_'+uuid.uuid4().hex[:8]).ljust(30,'X');wire=(body+'\r\n').encode('ascii')
        report.update(payload=body,rf_payload_bytes=len(wire),sent_hex=wire.hex())
        assert len(wire)==32
        partial={p:bytearray() for p in radios};lines={p:[] for p in radios}
        report['send_perf_counter_ns']=time.perf_counter_ns()
        assert radios['COM28'].serial.write(wire)==len(wire)
        radios['COM28'].serial.flush()
        until=time.monotonic()+1.2
        while time.monotonic()<until:
            for port,r in radios.items():
                n=r.serial.in_waiting
                if n:
                    raw=r.serial.read(n);report['uart_raw'].append({'port':port,'perf_counter_ns':time.perf_counter_ns(),'hex':raw.hex()})
                    partial[port].extend(raw)
                    while b'\n' in partial[port]:
                        line,_,rest=partial[port].partition(b'\n');partial[port]=bytearray(rest)
                        lines[port].append(bytes(line).decode('utf-8',errors='replace').rstrip('\r'))
            time.sleep(.001)
        report.update(lines=lines,partial_uart_hex={p:bytes(v).hex() for p,v in partial.items()},
            tx_ok_count=lines['COM28'].count('[TX] 32 bytes, state: 0'),rx_exact_count=lines['COM27'].count(body),completed=True)
        report['passed']=report['tx_ok_count']==1 and report['rx_exact_count']==1
        for port,r in radios.items():
            result=r.command('AT+STATUS?',drain_before=False)
            report['commands'].append({'port':port,'command':'AT+STATUS?','lines':result.lines})
except BaseException as exc:
    report['error']=repr(exc);raise
finally:
    save();print(json.dumps(report,indent=2),flush=True)
