# SX1278-Naked campaign validation

## Verdict

The authoritative campaign `20260719_085301_campaign_radio_sx1278_naked`
completed all 40 planned steps with no technical retries or failed batches. The
measurement set is accepted for energy, average-power, and radio-loss analysis.
Measured radio losses are preserved, including the repeatable 100% loss point.

## Configuration and coverage

- Profile: `RADIO_SX1278_NAKED`, with coding rate explicitly configured as
  `AT+CR=5` on both radios.
- Measured DUT: COM19; peer: COM20; PPK2: COM11 in Ampere Meter mode at 3300 mV.
- Packet TX: 27 aggregate points, 135 raw captures, three payloads, three
  spreading factors, and three configured TX powers.
- Packet RX: 9 aggregate points and 45 raw captures at 20 dBm.
- Continuous tests: three TX power points at SF9 and nine RX loss/power points
  across SF7, SF9, and SF12, each measured for 60 seconds.
- Full raw PPK2 traces were saved in the authoritative web session.

## Metrology checks

- Current event detected: 180/180 packet captures.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum within-condition energy coefficient of variation: 0.619955%.
- Continuous-capture PPK2 sample loss: at most 0.002494%.
- No payload-energy, spreading-factor, or TX-power energy inversions were found.

## Packet delivery

- COM19 TX to COM20 RX: 134/135 packets received. The sole loss was repetition
  4 at 8 B, SF9, and -4 dBm.
- COM20 TX to COM19 RX at the campaign RX setting of 20 dBm: 45/45 packets
  received.

## Continuous average TX power

| Configured TX power | Mean current | Mean electrical power |
|---:|---:|---:|
| -4 dBm | 11.623 mA | 38.357 mW |
| 10 dBm | 54.438 mA | 179.644 mW |
| 20 dBm | 72.917 mA | 240.625 mW |

## Continuous RX loss

| SF | TX power | Received / transmitted | Loss |
|---:|---:|---:|---:|
| 7 | -4 dBm | 0 / 450 | 100.000% |
| 7 | 10 dBm | 449 / 449 | 0.000% |
| 7 | 20 dBm | 447 / 450 | 0.667% |
| 9 | -4 dBm | 83 / 148 | 43.919% |
| 9 | 10 dBm | 137 / 148 | 7.432% |
| 9 | 20 dBm | 137 / 148 | 7.432% |
| 12 | -4 dBm | 19 / 22 | 13.636% |
| 12 | 10 dBm | 19 / 22 | 13.636% |
| 12 | 20 dBm | 19 / 22 | 13.636% |

## Directional-link diagnosis

The SF7/-4 dBm total-loss result was investigated while the same modules were
still connected:

- Autorotative continuous retry, COM20 TX to COM19 RX: 0/449 at -4 dBm,
  450/450 at 10 dBm, and 449/450 at 20 dBm.
- Targeted individual-packet control, COM20 TX to COM19 RX at SF7/-4 dBm:
  0/20 received.
- Reciprocal direction from the campaign, COM19 TX to COM20 RX at SF7/-4 dBm:
  15/15 received across the three payload sizes.

This proves a repeatable directional asymmetry between the two physical radio
paths. The available measurements cannot separate weak COM20 TX output/antenna
path from reduced COM19 RX sensitivity. It is not a PPK2 sampling problem and
must not be attributed solely to the absence of a shield.

The original 0/450 result remains authoritative because the autorotative retry
confirmed it. Both diagnostic summaries and their metadata are copied under
`campaign_logs/recovery`.

## Deliverables

- Consolidated CSV and XLSX files for TX energy, RX energy, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Authoritative manifest, session log, 40 attempt logs, callback log, and the
  compact diagnostic provenance.

The PDF/PNG renderings use the same generated CSV series as the LaTeX sources.
They were rendered with the dependency-free project renderer because the local
MiKTeX profile was not writable in the callback sandbox.
