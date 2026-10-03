"""E07-900MM10S whole-lot diagnostic retries; 30 ASCII + CRLF = 32 RF bytes.
No energy acceptance. STOP releases held PPK ports. No hardware at import.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'power_profiler'))
from radio_power_profiler.ppk import Ppk2Sampler
from radio_power_profiler.serial_radio import SerialRadio
from radio_power_profiler.paired_ppk import capture_pair
from radio_power_profiler.results import save_raw_capture
from serial.tools import list_ports

PPK_SERIALS = {'COM10': 'E753C4E81F3D', 'COM11': 'CD2D332DB09A'}
RADIO_SERIALS = {'COM29': '08:92:72:9A:C2:8C', 'COM30': '08:92:72:9A:CC:88'}
RATE_PARAMETERS = {1.2: (5.2, 58.03), 38.4: (20.0, 101.56), 250.0: (127.0, 541.67)}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


class Hold:
    """Drain open samplers; pause this reader before capture_pair owns their I/O."""
    def __init__(self, samplers):
        self.samplers, self.stop, self.thread = samplers, threading.Event(), None
        self.stats, self.errors = {}, {}

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError('Previous PPK drain reader remains alive')
        self.stop.clear()
        for sampler in self.samplers.values():
            sampler.api.start_measuring()
            sampler.api.ser.flush()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        while not self.stop.is_set():
            for role, sampler in self.samplers.items():
                if role in self.errors:
                    continue
                try:
                    data = sampler.api.get_data()
                    if data:
                        currents, _ = sampler.api.get_samples(data)
                        if any(not math.isfinite(x) for x in currents):
                            raise ValueError('Nonfinite hold current')
                        prior = self.stats.get(role, {}).get('samples_drained', 0)
                        self.stats[role] = {'samples_drained': prior + len(currents),
                            'last_chunk_samples': len(currents), 'time': time.time(),
                            'last_chunk_mean_current_uA': sum(currents) / len(currents) if currents else None}
                except Exception as exc:
                    self.errors[role] = repr(exc)
            self.stop.wait(.005)

    def pause(self):
        self.stop.set()
        if self.thread:
            self.thread.join(3)
            if self.thread.is_alive():
                raise RuntimeError('PPK hold reader did not stop')


def parse_start_request(data):
    if len(data) > 4096:
        raise ValueError('START.json exceeds 4096 bytes')
    request = json.loads(data.decode('utf-8-sig'))
    if not isinstance(request, dict) or set(request) != {'radio_ports', 'mapping_provenance'}:
        raise ValueError('START.json requires only radio_ports and mapping_provenance')
    ports, provenance = request['radio_ports'], request['mapping_provenance']
    if not isinstance(ports, dict) or set(ports) != {'tx', 'rx'}:
        raise ValueError('START radio_ports requires exactly tx and rx')
    if any(not isinstance(port, str) for port in ports.values()) or set(ports.values()) != set(RADIO_SERIALS):
        raise ValueError('START must assign COM29 and COM30 to distinct TX/RX roles')
    if not isinstance(provenance, str) or not provenance.strip():
        raise ValueError('START requires nonempty physical mapping provenance')
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-attempts', type=int, default=20, choices=range(1, 21))
    parser.add_argument('--voltage-mv', type=int, default=3300)
    parser.add_argument('--voltage-provenance', required=True)
    parser.add_argument('--rate-kbps', type=float, choices=tuple(RATE_PARAMETERS), default=250.0)
    parser.add_argument('--drive-dbm', type=int, choices=(-30, -20, -15, -10, 0, 5, 7, 10), default=10)
    parser.add_argument('--expected-chip-version', type=lambda value: int(value, 0), default=0x14)
    args = parser.parse_args()
    if not 800 <= args.voltage_mv <= 5000 or not 0 < args.expected_chip_version < 255:
        parser.error('Invalid voltage or expected chip version')
    if not args.voltage_provenance.strip():
        parser.error('External VIN provenance is required')
    RADIOS, mapping_provenance = {}, None
    PPKS = {'tx': ('COM10', PPK_SERIALS['COM10']), 'rx': ('COM11', PPK_SERIALS['COM11'])}
    deviation, bandwidth = RATE_PARAMETERS[args.rate_kbps]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stop_file = out / 'STOP'
    start_file = out / 'START.json'
    samplers, radios, partial = {}, {}, {p: bytearray() for p in RADIOS.values()}
    hold, hold_safe, startup_complete = None, True, False
    report = {'kind': 'diagnostic_only', 'accepted_energy_points': 0, 'candidate': None,
        'argv': sys.argv, 'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'ports': {'ppk': PPKS, 'radio': RADIOS}, 'sample_rate_hz': 100000,
        'voltage_mv_for_decoder': args.voltage_mv, 'mode': 'ampere',
        'voltage_provenance': args.voltage_provenance, 'mapping_provenance': mapping_provenance,
        'settings': {'profile_id': 'RADIO_EBYTE_E07_900MM10S', 'rate_kbps': args.rate_kbps,
            'chip_drive_dbm': args.drive_dbm, 'frequency_mhz': 915.0, 'modulation': 'GFSK',
            'deviation_khz': deviation, 'bandwidth_khz': bandwidth, 'preamble_bits': 64,
            'sync_word': 'D391', 'sync_error_bits': 1, 'crc': True,
            'payload_bytes': 32, 'content_bytes': 30, 'line_overhead_bytes': 2,
            'tx_success_lines': ['[TX] 32 bytes, state: 0', '[TX] 32 bytes'],
            'expected_chip_version': args.expected_chip_version, 'pre_s': .2, 'after_trigger_s': .5,
            'minimum_tx_gap_s': 1.2, 'max_attempts': args.max_attempts},
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'commands': [], 'attempts': [], 'errors': [], 'cleanup': {}}
    state, current_attempt, last_send_ns = 'starting', None, None

    def save():
        report['partial_uart_hex'] = {p: bytes(v).hex() for p, v in partial.items()}
        write_json(out / 'report.json', report)
        write_json(out / 'status.json', {'state': state, 'time': time.time(),
            'candidate': report['candidate'], 'accepted_energy_points': 0,
            'attempt': current_attempt, 'ports': report['ports'], 'stop_file': str(stop_file),
            'start_file': str(start_file),
            'ppk_handles_open': {r: bool(s.api.ser.is_open) for r, s in samplers.items()},
            'ppk_dut_power_command': 'ON', 'hold_io_safe': hold_safe,
            'samples_currents': dict(hold.stats) if hold else {},
            'hold_errors': dict(hold.errors) if hold else {}, 'errors': report['errors']})

    def check():
        if stop_file.exists():
            raise InterruptedError('Explicit STOP file received')
        if hold and hold.errors:
            raise RuntimeError(f'PPK hold read failure: {hold.errors}')

    def collect(duration):
        result = {'lines': {p: [] for p in radios}, 'raw': []}
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            for port, radio in radios.items():
                waiting = radio.serial.in_waiting
                if waiting:
                    raw = radio.serial.read(waiting)
                    result['raw'].append({'port': port, 'perf_counter_ns': time.perf_counter_ns(), 'hex': raw.hex()})
                    partial[port].extend(raw)
                    while b'\n' in partial[port]:
                        line, _, tail = partial[port].partition(b'\n')
                        partial[port] = bytearray(tail)
                        result['lines'][port].append(bytes(line).decode('utf-8', errors='replace').rstrip('\r'))
            time.sleep(.001)
        return result

    def send(radio, text):
        data = (text + '\r\n').encode('ascii')
        if radio.serial.write(data) != len(data):
            raise OSError(f'{radio.port}: incomplete UART write')
        radio.serial.flush()

    def command(radio, text):
        check()
        record = {'port': radio.port, 'command': text, 'lines': [], 'uart': []}
        report['commands'].append(record)
        send(radio, text)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            chunk = collect(.025)
            record['uart'].append(chunk)
            record['lines'].extend(line.strip() for line in chunk['lines'][radio.port])
            if any(line.startswith('#ERROR') for line in record['lines']):
                raise RuntimeError(f'{radio.port}: {text}: {record["lines"]}')
            if 'OK' in record['lines']:
                return record['lines']
        raise TimeoutError(f'{radio.port}: {text}: {record["lines"]}')

    def verify():
        found = {}
        numeric = {'FREQ': 915.0, 'BR': args.rate_kbps, 'DEV': deviation,
            'BW': bandwidth, 'PWR': args.drive_dbm, 'PRE': 64, 'SYNCERR': 1}
        exact = {'SYNC': '0xD391', 'CRC': 'ON', 'MOD': 'GFSK', 'SHAPE': '0.5',
            'ENC': 'NRZ', 'PKT': 'VARIABLE,64', 'ADDR': 'OFF', 'PROMISC': 'OFF',
            'CS': 'OFF', 'BRIDGE': 'ON'}
        for role, port in RADIOS.items():
            radio = radios[port]
            cfg = command(radio, 'AT+CFG?')
            if not any('Module:' in line and 'E07-900MM10S' in line for line in cfg):
                raise RuntimeError(f'{port}: firmware module identity is not E07-900MM10S')
            values = {}
            for key in list(numeric) + list(exact) + ['DEBUG']:
                reply = command(radio, f'AT+{key}?')
                matches = [line.split('=', 1)[1] for line in reply if line.startswith(key + '=')]
                if len(matches) != 1:
                    raise RuntimeError(f'{port}: missing/duplicate {key} readback: {reply}')
                values[key] = matches[0]
                if key in numeric:
                    if not math.isclose(float(matches[0]), numeric[key], rel_tol=0, abs_tol=.005):
                        raise RuntimeError(f'{port}: configuration mismatch {key}: {matches[0]}')
                elif matches[0] != (('ON' if role == 'tx' else 'OFF') if key == 'DEBUG' else exact[key]):
                    raise RuntimeError(f'{port}: configuration mismatch {key}: {matches[0]}')
            lines = command(radio, 'AT+STATUS?')
            status = {}
            for line in lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    if key in status:
                        raise RuntimeError(f'{port}: duplicate status field {key}')
                    status[key] = value
            if (int(status.get('CHIP_VERSION', '-1'), 0) != args.expected_chip_version
                    or status.get('RX') != ('OFF' if role == 'tx' else 'ON')
                    or status.get('MODE') != 'GFSK' or status.get('SLEEP') != 'NO'
                    or status.get('BRIDGE') != 'ON'):
                raise RuntimeError(f'{role}: chip/status mismatch: {status}')
            found[role] = {'configuration_queries': values, 'status': status, 'configuration': cfg,
                'limitation': 'Chip version is a hardware read; RSSI/LQI are cached by the driver from its last FIFO read. RF settings and RX mode are firmware configuration/state readbacks, not a complete hardware register dump.'}
        return found

    try:
        ports = {p.device: p for p in list_ports.comports()}
        for role, (port, serial) in PPKS.items():
            p = ports.get(port)
            if p is None or p.serial_number != serial or (p.vid, p.pid) != (0x1915, 0xC00A):
                raise RuntimeError(f'Unexpected PPK identity: {port}')
            samplers[role] = Ppk2Sampler(port, voltage_mv=args.voltage_mv)
            samplers[role].start_continuous()
        hold = Hold(samplers)
        hold.start()
        startup_complete = True
        report['calibrations'] = {role: s.api.modifiers for role, s in samplers.items()}
        state = 'waiting_for_start'
        save()
        print(json.dumps({'state': state, 'start_file': str(start_file),
            'ppk_roles': PPKS, 'radio_ports_open': False}), flush=True)
        while not start_file.exists():
            check()
            save()
            time.sleep(.25)
        check()
        start_bytes = start_file.read_bytes()
        start = parse_start_request(start_bytes)
        RADIOS = start['radio_ports']
        mapping_provenance = start['mapping_provenance']
        partial = {port: bytearray() for port in RADIOS.values()}
        report['ports']['radio'] = dict(RADIOS)
        report['mapping_provenance'] = mapping_provenance
        report['staged_start'] = {'path': str(start_file), 'bytes': len(start_bytes),
            'sha256': hashlib.sha256(start_bytes).hexdigest(), 'request': start,
            'read_perf_counter_ns': time.perf_counter_ns()}
        ports = {p.device: p for p in list_ports.comports()}
        for port, serial in RADIO_SERIALS.items():
            p = ports.get(port)
            if p is None or p.serial_number != serial or (p.vid, p.pid) != (0x303A, 0x1001):
                raise RuntimeError(f'Unexpected radio identity: {port}')
        report['radio_usb_identities'] = {p: {'serial': s, 'vid': 0x303A, 'pid': 0x1001}
            for p, s in RADIO_SERIALS.items()}
        state = 'starting_radios'
        save()
        check()
        for port in RADIOS.values():
            radios[port] = SerialRadio(port, 115200, dtr=True, rts=False, open_wait_s=.3)
        setup = ['AT+RESET', 'AT+DEFAULT', 'AT+DEBUG=OFF', 'AT+BRIDGE=ON',
            'AT+CS=OFF', 'AT+FREQ=915.0', 'AT+MOD=GFSK', 'AT+PRE=64',
            'AT+SYNC=D391', 'AT+SYNCERR=1', 'AT+CRC=ON', 'AT+ENC=NRZ',
            'AT+PKT=VARIABLE,64', 'AT+ADDR=OFF', 'AT+PROMISC=OFF',
            f'AT+BR={args.rate_kbps:g}', f'AT+DEV={deviation:g}',
            f'AT+BW={bandwidth:g}', f'AT+PWR={args.drive_dbm}']
        report['setup_commands'] = setup
        for radio in radios.values():
            for text in setup:
                command(radio, text)
        command(radios[RADIOS['tx']], 'AT+DEBUG=ON')
        command(radios[RADIOS['tx']], 'AT+RX=OFF')
        command(radios[RADIOS['rx']], 'AT+DEBUG=OFF')
        command(radios[RADIOS['rx']], 'AT+RX=ON')
        for radio in radios.values():
            command(radio, 'AT+CFG?')
        token = uuid.uuid4().hex[:8]
        for number in range(1, args.max_attempts + 1):
            check()
            current_attempt = f'attempt_{number:03d}'
            directory = out / current_attempt
            directory.mkdir(exist_ok=False)
            attempt = {'attempt': number, 'status': 'running', 'completed': False, 'runs': [],
                'kind': 'diagnostic_only', 'accepted_energy_points': 0,
                'radio_ports': RADIOS, 'sample_rate_hz': report['sample_rate_hz'],
                'radio_usb_identities': report['radio_usb_identities'],
                'mapping_provenance': mapping_provenance, 'setup_commands': setup,
                'voltage_mv_for_decoder': report['voltage_mv_for_decoder'],
                'voltage_provenance': report['voltage_provenance'],
                'calibrations': report['calibrations'], 'settings': report['settings']}
            report['attempts'].append({'path': current_attempt, 'status': 'running'})
            write_json(directory / 'report.json', attempt)
            state = 'capturing'
            save()
            try:
                attempt['hardware_before'] = verify()
                for index in range(1, 6):
                    check()
                    while last_send_ns and time.perf_counter_ns() - last_send_ns < 1_200_000_000:
                        check()
                        time.sleep(.025)
                    run_id = f'run_{index:05d}'
                    payload = f'E07_{token}_{number:02d}_{index:02d}_'.ljust(30, 'X')
                    row = {'run_id': run_id, 'payload': payload,
                        'sent_rf_hex': (payload + '\r\n').encode('ascii').hex(),
                        'physical_payload_bytes': 32, 'before_uart': collect(.05)}
                    attempt['runs'].append(row)
                    transfer = {}
                    def trigger():
                        nonlocal last_send_ns
                        check()
                        now = time.perf_counter_ns()
                        transfer['send_perf_counter_ns'] = now
                        transfer['previous_tx_gap_s'] = (now - last_send_ns) / 1e9 if last_send_ns else None
                        last_send_ns = now
                        send(radios[RADIOS['tx']], payload)
                        transfer['during_uart'] = collect(.45)
                    hold.pause()
                    hold_safe = False
                    pair = capture_pair(samplers, pre_s=.2, after_trigger_s=.5,
                        trigger=trigger, wire_directory=directory / 'wire' / run_id)
                    hold_safe = not any(k in pair.errors for k in ('reader_cleanup', 'trigger_cleanup'))
                    row.update(transfer)
                    row.update(timing=pair.timing, capture_errors=pair.errors, captures={},
                        wire_paths={r: str(Path(p).relative_to(directory)) for r, p in pair.wire_paths.items()})
                    save_errors = []
                    for role, cap in pair.captures.items():
                        try:
                            path = save_raw_capture(directory / 'raw' / role / (run_id + '.csv.gz'), cap)
                            row['captures'][role] = {'raw_path': str(path.relative_to(directory)),
                                'samples': len(cap.samples_uA), 'trigger_index': cap.trigger_index,
                                'elapsed_s': cap.elapsed_s, 'expected_samples': cap.expected_samples,
                                'sample_loss_percent': cap.sample_loss_percent}
                        except Exception as exc:
                            save_errors.append(f'{role}: {exc!r}')
                    row['save_errors'] = save_errors
                    write_json(directory / 'report.json', attempt)
                    if hold_safe:
                        hold.start()
                    if pair.errors or save_errors or set(pair.captures) != {'tx', 'rx'}:
                        raise RuntimeError('Acquisition/RAW failure; evidence retained')
                    row['after_uart'] = collect(.2)
                    txlines = transfer.get('during_uart', {}).get('lines', {}).get(RADIOS['tx'], []) + row['after_uart']['lines'][RADIOS['tx']]
                    rxlines = transfer.get('during_uart', {}).get('lines', {}).get(RADIOS['rx'], []) + row['after_uart']['lines'][RADIOS['rx']]
                    row['tx_state_ok_count'] = txlines.count('[TX] 32 bytes, state: 0')
                    row['tx_bridge_ack_count'] = txlines.count('[TX] 32 bytes')
                    row['tx_ok_count'] = row['tx_state_ok_count']
                    row['tx_ok'] = row['tx_state_ok_count'] == row['tx_bridge_ack_count'] == 1
                    row['rx_exact_count'] = rxlines.count(payload)
                    row['capture_ok'] = all(cap.samples_uA and math.isfinite(cap.sample_loss_percent)
                        and cap.sample_loss_percent <= 1 for cap in pair.captures.values())
                    row['candidate'] = row['tx_ok'] and row['rx_exact_count'] == 1 and row['capture_ok']
                    write_json(directory / 'report.json', attempt)
                    save()
                    print(json.dumps({'attempt': number, 'run_id': run_id,
                        'tx_state_ok_count': row['tx_state_ok_count'],
                        'tx_bridge_ack_count': row['tx_bridge_ack_count'], 'rx_exact_count': row['rx_exact_count'],
                        'capture_ok': row['capture_ok'], 'candidate': row['candidate']}), flush=True)
                    if not row['capture_ok']:
                        raise RuntimeError('Sample loss exceeds 1 percent or empty capture')
                    if any('#ERROR' in line or '[TX] FAILED' in line or
                            (line.startswith('[TX] 32 bytes, state:') and line != '[TX] 32 bytes, state: 0')
                            for line in txlines + rxlines):
                        raise RuntimeError('Explicit radio error; RF halted')
                attempt['hardware_after'] = verify()
                attempt['completed'] = True
                attempt['status'] = 'candidate' if all(r['candidate'] for r in attempt['runs']) else 'incomplete_delivery'
            except Exception as exc:
                attempt.update(status='failed', error=repr(exc))
                raise
            finally:
                write_json(directory / 'report.json', attempt)
                report['attempts'][-1]['status'] = attempt['status']
                save()
                print(json.dumps({'attempt': number, 'status': attempt['status'],
                    'directory': str(directory), 'error': attempt.get('error')}), flush=True)
            if attempt['status'] == 'candidate':
                report['candidate'] = current_attempt
                break
        state = 'candidate_holding' if report['candidate'] else 'exhausted_holding'
    except Exception as exc:
        report['errors'].append(repr(exc))
        state = 'error_holding' if startup_complete else 'startup_failed'
    finally:
        for port, radio in radios.items():
            try:
                radio.close()
                report['cleanup'][port] = 'closed'
            except Exception as exc:
                report['cleanup'][port] = repr(exc)
                report['errors'].append(f'UART close {port}: {exc!r}')
                state = 'error_holding' if startup_complete else 'startup_failed'
        save()
    if startup_complete:
        if hold_safe and not (hold.thread and hold.thread.is_alive()):
            try:
                hold.start()
            except Exception as exc:
                report['errors'].append(f'Hold restart: {exc!r}')
                state = 'error_holding'
        while not stop_file.exists():
            if hold.errors:
                state = 'error_holding'
            save()
            time.sleep(1)
    # Only an explicit STOP or fatal startup failure reaches sampler.close.
    if hold:
        try:
            hold.pause()
        except Exception as exc:
            report['errors'].append(f'Hold stop: {exc!r}')
    for role, sampler in samplers.items():
        try:
            sampler.close(keep_power_on=True)
            report['cleanup'][role] = 'closed_keep_power_on_requested'
        except Exception as exc:
            report['errors'].append(f'PPK close {role}: {exc!r}')
    state = 'released' if stop_file.exists() else 'startup_failed'
    save()


if __name__ == '__main__':
    main()
