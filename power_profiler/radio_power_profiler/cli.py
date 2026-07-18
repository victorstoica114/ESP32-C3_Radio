from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .planning import build_cases
from .profiles import list_profiles, load_profile, override_profile


def _csv_ints(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(value.strip()) for value in text.split(",") if value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected comma-separated integers") from exc


def _csv_floats(text: str) -> tuple[float, ...]:
    try:
        return tuple(float(value.strip()) for value in text.split(",") if value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected comma-separated numbers") from exc


def _axis_overrides(items: list[str], profile) -> dict[str, tuple[Any, ...]]:
    axes = {axis.name: axis for axis in profile.axes}
    overrides: dict[str, tuple[Any, ...]] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Axis override must be NAME=VALUE1,VALUE2: {item!r}")
        name, raw_values = item.split("=", 1)
        if name not in axes:
            raise ValueError(f"Unknown axis {name!r} for {profile.profile_id}")
        default = axes[name].values[0]
        converter = str if isinstance(default, str) else float if isinstance(default, float) else int
        try:
            values = tuple(converter(value.strip()) for value in raw_values.split(","))
        except ValueError as exc:
            raise ValueError(f"Invalid value in axis override {item!r}") from exc
        overrides[name] = values
    return overrides


def _selected_profile(args):
    profile = load_profile(args.module)
    return override_profile(
        profile,
        sizes=args.sizes,
        repetitions=args.repetitions,
        cooldown_s=args.cooldown_s,
        axis_overrides=_axis_overrides(args.axis, profile),
    )


def cmd_profiles(_args) -> int:
    print(f"{'PROFILE':<31} {'BAUD':>7}  MODULE")
    for profile in list_profiles():
        print(f"{profile.profile_id:<31} {profile.baudrate:>7}  {profile.display_name}")
    return 0


def cmd_ports(_args) -> int:
    try:
        from serial.tools import list_ports
        from .ppk import Ppk2Sampler
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: python -m pip install -r requirements.txt") from exc

    ppk_ports = {device for device, _serial in Ppk2Sampler.list_devices()}
    print(f"{'PORT':<10} {'TYPE':<8} DESCRIPTION")
    for port in list_ports.comports():
        kind = "PPK2" if port.device in ppk_ports else "serial"
        print(f"{port.device:<10} {kind:<8} {port.description}")
    return 0


def cmd_plan(args) -> int:
    profile = _selected_profile(args)
    cases = build_cases(profile, args.direction)
    capture_s = sum(
        profile.capture.pre_s + case.capture_after_trigger_s + profile.cooldown_s
        for case in cases
    )
    print(profile.display_name)
    print(f"Measurement direction: {args.direction.upper()}")
    print(f"Firmware: {profile.firmware_selection}")
    print(f"Serial: {profile.baudrate} baud")
    print(f"Radio payload sizes: {', '.join(map(str, profile.payload_sizes))} bytes")
    for axis in profile.axes:
        print(f"{axis.name}: {', '.join(map(str, axis.values))}")
    print(f"Repetitions: {profile.repetitions}")
    print(f"Measurements: {len(cases)}")
    print(f"Estimated minimum bench time: {capture_s / 60.0:.1f} minutes")
    for note in profile.notes:
        print(f"Note: {note}")
    return 0


def _resolve_ppk_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    from .ppk import Ppk2Sampler

    devices = Ppk2Sampler.list_devices()
    if len(devices) == 1:
        return devices[0][0]
    if not devices:
        raise RuntimeError("No PPK2 detected; pass its data COM port with --ppk-port")
    raise RuntimeError("Multiple PPK2 devices detected; select one with --ppk-port")


def cmd_run(args) -> int:
    try:
        from .runner import run_profile
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: python -m pip install -r requirements.txt") from exc

    profile = _selected_profile(args)
    if args.direction == "rx":
        if args.receiver_port:
            raise ValueError("--receiver-port is only valid with --direction tx")
        if not args.transmitter_port:
            raise ValueError("--direction rx requires --transmitter-port")
    elif args.transmitter_port:
        raise ValueError("--transmitter-port is only valid with --direction rx")
    ppk_port = _resolve_ppk_port(args.ppk_port)
    print(f"PPK2: {ppk_port}, mode=ampere, input voltage={args.voltage_mv} mV")
    measured_role = "transmitter" if args.direction == "tx" else "receiver"
    print(
        f"Measured {measured_role}: {args.radio_port}, "
        f"{profile.baudrate} baud"
    )
    peer_port = args.receiver_port if args.direction == "tx" else args.transmitter_port
    if peer_port:
        peer_role = "receiver" if args.direction == "tx" else "transmitter"
        print(f"Peer {peer_role}: {peer_port}, {profile.baudrate} baud")
    output = run_profile(
        profile,
        radio_port=args.radio_port,
        receiver_port=args.receiver_port,
        measurement_direction=args.direction,
        transmitter_port=args.transmitter_port,
        ppk_port=ppk_port,
        voltage_mv=args.voltage_mv,
        output_root=args.output,
        save_raw=args.save_raw,
        keep_power_on=args.keep_power_on,
        boot_wait_s=args.boot_wait_s,
    )
    print(f"Results: {output.resolve()}")
    return 0


def cmd_continuous(args) -> int:
    try:
        from .continuous_runner import run_continuous_profile
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: python -m pip install -r requirements.txt") from exc

    if args.direction == "rx" and not args.transmitter_port:
        raise ValueError("continuous --direction rx requires --transmitter-port")
    if args.direction == "tx" and args.transmitter_port:
        raise ValueError("--transmitter-port is only valid with continuous RX")
    profile = load_profile(args.module)
    ppk_port = _resolve_ppk_port(args.ppk_port)
    print(f"PPK2: {ppk_port}, mode=ampere, input voltage={args.voltage_mv} mV")
    print(
        f"Continuous {args.direction.upper()}: {args.duration_s:g} s per power, "
        f"{args.bit_rate_kbps:g} kbps, {args.frame_bytes} B frames, "
        f"{args.gap_ms} ms gap"
    )
    output = run_continuous_profile(
        profile,
        measurement_direction=args.direction,
        powers_dbm=args.powers,
        bit_rate_kbps=args.bit_rate_kbps,
        duration_s=args.duration_s,
        frame_bytes=args.frame_bytes,
        inter_frame_gap_ms=args.gap_ms,
        radio_port=args.radio_port,
        transmitter_port=args.transmitter_port,
        ppk_port=ppk_port,
        voltage_mv=args.voltage_mv,
        output_root=args.output,
        boot_wait_s=args.boot_wait_s,
        save_raw=args.save_raw,
    )
    print(f"Results: {output.resolve()}")
    return 0


def cmd_web(args) -> int:
    from .web_app import run_web_server

    run_web_server(
        bind=args.bind,
        port=args.port,
        sessions_root=args.sessions_root,
        open_browser=not args.no_browser,
    )
    return 0


def _add_matrix_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--module", required=True, help="profile ID shown by the profiles command")
    parser.add_argument(
        "--direction",
        choices=("tx", "rx"),
        default="tx",
        help="measure transmission or reception energy (default: tx)",
    )
    parser.add_argument("--sizes", type=_csv_ints, help="radio-payload sizes, for example 8,32,64")
    parser.add_argument("--repetitions", type=int, help="repetitions per matrix point")
    parser.add_argument("--cooldown-s", type=float, help="idle time between packets")
    parser.add_argument(
        "--axis",
        action="append",
        default=[],
        metavar="NAME=VALUES",
        help="override one axis; repeat as needed",
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radio-power-profiler",
        description="Automated per-packet current measurements with Nordic PPK2.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profiles_parser = subparsers.add_parser("profiles", help="list supported radio profiles")
    profiles_parser.set_defaults(func=cmd_profiles)

    ports_parser = subparsers.add_parser("ports", help="list serial ports and identify PPK2")
    ports_parser.set_defaults(func=cmd_ports)

    plan_parser = subparsers.add_parser("plan", help="show a test matrix without hardware")
    _add_matrix_arguments(plan_parser)
    plan_parser.set_defaults(func=cmd_plan)

    run_parser = subparsers.add_parser("run", help="execute a measurement matrix")
    _add_matrix_arguments(run_parser)
    run_parser.add_argument(
        "--radio-port",
        required=True,
        help="serial port of the measured DUT powered through PPK2",
    )
    run_parser.add_argument(
        "--receiver-port",
        help="optional peer receiver used to verify a TX measurement",
    )
    run_parser.add_argument(
        "--transmitter-port",
        help="required peer transmitter for an RX measurement",
    )
    run_parser.add_argument("--ppk-port", help="PPK2 data port; auto-detected if unique")
    run_parser.add_argument(
        "--voltage-mv",
        type=int,
        default=3300,
        help="actual VIN rail voltage used for calibration and energy; PPK2 does not generate it",
    )
    run_parser.add_argument("--output", type=Path, default=Path("results"))
    run_parser.add_argument("--save-raw", action="store_true", help="save every 100 kS/s trace as gzip CSV")
    run_parser.add_argument("--keep-power-on", action="store_true", help="leave the PPK2 DUT path enabled after the run")
    run_parser.add_argument("--boot-wait-s", type=float, default=1.5)
    run_parser.set_defaults(func=cmd_run)

    continuous_parser = subparsers.add_parser(
        "continuous",
        help="measure average power during a continuous framed data stream",
    )
    continuous_parser.add_argument("--module", required=True)
    continuous_parser.add_argument(
        "--direction",
        choices=("tx", "rx"),
        required=True,
    )
    continuous_parser.add_argument(
        "--powers",
        type=_csv_floats,
        default=(-30.0, 0.0, 10.0),
        help="comma-separated transmitter powers in dBm",
    )
    continuous_parser.add_argument("--bit-rate-kbps", type=float, default=38.4)
    continuous_parser.add_argument("--frame-bytes", type=int, default=32)
    continuous_parser.add_argument("--gap-ms", type=int, default=15)
    continuous_parser.add_argument("--duration-s", type=float, default=60.0)
    continuous_parser.add_argument("--radio-port", required=True)
    continuous_parser.add_argument(
        "--transmitter-port",
        help="peer transmitter required when measuring RX",
    )
    continuous_parser.add_argument("--ppk-port")
    continuous_parser.add_argument("--voltage-mv", type=int, default=3300)
    continuous_parser.add_argument(
        "--output",
        type=Path,
        default=Path("continuous_results"),
    )
    continuous_parser.add_argument("--boot-wait-s", type=float, default=1.5)
    continuous_parser.add_argument(
        "--save-raw",
        action="store_true",
        help="save each continuous 100 kS/s trace as gzip CSV",
    )
    continuous_parser.set_defaults(func=cmd_continuous)

    web_parser = subparsers.add_parser(
        "web",
        help="serve local web UI for quick checks and unattended campaigns",
    )
    web_parser.add_argument("--bind", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument(
        "--sessions-root",
        type=Path,
        default=Path("web_sessions"),
    )
    web_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the UI in the default browser",
    )
    web_parser.set_defaults(func=cmd_web)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted. Completed rows remain in summary.csv.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
