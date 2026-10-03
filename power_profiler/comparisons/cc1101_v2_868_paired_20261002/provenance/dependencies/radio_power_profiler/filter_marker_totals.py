"""Independent ppk2-api filter replay with bounded uncertain history.

This is a distinct, opt-in proof, not the constant-range direct-ADC proof.
Replay uses the complete recorded stream and a known reset state. Suspect
counter words are NOT repaired: their influence is separately bounded using
every possible calibrated 14-bit ADC value and all possible filter controls.
The guard and marker must be clean. The default current_equivalence_v1 policy
limits replay error plus maximum marker interval width to 1e-6 microamperes.
Explicit energy_relative_v2 instead keeps that strict tolerance for replay and
limits uncertain-history energy interval width to 0.01% of its positive lower
endpoint. This is a software uncertainty budget, not instrument accuracy.

Endpoint recurrences execute the actual binary64 operations. Their monotonicity
and a checked invariant state interval include rounding, unlike alpha**n alone.
Range-4 freezes apply to both states. This certifies decoding and bounded prior
state influence, not analog accuracy during range switching. Modulo-64 counters
cannot detect losses of multiples of 64. No baseline/excess, repair or clipping.
Reference: nordicsemi/pc-nrfconnect-ppk src/device/serialDevice.ts getAdcResult.
"""
from __future__ import annotations

import collections
from functools import lru_cache
import hashlib
import json
import math
import operator
from pathlib import Path
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ppk import Capture


FILTER_TOLERANCE_UA = 1e-6
ENERGY_HISTORY_RELATIVE_TOLERANCE = 1e-4
FILTER_GUARD_SAMPLES = 3
_COEFFICIENTS = ("R", "O", "GS", "GI", "S", "I", "UG")
_ALPHA, _ALPHA5 = 0.18, 0.06


def _adc(code, range_code, coefficients, voltage_v):
    r, o, gs, gi, s, offset, ug = (values[range_code] for values in coefficients)
    unscaled = (code * 4 - o) * ((1.8 / 163840) / r)
    return ug * (unscaled * (gs * unscaled + gi) + (s * voltage_v + offset))


def _recurrence(value, previous, alpha):
    # Keep operation order identical to ppk2-api; do not fuse, reassociate or round.
    return alpha * value + (1 - alpha) * previous


def _upper_difference(high, low):
    return 0.0 if high == low else math.nextafter(high - low, math.inf)


@lru_cache(maxsize=16)
def _global_bounds(coefficients, voltage_v):
    values = [_adc(code, r, coefficients, voltage_v) for r in range(5) for code in range(16384)]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Calibrated ADC domain is not finite")
    minimum, maximum = min(values), max(values)
    low, high = minimum, maximum
    # Monotonicity means these four corner checks cover the entire ADC/state box.
    for iterations in range(4096):
        lows = [_recurrence(minimum, low, alpha) for alpha in (_ALPHA, _ALPHA5)]
        highs = [_recurrence(maximum, high, alpha) for alpha in (_ALPHA, _ALPHA5)]
        if not all(math.isfinite(value) for value in lows + highs):
            raise ValueError("Filter invariant recurrence is not finite")
        low_ok, high_ok = min(lows) >= low, max(highs) <= high
        if low_ok and high_ok:
            return minimum, maximum, low, high, iterations
        if not low_ok:
            low = math.nextafter(low, -math.inf)
        if not high_ok:
            high = math.nextafter(high, math.inf)
    raise ValueError("Unable to certify the global binary64 filter invariant")


def _controls(previous, after, consecutive, current):
    filtered = previous != current or after > 0
    if previous != current:
        after, consecutive = 3, 0
    elif filtered:
        consecutive = min(2, consecutive + 1)
    freeze = filtered and current == 4 and consecutive < 2
    return (current, after - 1 if filtered else after, consecutive), filtered, freeze


def _unknown_states(low, high):
    # Capping consecutive at 2 is exact: only the predicate <2 is observed.
    return {(r, after, consecutive): (low, high, low, high)
            for r in range(5) for after in range(3) for consecutive in range(3)}


def _interval_step(states, value, current):
    following, outputs = {}, []
    for (previous, after, consecutive), (flo, fhi, slo, shi) in states.items():
        control, filtered, freeze = _controls(previous, after, consecutive, current)
        if not freeze:
            flo, fhi = (_recurrence(value, endpoint, _ALPHA) for endpoint in (flo, fhi))
            slo, shi = (_recurrence(value, endpoint, _ALPHA5) for endpoint in (slo, shi))
        outputs.append((slo, shi) if filtered and current == 4 else
                       (flo, fhi) if filtered else (value, value))
        candidate = (flo, fhi, slo, shi)
        if control in following:
            old = following[control]
            candidate = (min(old[0], flo), max(old[1], fhi), min(old[2], slo), max(old[3], shi))
        following[control] = candidate
    return following, (min(pair[0] for pair in outputs), max(pair[1] for pair in outputs))


def _replay(words, coefficients, voltage_v, suspects, window, bounds):
    """Nominal full replay plus a separate conservative set of possible states."""
    low, high = bounds
    fast = slow = previous = None
    after = consecutive = 0
    states = None
    replay, intervals = [], []
    converged = {"fast": None, "slow": None}
    start, stop = window
    for index, word in enumerate(words):
        current = (word >> 14) & 7
        if current > 4:
            raise ValueError(f"Cannot replay invalid range at sample {index}")
        value = _adc(word & 0x3FFF, current, coefficients, voltage_v)
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite calibrated ADC at sample {index}")
        if previous is None:
            fast = slow = value
            previous = current
        else:
            control, filtered, freeze = _controls(previous, after, consecutive, current)
            if not freeze:
                fast = _recurrence(value, fast, _ALPHA)
                slow = _recurrence(value, slow, _ALPHA5)
            previous, after, consecutive = control
            value = slow if filtered and current == 4 else fast if filtered else value
        replay.append(value * 1e6)
        if index > stop:
            continue  # Tail replay is checked, but cannot affect the earlier marker.
        if index in suspects:
            states = _unknown_states(low, high)
            interval = (low, high)
            converged = {"fast": None, "slow": None}
        elif states is None:
            states = {(current, 0, 0): (fast, fast, slow, slow)}
            interval = (value, value)
        else:
            adc = _adc(word & 0x3FFF, current, coefficients, voltage_v)
            states, interval = _interval_step(states, adc, current)
        for name, positions in (("fast", (0, 1)), ("slow", (2, 3))):
            first, second = positions
            if min(s[first] for s in states.values()) == max(s[second] for s in states.values()):
                if converged[name] is None:
                    converged[name] = index
            else:
                converged[name] = None
        if start <= index < stop:
            intervals.append((interval[0] * 1e6, interval[1] * 1e6))
    return replay, intervals, converged


def _total_interval(intervals, sample_rate_hz, voltage_v):
    # Outward rounding includes summation, division and voltage multiplication.
    low = math.nextafter(math.fsum(pair[0] for pair in intervals), -math.inf)
    high = math.nextafter(math.fsum(pair[1] for pair in intervals), math.inf)
    charge = [math.nextafter(low / sample_rate_hz, -math.inf),
              math.nextafter(high / sample_rate_hz, math.inf)]
    energy = [math.nextafter(charge[0] * voltage_v, -math.inf),
              math.nextafter(charge[1] * voltage_v, math.inf)]
    return charge, energy


def _energy_history_relative_bound(energy_interval, nominal_energy, width):
    low, high = energy_interval
    if (not all(math.isfinite(value) for value in (low, high, nominal_energy, width))
            or not 0 < low <= nominal_energy <= high or width < 0):
        raise ValueError("Energy-relative history policy requires positive finite energy and interval lower bound")
    denominator = min(abs(low), abs(high))
    bound = width / denominator
    if width > 0:
        bound = math.nextafter(bound, math.inf)
    if not math.isfinite(bound):
        raise ValueError("Unsafe denominator or nonfinite relative history bound")
    return bound


def prove_filter_marker_total(
    capture: Capture,
    wire_path: str | Path,
    window: tuple[int, int],
    calibration: dict,
    voltage_mv: float,
    sample_rate_hz: int = 100_000,
    *,
    history_policy: str = "current_equivalence_v1",
) -> dict:
    """Return an inspectable proof; invalid input gives reasons and null totals.

    window_samples and the local guard are half-open. Wire QA also
    examines the word at stop and its incoming counter transition. The full
    capture's digital values must agree with wire data. Filter replay is checked
    over the full capture; history bounds apply to every integrated sample.
    """
    proof = {
        "schema_version": 1,
        "method": "bounded_filter_replay_marker_total",
        "decoder_reference": "ppk2-api / Nordic serialDevice.ts getAdcResult",
        "valid": False, "reasons": [], "warnings": [],
        "window_samples": None, "guard_window_samples": None,
        "guard_qa_includes_stop": True,
        "sample_rate_hz": sample_rate_hz,
        "voltage_mv": None, "wire_sha256": None,
        "wire_sample_count": None, "captured_sample_count": None,
        "range_code": None, "range_counts_guard": {}, "constant_range_guard": False,
        "counter_anomaly_indices_guard": [], "outside_counter_anomaly_count": 0,
        "invalid_range_indices_guard": [], "outside_invalid_range_count": 0,
        "bit17_indices_guard": [], "outside_bit17_count": 0,
        "nonfinite_current_indices_guard": [],
        "wire_logic_match_full_capture": False, "wire_logic_mismatch_count": None,
        "marker_window_complete": False,
        "calibration_valid": False, "calibration_sha256": None,
        "filter_parameters": {"alpha": _ALPHA, "alpha5": _ALPHA5, "samples": 3},
        "filter_initial_state": {"rolling_avg": None, "rolling_avg4": None, "prev_range": None,
                                 "after_spike": 0, "consecutive_range_samples": 0},
        "filter_tolerance_uA": FILTER_TOLERANCE_UA,
        "filter_replay_max_difference_uA": None, "filter_replay_compared_samples": 0,
        "filter_replay_match": False, "filter_replay_nonfinite_indices": [],
        "global_adc_domain_values": 81920, "global_adc_bounds_A": None,
        "global_state_bounds_A": None, "global_state_invariant": False,
        "history_bound_valid": False, "history_interval_max_width_uA": None,
        "combined_error_bound_uA": None, "history_clean_suffix_start": None,
        "history_last_suspect_index": None, "history_suspect_count": 0,
        "history_state_converged_samples": {"fast": None, "slow": None},
        "history_interval_algorithm": "binary64_monotone_endpoints_with_control_state_union",
        "charge_interval_uC": None, "energy_interval_uJ": None,
        "charge_interval_width_uC": None, "energy_interval_width_uJ": None,
        "charge_total_uC": None, "energy_total_uJ": None,
        "limitation": "Certifies recorded-data decoding and bounds prior filter-state influence, not analog accuracy during range switching. Modulo-64 continuity cannot detect losses of multiples of 64. Whole-endpoint local marker energy; no baseline/excess or internal RF-only claim.",
    }
    if history_policy == "energy_relative_v2":
        proof.update(schema_version=2, history_policy=history_policy,
                     energy_history_relative_tolerance=ENERGY_HISTORY_RELATIVE_TOLERANCE,
                     energy_history_relative_bound=None, energy_history_budget_valid=False,
                     energy_history_budget_scope="Software history-state uncertainty only; not instrument accuracy")
    reasons = proof["reasons"]
    try:
        if history_policy not in ("current_equivalence_v1", "energy_relative_v2"):
            raise ValueError("Unknown filter history policy")
        if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int) or sample_rate_hz <= 0:
            raise ValueError("Sample rate must be a positive integer")
        voltage = float(voltage_mv)
        if not math.isfinite(voltage) or voltage <= 0:
            raise ValueError("Voltage must be positive and finite")
        proof["voltage_mv"] = voltage
        voltage_v = voltage / 1000
        if len(window) != 2:
            raise ValueError("Expected a two-index marker window")
        if any(isinstance(value, bool) for value in window):
            raise ValueError("Marker indices must be integers")
        start, stop = (operator.index(value) for value in window)
        count = len(capture.samples_uA)
        proof["captured_sample_count"] = count
        proof["window_samples"] = [start, stop]
        proof["guard_window_samples"] = [start - FILTER_GUARD_SAMPLES, stop]
        if not FILTER_GUARD_SAMPLES <= start < stop < count:
            raise ValueError("Marker needs three preceding samples and a following LOW sample")
        if stop - start < 3:
            raise ValueError("Marker interval must contain at least three samples")
        if len(capture.logic_bits) != count:
            raise ValueError("Decoded digital and current sample counts differ")

        raw = Path(wire_path).read_bytes()
        proof["wire_sha256"] = hashlib.sha256(raw).hexdigest()
        if len(raw) != count * 4:
            raise ValueError("Wire length does not match the decoded capture")
        words = [value for (value,) in struct.iter_unpack("<I", raw)]
        proof["wire_sample_count"] = len(words)
        logic = [operator.index(value) for value in capture.logic_bits]
        mismatch = sum(not 0 <= value <= 255 or value != word >> 24
                       for value, word in zip(logic, words))
        proof["wire_logic_mismatch_count"] = mismatch
        proof["wire_logic_match_full_capture"] = mismatch == 0
        if mismatch:
            reasons.append("Decoded digital values do not match wire over the full capture")
        complete = (not words[start - 1] & (1 << 24)
                    and not words[stop] & (1 << 24)
                    and all(word & (1 << 24) for word in words[start:stop]))
        proof["marker_window_complete"] = bool(complete)
        if not complete:
            reasons.append("Window does not match complete local D0 rising/falling edges")

        guard_start = start - FILTER_GUARD_SAMPLES
        ranges = [(word >> 14) & 7 for word in words]
        counts = collections.Counter(ranges[guard_start:stop])
        proof["range_counts_guard"] = {str(key): value for key, value in counts.items()}
        proof["constant_range_guard"] = len(counts) == 1 and next(iter(counts)) <= 4
        if proof["constant_range_guard"]:
            proof["range_code"] = ranges[start]
        previous_counter = None
        suspects = set()
        for index, word in enumerate(words):
            in_guard = guard_start <= index <= stop
            counter = (word >> 18) & 63
            if previous_counter is not None and counter != (previous_counter + 1) % 64:
                suspects.update((index - 1, index))
                if in_guard or guard_start <= index - 1 <= stop:
                    proof["counter_anomaly_indices_guard"].append(index)
                else:
                    proof["outside_counter_anomaly_count"] += 1
            previous_counter = counter
            if ranges[index] > 4:
                suspects.add(index)
                if in_guard:
                    proof["invalid_range_indices_guard"].append(index)
                else:
                    proof["outside_invalid_range_count"] += 1
            if word & (1 << 17):
                suspects.add(index)
                if in_guard:
                    proof["bit17_indices_guard"].append(index)
                else:
                    proof["outside_bit17_count"] += 1
        for key, description in (
            ("counter_anomaly_indices_guard", "Counter discontinuity"),
            ("invalid_range_indices_guard", "Invalid range code"),
            ("bit17_indices_guard", "Bit 17 set"),
        ):
            if proof[key]:
                reasons.append(f"{description} touches the guard, pulse or falling boundary")
        for key, description in (
            ("outside_counter_anomaly_count", "counter transition anomalies"),
            ("outside_invalid_range_count", "invalid range words"),
            ("outside_bit17_count", "words with bit 17 set"),
        ):
            if proof[key]:
                proof["warnings"].append(f"{proof[key]} {description} outside the guarded interval; retained without repair")
        relevant_currents = [float(value) for value in capture.samples_uA[guard_start:stop + 1]]
        proof["nonfinite_current_indices_guard"] = [guard_start + i for i, value in enumerate(relevant_currents)
                                                    if not math.isfinite(value)]
        if proof["nonfinite_current_indices_guard"]:
            reasons.append("Nonfinite current touches the guarded interval")
        proof["filter_replay_nonfinite_indices"] = [i for i, value in enumerate(capture.samples_uA)
                                                     if not math.isfinite(float(value))]
        if proof["filter_replay_nonfinite_indices"]:
            reasons.append("Full recorded current stream must be finite for replay")

        coefficients = {name: {str(i): float(calibration[name][str(i)]) for i in range(5)}
                        for name in _COEFFICIENTS}
        if any(not math.isfinite(value) for values in coefficients.values() for value in values.values()):
            raise ValueError("Calibration coefficients must all be finite")
        if any(value <= 0 for value in coefficients["R"].values()):
            raise ValueError("Calibration resistances must be positive")
        proof["calibration_valid"] = True
        proof["calibration_sha256"] = hashlib.sha256(
            json.dumps(coefficients, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

        coefficients_tuple = tuple(tuple(coefficients[name][str(i)] for i in range(5)) for name in _COEFFICIENTS)
        amin, amax, low, high, iterations = _global_bounds(coefficients_tuple, voltage_v)
        proof.update(global_adc_bounds_A=[amin, amax], global_state_bounds_A=[low, high],
                     global_state_invariant=True, global_state_invariant_expansions=iterations)
        history = sorted(index for index in suspects if index < start)
        proof["history_suspect_count"] = len(history)
        proof["history_last_suspect_index"] = history[-1] if history else None
        proof["history_clean_suffix_start"] = history[-1] + 1 if history else 0
        if proof["history_clean_suffix_start"] > guard_start:
            reasons.append("Uncertain history overlaps the local marker guard")

        replay, intervals, converged = _replay(words, coefficients_tuple, voltage_v,
                                              suspects, (start, stop), (low, high))
        if not all(math.isfinite(value) for value in replay):
            raise ValueError("Full filter replay must be finite")
        proof["filter_replay_compared_samples"] = len(replay)
        proof["history_state_converged_samples"] = converged
        if not proof["filter_replay_nonfinite_indices"]:
            maximum = max(_upper_difference(max(value, float(actual)), min(value, float(actual)))
                          for value, actual in zip(replay, capture.samples_uA))
            proof["filter_replay_max_difference_uA"] = maximum
            proof["filter_replay_match"] = maximum <= FILTER_TOLERANCE_UA
            if not proof["filter_replay_match"]:
                reasons.append("Independent full filter replay differs from recorded current by more than 1e-6 uA")
        if (len(intervals) != stop - start or
                not all(math.isfinite(lo) and math.isfinite(hi) and lo <= hi for lo, hi in intervals)):
            raise ValueError("Invalid marker history intervals")
        if any(not lo <= value <= hi for (lo, hi), value in zip(intervals, replay[start:stop])):
            raise ValueError("Nominal replay escapes the proven history enclosure")
        width = max(_upper_difference(hi, lo) for lo, hi in intervals)
        proof["history_interval_max_width_uA"] = width
        maximum = proof["filter_replay_max_difference_uA"]
        combined = None if maximum is None else maximum + width
        if combined:
            combined = math.nextafter(combined, math.inf)
        proof["combined_error_bound_uA"] = combined
        if history_policy == "current_equivalence_v1":
            proof["history_bound_valid"] = (combined is not None and math.isfinite(combined)
                                            and combined <= FILTER_TOLERANCE_UA)
            if not proof["history_bound_valid"]:
                reasons.append("Replay error plus uncertain-history width exceeds 1e-6 uA")
        charge_interval, energy_interval = _total_interval(intervals, sample_rate_hz, voltage_v)
        if not all(math.isfinite(value) for value in charge_interval + energy_interval):
            raise ValueError("Nonfinite total interval")
        proof.update(charge_interval_uC=charge_interval, energy_interval_uJ=energy_interval,
                     charge_interval_width_uC=_upper_difference(charge_interval[1], charge_interval[0]),
                     energy_interval_width_uJ=_upper_difference(energy_interval[1], energy_interval[0]))
        if history_policy == "energy_relative_v2":
            nominal_energy = (math.fsum(replay[start:stop]) / sample_rate_hz) * voltage_v
            relative = _energy_history_relative_bound(energy_interval, nominal_energy,
                                                       proof["energy_interval_width_uJ"])
            passed = relative <= ENERGY_HISTORY_RELATIVE_TOLERANCE
            proof.update(energy_history_relative_bound=relative, energy_history_budget_valid=passed,
                         history_bound_valid=passed)
            if not passed:
                reasons.append("Uncertain-history energy interval exceeds the 0.01% software budget")
        if not reasons:
            charge = math.fsum(replay[start:stop]) / sample_rate_hz
            energy = charge * voltage_v
            if not (charge_interval[0] <= charge <= charge_interval[1]
                    and energy_interval[0] <= energy <= energy_interval[1]):
                raise ValueError("Nominal total escapes the proven interval")
            proof.update(valid=True, charge_total_uC=charge, energy_total_uJ=energy)
    except (AttributeError, OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        reasons.append(f"{type(exc).__name__}: {exc}")
    return proof
