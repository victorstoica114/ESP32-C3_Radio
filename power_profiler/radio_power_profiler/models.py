from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Axis:
    name: str
    values: tuple[Any, ...]
    command: str | None = None
    commands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    label: str = ""

    def command_for(self, value: Any) -> str:
        commands = self.commands_for(value)
        if len(commands) != 1:
            raise ValueError(
                f"Axis {self.name!r} expands to {len(commands)} commands; "
                "use commands_for()"
            )
        return commands[0]

    def commands_for(self, value: Any) -> tuple[str, ...]:
        if self.commands:
            key = str(value)
            if isinstance(value, float) and value.is_integer():
                key = str(int(value))
            try:
                return self.commands[key]
            except KeyError as exc:
                raise ValueError(
                    f"Axis {self.name!r} has no command for value {value!r}"
                ) from exc
        if self.command is None:
            raise ValueError(f"Axis {self.name!r} has no command template")
        return (self.command.format(value=value),)


@dataclass(frozen=True)
class TransmitSpec:
    mode: str
    command: str | None = None
    line_overhead_bytes: int = 0
    max_payload_bytes: int = 255
    frame_payload_bytes: int | None = None
    wait_for_ok: bool = False

    def frame_sizes(self, payload_bytes: int) -> tuple[int, ...]:
        frame_limit = self.frame_payload_bytes or payload_bytes
        if frame_limit <= self.line_overhead_bytes:
            raise ValueError(
                "Physical frame limit must exceed firmware-added line overhead"
            )
        remaining = payload_bytes
        frames: list[int] = []
        while remaining > 0:
            frame_bytes = min(frame_limit, remaining)
            if frame_bytes <= self.line_overhead_bytes:
                raise ValueError(
                    f"Final frame has only {frame_bytes} bytes, not enough for "
                    f"{self.line_overhead_bytes} bytes of line overhead"
                )
            frames.append(frame_bytes)
            remaining -= frame_bytes
        return tuple(frames)


@dataclass(frozen=True)
class CaptureSpec:
    pre_s: float = 0.20
    post_s: float = 0.25
    minimum_after_trigger_s: float = 0.50
    max_after_trigger_s: float = 15.0
    threshold_margin_uA: float = 500.0
    merge_gap_ms: float = 0.50
    minimum_event_ms: float = 0.05
    align_tx_airtime_window: bool = False


@dataclass(frozen=True)
class ReceiveSpec:
    inter_frame_gap_ms: float = 0.0
    post_receive_s: float = 0.05


@dataclass(frozen=True)
class Profile:
    profile_id: str
    display_name: str
    firmware_selection: str
    baudrate: int
    setup_commands: tuple[str, ...]
    post_config_commands: tuple[str, ...]
    receiver_enable_commands: tuple[str, ...]
    payload_sizes: tuple[int, ...]
    repetitions: int
    cooldown_s: float
    axes: tuple[Axis, ...]
    transmit: TransmitSpec
    receive: ReceiveSpec
    capture: CaptureSpec
    airtime: dict[str, Any]
    inter_run_commands: tuple[str, ...] = ()
    power_cycle_between_runs: bool = False
    power_cycle_min_airtime_s: float = 0.0
    power_cycle_off_s: float = 1.0
    restore_after_receive: bool = True
    warmup_transfers: int = 0
    reopen_continuous_between_powers: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestCase:
    case_index: int
    repetition: int
    payload_bytes: int
    parameters: dict[str, Any]
    estimated_airtime_s: float
    estimated_event_s: float
    capture_after_trigger_s: float


@dataclass
class Metrics:
    event_detected: bool
    baseline_median_uA: float
    threshold_uA: float
    event_start_ms: float | None = None
    event_duration_ms: float | None = None
    tx_mean_uA: float | None = None
    tx_peak_uA: float | None = None
    charge_total_uC: float | None = None
    charge_excess_uC: float | None = None
    energy_total_uJ: float | None = None
    energy_excess_uJ: float | None = None
