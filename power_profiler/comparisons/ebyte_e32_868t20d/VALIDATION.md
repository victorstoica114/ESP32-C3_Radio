# Ebyte E32-868T20D power-campaign validation

## Verdict

The COM50/COM49 campaign is complete and suitable for comparison. All 76
planned steps completed on their first campaign attempt, and no additional
hardware measurement is required for this module pair.

- Packet measurements: 72 batches, 360 runs, 360 detected current events, and
  360 retained raw traces.
- Packet delivery: 359/360 logical transfers were complete. The sole incomplete
  transfer lost one 56-byte radio-content frame during the second RX repetition
  at 1024 B, 20 dBm, and 19.2 kbps.
- Continuous measurements: three TX and nine RX points, all with status `ok`,
  with 12 retained 60-second raw traces.
- Maximum packet PPK2 sample loss is 0.294737%; maximum continuous sample loss
  is 0.002978%.
- Maximum packet-energy coefficient of variation is 0.528072% at TX, 128 B,
  14 dBm, and 19.2 kbps.
- Maximum packet peak is 155.865 mA and maximum continuous peak is 155.104 mA;
  neither capture shows clipping or range saturation.
- All 372 gzip raw captures passed full decompression and CRC validation.

The requested TX powers are modem settings, not calibrated radiated-power
measurements. The delivery losses are retained as measured end-to-end behavior
of this E32 pair and its transparent UART path.

## Setup

- Measured device: COM50; peer: COM49.
- PPK2: COM11 in ampere-meter mode at 3300 mV, with external VIN -> VOUT.
- Packet payloads: 8/32/58/128/512/1024 B.
- Requested powers: 10/14/20 dBm.
- Air rates: 0.3/4.8/19.2 kbps.
- Packet repetitions: five per point and direction.
- Continuous measurement: 58 B frames, 15 ms gap, 60 seconds per point.

Every requested radio configuration was confirmed through the module's
physical `AT+CFG?` readback.

## Continuous average power

The common TX/RX comparison uses 4.8 kbps. TX consumption rises monotonically
with the configured output-power setting, while RX consumption remains almost
constant because the measured receiver's own operating state does not change
with the peer's configured TX power.

| Direction / configured peer power | Mean current | Mean power | 60 s energy |
|---|---:|---:|---:|
| TX, 10 dBm | 45.603 mA | 150.491 mW | 9029.453 mJ |
| TX, 14 dBm | 52.708 mA | 173.938 mW | 10436.267 mJ |
| TX, 20 dBm | 83.747 mA | 276.366 mW | 16581.980 mJ |
| RX, 10 dBm stimulus | 13.251 mA | 43.729 mW | 2623.770 mJ |
| RX, 14 dBm stimulus | 13.237 mA | 43.684 mW | 2621.011 mJ |
| RX, 20 dBm stimulus | 13.163 mA | 43.438 mW | 2606.264 mJ |

## Continuous RX delivery

Delivery depends strongly on radio rate and is essentially independent of the
configured peer power in this bench arrangement:

| Rate | 10 dBm | 14 dBm | 20 dBm |
|---:|---:|---:|---:|
| 0.3 kbps | 13/13 (0% loss) | 13/13 (0%) | 13/13 (0%) |
| 4.8 kbps | 226/271 (16.6052%) | 226/271 (16.6052%) | 226/271 (16.6052%) |
| 19.2 kbps | 451/569 (20.7381%) | 452/569 (20.5624%) | 451/569 (20.7381%) |

Across the nine RX windows, 2,071 of 2,559 offered logical frames were
received. All nine power captures are complete and every transmitting run
reported zero serial errors. The loss curve therefore describes the tested
transparent-radio throughput rather than missing measurement data.

## Packet and UART observations

The only incomplete packet transfer occurred at the most demanding tested RX
point: 1024 B, 20 dBm, 19.2 kbps, repetition two. Its receiver response is
short by exactly one full 56-byte content frame. The PPK event is present, the
1.6-second integration window is complete, its energy differs by less than
0.15% from the four complete repetitions, and its raw capture has the same
sample integrity as the surrounding runs. This is a radio/transparent-UART
delivery event, not a power-capture failure.

At 0.3 kbps, 18 otherwise complete RX responses begin with one NUL byte. The
pattern is repeatable after module resets and does not remove packet content.
The source logs and raw summaries remain untouched. Because XML forbids this
control character, the XLSX exporter removes only XML-illegal characters when
writing workbook text cells; numeric measurement data and CSV aggregates are
unchanged.

## Raw-data integrity

The campaign contains 360 packet and 12 continuous raw `.csv.gz` captures.
Their metadata agrees with the manifest profile, ports, PPK mode, voltage, and
sample counts. All gzip streams were fully decompressed and CRC-checked:

- Compressed size: 3,546,230,583 bytes.
- Validated uncompressed size: 20,996,911,303 bytes.
- Smallest raw capture: 627,078 bytes.

No raw file is absent, truncated, or assigned to the wrong campaign point.

## Deliverables

This directory contains consolidated CSV/XLSX files for packet TX, packet RX,
large payloads, continuous power, continuous delivery, and loss versus radio
rate. Six LaTeX sources have matching PDF and PNG plots. The campaign manifest,
session log, callback log, and all 76 per-attempt logs are archived under
`campaign_logs`.
