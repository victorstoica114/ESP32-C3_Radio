from __future__ import annotations

import statistics

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
) -> Metrics:
    if len(samples_uA) < 100 or trigger_index < 10:
        raise ValueError("Capture is too short to calculate a baseline")

    baseline_start = min(int(0.010 * sample_rate_hz), trigger_index // 4)
    baseline_end = max(baseline_start + 1, trigger_index - int(0.005 * sample_rate_hz))
    baseline_samples = samples_uA[baseline_start:baseline_end]
    baseline = statistics.median(baseline_samples)
    absolute_deviations = [abs(value - baseline) for value in baseline_samples]
    mad = statistics.median(absolute_deviations)
    robust_noise = 1.4826 * mad
    threshold = baseline + max(capture_spec.threshold_margin_uA, 8.0 * robust_noise)

    search_start = max(baseline_end, trigger_index - int(0.002 * sample_rate_hz))
    search_end = len(samples_uA)
    if search_window_s is not None:
        search_end = min(
            search_end,
            trigger_index + max(1, int(search_window_s * sample_rate_hz)),
        )
    using_fixed_window = integration_window_s is not None and integration_window_s > 0
    if using_fixed_window:
        fixed_start = max(search_start, trigger_index)
        fixed_end = min(
            search_end - 1,
            fixed_start + max(1, int(integration_window_s * sample_rate_hz)) - 1,
        )
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
    event_start = padded[0][0]
    event = [
        value
        for start, end in padded
        for value in samples_uA[start : end + 1]
    ]
    duration_s = len(event) / sample_rate_hz
    charge_total_uC = sum(max(0.0, value) for value in event) / sample_rate_hz
    charge_excess_uC = sum(max(0.0, value - baseline) for value in event) / sample_rate_hz
    voltage_v = voltage_mv / 1000.0

    return Metrics(
        event_detected=True,
        baseline_median_uA=baseline,
        threshold_uA=threshold,
        event_start_ms=(event_start - trigger_index) * 1000.0 / sample_rate_hz,
        event_duration_ms=duration_s * 1000.0,
        tx_mean_uA=statistics.fmean(event),
        tx_peak_uA=max(event),
        charge_total_uC=charge_total_uC,
        charge_excess_uC=charge_excess_uC,
        energy_total_uJ=charge_total_uC * voltage_v,
        energy_excess_uJ=charge_excess_uC * voltage_v,
    )
