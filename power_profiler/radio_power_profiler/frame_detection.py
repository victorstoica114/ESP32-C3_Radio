"""Conservative offline E79 burst anchors; does not impose an expected count.

1 ms means suppress PPK switching/noise spikes. A burst must contain at least
two consecutive above-threshold bins; isolated crossings cannot create a burst
or extend its anchors. Calibration uses only pre-trigger samples. Independent
burst count is a validation result, never an input. The returned groups are
approximate anchors, not integration windows or synchronized RF timing. Bursts
shorter than the required sustained core can remain undetected and must not be
manufactured to match a caller's expected count.
"""
from bisect import bisect_left
import math
import statistics


def _groups(indices, max_gap):
    if not indices:
        return []
    output=[]
    left=last=indices[0]
    for value in indices[1:]:
        if value-last>max_gap:
            output.append((left,last+1))
            left=value
        last=value
    output.append((left,last+1))
    return output


def _sustained_groups(indices, max_gap):
    """Trim each gap-connected group to its sustained above-threshold cores.

    The original gap tolerance still connects internal noise dips in a plateau.
    Only a crossing with an adjacent above-threshold bin can set an anchor.
    This rule is applied identically to the baseline and post-trigger trace.
    """
    present = set(indices)
    supported = [index for index in indices
                 if index - 1 in present or index + 1 in present]
    output = []
    for start, stop in _groups(indices, max_gap):
        first = bisect_left(supported, start)
        last = bisect_left(supported, stop)
        if first < last:
            output.append((supported[first], supported[last - 1] + 1))
    return output


def detect_frames(samples, trigger, rate, frame_window_samples, *, sensitivity=4.0,
                  merge_gap_ms=5.0, minimum_width_fraction=0.4,
                  maximum_frame_window_samples=None):
    """Return (absolute [start,end) groups, diagnostics), scanning full RAW.

    Call with sensitivity 3, 4, and 5; reject cases with unstable frame count or
    material integration sensitivity. Compare observed count to expected count
    in the caller. Do not truncate or supplement groups to force a match.

    For unequal physical frame lengths, frame_window_samples is the smallest
    modeled frame window and maximum_frame_window_samples the largest. These
    only define global width checks; the caller must validate each matched
    group's own modeled duration after checking the independently found count.
    """
    if rate<=0 or frame_window_samples<=0 or not 0<trigger<len(samples):
        raise ValueError('Invalid sample rate, frame window, or trigger')
    maximum_frame_window_samples = (
        frame_window_samples if maximum_frame_window_samples is None
        else maximum_frame_window_samples
    )
    if maximum_frame_window_samples < frame_window_samples:
        raise ValueError('Maximum frame window must be at least the minimum')
    bin_samples=max(1,round(rate*.001))
    pre_start=round(rate*.010)
    pre_stop=trigger-round(rate*.006)
    pre=[statistics.fmean(samples[i:i+bin_samples])
         for i in range(pre_start, pre_stop, bin_samples)
         if i+bin_samples<=pre_stop]
    diagnostics={'bin_samples':bin_samples,'baseline_bins':len(pre),
                 'sensitivity':sensitivity,'merge_gap_ms':merge_gap_ms,
                 'minimum_sustained_core_bins':2,
                 'anchor_rule':'first_and_last_sustained_above_threshold_core',
                 'expected_count_used_by_detector':False}
    if len(pre)<30 or any(not math.isfinite(x) for x in pre):
        diagnostics.update(valid=False,reasons=['insufficient_or_invalid_baseline'])
        return [],diagnostics
    center=statistics.median(pre)
    sigma=1.4826*statistics.median(abs(x-center) for x in pre)
    threshold=center+max(150.0,sensitivity*sigma)
    # A final partial bin is excluded, because its variance differs from all
    # other bins. At 100 kS/s this leaves <1 ms at the capture end for QC.
    means=[statistics.fmean(samples[i:i+bin_samples])
           for i in range(trigger,len(samples)-bin_samples+1,bin_samples)]
    if any(not math.isfinite(x) for x in means):
        diagnostics.update(valid=False,reasons=['nonfinite_samples'])
        return [],diagnostics
    bin_ms=bin_samples*1000.0/rate
    max_gap=max(1,round(merge_gap_ms/bin_ms))
    frame_ms=frame_window_samples*1000.0/rate
    maximum_frame_ms=maximum_frame_window_samples*1000.0/rate
    min_bins=max(2,math.ceil(max(2.0,frame_ms*minimum_width_fraction)/bin_ms))
    active_indices=[i for i,x in enumerate(means) if x>=threshold]
    all_groups=_groups(active_indices,max_gap)
    supported_groups=_sustained_groups(active_indices,max_gap)
    accepted=[g for g in supported_groups if g[1]-g[0]>=min_bins]
    groups=[(trigger+left*bin_samples,trigger+end*bin_samples) for left,end in accepted]
    widths=[(end-left)*bin_ms for left,end in accepted]
    overlong=[i for i,w in enumerate(widths) if w>maximum_frame_ms*1.3+3.0]
    edge=[i for i,(_,end) in enumerate(accepted) if len(means)-end<max_gap]
    null_groups=[g for g in _sustained_groups([i for i,x in enumerate(pre) if x>=threshold],max_gap)
                 if g[1]-g[0]>=min_bins]
    reasons=[]
    if overlong:reasons.append('overlong_group_may_merge_frames')
    if edge:reasons.append('activity_near_capture_end')
    if null_groups:reasons.append('frame_like_pretrigger_noise')
    diagnostics.update(valid=not reasons,reasons=reasons,
        baseline_mean_uA=statistics.fmean(pre),baseline_median_bin_uA=center,
        baseline_sigma_mad_uA=sigma,threshold_uA=threshold,
        minimum_group_bins=min_bins,raw_group_count=len(all_groups),
        supported_group_count=len(supported_groups),
        dropped_unsupported_groups=len(all_groups)-len(supported_groups),
        retained_group_count=len(groups),dropped_short_groups=len(supported_groups)-len(groups),
        frame_window_ms=frame_ms,maximum_frame_window_ms=maximum_frame_ms,
        group_widths_ms=widths,
        group_mean_uA=[statistics.fmean(means[left:end]) for left,end in accepted],
        group_excess_over_baseline_uA=[statistics.fmean(means[left:end])-center for left,end in accepted],
        overlong_groups=overlong,groups_near_capture_end=edge,
        pretrigger_frame_like_group_count=len(null_groups))
    return groups,diagnostics
