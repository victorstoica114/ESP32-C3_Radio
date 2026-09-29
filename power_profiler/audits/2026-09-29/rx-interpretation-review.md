# RX and continuous interpretation review — 2026-09-29

**For the existing, explicitly defined integration windows, no compulsory RX or continuous hardware retakes follow from the missing RAW archive.** The per-run summaries retain the quantities actually reported. This does not restore the historical waveforms or establish a new whole-transaction energy quantity. TX fragmentation is reviewed separately and is not cleared by this conclusion.

## Minimal decision matrix

| Published observations without RAW | Count | Retain | Clarification possible without hardware | Hardware required only if |
|---|---:|---|---|---|
| CC1101 V1/V2 packet RX | 180 runs = 36 conditions × 5 | Original controlled-RX event energies, currents, durations and reception records | Identify these as the older controlled receiver ON/OFF event-window policy; keep the existing warning that E07 has a different RX window | A new common RX timing policy across CC1101 and E07 is required |
| E07-400M10S, E07-433M20S, E07-900MM10S packet RX | 405 runs = 81 conditions × 5 | Current and energy within the recorded deterministic airtime-length integration window; keep observed losses | Label energy as a measured RX/listening-window metric, with configured airtime duration; do not silently present failed receptions as successful delivery | Exact RF-synchronized or complete receiver startup-to-shutdown energy is required |
| E79 CH9340C packet RX | 630 runs = 126 conditions × 5 | Recorded window energy/current, PHY and host-context comparisons under that definition, reception outcomes | Distinguish the configured airtime-length window from the whole host-paced multi-frame transaction; 315 fragmented RX runs do not automatically become mandatory retakes | Corrected full multi-frame transaction energy, including host/inter-frame delays, is required |
| RA-09 packet RX | 135 runs = 27 conditions × 5 | Recorded LoRa-window energy/current and the existing RA-08/RA-09 comparison over equal windows | Keep the comparison at module-current/defined-window level; the paper already excludes sleep-state transition energy | Exact synchronized RF packet energy or receiver wake-up/shutdown energy is required |
| CC1101 V1/V2 continuous | 27 windows = 6 TX + 21 RX | Total mean current/power, 60-second energy, baseline and existing clipped excess-power metric, status and delivery evidence | Use the universal label “increment above that session's pre-trigger baseline”; identify baseline state by historical acquisition version | A different baseline state or a new workload is requested, or missing receiver telemetry must be established |

**RX total: 1,350 runs can remain as observations of their original windows.** Of these, 1,170 use the newer deterministic airtime-length RX policy, while 180 legacy CC1101 observations use the earlier event policy. Missing RAW alone does not make any of them invalid. This table is not permission to retain an unqualified claim of full transaction energy where the integration window omitted part of that transaction.

## Checks supporting retention

I read all 1,350 no-RAW RX source-summary rows. For every row, the stored energy satisfies

`energy_total_uJ = event_mean_uA * event_duration_ms * voltage_mv / 1_000_000`

to numerical precision (maximum absolute residual `1.17e-10 uJ`). The historical per-run summaries exist, so current-based comparisons, mean/stdev recalculation, and duration/label disclosures can be prepared without reconstructing a waveform. This is an arithmetic/provenance check, not an independent metrological validation of the original window.

RX outcome counts are retained unchanged:

| Source | ok | rx_missing |
|---|---:|---:|
| CC1101 V1 | 90 | 0 |
| CC1101 V2 | 90 | 0 |
| E07-400M10S | 45 | 90 |
| E07-433M20S | 134 | 1 |
| E07-900MM10S | 90 | 45 |
| E79 CH9340C | 628 | 2 |
| RA-09 | 135 | 0 |

The E07 losses are already discussed as a setup-dependent delivery limitation in [the study, line 332](../../study/radio_module_energy_study.tex#L332). Repeating only the losses would change the original experiment and should not be used to replace them with cherry-picked successes.

All 27 no-RAW continuous summaries have `active_window_s=60.0`; their stored total and excess-power values agree exactly with `V*mean_current` and `V*max(0, mean_current-baseline_mean)`. There are 26 `ok` rows and one `no_rx_data`: CC1101 V2, -30 dBm, 250 kbps, `loss_results/20260717_144531_radio_cc1101_v2_868_continuous_rx/continuous_001`. Keep the latter as a power observation with its original delivery limitation. It does not support a claim of useful delivered traffic; zero received telemetry cannot by itself isolate RF sensitivity as the cause.

## Important historical baseline distinction

Do not apply the modern RX-idle baseline interpretation indiscriminately to CC1101 data from 17 July.

The historical implementation at Git commit `8f4f867` enabled RX **inside** the trigger callback: packet `_execute_receive_transfer` configured `receiver_enable_commands` and restored the profile afterward; continuous `_receive_continuous` issued `AT+RX=ON` and subsequently `AT+RX=OFF`. Its pre-trigger baseline therefore preceded RX enable. The 27 archived continuous rows independently agree with that history: baseline is **1,747.43–1,782.88 uA**, while active RX currents are approximately **13.8–16.6 mA**. The previous description of these CC1101 baselines as a receiver-off/standby reference is consistent with the historical evidence.

Modern code enables RX before acquisition: [packet runner, line 351](../../radio_power_profiler/runner.py#L351) and [continuous runner, line 455](../../radio_power_profiler/continuous_runner.py#L455). For those sessions, the RX baseline is pre-traffic listening, not receiver-off standby. The total-power values are independent of this label. An excess of zero means the active-window mean did not exceed the recorded baseline, not zero radio power. The calculation is directly visible at [continuous_runner.py:100](../../radio_power_profiler/continuous_runner.py#L100).

## Minimal interpretation corrections

1. Replace the universal “standby baseline” designation in [study line 107](../../study/radio_module_energy_study.tex#L107) with “session pre-trigger baseline”, then identify RX-off versus RX-listening by campaign. Existing numeric total/excess values remain unchanged. This also corrects later SX1278/E32 captions without repeating their 60-second traffic windows.
2. Preserve the explicitly limited E07-versus-CC1101 RX comparison in [study line 330](../../study/radio_module_energy_study.tex#L330): the unequal 12.37 ms versus approximately 119 ms windows are already disclosed. A new common-window experiment is an optional new comparison, not a repair needed to keep the disclosed observations.
3. Preserve the RA-08/RA-09 interpretation at [study line 352](../../study/radio_module_energy_study.tex#L352): an approximately equal-duration module-current comparison, explicitly excluding sleep-state transition energy. RAW absence for RA-09 does not itself negate it.
4. Narrow broad statements at [study line 86](../../study/radio_module_energy_study.tex#L86) and line 206 that imply every packet metric includes all startup/host costs. For modern RX, the code integrates a deterministic duration equal to estimated airtime ([runner.py:413](../../radio_power_profiler/runner.py#L413)); this supports the reported window metric, not automatic inclusion of wake-up, all host gaps or shutdown.
5. Preserve the five newer modules' continuous fields as “not measured”, as already stated at [study line 88](../../study/radio_module_energy_study.tex#L88). No automatic continuous retakes are needed to retain the current scope.

## What cannot be corrected exactly from summaries

The energy of omitted intervals, RF-aligned boundaries, individual frame pulses, receiver startup/shutdown, and a new standby-referenced quantity cannot be reconstructed exactly from an aggregate. Multiplying a recorded window's mean current by an assumed longer transaction duration creates a model estimate; it is not a recovered measurement. A separate controlled baseline can establish a new standby reference without automatically repeating every traffic point, but matching hardware/configuration and uncertainty still need explicit treatment.

Thus a blanket RX retake count (including the earlier conservative 765 total proposal) should be replaced by a decision tied to the quantity the publication actually intends to retain. For the stated aim of preserving existing observations and their limited interpretations, this review adds **0 mandatory RX retakes and 0 mandatory continuous retakes**. It does not adjudicate the separate E79 fragmented-TX correction.

Sources and reproducibility: [missing_published.json](missing_published.json), [per-run no-RAW matrix](missing_packet_runs.csv), [continuous no-RAW matrix](missing_continuous_runs.csv), [metadata review](reanalysis_missing_metadata.json), Git `show 8f4f867:power_profiler/radio_power_profiler/{runner,continuous_runner}.py`. No source data, code, or publication files were modified; only this report was written.
