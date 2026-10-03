"""Prove a marker total without baseline or stateful-decoder assumptions.

This is a sufficient, deliberately narrow proof for ppk2-api. Its
range-change filter substitutes an IIR output for a range transition and the
following two samples. A constant valid range from start-3 to stop-1 therefore
makes every integrated sample a direct calibrated ADC value, independently of
earlier IIR state. No samples are repaired, removed, clipped or reindexed.

Callers must opt into this policy and retain their separate pair, delivery and
marker-count gates. This function does not calculate baseline/excess metrics.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import operator
from pathlib import Path
from .storage import resolve_measurement_path
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ppk import Capture


DIRECT_ADC_TOLERANCE_UA = 1e-6
FILTER_GUARD_SAMPLES = 3
_COEFFICIENTS = ("R", "O", "GS", "GI", "S", "I", "UG")


def prove_marker_total(
    capture: Capture,
    wire_path: str | Path,
    window: tuple[int, int],
    calibration: dict,
    voltage_mv: float,
    sample_rate_hz: int = 100_000,
) -> dict:
    """Return an inspectable proof; invalid input gives reasons and null totals.

    window_samples and the constant-range guard are half-open. Wire QA also
    examines the word at stop and its incoming counter transition. The full
    capture's digital values must agree with wire data. ADC agreement is checked
    for every integrated sample against the fixed 1e-6 microampere tolerance.
    """
    proof = {
        "schema_version": 1,
        "method": "direct_adc_constant_range_marker_total",
        "decoder_reference": "ppk2-api; three samples affected per range change",
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
        "direct_adc_tolerance_uA": DIRECT_ADC_TOLERANCE_UA,
        "direct_adc_max_difference_uA": None, "direct_adc_compared_samples": 0,
        "direct_adc_match": False,
        "charge_total_uC": None, "energy_total_uJ": None,
        "limitation": "Modulo-64 continuity is not a checksum and cannot prove zero sample loss. Total covers the whole endpoint in this marker interval; it is not baseline-subtracted or internal RF-only energy.",
    }
    reasons = proof["reasons"]
    try:
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

        raw = resolve_measurement_path(wire_path).read_bytes()
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
        else:
            reasons.append("Valid constant range over [start-3,stop) is required to exclude IIR dependence")
        previous_counter = None
        for index, word in enumerate(words):
            in_guard = guard_start <= index <= stop
            counter = (word >> 18) & 63
            if previous_counter is not None and counter != (previous_counter + 1) % 64:
                if in_guard:
                    proof["counter_anomaly_indices_guard"].append(index)
                else:
                    proof["outside_counter_anomaly_count"] += 1
            previous_counter = counter
            if ranges[index] > 4:
                if in_guard:
                    proof["invalid_range_indices_guard"].append(index)
                else:
                    proof["outside_invalid_range_count"] += 1
            if word & (1 << 17):
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

        coefficients = {name: {str(i): float(calibration[name][str(i)]) for i in range(5)}
                        for name in _COEFFICIENTS}
        if any(not math.isfinite(value) for values in coefficients.values() for value in values.values()):
            raise ValueError("Calibration coefficients must all be finite")
        if any(value <= 0 for value in coefficients["R"].values()):
            raise ValueError("Calibration resistances must be positive")
        proof["calibration_valid"] = True
        proof["calibration_sha256"] = hashlib.sha256(
            json.dumps(coefficients, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

        if proof["constant_range_guard"] and not proof["nonfinite_current_indices_guard"]:
            key = str(proof["range_code"])
            direct = []
            differences = []
            for index in range(start, stop):
                adc = (words[index] & 0x3FFF) * 4
                unscaled = ((adc - coefficients["O"][key])
                            * ((1.8 / 163840) / coefficients["R"][key]))
                current = coefficients["UG"][key] * (
                    unscaled * (coefficients["GS"][key] * unscaled + coefficients["GI"][key])
                    + (coefficients["S"][key] * voltage_v + coefficients["I"][key])) * 1e6
                if not math.isfinite(current):
                    raise ValueError("Independent calibrated ADC value is not finite")
                direct.append(current)
                differences.append(abs(current - float(capture.samples_uA[index])))
            proof["direct_adc_compared_samples"] = len(direct)
            maximum = max(differences)
            proof["direct_adc_max_difference_uA"] = maximum if math.isfinite(maximum) else None
            proof["direct_adc_match"] = math.isfinite(maximum) and maximum <= DIRECT_ADC_TOLERANCE_UA
            if not proof["direct_adc_match"]:
                reasons.append("Independent calibrated ADC differs from decoded current by more than 1e-6 uA")
            if not reasons:
                charge = math.fsum(direct) / sample_rate_hz
                energy = charge * voltage_v
                if not math.isfinite(charge) or not math.isfinite(energy):
                    raise ValueError("Integrated charge or energy is not finite")
                proof.update(valid=True, charge_total_uC=charge, energy_total_uJ=energy)
    except (AttributeError, OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        reasons.append(f"{type(exc).__name__}: {exc}")
    return proof
