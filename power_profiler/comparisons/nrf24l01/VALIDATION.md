# nRF24L01 campaign validation

Authoritative campaign: `20260720_045645_campaign_radio_nrf24l01`

## Verdict

The measurement set is complete and accepted for packet-energy, continuous
average-power, delivery, and loss-versus-rate analysis. All 40/40 campaign
batches completed on their first attempt. The raw PPK2 data are intact, and
the observed RF loss is a repeatable characteristic of this module pair and
bench setup rather than a failed measurement.

The pair is not a clean high-power reference link. Raising the configured TX
power from -18 dBm to -6 or 0 dBm causes severe loss at 250 kbps and 1 Mbps,
while 2 Mbps remains loss-free on campaign channel 80. This result should be
preserved, not replaced with selectively successful transfers.

## Configuration and coverage

- Profile: `RADIO_NRF24L01`, channel 80, shared address `0123456789`, dynamic
  payloads, CRC enabled, auto-ack disabled.
- Configured rates: 250, 1000, and 2000 kbps.
- Configured TX powers: -18, -6, and 0 dBm.
- Payloads: 8, 16, and 32 B; five repetitions per packet point.
- Measured DUT: COM41; peer: COM42; PPK2: COM11 in Ampere Meter mode at
  3300 mV. The DUT remained externally powered while VIN-to-VOUT stayed
  guarded.
- Packet TX: 27 aggregate points and 135 raw captures.
- Packet RX: 9 aggregate points and 45 raw captures at 0 dBm stimulus.
- Continuous tests: three TX points at 1 Mbps and nine RX rate/power points,
  each with a 60 s active window.
- Raw coverage: 192/192 gzip traces. Every stream was decompressed fully and
  passed its gzip CRC: 562,502,506 compressed bytes and 3,311,460,490
  uncompressed bytes.

## Integrity checks

- Final bidirectional channel-isolation diagnostics passed 18/18 checks at
  each of 250 kbps, 1 Mbps, and 2 Mbps.
- The first diagnostic used an identifier longer than the physical 32 B
  payload and was correctly rejected by the firmware; a subsequent 250 kbps
  run passed 18/18 with a valid identifier. Both logs are retained.
- Initial quick check: 4/4 batches passed, all 8 packets received, and peak
  current 35.688 mA. This exposed a coverage gap rather than a hardware pass:
  it did not combine maximum power with minimum rate.
- Packet current events: 180/180 detected. Packet delivery was 142/180, with
  38 RF losses retained as measured.
- Continuous rows: 12/12 have status `ok`, 60 s active analysis windows, and
  zero transmitter serial errors.
- Maximum packet-energy coefficient of variation: 5.080910% (TX, 16 B,
  -18 dBm, 2 Mbps).
- Maximum packet PPK2 sample loss: 0.717651%; maximum continuous PPK2 sample
  loss: 0.002494%. These small stream gaps do not coincide with the RF loss
  pattern and remain below the campaign acceptance threshold.

## Continuous average power

The common TX comparison uses 32 B frames at 1 Mbps.

| Direction / configured TX power | Mean current | Mean electrical power | 60 s energy |
|---|---:|---:|---:|
| TX, -18 dBm | 0.267 mA | 0.881 mW | 52.877 mJ |
| TX, -6 dBm | 0.400 mA | 1.319 mW | 79.156 mJ |
| TX, 0 dBm | 0.514 mA | 1.695 mW | 101.684 mJ |
| RX, -18 dBm stimulus | 12.059 mA | 39.796 mW | 2387.758 mJ |
| RX, -6 dBm stimulus | 12.539 mA | 41.377 mW | 2482.631 mJ |
| RX, 0 dBm stimulus | 12.667 mA | 41.801 mW | 2508.060 mJ |

TX current and power rise monotonically with configured output power. RX
draws substantially more average current than the duty-cycled host-driven TX
stream because the measured radio remains in receive mode throughout the
active window.

## Continuous RX delivery

| Rate | -18 dBm | -6 dBm | 0 dBm |
|---:|---:|---:|---:|
| 250 kbps | 3366/3367 (0.0297% loss) | 1999/3364 (40.5767%) | 2194/3364 (34.7800%) |
| 1000 kbps | 3566/3566 (0%) | 2802/3566 (21.4246%) | 2594/3565 (27.2370%) |
| 2000 kbps | 3603/3603 (0%) | 3603/3603 (0%) | 3602/3602 (0%) |

Across the nine RX windows, 27,329 of 31,600 offered frames were received.
The loss is strongly dependent on rate and configured TX power.

## Diagnosed anomaly

A separate 36-scenario diagnostic removed PPK2 from the traffic path and
tested both link directions on channels 80 and 40. It reproduced the campaign
pattern with zero serial errors:

- On channel 80, -18 dBm delivered every frame at all rates. At -6/0 dBm,
  loss was 30--98% at 250 kbps and 21--41% at 1 Mbps, while 2 Mbps remained
  loss-free in both directions.
- On channel 40, -18 dBm again delivered every frame. At -6/0 dBm, 250 kbps
  lost 100%, 1 Mbps lost roughly 36--41%, and 2 Mbps lost roughly 19--26%.
- Both radios reported `RF_SETUP=0x21`, `0x25`, and `0x27` for 250 kbps at
  -18, -6, and 0 dBm. The power/rate register programming is correct.

The data therefore exclude PPK2, the web runner, a transmitter serial
overrun, and a single interfered RF channel. The leading hardware causes are
insufficient local VDD decoupling/supply integrity or a non-ideal compatible
radio-module implementation at higher output power. Nordic's nRF24L01+
product specification recommends RF-grade decoupling close to VDD, a larger
ceramic capacitor (approximately 4.7 uF) in parallel with the smaller
capacitors, filtered supply routing, and short supply connections.

The profiler quick check now includes maximum-power/minimum-rate TX and RX
cases with a full 32 B frame, so this interaction will be caught before future
campaigns. If local decoupling or antenna separation is changed, the correct
next step is a new named comparison campaign; these results remain the
authoritative baseline for the modules as connected.

## Post-validation cleanup

Cleanup removed the eight non-authoritative quick-check raw traces (2,867,760
bytes) after their compact CSV/JSON data and all logs were copied into this
comparison. Duplicate source copies of seven diagnostic logs and the sustained
diagnostic directory were also removed after SHA-256 verification. All 192
authoritative campaign traces remain present and unchanged.

## Deliverables

- Consolidated CSV/XLSX files for packet TX, packet RX, continuous power,
  delivery, and loss versus radio rate.
- Six LaTeX sources and matching dependency-free PDF/PNG renderings.
- Campaign manifest, session/callback logs, all 40 attempt logs, compact quick
  check results/logs, RF register probes, channel-isolation logs, and the
  sustained bidirectional diagnostic CSV/log.
