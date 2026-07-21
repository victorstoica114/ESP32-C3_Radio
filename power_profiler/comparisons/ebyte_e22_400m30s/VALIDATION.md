# Ebyte E22-400M30S power-campaign validation

## Verdict

The COM52/COM51 campaign is complete and suitable for electrical-energy and
average-power comparison. All 40 planned steps completed on their first
attempt. Every one of the 180 packet runs produced a valid PPK2 current event,
and all 12 continuous points have status `ok`.

The campaign also exposed a reproducible, direction-specific delivery limit:
COM51 does not receive long 128 B SF12 packets from COM52 at the 10 and 18 dBm
SX1268 front-stage settings in the current bench geometry. This does not
invalidate the COM52 TX energy captures; their current events, integration
windows, sample continuity, and repetition stability are valid.

`AT+PWR` controls the SX1268 front-stage setting. On E22-400M30S, the maximum
accepted setting of 18 corresponds to approximately 30 dBm module output; the
x-axis is therefore a configured drive setting rather than a calibrated RF
power measurement.

## Setup

- Measured device: COM52; peer: COM51.
- PPK2: COM11 in ampere-meter mode at 3300 mV, external VIN to VOUT.
- Payloads: 8/32/128 B.
- Front-stage settings: -9/10/18 dBm.
- LoRa profiles: SF7/SF9/SF12 at 125 kHz bandwidth.
- Packet repetitions: five per point and direction.
- Continuous test: 64 B frames, 15 ms host gap, 60 seconds per point.

## Measurement integrity

- Campaign: 40/40 steps, 40 attempts, no retry or failed step.
- Packet captures: 180/180 current events detected.
- Packet sample loss: at most 0.525714%.
- Continuous sample loss: at most 0.003631%.
- Maximum packet energy CV: 1.970471%, at RX 128 B / 18 / SF7.
- Maximum observed current: 69.672 mA; no PPK2 clipping or range saturation.
- No metadata mismatch or non-finite numeric value was found.

All 192 authoritative gzip traces decompressed fully and passed their gzip CRC.
They occupy 1,105,290,276 bytes compressed and 4,242,726,782 bytes after
validation. The 15 targeted diagnostic traces also passed CRC and occupy
87,038,930 bytes compressed.

## Continuous average power at SF9

| Direction / setting | Mean current | Mean power | 60 s energy |
|---|---:|---:|---:|
| TX, -9 | 11.185 mA | 36.909 mW | 2214.561 mJ |
| TX, 10 | 33.625 mA | 110.961 mW | 6657.673 mJ |
| TX, 18 | 58.162 mA | 191.934 mW | 11516.060 mJ |
| RX, -9 stimulus | 5.762 mA | 19.015 mW | 1140.895 mJ |
| RX, 10 stimulus | 5.591 mA | 18.449 mW | 1106.965 mJ |
| RX, 18 stimulus | 5.500 mA | 18.150 mW | 1089.000 mJ |

TX consumption rises monotonically with front-stage drive. RX power remains
nearly constant because the measured receiver state does not change with the
peer's configured TX setting.

## Continuous delivery and loss versus speed

| LoRa profile | Effective payload speed | -9 | 10 | 18 |
|---|---:|---:|---:|---:|
| SF12 / 125 kHz | 0.188 kbps | 20/22 (9.091% loss) | 20/22 (9.091%) | 20/22 (9.091%) |
| SF9 / 125 kHz | 1.26 kbps | 108/148 (27.027%) | 108/148 (27.027%) | 108/148 (27.027%) |
| SF7 / 125 kHz | 3.83 kbps | 335/450 (25.556%) | 335/449 (25.390%) | 336/450 (25.333%) |

Across the nine RX windows, 1,390 of 1,859 offered frames were received. Loss
is effectively independent of peer power, so the curve represents the tested
continuous receive/re-arm throughput rather than a link-budget threshold.

## Long-packet directional diagnostic

The campaign recorded 11 missing peer confirmations, all for COM52 to COM51 at
128 B, SF12, and 125 kHz: one at -9, five at 10, and five at 18. The associated
TX current captures are complete and stable.

The profiler's receive tail was increased from 50 ms to 250 ms because a full
128-byte serial confirmation itself requires over 133 ms at 9600 baud. Targeted
five-repetition controls then produced:

| Front-stage setting | COM52 to COM51 delivery |
|---:|---:|
| -9 | 5/5 |
| 10 | 0/5 |
| 18 | 0/5 |

The unchanged failure at 10 and 18 rules out a host serial timeout. The reverse
campaign direction, COM51 to COM52, delivered 5/5 at 18 for the same 128 B SF12
point. The effect is therefore reproducible and direction-specific to COM51 as
receiver under long, high-drive SF12 packets. No recovery override is applied:
the measured delivery behavior remains visible, while all electrical-energy
values remain authoritative.

## Deliverables

This directory contains consolidated packet TX/RX CSV and XLSX workbooks,
continuous-power CSV/XLSX data, loss-versus-speed CSV/XLSX data, and four LaTeX
plots with matching PDF and PNG renderings. `campaign_logs` archives the
manifest, session and callback logs, all 40 attempt logs, plus compact metadata
and summaries for the three targeted diagnostics. Raw traces remain in the
source web session and are intentionally excluded from Git because of size.
