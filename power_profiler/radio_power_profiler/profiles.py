from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .models import Axis, CaptureSpec, Profile, ReceiveSpec, TransmitSpec


def _catalog() -> dict[str, Any]:
    path = files("radio_power_profiler").joinpath("profiles.json")
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles() -> list[Profile]:
    return [load_profile(profile_id) for profile_id in sorted(_catalog())]


def load_profile(profile_id: str) -> Profile:
    catalog = _catalog()
    try:
        raw = catalog[profile_id]
    except KeyError as exc:
        choices = ", ".join(sorted(catalog))
        raise ValueError(f"Unknown module profile {profile_id!r}. Choices: {choices}") from exc

    axes = tuple(
        Axis(
            name=item["name"],
            values=tuple(item["values"]),
            command=item.get("command"),
            commands={
                str(value): (
                    tuple(commands)
                    if isinstance(commands, list)
                    else (str(commands),)
                )
                for value, commands in item.get("commands", {}).items()
            },
            label=item.get("label", ""),
        )
        for item in raw.get("axes", [])
    )
    tx_raw = raw["transmit"]
    rx_raw = raw.get("receive", {})
    capture_raw = raw.get("capture", {})

    return Profile(
        profile_id=profile_id,
        display_name=raw["display_name"],
        firmware_selection=raw["firmware_selection"],
        baudrate=int(raw["baudrate"]),
        setup_commands=tuple(raw.get("setup_commands", [])),
        post_config_commands=tuple(raw.get("post_config_commands", [])),
        receiver_enable_commands=tuple(raw.get("receiver_enable_commands", [])),
        payload_sizes=tuple(int(value) for value in raw["payload_sizes"]),
        repetitions=int(raw.get("repetitions", 5)),
        cooldown_s=float(raw.get("cooldown_s", 0.5)),
        axes=axes,
        transmit=TransmitSpec(
            mode=tx_raw["mode"],
            command=tx_raw.get("command"),
            line_overhead_bytes=int(tx_raw.get("line_overhead_bytes", 0)),
            max_payload_bytes=int(tx_raw.get("max_payload_bytes", 255)),
            frame_payload_bytes=(
                int(tx_raw["frame_payload_bytes"])
                if tx_raw.get("frame_payload_bytes") is not None
                else None
            ),
            wait_for_ok=bool(tx_raw.get("wait_for_ok", False)),
        ),
        receive=ReceiveSpec(
            inter_frame_gap_ms=float(rx_raw.get("inter_frame_gap_ms", 0.0)),
            post_receive_s=float(rx_raw.get("post_receive_s", 0.05)),
        ),
        capture=CaptureSpec(
            pre_s=float(capture_raw.get("pre_s", 0.20)),
            post_s=float(capture_raw.get("post_s", 0.25)),
            minimum_after_trigger_s=float(
                capture_raw.get("minimum_after_trigger_s", 0.50)
            ),
            max_after_trigger_s=float(capture_raw.get("max_after_trigger_s", 15.0)),
            threshold_margin_uA=float(
                capture_raw.get("threshold_margin_uA", 500.0)
            ),
            merge_gap_ms=float(capture_raw.get("merge_gap_ms", 0.50)),
            minimum_event_ms=float(capture_raw.get("minimum_event_ms", 0.05)),
        ),
        airtime=raw.get("airtime", {"kind": "fixed", "seconds": 0.25}),
        inter_run_commands=tuple(raw.get("inter_run_commands", [])),
        power_cycle_between_runs=bool(raw.get("power_cycle_between_runs", False)),
        power_cycle_min_airtime_s=float(raw.get("power_cycle_min_airtime_s", 0.0)),
        power_cycle_off_s=float(raw.get("power_cycle_off_s", 1.0)),
        restore_after_receive=bool(raw.get("restore_after_receive", True)),
        notes=tuple(raw.get("notes", [])),
    )


def override_profile(
    profile: Profile,
    *,
    sizes: tuple[int, ...] | None = None,
    repetitions: int | None = None,
    cooldown_s: float | None = None,
    axis_overrides: dict[str, tuple[Any, ...]] | None = None,
) -> Profile:
    axis_overrides = axis_overrides or {}
    known_axes = {axis.name for axis in profile.axes}
    unknown = set(axis_overrides) - known_axes
    if unknown:
        raise ValueError(f"Unknown axes for {profile.profile_id}: {', '.join(sorted(unknown))}")

    axes = tuple(
        Axis(
            name=axis.name,
            values=axis_overrides.get(axis.name, axis.values),
            command=axis.command,
            commands=axis.commands,
            label=axis.label,
        )
        for axis in profile.axes
    )
    return Profile(
        profile_id=profile.profile_id,
        display_name=profile.display_name,
        firmware_selection=profile.firmware_selection,
        baudrate=profile.baudrate,
        setup_commands=profile.setup_commands,
        post_config_commands=profile.post_config_commands,
        receiver_enable_commands=profile.receiver_enable_commands,
        payload_sizes=sizes or profile.payload_sizes,
        repetitions=repetitions if repetitions is not None else profile.repetitions,
        cooldown_s=cooldown_s if cooldown_s is not None else profile.cooldown_s,
        axes=axes,
        transmit=profile.transmit,
        receive=profile.receive,
        capture=profile.capture,
        airtime=profile.airtime,
        inter_run_commands=profile.inter_run_commands,
        power_cycle_between_runs=profile.power_cycle_between_runs,
        power_cycle_min_airtime_s=profile.power_cycle_min_airtime_s,
        power_cycle_off_s=profile.power_cycle_off_s,
        restore_after_receive=profile.restore_after_receive,
        notes=profile.notes,
    )
