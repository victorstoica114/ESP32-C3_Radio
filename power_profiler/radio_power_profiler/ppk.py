from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable


SAMPLE_RATE_HZ = 100_000


@dataclass(frozen=True)
class Capture:
    samples_uA: list[float]
    logic_bits: list[int]
    trigger_index: int
    elapsed_s: float
    expected_samples: int

    @property
    def sample_loss_percent(self) -> float:
        if self.expected_samples <= 0:
            return 0.0
        missing = max(0, self.expected_samples - len(self.samples_uA))
        return 100.0 * missing / self.expected_samples


class Ppk2Sampler:
    def __init__(self, port: str, *, voltage_mv: int):
        if not 800 <= voltage_mv <= 5000:
            raise ValueError("PPK2 voltage must be between 800 and 5000 mV")

        from ppk2_api.ppk2_api import PPK2_API

        self.mode = "ampere"
        self.voltage_mv = voltage_mv
        self._continuous_hold = False
        self.api = PPK2_API(port, timeout=0)
        try:
            self._stop_and_drain()
            self._read_modifiers_with_retry()
            self.api.use_ampere_meter()
        except BaseException as exc:
            # A failed constructor has no caller-owned sampler to close it.
            # Release its serial handle without changing the DUT power state.
            try:
                self.api.ser.close()
            except Exception as close_exc:
                if hasattr(exc, "add_note"):
                    exc.add_note(f"PPK2 initialization cleanup: {type(close_exc).__name__}: {close_exc}")
            raise
        # The third-party API uses this value for voltage-dependent calibration.
        # Ampere mode does not expose a public setter, so set its internal state.
        self.api.current_vdd = voltage_mv
        # Do not change DEVICE_RUNNING_SET during initialization. The PPK2 sits
        # in the DUT supply path, so an implicit OFF here would brown out the
        # measured module every time a new batch opens the measurement port.

    def _stop_and_drain(self) -> None:
        """Stop a stale capture and discard binary samples before metadata."""
        self.api.stop_measuring()
        time.sleep(0.05)
        quiet_deadline = time.monotonic() + 0.10
        while time.monotonic() < quiet_deadline:
            data = self.api.ser.read_all()
            if data:
                quiet_deadline = time.monotonic() + 0.05
            else:
                time.sleep(0.005)

    def _read_modifiers_with_retry(self) -> None:
        # ppk2-api discards metadata fragments before the chunk containing
        # END and can silently retain default coefficients. Read a complete
        # response and validate every coefficient before replacing modifiers.
        last_error: Exception | None = None
        for _attempt in range(3):
            # A transport write/flush failure must propagate; only an
            # incomplete or invalid metadata response is retried below.
            if self.api.ser.write(b"\x19") != 1:  # GET_META_DATA
                raise OSError("Incomplete PPK2 metadata command write")
            self.api.ser.flush()
            try:
                raw = bytearray()
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    waiting = self.api.ser.in_waiting
                    if waiting:
                        raw.extend(self.api.ser.read(waiting))
                        if len(raw) > 16_384:
                            raise ValueError("Oversized PPK2 calibration response")
                        if any(line.strip() == b"END" for line in raw.splitlines()):
                            break
                    else:
                        time.sleep(0.005)
                else:
                    raise TimeoutError("Incomplete PPK2 calibration response: END missing")
                self.api.modifiers = self._parse_calibration_metadata(raw.decode("ascii"))
                return
            except (UnicodeDecodeError, ValueError, TimeoutError) as exc:
                last_error = exc
                self._stop_and_drain()
        raise RuntimeError("Could not read PPK2 calibration metadata cleanly") from last_error

    @staticmethod
    def _parse_calibration_metadata(metadata: str) -> dict:
        if not any(line.strip() == "END" for line in metadata.splitlines()):
            raise ValueError("PPK2 calibration response has no END marker")
        fields = {}
        for line in metadata.splitlines():
            line = line.strip()
            if line == "END":
                break
            if not line:
                continue
            key, separator, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if not separator or not value or key in fields:
                raise ValueError("Malformed or duplicate PPK2 calibration field")
            fields[key] = value
        result = {}
        for key in ("Calibrated", "HW", "IA"):
            if not fields.get(key):
                raise ValueError(f"Missing PPK2 calibration field: {key}")
            result[key] = fields[key]
        for key in ("R", "O", "GS", "GI", "S", "I", "UG"):
            result[key] = {}
            for index in range(5):
                field = f"{key}{index}"
                if field not in fields:
                    raise ValueError(f"Missing PPK2 calibration coefficient: {field}")
                value = float(fields[field])
                if not math.isfinite(value) or (key == "R" and value <= 0):
                    raise ValueError(f"Invalid PPK2 calibration coefficient: {field}")
                result[key][str(index)] = value
        return result

    @staticmethod
    def list_devices() -> list[tuple[str, str]]:
        from ppk2_api.ppk2_api import PPK2_API
        from serial.tools import list_ports

        devices: dict[str, str] = {}

        def port_key(port: str) -> str:
            # COM names are case-insensitive; Unix device paths are not.
            return port.upper() if port[:3].upper() == "COM" and port[3:].isdigit() else port

        def is_shell_port(port) -> bool:
            # PPK2 can expose a shell on USB interface 3; measurements
            # remain on interface 1. Never infer this from the COM number.
            interface = str(getattr(port, "interface", None) or "").strip()
            hwid = str(getattr(port, "hwid", None) or "")
            if (interface.lower() in {"3", "03", "0x03"}
                    or re.search(r"\bshell\b", interface, re.IGNORECASE)
                    or re.search(r"(?:^|[^a-z0-9])MI_03(?:$|[^a-z0-9])",
                                 interface + " " + hwid, re.IGNORECASE)):
                return True
            # pyserial Windows commonly reports interface only in location
            # (e.g. 1-3:x.3); Linux uses 1-3:1.3. A bare 1-3 is USB port 3,
            # not interface 3. Unknown interfaces remain legacy-compatible.
            location = str(getattr(port, "location", None) or "")
            if not location:
                match = re.search(r"(?:^|\s)LOCATION=(\S+)", hwid, re.IGNORECASE)
                location = match.group(1) if match else ""
            return bool(re.search(r":[^.:\s]+\.0?3$", location))

        ports = list(list_ports.comports())
        shell_ports = {port_key(port.device) for port in ports if is_shell_port(port)}

        def remember(port: str, serial_number: str | None) -> None:
            port = port_key(port)
            if port in shell_ports:
                return
            serial_number = str(serial_number) if serial_number is not None else ""
            if port not in devices or not devices[port]:
                devices[port] = serial_number

        for item in PPK2_API.list_devices():
            # ppk2-api returns port-name strings. Newer unreleased code
            # returns (port, serial-number) tuples, so normalize both forms.
            if isinstance(item, str):
                remember(item, "")
            else:
                remember(str(item[0]), item[1])
        # Windows can call the CDC interface "USB Serial Device", which the
        # API's description-based discovery misses. Enumerating VID/PID does
        # not open the port and must not include other Nordic USB products.
        for port in ports:
            if (port.vid, port.pid) == (0x1915, 0xC00A):
                remember(port.device, port.serial_number)
        return list(devices.items())

    def power_on(self) -> None:
        self.api.toggle_DUT_power("ON")
        # The API command is write-only. Flush it before releasing COM11 so the
        # final VIN -> VOUT switch state cannot be lost with buffered USB data.
        self.api.ser.flush()
        time.sleep(0.02)

    def power_off(self) -> None:
        self.api.toggle_DUT_power("OFF")
        self.api.ser.flush()
        time.sleep(0.02)

    def start_continuous(self) -> None:
        """Keep the PPK2 sampling between captures so its DUT path stays blue."""
        self._stop_and_drain()
        self.power_on()
        self.api.start_measuring()
        self.api.ser.flush()
        self._continuous_hold = True

    def close(self, *, keep_power_on: bool = True) -> None:
        self._continuous_hold = False
        serial = getattr(self.api, "ser", None)
        if serial is None or not serial.is_open:
            return
        power_error = None
        try:
            try:
                self.api.stop_measuring()
            except Exception:
                pass
            # Reassert the desired switch state as the final PPK2 command.
            # A disconnected USB device may reject it; retain that uncertainty
            # while still releasing the obsolete serial handle below.
            if keep_power_on:
                self.power_on()
            else:
                self.power_off()
        except BaseException as exc:
            power_error = exc
            if hasattr(exc, "add_note"):
                exc.add_note("PPK2 final DUT power state could not be reasserted; serial cleanup is still attempted")
            raise
        finally:
            try:
                serial.close()
            except Exception as close_exc:
                if power_error is None:
                    raise
                if hasattr(power_error, "add_note"):
                    power_error.add_note(f"PPK2 serial close also failed: {type(close_exc).__name__}: {close_exc}")

    def _drain_for(self, duration_s: float, chunks: list[bytes]) -> None:
        deadline = time.perf_counter() + duration_s
        while time.perf_counter() < deadline:
            data = self.api.get_data()
            if data:
                chunks.append(data)
            else:
                time.sleep(0.0005)

    def capture(
        self,
        *,
        pre_s: float,
        after_trigger_s: float,
        trigger: Callable[[], None],
    ) -> Capture:
        if pre_s <= 0 or after_trigger_s <= 0:
            raise ValueError("Capture durations must be positive")

        resume_continuous = self._continuous_hold
        if resume_continuous:
            self._stop_and_drain()
        else:
            while self.api.get_data():
                pass
        self.api.remainder = {"sequence": b"", "len": 0}
        self.api.rolling_avg = None
        self.api.rolling_avg4 = None
        self.api.prev_range = None
        self.api.after_spike = 0

        try:
            chunks: list[bytes] = []
            trigger_errors: list[BaseException] = []

            def run_trigger() -> None:
                try:
                    trigger()
                except BaseException as exc:
                    trigger_errors.append(exc)

            start = time.perf_counter()
            self.api.start_measuring()
            trigger_thread: threading.Thread | None = None
            try:
                self._drain_for(pre_s, chunks)
                queued_bytes = sum(len(chunk) for chunk in chunks)
                queued_bytes += int(getattr(self.api.ser, "in_waiting", 0))
                trigger_index = queued_bytes // 4
                # Serial.flush() can block for more than 100 ms at 9600 baud. Keep
                # draining the PPK2 port concurrently so its USB buffers do not fill.
                trigger_thread = threading.Thread(target=run_trigger, daemon=True)
                trigger_thread.start()
                self._drain_for(after_trigger_s, chunks)
                trigger_thread.join(timeout=1.0)
                if trigger_thread.is_alive():
                    raise RuntimeError("Radio serial transmission did not finish in time")
                if trigger_errors:
                    raise trigger_errors[0]
                final = self.api.get_data()
                if final:
                    chunks.append(final)
            finally:
                self.api.stop_measuring()

            time.sleep(0.01)
            tail = self.api.get_data()
            if tail:
                chunks.append(tail)
            elapsed = time.perf_counter() - start
            raw = b"".join(chunks)
            if not raw:
                raise RuntimeError("PPK2 returned no measurement data")
            samples, logic_bits = self.api.get_samples(raw)
            expected = int((pre_s + after_trigger_s) * SAMPLE_RATE_HZ)
            trigger_index = min(trigger_index, max(0, len(samples) - 1))
            return Capture(samples, logic_bits, trigger_index, elapsed, expected)
        finally:
            if resume_continuous and self.api.ser.is_open:
                self.api.start_measuring()
                self.api.ser.flush()
