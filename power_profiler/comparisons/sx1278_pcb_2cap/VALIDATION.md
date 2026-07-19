# SX1278-PCB-2Cap campaign validation

## Verdict

The authoritative campaign `20260719_120937_campaign_radio_sx1278_pcb_2cap`
completed all 40 planned steps without technical retries or failed batches. The
measurement set is accepted for energy, average-power, and radio-loss analysis.
The measured RF losses are preserved, including the repeatable bidirectional
100% loss point at SF7 and -4 dBm.

## Configuration and coverage

- Profile: `RADIO_SX1278_PCB_2CAP`, with coding rate explicitly configured as
  `AT+CR=5` on both radios.
- Hardware variant: SX1278 module mounted on a carrier PCB with two additional
  capacitors.
- Measured DUT: COM25; peer: COM26; PPK2: COM11 in Ampere Meter mode at 3300 mV.
- Packet TX: 27 aggregate points and 135 raw captures across three payloads,
  three spreading factors, and three configured TX powers.
- Packet RX: 9 aggregate points and 45 raw captures at 20 dBm.
- Continuous tests: three TX power points at SF9 and nine RX loss/power points
  across SF7, SF9, and SF12, each measured for 60 seconds.
- Full campaign raw coverage: 192/192 gzip traces, 626,844,185 bytes, with no
  empty files.

## Metrology checks

- Current event detected: 180/180 packet captures.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum within-condition energy coefficient of variation: 0.594773%.
- Continuous-capture PPK2 sample loss: at most 0.002494%.
- No payload-energy, spreading-factor, or TX-power energy inversions were
  observed.
- No tracebacks, nonzero serial-error counters, or corrupt/empty raw captures
  were found in the preserved data.

## Packet delivery

- COM25 TX to COM26 RX: 109/135 packets received. All 15 SF7/-4 dBm packets
  were lost. SF9/-4 dBm delivered 4/15 packets, while SF12/-4 dBm and every
  tested point at 10 or 20 dBm delivered all packets.
- COM26 TX to COM25 RX at the campaign RX setting of 20 dBm: 44/45 packets
  received. The isolated loss occurred at 128 B and SF9.
- Overall campaign packet delivery: 153/180 packets (85.0%). The 27 losses are
  retained in the consolidated CSV/XLSX data.

## Continuous average TX power

| Configured TX power | Mean current | Mean electrical power | 60 s energy |
|---:|---:|---:|---:|
| -4 dBm | 11.834 mA | 39.051 mW | 2343.060 mJ |
| 10 dBm | 42.971 mA | 141.803 mW | 8508.185 mJ |
| 20 dBm | 72.030 mA | 237.698 mW | 14261.905 mJ |

## Continuous RX loss

| SF | TX power | Received / transmitted | Loss |
|---:|---:|---:|---:|
| 7 | -4 dBm | 0 / 450 | 100.000% |
| 7 | 10 dBm | 448 / 449 | 0.223% |
| 7 | 20 dBm | 450 / 450 | 0.000% |
| 9 | -4 dBm | 0 / 148 | 100.000% |
| 9 | 10 dBm | 134 / 148 | 9.459% |
| 9 | 20 dBm | 137 / 148 | 7.432% |
| 12 | -4 dBm | 19 / 22 | 13.636% |
| 12 | 10 dBm | 19 / 22 | 13.636% |
| 12 | 20 dBm | 19 / 22 | 13.636% |

The equal 19/22 SF12 result at all powers is consistent with deterministic
continuous-window boundary loss rather than an electrical measurement fault.

## Bidirectional RF diagnosis

Two targeted 20-packet controls were run after the campaign while the same
modules remained connected:

- COM25 TX to COM26 RX, 64 B, SF7/-4 dBm: 0/20 received.
- COM26 TX to COM25 RX, 64 B, SF7/-4 dBm: 0/20 received.

All 40 diagnostic electrical events were detected. Their energy coefficients
of variation were 0.156784% and 0.116916%, respectively. The controls therefore
confirm a bidirectional RF-link threshold, not a PPK2 sampling failure or an
intermittent power/reset issue. The available data cannot separate antenna and
layout effects from radio-to-radio variation or the actual conducted output at
the nominal -4 dBm setting.

## Cross-variant context

Compared with the previously measured SX1278-Naked module, continuous TX
current for this DUT was 1.8% higher at -4 dBm, 21.1% lower at 10 dBm, and 1.2%
lower at 20 dBm. Its mean continuous RX current was 11.700 mA, between the
Naked (11.438 mA), Adafruit level-shifter (11.900 mA), and Shielded (12.268 mA)
measurements.

These differences demonstrate that the hardware variants are measurably
different, but they do not by themselves prove that the two capacitors are the
cause: the tested PCBs, individual radios, antennas, and RF paths also differ.
The stable event energy does support the narrower conclusion that the added
capacitors did not introduce observable supply instability during this test.

## Deliverables

- Consolidated CSV and XLSX files for TX energy, RX energy, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Authoritative manifest, session log, 40 attempt logs, callback log, and
  compact bidirectional diagnostic provenance.

The PDF/PNG renderings use the same generated CSV series as the LaTeX sources.
They were rendered with the dependency-free project renderer.
