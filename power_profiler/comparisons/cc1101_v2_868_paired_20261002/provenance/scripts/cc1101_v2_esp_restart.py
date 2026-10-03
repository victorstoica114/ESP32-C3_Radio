"""Restart ESP32 applications using installed Espressif HardReset USB sequence; no flash."""
import hashlib,json,time
from pathlib import Path
import serial
from serial.tools import list_ports
ROOT=Path(__file__).resolve().parents[1]
session=Path((ROOT/'.tmp/cc1101_v2_active_session.txt').read_text().strip())
target=session/'esp_restart_04.json'
assert not target.exists()
source=Path('C:/Users/User/.platformio/packages/tool-esptoolpy/esptool/reset.py')
report={'method':'Espressif HardReset(uses_usb=True) equivalent, DTR false during reset; no bootloader commands or flash writes',
        'reference':str(source),'reference_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'radios':[]}
def save():target.write_text(json.dumps(report,indent=2),encoding='utf-8')
def collect(s,duration):
    chunks=[];end=time.monotonic()+duration
    while time.monotonic()<end:
        n=s.in_waiting
        if n:chunks.append({'time_ns':time.perf_counter_ns(),'hex':s.read(n).hex()})
        time.sleep(.001)
    return chunks
def text(chunks):return b''.join(bytes.fromhex(c['hex']) for c in chunks).decode(errors='replace')
try:
    ppk=json.loads((session/'acquisition_retry/status.json').read_text())
    assert ppk['state']=='waiting_for_start' and time.time()-ppk['time']<5 and not ppk['errors'] and not ppk['hold_errors']
    assert ppk['ppk_handles_open']=={'tx':True,'rx':True}
    report['power_before']=ppk
    devices={p.device:p for p in list_ports.comports()}
    for port,sn in {'COM31':'08:92:72:9A:D4:B4','COM32':'08:92:72:9A:C8:C8'}.items():
        assert devices[port].serial_number==sn and (devices[port].vid,devices[port].pid)==(0x303A,0x1001)
        row={'port':port,'serial':sn};report['radios'].append(row)
        s=serial.Serial();s.port=port;s.baudrate=115200;s.timeout=.03;s.write_timeout=5;s.dtr=False;s.rts=False
        try:
            s.open();row['before']=collect(s,.2)
            s.rts=True;s.dtr=False;time.sleep(.2)
            s.rts=False;s.dtr=False;time.sleep(.2)
            s.dtr=True
            row['boot_uart']=collect(s,5);row['boot_text']=text(row['boot_uart'])
            row['boot_banner_seen']='ESP-ROM:' in row['boot_text'] or '[EEPROM]' in row['boot_text'] or '[RADIO] Initializing' in row['boot_text']
            assert s.write(b'AT\r\n')==4;s.flush()
            row['at_uart']=collect(s,1);row['at_text']=text(row['at_uart'])
            row['at_ok']='OK' in row['at_text'].splitlines()
            save();print(json.dumps({'port':port,'boot_banner_seen':row['boot_banner_seen'],'at_ok':row['at_ok'],'boot_text':row['boot_text']}),flush=True)
            if not row['at_ok']:raise RuntimeError(f'{port} did not acknowledge AT after reset')
        finally:
            s.close()
    report['completed']=True
finally:save()
