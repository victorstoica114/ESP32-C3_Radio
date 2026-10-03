"""Integrate hardware marker intervals on two independent PPK2 clocks."""
from __future__ import annotations

import math
import operator
from pathlib import Path
import statistics
import struct
from typing import Mapping

from .models import Metrics
from .ppk import Capture


INTEGRATION_METHOD = "common_tx_hardware_marker"
RADIO_INTEGRATION_METHOD = "independent_radio_hardware_markers"
RADIO_TOTALS_INTEGRATION_METHOD = "independent_radio_hardware_marker_totals"
TOTAL_ONLY_ENERGY_POLICY = "total_only_with_direct_adc_proof"
FILTER_TOTAL_ONLY_ENERGY_POLICY = "total_only_with_bounded_filter_replay_proof"
FILTER_RADIO_TOTALS_INTEGRATION_METHOD = "independent_radio_hardware_filter_marker_totals"
ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY = "total_only_with_bounded_filter_energy_proof_v2"
ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD = "independent_radio_hardware_filter_energy_totals_v2"
TOTAL_ONLY_EXCESS_DEFINITION = "Not calculated: total-only marker metric; no baseline subtraction."
MARKER_BIT = 0
WIDTH_TOLERANCE_SAMPLES = 2
MINIMUM_PULSE_SAMPLES = 3
MARKER_SOURCE = "TX DIO17 / RAT_GPO0 / active HIGH"
RADIO_MARKER_SOURCE = "Local TX and RX DIO17 / active HIGH"
RADIO_MARKER_SOURCES = {"tx": MARKER_SOURCE, "rx": "RX DIO17 / RAT_GPO1 / active HIGH"}
RADIO_ROLE_SCOPES = {
    "tx": "Whole powered TX module current during its local transmission-active marker interval.",
    "rx": (
        "Whole powered RX module current from sync detected to packet end/abort. "
        "Excludes preamble, sync acquisition and listening; a marker does not prove packet delivery."
    ),
}
RADIO_MEASUREMENT_SCOPE = (
    "Current of each whole powered module integrated between its own local D0 rising/falling edges. "
    "TX uses its transmission-active interval. RX uses sync detected to packet end/abort, "
    "excluding preamble, sync acquisition and listening. The two PPK2 sample clocks remain "
    "independent; local marker durations need not agree."
)
MEASUREMENT_SCOPE = (
    "Current integrated between local D0 rising/falling edges of the common TX marker. "
    "The two PPK2 sample clocks remain independent. RX energy covers the TX interval, "
    "not an independently delimited RX event or the full transaction."
)
EXCESS_DEFINITION = (
    "Legacy rectified excess: V * sum(max(0, current - pretrigger median)) / sample_rate. "
    "This is not signed baseline subtraction or RF-only energy."
)


def _wire_quality(path: Path, sample_count: int, window, baseline_window) -> dict:
    raw = path.read_bytes()
    if len(raw) != sample_count * 4:
        raise ValueError("Wire length does not match the decoded marker trace")
    previous = None
    anomalies = []
    for index, (word,) in enumerate(struct.iter_unpack("<I", raw)):
        value = (word >> 18) & 63
        if previous is not None and value != (previous + 1) % 64:
            anomalies.append(index)
        previous = value
    # A transition at either boundary touches a sample used by the estimate.
    relevant = [index for index in anomalies
                if any(start <= index <= stop for start, stop in (window, baseline_window))]
    return {
        "status": "review_required" if relevant else "passed_relevant_intervals",
        "counter_bits": [18, 23], "counter_modulus": 64,
        "transition_anomaly_count": len(anomalies), "first_anomaly_indices": anomalies[:32],
        "relevant_anomaly_count": len(relevant), "first_relevant_anomaly_indices": relevant[:32],
        "scope": "Marker interval and legacy pretrigger baseline, including boundary transitions",
        "limitation": "Modulo-64 continuity cannot detect losses of multiples of 64; no samples are repaired or removed.",
    }


def _analyze_marker_pair(
    captures: Mapping[str, Capture], *, sample_rate_hz: int,
    voltages_mv: Mapping[str, int], wire_paths: Mapping[str, str | Path] | None = None,
    independent_radio_markers: bool = False,
    marker_totals_only: bool = False, calibrations: Mapping[str, dict] | None = None,
    filter_aware_totals: bool = False,
    filter_history_policy: str = "current_equivalence_v1",
) -> tuple[dict[str, Metrics], dict]:
    """Fail closed for the entire pair; never select, smooth or model a pulse."""
    if type(marker_totals_only) is not bool:
        raise ValueError("marker_totals_only must be an explicit boolean")
    if marker_totals_only and not independent_radio_markers:
        raise ValueError("Total-only marker proof requires independent radio markers")
    if type(filter_aware_totals) is not bool:
        raise ValueError("filter_aware_totals must be an explicit boolean")
    if filter_aware_totals and not marker_totals_only:
        raise ValueError("Filter-aware proof requires explicit total-only independent radio markers")
    if (not isinstance(filter_history_policy, str)
            or filter_history_policy not in {"current_equivalence_v1", "energy_relative_v2"}
            or (filter_history_policy != "current_equivalence_v1" and not filter_aware_totals)):
        raise ValueError("An explicit supported history policy requires filter-aware totals")
    energy_budget = filter_history_policy == "energy_relative_v2"
    energy_policy = (ENERGY_FILTER_TOTAL_ONLY_ENERGY_POLICY if energy_budget else
                     FILTER_TOTAL_ONLY_ENERGY_POLICY if filter_aware_totals else TOTAL_ONLY_ENERGY_POLICY)
    method = (ENERGY_FILTER_RADIO_TOTALS_INTEGRATION_METHOD if energy_budget else
              FILTER_RADIO_TOTALS_INTEGRATION_METHOD if filter_aware_totals else
              RADIO_TOTALS_INTEGRATION_METHOD if marker_totals_only else
              RADIO_INTEGRATION_METHOD if independent_radio_markers else INTEGRATION_METHOD)
    diagnostics = {
        "valid": False, "marker_bit": MARKER_BIT,
        "source": RADIO_MARKER_SOURCE if independent_radio_markers else MARKER_SOURCE,
        "width_tolerance_samples": None if independent_radio_markers else WIDTH_TOLERANCE_SAMPLES,
        "minimum_pulse_samples": MINIMUM_PULSE_SAMPLES,
        "edge_convention": "[first HIGH sample, first following LOW sample)",
        "hardware_synchronized": False,
        "measurement_scope": RADIO_MEASUREMENT_SCOPE if independent_radio_markers else MEASUREMENT_SCOPE,
        "roles": {}, "reasons": [], "warnings": [],
    }
    if independent_radio_markers:
        diagnostics["width_comparison"] = "not_applicable_independent_radio_intervals"
    if marker_totals_only:
        diagnostics["energy_policy"] = energy_policy
        diagnostics["baseline_policy"] = "Not used or calculated; legacy counter QA remains diagnostic only."
    if energy_budget:
        diagnostics["filter_history_policy"] = filter_history_policy
    reasons = diagnostics["reasons"]
    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        reasons.append("Positive integer sample rate required")
    for role in ("tx", "rx"):
        info = diagnostics["roles"][role] = {}
        if independent_radio_markers:
            info.update(source=RADIO_MARKER_SOURCES[role], measurement_scope=RADIO_ROLE_SCOPES[role])
        capture = captures.get(role)
        try:
            if reasons and "Positive integer sample rate required" in reasons:
                continue
            if capture is None:
                raise ValueError("Missing decoded capture")
            samples = capture.samples_uA
            count, trigger = len(samples), capture.trigger_index
            if count < 100 or not 10 <= trigger < count:
                raise ValueError("Capture is too short or has an invalid software marker")
            if len(capture.logic_bits) != count:
                raise ValueError("Digital/current sample lengths differ")
            if not math.isfinite(capture.sample_loss_percent) or capture.sample_loss_percent > 1:
                raise ValueError("Acquisition sample loss exceeds the paired acceptance range")
            if any(not math.isfinite(value) for value in samples):
                raise ValueError("Nonfinite current sample")
            voltage = voltages_mv.get(role)
            if voltage is None or not math.isfinite(voltage) or voltage <= 0:
                raise ValueError("Missing or invalid endpoint voltage")
            bits = [operator.index(value) for value in capture.logic_bits]
            if any(not 0 <= value <= 255 for value in bits):
                raise ValueError("Digital sample is not an 8-bit value")
            high = [bool(value & (1 << MARKER_BIT)) for value in bits]
            windows, first = [], None
            for index, state in enumerate(high):
                if state and first is None:
                    first = index
                elif not state and first is not None:
                    windows.append((first, index))
                    first = None
            if first is not None:
                windows.append((first, count))
            info.update(software_trigger_index=trigger, sample_count=count, pulse_count=len(windows))
            if high[0] or high[-1]:
                raise ValueError("Marker HIGH at capture boundary; pulse is truncated")
            if len(windows) != 1:
                raise ValueError(f"Expected exactly one complete D0 pulse; found {len(windows)}")
            start, stop = windows[0]
            info.update(window_samples=[start, stop], duration_samples=stop - start)
            if start <= trigger:
                raise ValueError("D0 pulse starts before or at the software marker")
            if stop - start < MINIMUM_PULSE_SAMPLES:
                raise ValueError("D0 pulse is too short; possible digital glitch")
            baseline_start = min(int(.010 * sample_rate_hz), trigger // 4)
            baseline_stop = max(baseline_start + 1, trigger - int(.005 * sample_rate_hz))
            info["baseline_window_samples"] = [baseline_start, baseline_stop]
            if wire_paths is not None:
                if role not in wire_paths:
                    raise ValueError("Missing wire evidence for counter QA")
                info["counter_qa"] = _wire_quality(
                    Path(wire_paths[role]), count, (start, stop), (baseline_start, baseline_stop),
                )
                if info["counter_qa"]["relevant_anomaly_count"] and not marker_totals_only:
                    raise ValueError("Counter discontinuity touches marker integration or baseline")
                if marker_totals_only and info["counter_qa"]["relevant_anomaly_count"]:
                    diagnostics["warnings"].append(
                        f"{role}: legacy counter QA remains review_required; no baseline or excess metric is calculated. "
                        "Total-only acceptance requires the separately selected local wire proof."
                    )
                elif info["counter_qa"]["transition_anomaly_count"]:
                    diagnostics["warnings"].append(f"{role}: counter anomalies outside integration/baseline intervals")
            else:
                info["counter_qa"] = {"status": "not_checked", "reason": "No wire paths supplied"}
            if marker_totals_only:
                if wire_paths is None or role not in wire_paths:
                    raise ValueError("Total-only marker metric requires wire evidence")
                from .marker_totals import prove_marker_total
                prove_total = prove_marker_total
                if filter_aware_totals:
                    from .filter_marker_totals import prove_filter_marker_total
                    prove_total = prove_filter_marker_total
                proof = info["total_qa"] = prove_total(
                    capture, wire_paths[role], (start, stop),
                    (calibrations or {}).get(role), voltage, sample_rate_hz=sample_rate_hz,
                    **({"history_policy": filter_history_policy} if filter_aware_totals else {}),
                )
                diagnostics["warnings"].extend(f"{role}: {warning}" for warning in proof.get("warnings", []))
                if not proof.get("valid") or proof.get("reasons"):
                    raise ValueError(("Filter replay" if filter_aware_totals else "Direct-ADC") + " total proof failed: " + "; ".join(proof.get("reasons", ["invalid proof"])))
                if any(not isinstance(proof.get(key), (int, float)) or isinstance(proof[key], bool)
                       or not math.isfinite(proof[key]) for key in ("charge_total_uC", "energy_total_uJ")):
                    raise ValueError("Selected total proof returned nonfinite totals")
        except (ValueError, TypeError, OSError) as exc:
            reasons.append(f"{role}: {exc}")
    durations = [info.get("duration_samples") for info in diagnostics["roles"].values()]
    if not independent_radio_markers and all(value is not None for value in durations) and abs(durations[0] - durations[1]) > WIDTH_TOLERANCE_SAMPLES:
        reasons.append("TX/RX marker widths disagree by more than two samples")
    diagnostics["valid"] = not reasons
    shared = {
        "marker_diagnostics": diagnostics, "total_energy_definition": "V * sum(raw current) / sample_rate; no clipping",
        "excess_energy_definition": TOTAL_ONLY_EXCESS_DEFINITION if marker_totals_only else EXCESS_DEFINITION,
    }
    if marker_totals_only:
        shared["energy_policy"] = energy_policy
        shared["total_energy_definition"] = (
            "V * sum(independently calibrated wire ADC current) / sample_rate; "
            "decoded RAW current must match; no clipping or baseline subtraction."
        )
        if filter_aware_totals:
            shared["total_energy_definition"] = (
                "V * sum(independently replayed calibrated wire current with PPK range-transition filter) / sample_rate; "
                "decoded RAW current must match and prior filter-state influence must be bounded; "
                "no clipping or baseline subtraction. Numerical validation does not establish analog transition accuracy."
            )
        if energy_budget:
            shared["filter_history_policy"] = filter_history_policy
            shared["total_energy_definition"] += " Relative history-energy interval width is bounded separately at 0.01%."
    if reasons:
        return {role: Metrics(False, None, None, integration_method=method,
                              analysis_error="; ".join(reasons), analysis_diagnostics=shared)
                for role in ("tx", "rx")}, diagnostics
    metrics = {}
    for role in ("tx", "rx"):
        capture = captures[role]
        info = diagnostics["roles"][role]
        start, stop = info["window_samples"]
        values = capture.samples_uA[start:stop]
        voltage_v = voltages_mv[role] / 1000
        if marker_totals_only:
            baseline, legacy_excess = None, None
            total = info["total_qa"]["charge_total_uC"]
            energy = info["total_qa"]["energy_total_uJ"]
        else:
            baseline_start, baseline_stop = info["baseline_window_samples"]
            baseline = statistics.median(capture.samples_uA[baseline_start:baseline_stop])
            total = math.fsum(values) / sample_rate_hz
            legacy_excess = math.fsum(max(0, value - baseline) for value in values) / sample_rate_hz
            energy = total * voltage_v
        window_ms = ((start - capture.trigger_index) * 1000 / sample_rate_hz,
                     (stop - capture.trigger_index) * 1000 / sample_rate_hz)
        metrics[role] = Metrics(
            True, baseline, None, event_start_ms=window_ms[0],
            event_duration_ms=(stop - start) * 1000 / sample_rate_hz,
            tx_mean_uA=total * sample_rate_hz / (stop - start) if marker_totals_only else statistics.fmean(values), tx_peak_uA=max(values),
            charge_total_uC=total, charge_excess_uC=legacy_excess,
            energy_total_uJ=energy, energy_excess_uJ=None if marker_totals_only else legacy_excess * voltage_v,
            integration_method=method, integration_windows_ms=(window_ms,),
            analysis_diagnostics=shared,
        )
    return metrics, diagnostics


def analyze_tx_marker_pair(
    captures: Mapping[str, Capture], *, sample_rate_hz: int,
    voltages_mv: Mapping[str, int], wire_paths: Mapping[str, str | Path] | None = None,
) -> tuple[dict[str, Metrics], dict]:
    """Integrate the shared TX pulse; its local widths must agree within two samples."""
    return _analyze_marker_pair(captures, sample_rate_hz=sample_rate_hz,
                                voltages_mv=voltages_mv, wire_paths=wire_paths)


def analyze_radio_marker_pair(
    captures: Mapping[str, Capture], *, sample_rate_hz: int,
    voltages_mv: Mapping[str, int], wire_paths: Mapping[str, str | Path] | None = None,
    marker_totals_only: bool = False, calibrations: Mapping[str, dict] | None = None,
    filter_aware_totals: bool = False,
    filter_history_policy: str = "current_equivalence_v1",
) -> tuple[dict[str, Metrics], dict]:
    """Integrate each local pulse; optional totals require the selected wire proof.

    The default retains strict integration-plus-baseline counter QA and legacy
    rectified excess. Explicit total-only mode does not estimate a baseline or
    excess; it preserves that QA as diagnostics and proves the local total anew.
    Filter-aware totals additionally require an explicit opt-in and bound the
    range-transition decoder state; the direct-ADC default is unchanged.
    """
    return _analyze_marker_pair(captures, sample_rate_hz=sample_rate_hz,
                                voltages_mv=voltages_mv, wire_paths=wire_paths,
                                independent_radio_markers=True, marker_totals_only=marker_totals_only,
                                calibrations=calibrations, filter_aware_totals=filter_aware_totals,
                                filter_history_policy=filter_history_policy)
