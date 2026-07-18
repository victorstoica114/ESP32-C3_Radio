from __future__ import annotations

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
        self.api = PPK2_API(port, timeout=0)
        self._stop_and_drain()
        self._read_modifiers_with_retry()
        self.api.use_ampere_meter()
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
        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                self.api.get_modifiers()
                return
            except (UnicodeDecodeError, TypeError, AttributeError) as exc:
                last_error = exc
                self._stop_and_drain()
        raise RuntimeError("Could not read PPK2 calibration metadata cleanly") from last_error

    @staticmethod
    def list_devices() -> list[tuple[str, str]]:
        from ppk2_api.ppk2_api import PPK2_API

        devices: list[tuple[str, str]] = []
        for item in PPK2_API.list_devices():
            # ppk2-api 0.9.2 returns port-name strings. Newer unreleased code
            # returns (port, serial-number) tuples, so normalize both forms.
            if isinstance(item, str):
                devices.append((item, ""))
            else:
                devices.append((str(item[0]), str(item[1])))
        return devices

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

    def close(self, *, keep_power_on: bool = True) -> None:
        try:
            self.api.stop_measuring()
        except Exception:
            pass
        # Reassert the desired switch state as the final PPK2 command. Merely
        # avoiding OFF is insufficient if a run was interrupted during an
        # intentional profile power cycle or a previous ON write was buffered.
        if keep_power_on:
            self.power_on()
        else:
            self.power_off()
        if getattr(self.api, "ser", None) is not None and self.api.ser.is_open:
            self.api.ser.close()

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

        while self.api.get_data():
            pass
        self.api.remainder = {"sequence": b"", "len": 0}
        self.api.rolling_avg = None
        self.api.rolling_avg4 = None
        self.api.prev_range = None
        self.api.after_spike = 0

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
