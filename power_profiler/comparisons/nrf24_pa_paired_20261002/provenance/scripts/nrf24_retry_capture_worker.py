"""Diagnostic whole-lot retries. No energy acceptance; STOP releases held PPK ports."""
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

PPKS = {'tx': ('COM10', 'E753C4E81F3D'), 'rx': ('COM11', 'CD2D332DB09A')}
RADIOS = {'tx': 'COM25', 'rx': 'COM26'}
RADIO_SERIALS = {'COM25': '08:92:72:9A:C2:80', 'COM26': '08:92:72:9A:BF:58'}


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-attempts', type=int, default=20, choices=range(1, 21))
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stop_file = out / 'STOP'
    samplers, radios, partial = {}, {}, {p: bytearray() for p in RADIOS.values()}
    hold, hold_safe, startup_complete = None, True, False
    report = {'kind': 'diagnostic_only', 'accepted_energy_points': 0, 'candidate': None,
        'argv': sys.argv, 'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'ports': {'ppk': PPKS, 'radio': RADIOS}, 'sample_rate_hz': 100000,
        'voltage_mv_for_decoder': 3300, 'mode': 'ampere',
        'voltage_provenance': 'Operator confirmed external 3.3 V',
        'settings': {'rate_kbps': 2000, 'chip_drive_dbm': 0, 'channel': 80,
            'payload_bytes': 32, 'auto_ack': False, 'pre_s': .2, 'after_trigger_s': .5,
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
        for role, port in RADIOS.items():
            lines = command(radios[port], 'AT+STATUS?')
            values = {key: int(value, 0) for line in lines if '=' in line
                for key, value in [line.split('=', 1)]
                if key in ('RF_CH', 'RF_SETUP', 'EN_AA', 'FEATURE', 'DYNPD')}
            if values != {'RF_CH': 80, 'RF_SETUP': 15, 'EN_AA': 0, 'FEATURE': 4, 'DYNPD': 63}:
                raise RuntimeError(f'{role}: hardware register mismatch: {values}')
            found[role] = values
        return found

    try:
        ports = {p.device: p for p in list_ports.comports()}
        for port, serial in RADIO_SERIALS.items():
            p = ports.get(port)
            if p is None or p.serial_number != serial or (p.vid, p.pid) != (0x303A, 0x1001):
                raise RuntimeError(f'Unexpected radio identity: {port}')
        report['radio_usb_identities'] = {p: {'serial': s, 'vid': 0x303A, 'pid': 0x1001}
            for p, s in RADIO_SERIALS.items()}
        for role, (port, serial) in PPKS.items():
            p = ports.get(port)
            if p is None or p.serial_number != serial or (p.vid, p.pid) != (0x1915, 0xC00A):
                raise RuntimeError(f'Unexpected PPK identity: {port}')
            samplers[role] = Ppk2Sampler(port, voltage_mv=3300)
            samplers[role].start_continuous()
        hold = Hold(samplers)
        hold.start()
        startup_complete = True
        report['calibrations'] = {role: s.api.modifiers for role, s in samplers.items()}
        save()
        time.sleep(2)
        for port in RADIOS.values():
            radios[port] = SerialRadio(port, 9600, dtr=True, rts=False, open_wait_s=.3)
        setup = ['AT+RESET', 'AT+RX=OFF', 'AT+CHAN=80', 'AT+ADDRWIDTH=5',
            'AT+ADDR=0123456789', 'AT+PIPE0=ON'] + [f'AT+PIPE{i}=OFF' for i in range(1, 6)] + [
            'AT+CRC=ON', 'AT+DYN=ON', 'AT+AUTOACK=OFF', 'AT+ACKPAY=OFF',
            'AT+LNA=ON', 'AT+RATE=2000', 'AT+PWR=0']
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
                    payload = f'NRF_{token}_{number:02d}_{index:02d}_'.ljust(32, 'X')
                    row = {'run_id': run_id, 'payload': payload, 'before_uart': collect(.05)}
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
                    row['tx_ok_count'] = txlines.count('[nRF24] TX OK')
                    row['tx_ok'] = row['tx_ok_count'] == 1
                    row['rx_exact_count'] = rxlines.count(payload)
                    row['capture_ok'] = all(cap.samples_uA and math.isfinite(cap.sample_loss_percent)
                        and cap.sample_loss_percent <= 1 for cap in pair.captures.values())
                    row['candidate'] = row['tx_ok_count'] == 1 and row['rx_exact_count'] == 1 and row['capture_ok']
                    write_json(directory / 'report.json', attempt)
                    save()
                    print(json.dumps({'attempt': number, 'run_id': run_id,
                        'tx_ok_count': row['tx_ok_count'], 'rx_exact_count': row['rx_exact_count'],
                        'capture_ok': row['capture_ok'], 'candidate': row['candidate']}), flush=True)
                    if not row['capture_ok']:
                        raise RuntimeError('Sample loss exceeds 1 percent or empty capture')
                    if any('#ERROR' in line or 'TX failed' in line for line in txlines + rxlines):
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
