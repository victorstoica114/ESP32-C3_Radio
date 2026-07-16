from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .models import Axis, CaptureSpec, Profile, TransmitSpec


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
            commands=item.get("commands", {}),
            label=item.get("label", ""),
        )
        for item in raw.get("axes", [])
    )
    tx_raw = raw["transmit"]
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
        capture=profile.capture,
        airtime=profile.airtime,
        notes=profile.notes,
    )
