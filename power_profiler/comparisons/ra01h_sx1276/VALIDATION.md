# RA-01H (SX1276) campaign validation

## Verdict

The authoritative campaign `20260719_155432_campaign_radio_ra01h_sx1276`
completed all 40 planned steps. The measurement set is accepted for packet
energy, continuous average-power, and radio-loss analysis after targeted
continuous-RX recovery with the corrected receiver-tail timing. No additional
hardware retry is required.

The three packet losses recorded by the original five-repetition campaign are
retained. Targeted ten-repetition controls show that one condition has a small
repeatable peer-reception loss, while the other two original misses were
isolated. None of the missed packets coincides with a missing TX current event
or an abnormal PPK2 trace.

## Configuration and coverage

- Profile: `RADIO_RA01H_SX1276`, explicitly configured for 868 MHz, coding rate
  4/5, explicit header, CRC, a 15-symbol preamble, and receiver entry through
  `AT+RX=ON`.
- The RA-01H antenna is routed through PA_BOOST, so the tested power matrix is
  +2, +10, and +20 dBm. Settings below +2 dBm select the unrouted RFO path and
  are intentionally rejected by the firmware/profile.
- Measured DUT: COM29; peer: COM30; PPK2: COM11 in Ampere Meter mode at
  3300 mV. The DUT remained externally powered; PPK2 provided the guarded
  VIN-to-VOUT current path.
- Packet TX: 27 aggregate points and 135 raw captures across three payloads,
  three spreading factors, and three TX powers.
- Packet RX: 9 aggregate points and 45 raw captures at +20 dBm.
- Continuous tests: three TX power points at SF9 and nine RX power/loss points
  across SF7, SF9, and SF12, each measured over exactly 60 active seconds.
- The source session preserves 201 gzip raw traces (192 original plus nine
  authoritative RX recovery traces), totalling 915,360,458 bytes. Compact
  metadata and summaries for all recovery and packet-diagnostic runs are copied
  into `campaign_logs`.

## Metrology checks

- Current event detected: 180/180 packet captures.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum within-condition energy coefficient of variation: 0.569791%.
- Continuous-capture PPK2 sample loss: at most 0.002494%; all SF12 recovery
  points have 0% sample loss.
- All continuous rows use a 60.0 s analysis window. Transmitter-reported
  durations are 60,000 or 60,001 ms and all serial-error counters are zero.
- The missed-packet TX event at 32 B, +10 dBm, SF9 has the same 275.78 ms event
  duration and essentially the same mean current as the nine received controls,
  excluding a missing transmission or PPK2-detection failure.

## Packet delivery and targeted diagnosis

- COM29 TX to COM30 RX: 132/135 packets received in the authoritative campaign.
- COM30 TX to COM29 RX at +20 dBm: 45/45 packets received.
- Overall campaign packet delivery: 177/180 packets (98.333%).

Targeted ten-repetition controls produced:

| TX condition | Received / transmitted | Result |
|---|---:|---|
| 128 B, +2 dBm, SF9 | 10 / 10 | Original miss not reproduced |
| 8 B, +10 dBm, SF7 | 10 / 10 | Original miss not reproduced |
| 32 B, +10 dBm, SF9 | 9 / 10 | Intermittent peer reception reproduced |

The two isolated misses are therefore kept as measured rather than replaced by
the cleaner controls. The repeated 32 B/SF9 miss is an RF/receiver-path delivery
event on COM30, not an energy-measurement anomaly; the available data cannot
separate antenna placement, the individual peer radio, and ambient RF effects.

## Continuous average TX power

| Configured TX power | Mean current | Mean electrical power | 60 s energy |
|---:|---:|---:|---:|
| +2 dBm | 48.428 mA | 159.812 mW | 9588.735 mJ |
| +10 dBm | 66.928 mA | 220.862 mW | 13251.698 mJ |
| +20 dBm | 111.322 mA | 367.363 mW | 22041.760 mJ |

Continuous RX remained nearly independent of peer TX power: 10.827--10.885 mA
and 35.728--35.920 mW across the nine points.

## Continuous RX loss

| SF | TX power | Received / transmitted | Loss |
|---:|---:|---:|---:|
| 7 | +2 dBm | 419 / 427 | 1.874% |
| 7 | +10 dBm | 427 / 427 | 0.000% |
| 7 | +20 dBm | 425 / 427 | 0.468% |
| 9 | +2 dBm | 139 / 139 | 0.000% |
| 9 | +10 dBm | 136 / 139 | 2.158% |
| 9 | +20 dBm | 139 / 139 | 0.000% |
| 12 | +2 dBm | 20 / 20 | 0.000% |
| 12 | +10 dBm | 20 / 20 | 0.000% |
| 12 | +20 dBm | 20 / 20 | 0.000% |

The original uniform 19/20 SF12 counts were caused by draining the receiver and
ending the PPK2 capture before a frame started at the 60-second boundary could
finish. Extending both tails by one calculated frame airtime removed that
deterministic artefact without changing the 60-second electrical analysis
window. The remaining 13 losses among 1,758 transmitted continuous frames are
sporadic and non-monotonic with configured TX power, so they are preserved as
observed link delivery rather than treated as a metrology fault.

## Deliverables

- Consolidated CSV and XLSX files for TX energy, RX energy, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Authoritative manifest, session log, 40 attempt logs, callback log, recovery
  override, and compact continuous/packet diagnostic provenance.

The PDF/PNG renderings use the same generated CSV series as the LaTeX sources.
The report generators derive power levels and plot bounds from the campaign,
so the RA-01H +2/+10/+20 dBm matrix is represented without clipping.
