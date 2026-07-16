from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Axis:
    name: str
    values: tuple[Any, ...]
    command: str | None = None
    commands: dict[str, str] = field(default_factory=dict)
    label: str = ""

    def command_for(self, value: Any) -> str:
        if self.commands:
            try:
                return self.commands[str(value)]
            except KeyError as exc:
                raise ValueError(
                    f"Axis {self.name!r} has no command for value {value!r}"
                ) from exc
        if self.command is None:
            raise ValueError(f"Axis {self.name!r} has no command template")
        return self.command.format(value=value)


@dataclass(frozen=True)
class TransmitSpec:
    mode: str
    command: str | None = None
    line_overhead_bytes: int = 0
    max_payload_bytes: int = 255


@dataclass(frozen=True)
class CaptureSpec:
    pre_s: float = 0.20
    post_s: float = 0.25
    minimum_after_trigger_s: float = 0.50
    max_after_trigger_s: float = 15.0
    threshold_margin_uA: float = 500.0
    merge_gap_ms: float = 0.50
    minimum_event_ms: float = 0.05


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
    capture: CaptureSpec
    airtime: dict[str, Any]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestCase:
    case_index: int
    repetition: int
    payload_bytes: int
    parameters: dict[str, Any]
    estimated_airtime_s: float
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
