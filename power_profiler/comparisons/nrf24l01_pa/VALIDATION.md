# nRF24L01+PA campaign validation

Authoritative campaign: `20260720_063622_campaign_radio_nrf24l01_pa`

## Verdict

The measurement set is complete and accepted for packet-energy, continuous
average-power, delivery, and loss-versus-rate analysis. All 40/40 campaign
batches completed. Two initial AT synchronization timeouts recovered on the
second attempt, so the campaign used 42 attempts in total. The accepted PPK2
data are complete and all authoritative raw streams pass gzip integrity checks.

The pair is not a clean RF reference link. At the two higher configured TX
powers, delivery degrades severely, especially at 250 kbps. This behavior was
reproduced outside the power campaign and is retained as a property of the
connected nRF24L01+PA pair and bench layout rather than hidden as a failed
measurement.

## Configuration and coverage

- Profile: `RADIO_NRF24L01_PA`, channel 80, shared address `0123456789`,
  dynamic payloads, CRC enabled, auto-ack disabled.
- Configured rates: 250, 1000, and 2000 kbps.
- Configured TX powers: -18, -6, and 0 dBm. These are the nRF24 stimulus
  settings; they are not a calibrated conducted measurement of the external
  PA output.
- Payloads: 8, 16, and 32 B; five repetitions per packet point.
- Measured DUT: COM43; peer: COM44; PPK2: COM11 in Ampere Meter mode at
  3300 mV. The DUT remained externally powered while VIN-to-VOUT stayed
  enabled and guarded.
- Packet TX: 27 aggregate points and 135 raw captures.
- Packet RX: 9 aggregate points and 45 raw captures at 0 dBm stimulus.
- Continuous tests: three TX points at 1 Mbps and nine RX rate/power points,
  each with a 60 s active window.
- Raw coverage: 192/192 authoritative gzip traces. Every stream was fully
  decompressed and passed its gzip CRC: 540,225,049 compressed bytes and
  3,309,339,844 uncompressed bytes.

## Integrity checks

- Campaign steps: 40 completed, zero failed. Two initial COM43 AT sync
  timeouts at TX, -6 dBm, 2 Mbps, 8 B and 16 B recovered on attempt two.
- Packet current events: 180/180 detected. Packet delivery was 116/180, with
  64 RF losses retained as measured.
- Continuous rows: 12/12 have complete 60 s PPK2 windows. Ten are `ok`; two
  are verified `no_rx_data` rows representing 100% RF loss, not missing power
  measurements.
- Transmitter serial errors: zero in the continuous and sustained RF tests.
- Maximum packet PPK2 sample loss: 0.775194%; maximum continuous PPK2 sample
  loss: 0.002494%.
- Maximum packet-energy coefficient of variation: 35.053985% at TX, 16 B,
  -18 dBm, 2 Mbps. A separate ten-repetition-per-size diagnostic reproduced
  variable pulse duration with stable current peaks, so this is real device or
  front-end variability rather than a missed PPK2 trigger.

## Continuous average power

The common TX comparison uses 32 B frames at 1 Mbps and a 15 ms gap.

| Direction / configured TX power | Mean current | Mean electrical power | 60 s energy |
|---|---:|---:|---:|
| TX, -18 dBm | 0.846 mA | 2.790 mW | 167.423 mJ |
| TX, -6 dBm | 1.855 mA | 6.121 mW | 367.263 mJ |
| TX, 0 dBm | 2.721 mA | 8.980 mW | 538.814 mJ |
| RX, -18 dBm stimulus | 20.227 mA | 66.748 mW | 4004.885 mJ |
| RX, -6 dBm stimulus | 21.996 mA | 72.588 mW | 4355.261 mJ |
| RX, 0 dBm stimulus | 22.212 mA | 73.299 mW | 4397.961 mJ |

Compared with the previously measured plain nRF24L01 pair at the same 1 Mbps
continuous settings, the PA board draws approximately 3.17x, 4.64x, and 5.30x
the TX average current at -18, -6, and 0 dBm. Its RX current is approximately
1.68x to 1.75x higher, consistent with an always-active external receive
front-end. RX remains much higher than duty-cycled TX because the measured
radio and receive front-end stay active for the complete 60 s window.

## Continuous RX delivery

| Rate | -18 dBm | -6 dBm | 0 dBm |
|---:|---:|---:|---:|
| 250 kbps | 3360/3365 (0.1486% loss) | 0/3366 (100%) | 0/3366 (100%) |
| 1000 kbps | 3568/3568 (0%) | 1922/3566 (46.1021%) | 1872/3567 (47.5189%) |
| 2000 kbps | 3602/3602 (0%) | 2661/3603 (26.1449%) | 2659/3601 (26.1594%) |

Across the nine RX windows, 19,644 of 31,604 offered frames were received.
The loss depends strongly on both data rate and configured transmitter power.

## Diagnosed anomaly

The quick check completed all six measurement steps but correctly rejected the
pair as campaign-ready: only the fast TX and slow low-power RX link checks
passed, while the other four exposed missing RF packets. Peak current was
132.314 mA, below the configured 850 mA check limit.

A separate 36-scenario sustained diagnostic removed PPK2 from the traffic path
and tested both link directions on channels 80 and 40. It reproduced the loss
with zero serial errors. On channel 80, both directions lost 100% at 250 kbps
and -6/0 dBm, roughly 39--51% at 1 Mbps, and roughly 20--33% at 2 Mbps. At
-18 dBm, channel 80 was essentially clean. Channel 40 also showed substantial
power/rate-dependent loss.

Both devices reported the expected RF register programming: at 250 kbps,
`RF_SETUP` was `0x21`, `0x25`, and `0x27` for -18, -6, and 0 dBm; the 1 Mbps
and 2 Mbps 0 dBm values were `0x07` and `0x0F`. Auto-ack was disabled, dynamic
payloads were enabled, and the channel was 80. Repeating the sustained test
with the nRF24 internal LNA disabled did not improve delivery.

These checks exclude PPK2, the web runner, serial overruns, incorrect nRF24
register settings, one isolated RF channel, and simple internal-LNA saturation.
The remaining leading hypotheses are the external PA/LNA front-end behavior,
local supply/decoupling integrity, and close-range RF coupling in the bench
layout. A follow-up should use a new named campaign after increasing antenna
separation and checking local PA supply decoupling; it must not overwrite this
baseline.

## Post-validation cleanup

Cleanup removed 42 non-authoritative quick-check and recovery raw traces
(14,909,740 compressed bytes) after all streams passed gzip CRC verification
and their compact CSV/JSON results and logs were archived in this comparison.
Duplicate diagnostic source copies were removed after SHA-256 verification.
All 192 authoritative campaign traces remain present and unchanged.

## Deliverables

- Consolidated CSV/XLSX files for packet TX, packet RX, continuous power,
  delivery, and loss versus radio rate.
- Six LaTeX sources and matching dependency-free PDF/PNG renderings.
- Campaign manifest, session and attempt logs, compact quick-check results,
  RF register probes, channel-isolation logs, sustained bidirectional test
  results, LNA-off diagnostic, and low-power/2 Mbps recovery measurements.
