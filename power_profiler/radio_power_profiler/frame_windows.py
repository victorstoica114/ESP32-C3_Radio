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
    checks_by_multiplier = {}

    def evaluate(multiplier):
        groups, detail = detect_frames(
            samples, trigger_index, sample_rate_hz, min(frame_lengths),
            maximum_frame_window_samples=max(frame_lengths), sensitivity=multiplier,
        )
        check = {"multiplier": multiplier, "detected_frames": len(groups), "groups": groups, "detector": detail}
        diagnostics["sensitivity"].append(check)
        checks_by_multiplier[multiplier] = check
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
            return check
        try:
            windows = align_windows(samples, baseline_uA, trigger_index, groups, frame_lengths)
        except ValueError as exc:
            check["reasons"] = [str(exc)]
            return check
        total, excess = _integrals(samples, windows, baseline_uA)
        check.update(windows=windows, total_integral_uA_samples=total, excess_integral_uA_samples=excess)
        return check

    def consensus(reference_multiplier, candidate_multipliers, required_support_count, mode):
        reference = checks_by_multiplier[reference_multiplier]
        if "windows" not in reference:
            return None, []
        reference_energy = reference["total_integral_uA_samples"]
        supporters = [reference_multiplier]
        outliers = []
        for multiplier in candidate_multipliers:
            check = checks_by_multiplier[multiplier]
            if "windows" not in check:
                outliers.append(multiplier)
                continue
            relative = 100.0 * (
                check["total_integral_uA_samples"] / reference_energy - 1.0
            ) if reference_energy > 0 else 0.0
            check["total_difference_percent"] = relative
            if abs(relative) <= 1.0:
                supporters.append(multiplier)
            else:
                outliers.append(multiplier)
                check.setdefault("reasons", []).append("energy_sensitivity_above_1_percent")
        diagnostics["sensitivity_consensus"] = {
            "mode": mode,
            "reference_multiplier": reference_multiplier,
            "supporting_multipliers": supporters,
            "outlier_multipliers": outliers,
            "required_support_count": required_support_count,
        }
        if len(supporters) >= required_support_count:
            diagnostics["detected_frames"] = reference["detected_frames"]
            diagnostics["groups"] = reference["groups"]
            return reference["windows"], outliers
        return None, outliers

    for multiplier in (4.0, 3.0, 5.0):
        evaluate(multiplier)

    primary = checks_by_multiplier[4.0]
    primary_windows, primary_outliers = consensus(
        4.0, (3.0, 5.0), 2, "primary_4_MAD",
    )
    if primary_windows is not None:
        result.update(valid=True, windows=primary_windows)
        return result

    # A strong frame can have a low-current setup shoulder that makes the
    # 4-MAD anchor overlong.  Accept a high-side fallback only when the entire
    # 4.5/5/5.5-MAD bracket independently passes count/QC and energy consensus.
    high_outliers = []
    if "windows" not in primary and "windows" in checks_by_multiplier[5.0]:
        for multiplier in (4.5, 5.5):
            evaluate(multiplier)
        high_windows, high_outliers = consensus(
            5.0, (4.5, 5.5), 3, "high_signal_5_MAD_fallback",
        )
        if high_windows is not None:
            diagnostics["sensitivity_consensus"]["primary_4_MAD_reasons"] = primary.get(
                "reasons", ["invalid_primary_sensitivity"]
            )
            result.update(valid=True, windows=high_windows)
            return result

    # Do not reinterpret a valid 4-MAD detection that merely lacks a confirming
    # neighbor, and do not lower thresholds for short/1-ms-bin frames.  The
    # fallback is specific to long, low-power plateaus using temporal averaging.
    adaptive_bin_samples = primary["detector"].get("bin_samples", 0)
    fallback_eligible = (
        "windows" not in primary
        and adaptive_bin_samples > round(sample_rate_hz * .001)
    )
    if not fallback_eligible:
        if "windows" not in primary:
            result["reasons"].extend(
                f"{reason}_at_4_MAD"
                for reason in primary.get("reasons", ["invalid_primary_sensitivity"])
            )
        for multiplier in primary_outliers:
            check = checks_by_multiplier[multiplier]
            result["reasons"].extend(
                f"{reason}_at_{multiplier:g}_MAD"
                for reason in check.get("reasons", ["sensitivity_did_not_confirm_primary"])
            )
        for multiplier in high_outliers:
            check = checks_by_multiplier[multiplier]
            result["reasons"].extend(
                f"{reason}_at_{multiplier:g}_MAD"
                for reason in check.get("reasons", ["high_sensitivity_did_not_confirm"])
            )
        result["reasons"].append("insufficient_sensitivity_consensus")
        return result

    # Every point in the 2.0-2.75-MAD bracket must independently find the exact
    # modeled count, pass detector QC, and agree on integration energy within
    # 1%.  The center of this stable low-threshold plateau supplies the windows.
    for multiplier in (2.5, 2.0, 2.25, 2.75):
        evaluate(multiplier)
    fallback_windows, fallback_outliers = consensus(
        2.5, (2.0, 2.25, 2.75), 4, "long_frame_low_signal_fallback",
    )
    if fallback_windows is not None:
        diagnostics["sensitivity_consensus"]["primary_4_MAD_reasons"] = primary.get(
            "reasons", ["invalid_primary_sensitivity"]
        )
        result.update(valid=True, windows=fallback_windows)
        return result

    result["reasons"].extend(
        f"{reason}_at_4_MAD"
        for reason in primary.get("reasons", ["invalid_primary_sensitivity"])
    )
    if "windows" not in checks_by_multiplier[2.5]:
        result["reasons"].extend(
            f"{reason}_at_2.5_MAD"
            for reason in checks_by_multiplier[2.5].get(
                "reasons", ["invalid_fallback_reference"]
            )
        )
    for multiplier in fallback_outliers:
        check = checks_by_multiplier[multiplier]
        result["reasons"].extend(
            f"{reason}_at_{multiplier:g}_MAD"
            for reason in check.get("reasons", ["sensitivity_did_not_confirm_primary"])
        )
    result["reasons"].append("insufficient_low_signal_sensitivity_consensus")
    return result
