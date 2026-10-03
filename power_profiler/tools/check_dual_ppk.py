"""Check two explicit PPK2 ports; optionally sample both without radio commands.

No DUT switch or source-voltage command is sent. Existing sampling is stopped;
both serial handles are closed on completion, including failures. This checks
parallel acquisition, not a paired RF campaign or hardware synchronization.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import re
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable

SAMPLE_RATE_HZ = 100_000


def _port(value: str) -> str:
    value = value.strip().upper().removeprefix("\\\\.\\")
    if not re.fullmatch(r"COM[1-9][0-9]*", value):
        raise ValueError("Specify a Windows data port such as COM10")
    return value


def _stop_and_drain(api: Any) -> None:
    api.stop_measuring()
    api.ser.flush()
    time.sleep(0.05)
    deadline = time.perf_counter() + 0.5
    quiet_since = time.perf_counter()
    while time.perf_counter() < deadline:
        if api.get_data():
            quiet_since = time.perf_counter()
        elif time.perf_counter() - quiet_since >= 0.05:
            return
        time.sleep(0.002)
    raise RuntimeError("PPK2 did not stop streaming before the metadata request")


def _prepare(api: Any, voltage_mv: int) -> dict[str, Any]:
    for attempt in range(3):
        _stop_and_drain(api)
        try:
            response = api.get_modifiers()
            modifiers = copy.deepcopy(api.modifiers)
            if response is not True or modifiers.get("HW") is None or modifiers.get("Calibrated") is None:
                raise ValueError("Incomplete PPK2 hardware/calibration metadata")
            for key in ("R", "GS", "GI", "O", "S", "I", "UG"):
                for index in range(5):
                    value = float(modifiers[key][str(index)])
                    if not math.isfinite(value) or (key == "R" and value <= 0):
                        raise ValueError(f"Invalid calibration coefficient {key}{index}")
            break
        except (AttributeError, KeyError, TypeError, ValueError):
            if attempt == 2:
                raise
    api.use_ampere_meter()
    # ppk2-api 0.9.2 uses this internal value for ampere-mode calibration.
    # It does not set a physical supply voltage or the DUT switch state.
    api.current_vdd = voltage_mv
    api.ser.flush()
    return modifiers


def _capture_parallel(devices: dict[str, Any], report: dict[str, Any], duration_s: float) -> None:
    cancel = threading.Event()
    timing: dict[str, float | int] = {}

    def release() -> None:
        timing["both_started_host_monotonic_ns"] = time.perf_counter_ns()
        timing["deadline"] = time.perf_counter() + duration_s

    barrier = threading.Barrier(2, action=release)
    chunks: dict[str, list[bytes]] = {role: [] for role in devices}
    errors: dict[str, str] = {}

    def collect(role: str, api: Any) -> None:
        item = report["devices"][role]
        try:
            item["start_command_host_monotonic_ns"] = time.perf_counter_ns()
            api.start_measuring()
            api.ser.flush()
            item["start_command_completed_host_monotonic_ns"] = time.perf_counter_ns()
            barrier.wait(timeout=3.0)
            while not cancel.is_set() and time.perf_counter() < timing["deadline"]:
                data = api.get_data()
                if data:
                    item.setdefault("first_data_host_monotonic_ns", time.perf_counter_ns())
                    chunks[role].append(data)
                else:
                    time.sleep(0.0005)
            item["stop_command_host_monotonic_ns"] = time.perf_counter_ns()
            api.stop_measuring()
            api.ser.flush()
            # Drain the bounded USB tail after STOP; never wait indefinitely.
            tail_deadline = time.perf_counter() + 0.05
            while time.perf_counter() < tail_deadline:
                data = api.get_data()
                if data:
                    chunks[role].append(data)
                else:
                    time.sleep(0.0005)
            item["read_completed_host_monotonic_ns"] = time.perf_counter_ns()
        except BaseException as exc:
            errors[role] = f"{type(exc).__name__}: {exc}"
            cancel.set()
            barrier.abort()

    workers = [threading.Thread(target=collect, args=(role, api), daemon=True)
               for role, api in devices.items()]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=duration_s + 4.0)
        if any(worker.is_alive() for worker in workers):
            raise RuntimeError("Parallel PPK2 acquisition did not finish within its deadline")
    finally:
        cancel.set()
        barrier.abort()
        for worker in workers:
            if worker.ident is not None:
                worker.join(timeout=2.0)
    report["capture"]["both_started_host_monotonic_ns"] = timing.get("both_started_host_monotonic_ns")
    starts = [item["start_command_host_monotonic_ns"] for item in report["devices"].values()
              if "start_command_host_monotonic_ns" in item]
    report["capture"]["host_start_command_skew_ms"] = (max(starts) - min(starts)) / 1e6 if starts else None
    for role, api in devices.items():
        item = report["devices"][role]
        raw = b"".join(chunks[role])
        item["received_bytes"] = len(raw)
        item["trailing_incomplete_sample_bytes"] = len(raw) % 4
        if role in errors:
            item["capture_error"] = errors[role]
            continue
        if len(raw) < 4:
            errors[role] = "PPK2 returned no complete samples"
            item["capture_error"] = errors[role]
            continue
        try:
            samples, logic = api.get_samples(raw[:len(raw) - len(raw) % 4])
            if not samples or any(not math.isfinite(value) for value in samples):
                raise ValueError("No finite current samples, or nonfinite values returned")
            item.update(
                sample_count=len(samples), logic_sample_count=len(logic),
                sample_duration_at_nominal_rate_s=len(samples) / SAMPLE_RATE_HZ,
                received_to_nominal_requested_sample_ratio=len(samples) / (duration_s * SAMPLE_RATE_HZ),
                mean_current_uA=statistics.fmean(samples),
                minimum_current_uA=min(samples), maximum_current_uA=max(samples),
                first_current_samples_uA=list(samples[:10]),
            )
        except Exception as exc:
            errors[role] = f"{type(exc).__name__}: {exc}"
            item["capture_error"] = errors[role]
    if errors:
        raise RuntimeError("; ".join(f"{role}: {error}" for role, error in errors.items()))


def diagnose(
    *, tx_ppk_port: str, rx_ppk_port: str, tx_voltage_mv: int = 3300,
    rx_voltage_mv: int = 3300, capture_seconds: float = 0,
    api_factory: Callable[..., Any] | None = None,
    port_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return JSON-compatible evidence; an injected API permits hardware-free tests."""
    ports = {"tx": _port(tx_ppk_port), "rx": _port(rx_ppk_port)}
    if ports["tx"] == ports["rx"]:
        raise ValueError("TX and RX PPK2 ports must be distinct")
    if not math.isfinite(capture_seconds) or not 0 <= capture_seconds <= 5:
        raise ValueError("capture_seconds must be between 0 and 5; zero reads metadata only")
    voltages = {"tx": tx_voltage_mv, "rx": rx_voltage_mv}
    if any(not 800 <= value <= 5000 for value in voltages.values()):
        raise ValueError("The actual input voltages must be between 800 and 5000 mV")
    report: dict[str, Any] = {
        "schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "mode": "ampere", "sample_rate_hz": SAMPLE_RATE_HZ,
        "dut_switch_commands_sent": False, "radio_commands_sent": False,
        "hardware_synchronized": False,
        "scope": "PPK metadata and optional concurrent current readout; no paired RF campaign",
        "synchronization": "Independent PPK clocks; host start times are not sample alignment or RF triggers",
        "capture": {"requested_seconds": capture_seconds, "requested": capture_seconds > 0,
                    "nominal_requested_samples_per_device": round(capture_seconds * SAMPLE_RATE_HZ)},
        "devices": {role: {"port": port, "voltage_mv": voltages[role]} for role, port in ports.items()},
        "errors": [], "warnings": [],
    }
    devices: dict[str, Any] = {}
    try:
        if api_factory is None:
            from ppk2_api.ppk2_api import PPK2_API
            from serial.tools.list_ports import comports
            api_factory = PPK2_API
            report["ppk2_api_version"] = version("ppk2-api")
            if port_metadata is None:
                port_metadata = {
                    port.device.upper(): {"serial_number": port.serial_number,
                                          "description": port.description, "hwid": port.hwid,
                                          "vid": port.vid, "pid": port.pid}
                    for port in comports()
                }
        for role, port in ports.items():
            report["devices"][role]["usb_metadata"] = (port_metadata or {}).get(port, {})
            devices[role] = api_factory(port, timeout=0, write_timeout=1.0)
        for role, api in devices.items():
            modifiers = _prepare(api, voltages[role])
            report["devices"][role]["calibration_metadata"] = modifiers
            report["devices"][role]["calibration_metadata_read"] = True
            calibrated = str(modifiers["Calibrated"]).strip().lower()
            if calibrated not in {"1", "true", "yes"}:
                report["warnings"].append(f"{role}: device reports Calibrated={modifiers['Calibrated']!r}")
        if capture_seconds:
            _capture_parallel(devices, report, capture_seconds)
        report["status"] = "ok"
    except (Exception, KeyboardInterrupt) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["status"] = "error"
    finally:
        for role, api in devices.items():
            try:
                api.stop_measuring()
                api.ser.flush()
            except Exception as exc:
                report["errors"].append(f"{role} cleanup STOP: {type(exc).__name__}: {exc}")
                report["status"] = "error"
            finally:
                try:
                    api.ser.close()
                    report["devices"][role]["serial_closed"] = True
                except Exception as exc:
                    report["errors"].append(f"{role} cleanup close: {type(exc).__name__}: {exc}")
                    report["status"] = "error"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tx-ppk-port", required=True)
    parser.add_argument("--rx-ppk-port", required=True)
    parser.add_argument("--tx-voltage-mv", type=int, default=3300, help="Actual external VIN; no voltage is generated")
    parser.add_argument("--rx-voltage-mv", type=int, default=3300, help="Actual external VIN; no voltage is generated")
    parser.add_argument("--capture-seconds", type=float, default=0, help="0: metadata only; >0 to 5: simultaneous passive readout")
    parser.add_argument("--output", type=Path, help="New JSON report path; existing files are never overwritten")
    args = parser.parse_args(argv)
    # Reserve the requested report before opening any PPK2; avoid losing results
    # to a bad output path or overwriting an earlier diagnostic.
    with contextlib.ExitStack() as stack:
        output = None
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = stack.enter_context(args.output.open("x", encoding="utf-8"))
        try:
            with contextlib.redirect_stdout(sys.stderr):
                report = diagnose(
                    tx_ppk_port=args.tx_ppk_port, rx_ppk_port=args.rx_ppk_port,
                    tx_voltage_mv=args.tx_voltage_mv, rx_voltage_mv=args.rx_voltage_mv,
                    capture_seconds=args.capture_seconds,
                )
        except ValueError as exc:
            report = {"status": "error", "errors": [str(exc)], "hardware_opened": False}
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if output:
            output.write(rendered)
        print(rendered, end="")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
