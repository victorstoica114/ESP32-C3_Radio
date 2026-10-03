"""Short RF-only CC1101 controls while staged acquisition holds PPK power."""
import json,sys,time,uuid
from pathlib import Path
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'power_profiler'))
from radio_power_profiler.serial_radio import SerialRadio
out=Path((ROOT/'.tmp/cc1101_v2_active_session.txt').read_text().strip())
target=out/'rf_rx_rearm_controls_05.json'
assert not target.exists()
report={'energy_capture':False,'commands':[],'batches':[],'ppk_handles_released':False}
partial={p:bytearray() for p in ('COM32','COM31')}
def save():target.write_text(json.dumps(report,indent=2),encoding='utf-8')
def power():
    s=json.loads((out/'acquisition_retry/status.json').read_text())
    assert time.time()-s['time']<5 and not s['errors'] and not s['hold_errors']
    assert s['state']=='waiting_for_start' and s['ppk_handles_open']=={'tx':True,'rx':True}
    assert all(time.time()-v['time']<5 for v in s['samples_currents'].values())
    return s
def collect(radios,duration):
    ans={'lines':{p:[] for p in radios},'raw':[]};end=time.monotonic()+duration
    while time.monotonic()<end:
        for p,r in radios.items():
            n=r.serial.in_waiting
            if n:
                data=r.serial.read(n);ans['raw'].append({'port':p,'perf_counter_ns':time.perf_counter_ns(),'hex':data.hex()})
                partial[p].extend(data)
                while b'\n' in partial[p]:
                    line,_,rest=partial[p].partition(b'\n');partial[p]=bytearray(rest)
                    ans['lines'][p].append(bytes(line).decode('utf-8',errors='replace').rstrip('\r'))
        time.sleep(.001)
    return ans
def command(radios,p,text):
    data=(text+'\r\n').encode();r=radios[p]
    assert r.serial.write(data)==len(data);r.serial.flush()
    row={'port':p,'command':text,'lines':[],'uart':[]};report['commands'].append(row)
    end=time.monotonic()+4
    while time.monotonic()<end:
        c=collect(radios,.025);row['uart'].append(c);row['lines'].extend(c['lines'][p])
        if any('#ERROR' in line for line in row['lines']):raise RuntimeError(row)
        if 'OK' in row['lines']:save();return row['lines']
    raise TimeoutError(row)
def setup(radios,rate,pwr,tx,rx,mod='2FSK'):
    dev,bw={250:(127,541.67),38.4:(20,101.56),1.2:(5.2,58.03)}[rate]
    for p,cmds in {tx:['AT+DEBUG=ON','AT+RX=OFF'],rx:['AT+DEBUG=OFF','AT+RX=ON']}.items():
        for c in cmds:command(radios,p,c)
    return {p:{q:command(radios,p,'AT+'+q+'?') for q in
        ('FREQ','BR','DEV','BW','PWR','PRE','MOD','SHAPE','ENC','SYNC','SYNCERR','CRC','STATUS')}
        for p in radios}
try:
    report['power_before']=power()
    with ExitStack() as stack:
        radios={p:stack.enter_context(SerialRadio(p,115200,dtr=True,rts=False,open_wait_s=.3)) for p in partial}
        cases=[('rx_on_each',10,'VARIABLE,64'),('rx_on_each_low_power',-30,'VARIABLE,64'),
               ('packet_reconfigure_each',10,'VARIABLE,64'),('fixed_length_diagnostic',10,'FIXED,32'),
               ('variable_restored',10,'VARIABLE,64')]
        tx,rx='COM32','COM31'
        for label,pwr,packet in cases:
            b={'control':label,'rate_kbps':250,'power_dbm':pwr,'tx':tx,'rx':rx,'modulation':'2FSK','packet':packet,'power':power(),'runs':[]}
            report['batches'].append(b)
            for p in radios:
                command(radios,p,f'AT+PWR={pwr}')
                command(radios,p,'AT+PKT='+packet)
            b['configuration']=setup(radios,250,pwr,tx,rx);b['before']=collect(radios,.3)
            for i in range(5):
                if label=='packet_reconfigure_each':
                    command(radios,rx,'AT+RX=OFF')
                    command(radios,rx,'AT+PKT=VARIABLE,64')
                if label!='variable_restored':command(radios,rx,'AT+RX=ON')
                body=('CC2_'+uuid.uuid4().hex[:16]).ljust(30,'X');data=(body+'\r\n').encode()
                row={'payload':body,'send_perf_counter_ns':time.perf_counter_ns()}
                assert radios[tx].serial.write(data)==32;radios[tx].serial.flush()
                row['uart']=collect(radios,1.2)
                row['tx_ok_count']=row['uart']['lines'][tx].count('[TX] 32 bytes, state: 0')
                row['rx_exact_count']=row['uart']['lines'][rx].count(body)
                b['runs'].append(row);save()
                print(json.dumps({'control':label,'power':pwr,'tx':tx,'trial':i+1,'tx_ok':row['tx_ok_count'],'rx':row['rx_exact_count'],'lines':row['uart']['lines']}),flush=True)
            b['status_after']={p:command(radios,p,'AT+STATUS?') for p in radios};save()
        report['restore_target']=setup(radios,250,10,'COM32','COM31');report['completed']=True
except BaseException as exc:
    report['error']=repr(exc);raise
finally:
    report['partial_uart_hex']={p:bytes(v).hex() for p,v in partial.items()};save()



