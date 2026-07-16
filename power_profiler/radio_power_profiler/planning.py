from __future__ import annotations

import itertools
import math
from typing import Any

from .models import Profile, TestCase


def _lookup_numeric(mapping: dict[str, Any], value: Any) -> float:
    try:
        return float(mapping[str(value)])
    except KeyError as exc:
        raise ValueError(f"No airtime mapping for axis value {value!r}") from exc


def estimate_airtime_s(profile: Profile, payload_bytes: int, params: dict[str, Any]) -> float:
    spec = profile.airtime
    kind = spec.get("kind", "fixed")

    if kind == "lora":
        sf = int(params[spec.get("sf_axis", "spreading_factor")])
        bw_value = params[spec.get("bw_axis", "bandwidth_khz")]
        bw_hz = float(bw_value) * float(spec.get("bw_multiplier", 1000.0))
        coding_rate_denominator = int(spec.get("coding_rate_denominator", 5))
        preamble_symbols = int(spec.get("preamble_symbols", 8))
        crc = 1 if spec.get("crc", True) else 0
        implicit_header = 1 if spec.get("implicit_header", False) else 0
        low_data_rate_opt = 1 if ((2**sf) / bw_hz) >= 0.016 else 0
        symbol_s = (2**sf) / bw_hz
        numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc - 20 * implicit_header
        denominator = 4 * (sf - 2 * low_data_rate_opt)
        payload_symbols = 8 + max(
            math.ceil(numerator / denominator) * coding_rate_denominator,
            0,
        )
        return (preamble_symbols + 4.25 + payload_symbols) * symbol_s

    if kind == "fsk":
        rate_axis = spec["rate_axis"]
        rate_value = params[rate_axis]
        if "rate_bps_by_value" in spec:
            rate_bps = _lookup_numeric(spec["rate_bps_by_value"], rate_value)
        else:
            rate_bps = float(rate_value) * float(spec.get("rate_multiplier", 1000.0))
        overhead_bytes = int(spec.get("overhead_bytes", 8))
        ramp_s = float(spec.get("ramp_s", 0.002))
        return ((payload_bytes + overhead_bytes) * 8 / rate_bps) + ramp_s

    if kind == "fixed":
        return float(spec.get("seconds", 0.25))

    raise ValueError(f"Unsupported airtime model: {kind!r}")


def build_cases(profile: Profile) -> list[TestCase]:
    if profile.repetitions < 1:
        raise ValueError("Repetitions must be at least 1")
    if not profile.payload_sizes:
        raise ValueError("At least one payload size is required")

    for size in profile.payload_sizes:
        if size <= profile.transmit.line_overhead_bytes:
            raise ValueError(
                f"Payload {size} is too small for {profile.transmit.line_overhead_bytes} "
                "bytes of firmware-added line ending"
            )
        if size > profile.transmit.max_payload_bytes:
            raise ValueError(
                f"Payload {size} exceeds {profile.transmit.max_payload_bytes} bytes for "
                f"{profile.profile_id}"
            )

    names = [axis.name for axis in profile.axes]
    products = itertools.product(*(axis.values for axis in profile.axes))
    parameter_sets = [dict(zip(names, values)) for values in products]
    if not parameter_sets:
        parameter_sets = [{}]

    cases: list[TestCase] = []
    index = 1
    for parameters in parameter_sets:
        for payload_bytes in profile.payload_sizes:
            airtime = estimate_airtime_s(profile, payload_bytes, parameters)
            after = max(
                profile.capture.minimum_after_trigger_s,
                airtime * 1.35 + profile.capture.post_s + 0.10,
            )
            after = min(after, profile.capture.max_after_trigger_s)
            for repetition in range(1, profile.repetitions + 1):
                cases.append(
                    TestCase(
                        case_index=index,
                        repetition=repetition,
                        payload_bytes=payload_bytes,
                        parameters=dict(parameters),
                        estimated_airtime_s=airtime,
                        capture_after_trigger_s=after,
                    )
                )
                index += 1
    return cases


def parameter_commands(profile: Profile, parameters: dict[str, Any]) -> list[str]:
    return [axis.command_for(parameters[axis.name]) for axis in profile.axes]
