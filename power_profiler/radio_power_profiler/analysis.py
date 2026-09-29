from __future__ import annotations

import math
import statistics

from .frame_windows import locate_frame_windows
from .models import CaptureSpec, Metrics


def _groups(active_indices: list[int], max_gap: int) -> list[tuple[int, int]]:
    if not active_indices:
        return []
    groups: list[tuple[int, int]] = []
    start = previous = active_indices[0]
    for index in active_indices[1:]:
        if index - previous > max_gap:
            groups.append((start, previous))
            start = index
        previous = index
    groups.append((start, previous))
    return groups


def _frame_sample_lengths(airtimes_s: tuple[float, ...], sample_rate_hz: int) -> tuple[int, ...]:
    """Quantize each frame while preserving the modeled total sample count."""
    if sample_rate_hz <= 0 or not airtimes_s or any(not math.isfinite(value) or value <= 0 for value in airtimes_s):
        raise ValueError("Positive finite frame airtimes are required")
    exact = [value * sample_rate_hz for value in airtimes_s]
    lengths = [int(value) for value in exact]
    # Accumulate in the sample domain: ordinary summation of e.g. eight
    # 15.48-ms IEEE154G50 frames can otherwise yield 12383.999999 samples,
    # smaller than the sum of their exact 1548-sample frame lengths.
    total_samples = int(math.fsum(exact))
    remainder = total_samples - sum(lengths)
    # Largest remainders avoid treating a shorter final frame as a full frame.
    order = sorted(range(len(lengths)), key=lambda index: exact[index] - lengths[index], reverse=True)
    for index in order[:remainder]:
        lengths[index] += 1
    if min(lengths) < 1 or sum(lengths) != total_samples:
        raise ValueError("Frame airtimes cannot be represented at this sample rate")
    return tuple(lengths)


def _integrate_windows(
    samples_uA: list[float], windows: list[tuple[int, int]], *, trigger_index: int,
    sample_rate_hz: int, voltage_mv: int, baseline: float, threshold: float,
    method: str,
) -> Metrics:
    """Integrate disjoint half-open windows without including intervening gaps."""
    event = [value for start, end in windows for value in samples_uA[start:end]]
    charge_total_uC = sum(max(0.0, value) for value in event) / sample_rate_hz
    charge_excess_uC = sum(max(0.0, value - baseline) for value in event) / sample_rate_hz
    voltage_v = voltage_mv / 1000.0
    return Metrics(
        event_detected=True,
        baseline_median_uA=baseline,
        threshold_uA=threshold,
        event_start_ms=(windows[0][0] - trigger_index) * 1000.0 / sample_rate_hz,
        event_duration_ms=(len(event) / sample_rate_hz) * 1000.0,
        tx_mean_uA=statistics.fmean(event),
        tx_peak_uA=max(event),
        charge_total_uC=charge_total_uC,
        charge_excess_uC=charge_excess_uC,
        energy_total_uJ=charge_total_uC * voltage_v,
        energy_excess_uJ=charge_excess_uC * voltage_v,
        integration_method=method,
        integration_windows_ms=tuple(
            ((start - trigger_index) * 1000.0 / sample_rate_hz,
             (end - trigger_index) * 1000.0 / sample_rate_hz)
            for start, end in windows
        ),
    )


def analyze_capture(
    samples_uA: list[float],
    *,
    trigger_index: int,
    sample_rate_hz: int,
    voltage_mv: int,
    capture_spec: CaptureSpec,
    expected_event_count: int = 1,
    search_window_s: float | None = None,
    fallback_window_s: float | None = None,
    integration_window_s: float | None = None,
    align_integration_window: bool = False,
    frame_airtimes_s: tuple[float, ...] | None = None,
) -> Metrics:
    if len(samples_uA) < 100 or not 10 <= trigger_index < len(samples_uA) or sample_rate_hz <= 0:
        error = "Capture is too short or has an invalid trigger/sample rate"
        if frame_airtimes_s is not None:
            return Metrics(
                event_detected=False, baseline_median_uA=None, threshold_uA=None,
                integration_method="per_frame_modeled_airtime_v1", analysis_error=error,
                analysis_diagnostics={"frame_airtimes_s": list(frame_airtimes_s)},
            )
        raise ValueError(error)

    baseline_start = min(int(0.010 * sample_rate_hz), trigger_index // 4)
    baseline_end = max(baseline_start + 1, trigger_index - int(0.005 * sample_rate_hz))
    baseline_samples = samples_uA[baseline_start:baseline_end]
    baseline = statistics.median(baseline_samples)
    absolute_deviations = [abs(value - baseline) for value in baseline_samples]
    mad = statistics.median(absolute_deviations)
    robust_noise = 1.4826 * mad
    threshold = baseline + max(capture_spec.threshold_margin_uA, 8.0 * robust_noise)

    if frame_airtimes_s is not None:
        method = "per_frame_modeled_airtime_v1"
        diagnostics = {"frame_airtimes_s": list(frame_airtimes_s)}
        try:
            if len(frame_airtimes_s) != expected_event_count:
                raise ValueError("Modeled frame count does not match transmission metadata")
            frame_lengths = _frame_sample_lengths(frame_airtimes_s, sample_rate_hz)
            # Search the complete RAW capture: host/UART/ACK gaps are not airtime
            # and can put later physical frames beyond the old search cutoff.
            located = locate_frame_windows(
                samples_uA, trigger_index=trigger_index, sample_rate_hz=sample_rate_hz,
                baseline_uA=baseline, frame_lengths=frame_lengths,
            )
            diagnostics.update(located["diagnostics"])
            if not located["valid"]:
                raise ValueError("; ".join(located["reasons"]) or "Frame windows could not be validated")
            windows = located["windows"]
            if len(windows) != len(frame_lengths) or any(
                start < trigger_index or end > len(samples_uA) or end - start != length
                for (start, end), length in zip(windows, frame_lengths)
            ) or any(a[1] > b[0] for a, b in zip(windows, windows[1:])):
                raise ValueError("Invalid or overlapping modeled frame windows")
        except ValueError as exc:
            return Metrics(
                event_detected=False, baseline_median_uA=baseline, threshold_uA=threshold,
                integration_method=method, analysis_error=str(exc),
                analysis_diagnostics=diagnostics,
            )
        metrics = _integrate_windows(
            samples_uA, windows, trigger_index=trigger_index,
            sample_rate_hz=sample_rate_hz, voltage_mv=voltage_mv,
            baseline=baseline, threshold=threshold, method=method,
        )
        metrics.analysis_diagnostics = diagnostics
        return metrics

    search_start = max(baseline_end, trigger_index - int(0.002 * sample_rate_hz))
    search_end = len(samples_uA)
    if search_window_s is not None:
        search_end = min(
            search_end,
            trigger_index + max(1, int(search_window_s * sample_rate_hz)),
        )
    using_fixed_window = integration_window_s is not None and integration_window_s > 0
    if using_fixed_window:
        fixed_length = max(1, int(integration_window_s * sample_rate_hz))
        first_start = max(search_start, trigger_index)
        last_start = search_end - fixed_length
        if align_integration_window and last_start >= first_start:
            # Low-power radios can draw a broad, repeatable plateau that sits
            # below a noise-derived point threshold. Align the physical-airtime
            # window by maximizing baseline-subtracted charge instead of
            # fragmenting that plateau into arbitrary threshold crossings.
            excess = [
                max(0.0, samples_uA[index] - baseline)
                for index in range(first_start, search_end)
            ]
            fixed_length = min(fixed_length, len(excess))
            rolling_score = sum(excess[:fixed_length])
            best_score = rolling_score
            fixed_start = first_start
            for offset in range(1, len(excess) - fixed_length + 1):
                rolling_score += (
                    excess[offset + fixed_length - 1] - excess[offset - 1]
                )
                if rolling_score > best_score:
                    best_score = rolling_score
                    fixed_start = first_start + offset
        else:
            fixed_start = first_start
        fixed_end = min(search_end - 1, fixed_start + fixed_length - 1)
        candidates = [(fixed_start, fixed_end)] if fixed_end >= fixed_start else []
    else:
        active = [
            index
            for index in range(search_start, search_end)
            if samples_uA[index] >= threshold
        ]
        max_gap = max(1, int(capture_spec.merge_gap_ms * sample_rate_hz / 1000.0))
        minimum_length = max(
            1, int(capture_spec.minimum_event_ms * sample_rate_hz / 1000.0)
        )
        candidates = [
            group
            for group in _groups(active, max_gap)
            if group[1] - group[0] + 1 >= minimum_length
        ]

    using_bounded_window = using_fixed_window
    if not candidates and fallback_window_s is not None and fallback_window_s > 0:
        fallback_start = max(search_start, trigger_index)
        fallback_end = min(
            search_end - 1,
            fallback_start + max(1, int(fallback_window_s * sample_rate_hz)) - 1,
        )
        if fallback_end >= fallback_start:
            candidates = [(fallback_start, fallback_end)]
            using_bounded_window = True

    if not candidates:
        return Metrics(
            event_detected=False,
            baseline_median_uA=baseline,
            threshold_uA=threshold,
        )

    def score(group: tuple[int, int]) -> float:
        start, end = group
        return sum(max(0.0, value - baseline) for value in samples_uA[start : end + 1])

    selected = sorted(
        sorted(candidates, key=score, reverse=True)[: max(1, expected_event_count)]
    )
    padding = 0 if using_bounded_window else max(1, int(0.0001 * sample_rate_hz))
    padded: list[tuple[int, int]] = []
    for start, end in selected:
        start = max(search_start, start - padding)
        end = min(search_end - 1, end + padding)
        if padded and start <= padded[-1][1] + 1:
            padded[-1] = (padded[-1][0], max(padded[-1][1], end))
        else:
            padded.append((start, end))
    return _integrate_windows(
        samples_uA, [(start, end + 1) for start, end in padded],
        trigger_index=trigger_index, sample_rate_hz=sample_rate_hz,
        voltage_mv=voltage_mv, baseline=baseline, threshold=threshold,
        method=(
            "aligned_modeled_airtime" if using_fixed_window and align_integration_window
            else "fixed_modeled_airtime" if using_fixed_window
            else "bounded_fallback" if using_bounded_window else "threshold_events"
        ),
    )
