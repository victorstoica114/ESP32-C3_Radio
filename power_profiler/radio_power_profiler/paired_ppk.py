"""Host-coordinated acquisition from two independent PPK2 sample clocks."""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .ppk import Capture, Ppk2Sampler, SAMPLE_RATE_HZ


@dataclass
class PairedCapture:
    captures: dict[str, Capture] = field(default_factory=dict)
    timing: dict = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    wire_paths: dict[str, str] = field(default_factory=dict)
    trigger_called: bool = False


class ContinuousDrain:
    """Drain held-open PPKs between captures; pause before exclusive capture IO."""
    def __init__(self, samplers):
        self.samplers = samplers
        self.stop_event = threading.Event()
        self.workers = []
        self.errors = []

    def start(self):
        if self.workers:
            raise RuntimeError("Continuous readers already started")
        self.stop_event.clear()
        for sampler in self.samplers.values():
            sampler.api.start_measuring()
            sampler.api.ser.flush()
        def drain(role, sampler):
            try:
                while not self.stop_event.is_set():
                    sampler.api.get_data()
                    self.stop_event.wait(.001)
            except BaseException as exc:
                self.errors.append(f"{role} continuous drain: {exc}")
                self.stop_event.set()
        for role, sampler in self.samplers.items():
            worker = threading.Thread(target=drain, args=(role, sampler), daemon=True)
            self.workers.append(worker)
            worker.start()

    def pause(self):
        self.stop_event.set()
        for worker in self.workers:
            worker.join(timeout=2)
        if any(worker.is_alive() for worker in self.workers):
            raise RuntimeError("Continuous PPK reader did not stop before exclusive capture")
        self.workers.clear()

    def check(self):
        if self.errors:
            raise RuntimeError("; ".join(self.errors))


def capture_pair(
    samplers: dict[str, Ppk2Sampler], *, pre_s: float, after_trigger_s: float,
    trigger: Callable[[], None], wire_directory: Path,
    ready_timeout_s: float = 3.0, trigger_timeout_s: float = 8.0,
) -> PairedCapture:
    """Keep both inputs draining, mark each local stream, then trigger once.

    Binary wire files are retained even when calibration decoding or the radio
    callback fails. Marks include queued USB bytes, matching the single-PPK
    convention; host timestamps do NOT establish hardware synchronization.
    The caller owns power state and closes the samplers after use.
    """
    if set(samplers) != {"tx", "rx"} or samplers["tx"] is samplers["rx"]:
        raise ValueError("Two distinct TX/RX samplers are required")
    if any(not math.isfinite(v) or v <= 0 for v in (pre_s, after_trigger_s, ready_timeout_s, trigger_timeout_s)):
        raise ValueError("Capture durations and timeouts must be positive and finite")
    wire_directory.mkdir(parents=True, exist_ok=False)
    result = PairedCapture(timing={
        "synchronization": "host_coordinated_independent_sample_clocks",
        "hardware_synchronized": False, "sample_rate_hz": SAMPLE_RATE_HZ,
        "requested_pre_s": pre_s, "requested_after_trigger_s": after_trigger_s,
        "devices": {role: {} for role in samplers},
    })
    stop = threading.Event()
    fault = threading.Event()
    locks = {role: threading.Lock() for role in samplers}
    ready = {role: threading.Event() for role in samplers}
    chunks: dict[str, list[bytes]] = {role: [] for role in samplers}
    counts = {role: 0 for role in samplers}
    streams = {}
    workers: list[threading.Thread] = []
    sender: threading.Thread | None = None

    def fail(role: str, exc: BaseException) -> None:
        result.errors[role] = f"{type(exc).__name__}: {exc}"
        fault.set()

    def read_once(role: str) -> bool:
        with locks[role]:
            data = samplers[role].api.get_data()
            if data:
                # Unbuffered files retain evidence before decode and analysis.
                streams[role].write(data)
                chunks[role].append(data)
                counts[role] += len(data)
                result.timing["devices"][role].setdefault("first_data_host_ns", time.perf_counter_ns())
            return bool(data)

    def reader(role: str) -> None:
        api = samplers[role].api
        detail = result.timing["devices"][role]
        try:
            detail["start_command_host_ns"] = time.perf_counter_ns()
            api.start_measuring()
            api.ser.flush()
            started = time.perf_counter()
            while not stop.is_set():
                data = read_once(role)
                if time.perf_counter() - started >= pre_s and counts[role] // 4 >= pre_s * SAMPLE_RATE_HZ * 0.9:
                    ready[role].set()
                if not data:
                    stop.wait(0.0005)
        except BaseException as exc:
            fail(role, exc)
        finally:
            try:
                api.stop_measuring()
                api.ser.flush()
                detail["stop_command_host_ns"] = time.perf_counter_ns()
                deadline = time.perf_counter() + 0.03
                while time.perf_counter() < deadline:
                    if not read_once(role):
                        time.sleep(0.0005)
            except BaseException as exc:
                fail(role, exc)

    def send() -> None:
        result.timing["trigger_callback_started_host_ns"] = time.perf_counter_ns()
        try:
            trigger()
        except BaseException as exc:
            fail("trigger", exc)
        finally:
            result.timing["trigger_callback_finished_host_ns"] = time.perf_counter_ns()

    try:
        for role, sampler in samplers.items():
            sampler._stop_and_drain()
            api = sampler.api
            api.remainder = {"sequence": b"", "len": 0}
            api.rolling_avg = api.rolling_avg4 = api.prev_range = None
            api.after_spike = 0
            api.consecutive_range_samples = 0
            path = wire_directory / f"{role}.ppk2.bin"
            streams[role] = path.open("xb", buffering=0)
            result.wire_paths[role] = str(path)
        for role in samplers:
            worker = threading.Thread(target=reader, args=(role,), daemon=True)
            workers.append(worker)
            worker.start()
        deadline = time.perf_counter() + pre_s + ready_timeout_s
        while not all(event.is_set() for event in ready.values()):
            if fault.is_set():
                raise RuntimeError("A PPK2 failed before both pretrigger streams were ready")
            if time.perf_counter() >= deadline:
                raise TimeoutError("Both PPK2 pretrigger streams were not ready; no RF trigger sent")
            fault.wait(0.001)
        # Freeze byte accounting briefly, not acquisition clocks. Each USB
        # queue contributes to that device's own marker sample index.
        with locks["tx"], locks["rx"]:
            if fault.is_set():
                raise RuntimeError("PPK2 failed before trigger")
            for role, sampler in samplers.items():
                detail = result.timing["devices"][role]
                detail["marker_host_ns"] = time.perf_counter_ns()
                detail["trigger_index"] = (counts[role] + int(sampler.api.ser.in_waiting)) // 4
            result.timing["host_trigger_ns"] = time.perf_counter_ns()
            result.trigger_called = True
            sender = threading.Thread(target=send, daemon=True)
            sender.start()
        end = time.perf_counter() + after_trigger_s
        while time.perf_counter() < end:
            # A callback failure still retains the bounded current record.
            time.sleep(min(0.005, max(0, end - time.perf_counter())))
        sender.join(timeout=trigger_timeout_s)
        if sender.is_alive():
            fail("trigger_cleanup", TimeoutError("Radio callback is still running; do not resume acquisition"))
            raise TimeoutError("Radio callback did not finish; current evidence retained")
    except BaseException as exc:
        fail("coordinator", exc)
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=2.0)
        if any(worker.is_alive() for worker in workers):
            fail("reader_cleanup", RuntimeError("PPK2 reader did not stop"))
        for stream in streams.values():
            stream.close()

    marks = [detail["marker_host_ns"] for detail in result.timing["devices"].values() if "marker_host_ns" in detail]
    result.timing["host_marker_skew_ms"] = (max(marks) - min(marks)) / 1e6 if len(marks) == 2 else None
    for role, sampler in samplers.items():
        detail = result.timing["devices"][role]
        raw = b"".join(chunks[role])
        detail["wire_bytes"] = len(raw)
        detail["trailing_bytes"] = len(raw) % 4
        if "trigger_index" not in detail:
            continue
        try:
            if not raw or len(raw) % 4:
                raise ValueError("Empty or incomplete PPK2 wire sample stream")
            samples, logic = sampler.api.get_samples(raw)
            if len(samples) != len(raw) // 4 or len(logic) != len(samples):
                raise ValueError("PPK2 decoder discarded samples; marker alignment cannot be guaranteed")
            if any(not math.isfinite(value) for value in samples):
                raise ValueError("Nonfinite current sample")
            marker = detail["trigger_index"]
            if not 10 <= marker < len(samples):
                raise ValueError("Local trigger marker is outside the acquired sample record")
            elapsed = (detail["stop_command_host_ns"] - detail["start_command_host_ns"]) / 1e9
            result.captures[role] = Capture(samples, logic, marker, elapsed,
                                             marker + round(after_trigger_s * SAMPLE_RATE_HZ))
        except BaseException as exc:
            fail(role + "_decode", exc)
    (wire_directory / "timing.json").write_text(json.dumps({
        "trigger_called": result.trigger_called, "timing": result.timing,
        "errors": result.errors,
    }, indent=2) + "\n", encoding="utf-8")
    return result
