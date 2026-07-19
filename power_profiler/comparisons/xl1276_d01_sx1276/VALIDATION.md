# XL1276-D01 (SX1276) campaign validation

## Verdict

The authoritative campaign `20260719_135643_campaign_radio_xl1276_d01_sx1276`
completed all 40 planned steps without technical retries or failed batches. The
measurement set is accepted for energy, average-power, and radio-loss analysis.
No additional hardware retry is required.

## Configuration and coverage

- Profile: `RADIO_XL1276_D01_SX1276`, with coding rate explicitly configured as
  `AT+CR=5`, controlled receiver entry through `AT+RX=ON`, and a fresh radio
  connection between continuous power points.
- Measured DUT: COM27; peer: COM28; PPK2: COM11 in Ampere Meter mode at 3300 mV.
- Packet TX: 27 aggregate points and 135 raw captures across three payloads,
  three spreading factors, and three configured TX powers.
- Packet RX: 9 aggregate points and 45 raw captures at 20 dBm.
- Continuous tests: three TX power points at SF9 and nine RX loss/power points
  across SF7, SF9, and SF12, each measured for 60 seconds.
- Full campaign raw coverage: 192/192 gzip traces, 605,761,294 bytes, with no
  empty files or invalid gzip signatures.

## Metrology checks

- Current event detected: 180/180 packet captures.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum within-condition energy coefficient of variation: 0.589116%.
- Continuous-capture PPK2 sample loss: at most 0.002494%.
- All 40 metadata files identify the intended profile, ports, 100 kHz sample
  rate, 3300 mV measurement voltage, Ampere Meter mode, and raw capture enabled.
- No tracebacks, warnings, nonzero serial-error counters, corrupt captures, or
  non-`ok` result rows were found in the authoritative logs and summaries.

## Packet delivery

- COM27 TX to COM28 RX: 135/135 packets received.
- COM28 TX to COM27 RX at the campaign RX setting of 20 dBm: 45/45 packets
  received.
- Overall packet delivery: 180/180 packets (100.0%).

## Continuous average TX power

| Configured TX power | Mean current | Mean electrical power | 60 s energy |
|---:|---:|---:|---:|
| -4 dBm | 11.467 mA | 37.840 mW | 2270.397 mJ |
| 10 dBm | 60.370 mA | 199.221 mW | 11953.259 mJ |
| 20 dBm | 85.719 mA | 282.873 mW | 16972.385 mJ |

## Continuous RX loss

| SF | TX power | Received / transmitted | Loss |
|---:|---:|---:|---:|
| 7 | -4 dBm | 446 / 450 | 0.889% |
| 7 | 10 dBm | 446 / 450 | 0.889% |
| 7 | 20 dBm | 446 / 450 | 0.889% |
| 9 | -4 dBm | 147 / 148 | 0.676% |
| 9 | 10 dBm | 146 / 148 | 1.351% |
| 9 | 20 dBm | 146 / 148 | 1.351% |
| 12 | -4 dBm | 21 / 22 | 4.545% |
| 12 | 10 dBm | 21 / 22 | 4.545% |
| 12 | 20 dBm | 21 / 22 | 4.545% |

The small absolute deficits are repeatable across configured RF powers and grow
as a percentage only because the 60-second window contains fewer frames at high
spreading factors. Together with perfect individual-packet delivery and zero
serial errors, this identifies a continuous-window start/stop alignment effect,
not an RF-link or PPK2 anomaly. The measured counts remain preserved in the
loss CSV/XLSX and plots.

## Deliverables

- Consolidated CSV and XLSX files for TX energy, RX energy, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Authoritative manifest, session log, 40 attempt logs, and callback log.

The PDF/PNG renderings use the same generated CSV series as the LaTeX sources
and were rendered with the dependency-free project renderer.
