"""Small E07 RF controls under continuously held PPK power; no energy points."""
import json,sys,time,uuid
from pathlib import Path
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'power_profiler'))
from radio_power_profiler.serial_radio import SerialRadio
from radio_power_profiler.profiles import load_profile
out=Path((ROOT/'.tmp/e07_active_session.txt').read_text());target=out/'rf_controls.json'
assert not target.exists()
report={'energy_capture':False,'commands':[],'batches':[],'ppk_handles_released':False}
partial={p:bytearray() for p in ('COM28','COM27')}
def save(): target.write_text(json.dumps(report,indent=2),encoding='utf-8')
def collect(radios,duration):
    answer={'lines':{p:[] for p in radios},'raw':[]};deadline=time.monotonic()+duration
    while time.monotonic()<deadline:
        for port,r in radios.items():
            n=r.serial.in_waiting
            if n:
                data=r.serial.read(n);answer['raw'].append({'port':port,'perf_counter_ns':time.perf_counter_ns(),'hex':data.hex()})
                partial[port].extend(data)
                while b'\n' in partial[port]:
                    line,_,rest=partial[port].partition(b'\n');partial[port]=bytearray(rest)
                    answer['lines'][port].append(bytes(line).decode('utf-8',errors='replace').rstrip('\r'))
        time.sleep(.001)
    return answer
def command(radios,port,text):
    data=(text+'\r\n').encode('ascii');r=radios[port]
    assert r.serial.write(data)==len(data);r.serial.flush()
    row={'port':port,'command':text,'lines':[],'uart':[]};report['commands'].append(row)
    end=time.monotonic()+4
    while time.monotonic()<end:
        chunk=collect(radios,.025);row['uart'].append(chunk);row['lines'].extend(chunk['lines'][port])
        if any('#ERROR' in line for line in row['lines']):raise RuntimeError(row)
        if 'OK' in row['lines']:save();return row['lines']
    raise TimeoutError(row)
def configure(radios,rate,power):
    dev,bw={250:(127,541.67),38.4:(20,101.56),1.2:(5.2,58.03)}[rate]
    for port in radios:
        for c in [f'AT+BR={rate}',f'AT+DEV={dev}',f'AT+BW={bw}',f'AT+PWR={power}']:
            command(radios,port,c)
    for port,commands in {'COM28':['AT+DEBUG=ON','AT+RX=OFF'],'COM27':['AT+DEBUG=OFF','AT+RX=ON']}.items():
        for c in commands: command(radios,port,c)
    return collect(radios,.3)
try:
    holder=ROOT/'power_profiler/web_sessions/20261002_135907_149907_nrf24_pa_paired_retries/status.json'
    s=json.loads(holder.read_text());assert time.time()-s['time']<5 and not s['errors'] and not s['hold_errors']
    assert s['ppk_handles_open']=={'tx':True,'rx':True}
    report['power_before']=s
    with ExitStack() as stack:
        radios={p:stack.enter_context(SerialRadio(p,115200,dtr=True,rts=False,open_wait_s=.3)) for p in partial}
        for port in radios:
            for c in load_profile('RADIO_EBYTE_E07_400M10S').setup_commands:command(radios,port,c)
        for rate,power in [(250,10),(250,-30),(38.4,10),(1.2,-30)]:
            b={'rate_kbps':rate,'power_dbm':power,'before':configure(radios,rate,power),'runs':[]};report['batches'].append(b)
            for i in range(2):
                body=('E07_'+uuid.uuid4().hex[:16]).ljust(30,'X');data=(body+'\r\n').encode('ascii')
                r={'payload':body,'send_perf_counter_ns':time.perf_counter_ns()}
                assert radios['COM28'].serial.write(data)==32;radios['COM28'].serial.flush()
                r['uart']=collect(radios,1.2)
                r['tx_ok_count']=r['uart']['lines']['COM28'].count('[TX] 32 bytes, state: 0')
                r['rx_exact_count']=r['uart']['lines']['COM27'].count(body)
                b['runs'].append(r);save()
                print(json.dumps({'rate':rate,'power':power,'trial':i+1,'tx_ok':r['tx_ok_count'],'rx':r['rx_exact_count'],'lines':r['uart']['lines']}),flush=True)
            b['status_after']={p:command(radios,p,'AT+STATUS?') for p in radios};save()
        report['restore_target']=configure(radios,250,10)
        report['final_config']={p:command(radios,p,'AT+CFG?') for p in radios}
        report['completed']=True
except BaseException as exc:
    report['error']=repr(exc);raise
finally:
    report['partial_uart_hex']={p:bytes(v).hex() for p,v in partial.items()};save()
