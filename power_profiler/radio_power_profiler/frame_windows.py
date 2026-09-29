"""Validated, disjoint modeled-airtime windows for a fragmented TX capture.

Frame count validates independently detected sustained bursts. It is never used
to select the strongest N noise groups or synthesize a missing transmission.
"""
from __future__ import annotations

from .frame_detection import detect_frames


def align_windows(samples, baseline, trigger, groups, frame_lengths):
    if not groups or len(groups) != len(frame_lengths):
        raise ValueError("Detected frame count does not match modeled frame lengths")
    windows = []
    for index, ((start, end), length) in enumerate(zip(groups, frame_lengths)):
        first = trigger if index == 0 else (groups[index - 1][1] + start) // 2
        stop = len(samples) if index == len(groups) - 1 else (end + groups[index + 1][0]) // 2
        center = (start + end) // 2
        first = max(first, center - length + 1)
        last = min(stop - length, center)
        if length < 1 or last < first:
            raise ValueError("Modeled frame window cannot fit its pulse cell")
        score = sum(max(0.0, value - baseline) for value in samples[first:first + length])
        best, best_start = score, first
        for candidate in range(first + 1, last + 1):
            score += max(0.0, samples[candidate + length - 1] - baseline)
            score -= max(0.0, samples[candidate - 1] - baseline)
            if score > best:
                best, best_start = score, candidate
        windows.append((best_start, best_start + length))
    if any(a[1] > b[0] for a, b in zip(windows, windows[1:])):
        raise ValueError("Overlapping frame windows")
    return windows


def _integrals(samples, windows, baseline):
    total = excess = 0.0
    for start, end in windows:
        for value in samples[start:end]:
            total += max(0.0, value)
            excess += max(0.0, value - baseline)
    return total, excess


def locate_frame_windows(
    samples, *, trigger_index, sample_rate_hz, baseline_uA, frame_lengths,
):
    """Return windows and diagnostics, or a closed failure with no windows.

    The 1% energy sensitivity criterion is a screening tolerance, not a PPK
    uncertainty estimate. All analysis uses the saved samples at nominal rate.
    """
    if not frame_lengths or min(frame_lengths) < 1:
        raise ValueError("Positive modeled frame lengths are required")
    expected = len(frame_lengths)
    diagnostics = {"expected_frames": expected, "frame_lengths": list(frame_lengths), "sensitivity": []}
    result = {"valid": False, "windows": [], "reasons": [], "diagnostics": diagnostics}
    reference_windows = None
    reference_energy = None
    for multiplier in (4.0, 3.0, 5.0):
        groups, detail = detect_frames(
            samples, trigger_index, sample_rate_hz, min(frame_lengths),
            maximum_frame_window_samples=max(frame_lengths), sensitivity=multiplier,
        )
        check = {"multiplier": multiplier, "detected_frames": len(groups), "groups": groups, "detector": detail}
        diagnostics["sensitivity"].append(check)
        reasons = []
        if len(groups) != expected:
            reasons.append("detected_frame_count_mismatch")
        if not detail["valid"]:
            reasons.extend(detail["reasons"])
        if len(groups) == expected:
            for (start, end), length in zip(groups, frame_lengths):
                if (end - start) > 1.3 * length + .003 * sample_rate_hz:
                    reasons.append("pulse_too_long_for_its_modeled_frame")
        if reasons:
            check["reasons"] = reasons
            result["reasons"].extend(f"{reason}_at_{multiplier:g}_MAD" for reason in reasons)
            continue
        try:
            windows = align_windows(samples, baseline_uA, trigger_index, groups, frame_lengths)
        except ValueError as exc:
            result["reasons"].append(str(exc))
            continue
        total, excess = _integrals(samples, windows, baseline_uA)
        check.update(windows=windows, total_integral_uA_samples=total, excess_integral_uA_samples=excess)
        if multiplier == 4.0:
            reference_windows, reference_energy = windows, total
            diagnostics["detected_frames"] = len(groups)
            diagnostics["groups"] = groups
        elif reference_energy is not None:
            relative = 100.0 * (total / reference_energy - 1.0) if reference_energy > 0 else 0.0
            check["total_difference_percent"] = relative
            if abs(relative) > 1.0:
                result["reasons"].append(f"energy_sensitivity_above_1_percent_at_{multiplier:g}_MAD")
    if not result["reasons"] and reference_windows is not None:
        result.update(valid=True, windows=reference_windows)
    return result
