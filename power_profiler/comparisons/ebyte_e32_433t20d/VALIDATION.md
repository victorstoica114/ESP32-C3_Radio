# Ebyte E32-433T20D power-campaign validation

## Verdict

The COM50/COM49 campaign is complete and suitable for comparison. All 76
planned steps completed on their first campaign attempt, and no additional
hardware measurement is required for this module pair.

The pair was initially recorded as E32-868T20D because COM49/COM50 had that
assignment in the historical port map. The physical modules used for this
campaign were subsequently confirmed by the operator to be E32-433T20D. The
profile ID, report names, tables, workbooks, and plot titles were corrected on
2026-07-20. Original timestamped session-directory names are retained where
they appear in provenance fields so the source captures remain traceable.

- Packet measurements: 72 batches, 360 runs, 360 detected current events, and
  360 retained raw traces.
- Packet delivery: 359/360 logical transfers were complete. The sole incomplete
  transfer lost one 56-byte radio frame during the fifth RX repetition at
  1024 B, 20 dBm, and 19.2 kbps.
- Continuous measurements: three TX and nine RX points, all with status `ok`,
  with 12 retained 60-second raw traces.
- Maximum packet PPK2 sample loss is 0.294737%; maximum continuous sample loss
  is 0.002978%.
- Maximum packet-energy coefficient of variation is 0.498635% at TX, 58 B,
  14 dBm, and 4.8 kbps.
- Maximum packet peak is 154.343 mA and maximum continuous peak is 152.061 mA,
  both comfortably inside the PPK2 range used by the campaign.
- All 372 gzip raw captures passed decompression and CRC validation.

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
| TX, 10 dBm | 45.470 mA | 150.051 mW | 9003.064 mJ |
| TX, 14 dBm | 52.438 mA | 173.046 mW | 10382.750 mJ |
| TX, 20 dBm | 83.594 mA | 275.859 mW | 16551.547 mJ |
| RX, 10 dBm stimulus | 13.266 mA | 43.777 mW | 2626.604 mJ |
| RX, 14 dBm stimulus | 13.234 mA | 43.672 mW | 2620.298 mJ |
| RX, 20 dBm stimulus | 13.164 mA | 43.441 mW | 2606.486 mJ |

## Continuous RX delivery

Delivery depends strongly on radio rate and is essentially independent of the
configured peer power in this bench arrangement:

| Rate | 10 dBm | 14 dBm | 20 dBm |
|---:|---:|---:|---:|
| 0.3 kbps | 13/13 (0% loss) | 13/13 (0%) | 13/13 (0%) |
| 4.8 kbps | 226/271 (16.6052%) | 226/271 (16.6052%) | 226/271 (16.6052%) |
| 19.2 kbps | 451/569 (20.7381%) | 452/569 (20.5624%) | 452/569 (20.5624%) |

Across the nine RX windows, 2,072 of 2,559 offered logical frames were
received. All nine power captures are complete and every transmitting run
reported zero serial errors. The loss curve therefore describes the tested
transparent-radio throughput rather than missing measurement data.

## Packet and UART observations

The only incomplete packet transfer occurred at the most demanding tested RX
point: 1024 B, 20 dBm, 19.2 kbps, repetition five. Its receiver response is
short by exactly one full 56-byte content frame. The PPK event is present, the
1.6-second integration window is complete, its energy is only about 0.26%
below repetitions one through four, and its raw capture has the same sample
integrity as the surrounding runs. This is a radio/transparent-UART delivery
event, not a power-capture failure.

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

- Compressed size: 3,588,324,734 bytes.
- Validated uncompressed size: 21,001,171,093 bytes.
- Smallest raw capture: 630,979 bytes.

No raw file is absent, truncated, or assigned to the wrong campaign point.

## Deliverables

This directory contains consolidated CSV/XLSX files for packet TX, packet RX,
large payloads, continuous power, continuous delivery, and loss versus radio
rate. Six LaTeX sources have matching PDF and PNG plots. The campaign manifest,
session log, callback log, and all 76 per-attempt logs are archived under
`campaign_logs`.
