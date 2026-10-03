"""Prove totals over every local radio marker of a fragmented transfer.

The gaps remain recorded but are not integrated. Each frame must independently
pass the existing direct-ADC proof; a failed frame invalidates both endpoints.
No pulse is selected, repaired, modeled, or inferred from the other radio.
"""
from __future__ import annotations

import math
import operator
from pathlib import Path
from typing import Mapping

from .marker_analysis import (
    MARKER_BIT, MINIMUM_PULSE_SAMPLES, RADIO_MARKER_SOURCE,
    RADIO_MARKER_SOURCES, RADIO_ROLE_SCOPES, TOTAL_ONLY_ENERGY_POLICY,
    TOTAL_ONLY_EXCESS_DEFINITION,
)
from .marker_totals import prove_marker_total
from .models import Metrics
from .ppk import Capture


FRAGMENT_TOTALS_INTEGRATION_METHOD = "independent_radio_fragment_marker_totals"
_FRAME_COUNTS = (2, 8, 16)
_MEASUREMENT_SCOPE = (
    "Whole powered module current summed over every local D0 frame interval; "
    "inter-frame gaps are excluded. TX uses transmission-active intervals. RX uses "
    "sync detected to packet end/abort, excluding preamble, sync acquisition and "
    "listening. Local PPK clocks remain independent; durations need not agree. "
    "Marker count does not prove payload delivery or correspondence between frames."
)


def analyze_fragmented_radio_marker_pair(
    captures: Mapping[str, Capture], *, sample_rate_hz: int,
    voltages_mv: Mapping[str, int], wire_paths: Mapping[str, str | Path],
    calibrations: Mapping[str, dict], expected_frame_count: int,
) -> tuple[dict[str, Metrics], dict]:
    """Integrate exactly 2, 8 or 16 complete, independently proven local pulses."""
    method = FRAGMENT_TOTALS_INTEGRATION_METHOD
    diagnostics = {
        "method": method, "integration_method": method, "valid": False,
        "energy_policy": TOTAL_ONLY_ENERGY_POLICY,
        "expected_frame_count": expected_frame_count,
        "marker_bit": MARKER_BIT, "source": RADIO_MARKER_SOURCE,
        "minimum_pulse_samples": MINIMUM_PULSE_SAMPLES,
        "width_tolerance_samples": None,
        "width_comparison": "not_applicable_independent_radio_intervals",
        "edge_convention": "[first HIGH sample, first following LOW sample)",
        "hardware_synchronized": False, "measurement_scope": _MEASUREMENT_SCOPE,
        "baseline_policy": "Not used or calculated; no baseline or excess metric.",
        "gap_policy": "Excluded from active duration, charge, energy, mean and peak.",
        "roles": {}, "reasons": [], "warnings": [],
    }
    reasons = diagnostics["reasons"]
    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        reasons.append("Positive integer sample rate required")
    if type(expected_frame_count) is not int or expected_frame_count not in _FRAME_COUNTS:
        reasons.append("Expected frame count must be exactly 2, 8 or 16")
    configuration_valid = not reasons
    for role in ("tx", "rx"):
        info = diagnostics["roles"][role] = {
            "valid": False, "source": RADIO_MARKER_SOURCES[role],
            "measurement_scope": RADIO_ROLE_SCOPES[role],
            "windows_samples": [], "frame_proofs": [],
            "duration_samples": None, "charge_total_uC": None,
            "energy_total_uJ": None, "reasons": [], "warnings": [],
        }
        if not configuration_valid:
            continue
        try:
            capture = captures.get(role)
            if capture is None:
                raise ValueError("Missing decoded capture")
            samples, logic = capture.samples_uA, capture.logic_bits
            count = len(samples)
            if isinstance(capture.trigger_index, bool):
                raise ValueError("Software marker must be an integer sample index")
            trigger = operator.index(capture.trigger_index)
            info.update(sample_count=count, software_trigger_index=trigger)
            if count < 100 or not 10 <= trigger < count:
                raise ValueError("Capture is too short or has an invalid software marker")
            if len(logic) != count:
                raise ValueError("Digital/current sample lengths differ")
            loss = capture.sample_loss_percent
            if not math.isfinite(loss) or not 0 <= loss <= 1:
                raise ValueError("Acquisition sample loss exceeds the paired acceptance range")
            if any(not math.isfinite(value) for value in samples):
                raise ValueError("Nonfinite current sample")
            voltage = voltages_mv.get(role)
            if isinstance(voltage, bool) or voltage is None or not math.isfinite(voltage) or voltage <= 0:
                raise ValueError("Missing or invalid endpoint voltage")
            bits = [operator.index(value) for value in logic]
            if any(not 0 <= value <= 255 for value in bits):
                raise ValueError("Digital sample is not an 8-bit value")
            windows, first = [], None
            for index, value in enumerate(bits):
                high = bool(value & (1 << MARKER_BIT))
                if high and first is None:
                    first = index
                elif not high and first is not None:
                    windows.append((first, index))
                    first = None
            if first is not None:
                windows.append((first, count))
            info.update(pulse_count=len(windows), windows_samples=[list(window) for window in windows])
            if bits[0] & (1 << MARKER_BIT) or bits[-1] & (1 << MARKER_BIT):
                raise ValueError("Marker HIGH at capture boundary; pulse is truncated")
            if len(windows) != expected_frame_count:
                raise ValueError(f"Expected exactly {expected_frame_count} complete D0 pulses; found {len(windows)}")
            if any(start <= trigger for start, _ in windows):
                raise ValueError("D0 pulse starts before or at the software marker")
            if any(stop - start < MINIMUM_PULSE_SAMPLES for start, stop in windows):
                raise ValueError("D0 pulse is too short; possible digital glitch")
            if wire_paths is None or role not in wire_paths:
                raise ValueError("Every endpoint requires wire evidence")
            if calibrations is None or role not in calibrations:
                raise ValueError("Every endpoint requires recorded calibration")
            for frame_index, window in enumerate(windows, 1):
                proof = prove_marker_total(
                    capture, wire_paths[role], window, calibrations[role], voltage,
                    sample_rate_hz=sample_rate_hz,
                )
                info["frame_proofs"].append(proof)
                info["warnings"].extend(f"frame {frame_index}: {warning}" for warning in proof["warnings"])
                if not proof["valid"] or proof["reasons"]:
                    info["reasons"].append(
                        f"frame {frame_index}: Direct-ADC total proof failed: "
                        + "; ".join(proof["reasons"] or ["invalid proof"])
                    )
                elif any(isinstance(proof.get(key), bool)
                         or not isinstance(proof.get(key), (int, float))
                         or not math.isfinite(proof[key])
                         for key in ("charge_total_uC", "energy_total_uJ")):
                    info["reasons"].append(f"frame {frame_index}: Direct-ADC proof returned nonfinite totals")
            if not info["reasons"]:
                charge = math.fsum(proof["charge_total_uC"] for proof in info["frame_proofs"])
                energy = math.fsum(proof["energy_total_uJ"] for proof in info["frame_proofs"])
                duration = sum(stop - start for start, stop in windows)
                mean = charge * sample_rate_hz / duration
                if not all(math.isfinite(value) for value in (charge, energy, mean)):
                    raise ValueError("Combined active-frame totals are not finite")
                info.update(valid=True, duration_samples=duration,
                            charge_total_uC=charge, energy_total_uJ=energy)
        except (AttributeError, ValueError, TypeError, OSError, OverflowError) as exc:
            info["reasons"].append(str(exc))
        reasons.extend(f"{role}: {reason}" for reason in info["reasons"])
        diagnostics["warnings"].extend(f"{role}: {warning}" for warning in info["warnings"])
    diagnostics["valid"] = not reasons and all(info["valid"] for info in diagnostics["roles"].values())
    shared = {
        "marker_diagnostics": diagnostics, "energy_policy": TOTAL_ONLY_ENERGY_POLICY,
        "total_energy_definition": (
            "Sum of independently calibrated wire ADC totals over every local frame marker; "
            "decoded RAW must match. No gaps, clipping or baseline subtraction."
        ),
        "excess_energy_definition": TOTAL_ONLY_EXCESS_DEFINITION,
    }
    if not diagnostics["valid"]:
        return {role: Metrics(False, None, None, integration_method=method,
                              analysis_error="; ".join(reasons), analysis_diagnostics=shared)
                for role in ("tx", "rx")}, diagnostics
    metrics = {}
    for role in ("tx", "rx"):
        capture, info = captures[role], diagnostics["roles"][role]
        windows = info["windows_samples"]
        windows_ms = tuple(tuple((index - capture.trigger_index) * 1000 / sample_rate_hz
                                 for index in window) for window in windows)
        metrics[role] = Metrics(
            True, None, None, event_start_ms=windows_ms[0][0],
            event_duration_ms=info["duration_samples"] * 1000 / sample_rate_hz,
            tx_mean_uA=info["charge_total_uC"] * sample_rate_hz / info["duration_samples"],
            tx_peak_uA=max(capture.samples_uA[index] for start, stop in windows for index in range(start, stop)),
            charge_total_uC=info["charge_total_uC"], energy_total_uJ=info["energy_total_uJ"],
            integration_method=method, integration_windows_ms=windows_ms,
            analysis_diagnostics=shared,
        )
    return metrics, diagnostics
