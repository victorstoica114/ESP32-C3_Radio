# Ebyte E32-433T33D power-campaign validation

## Verdict

The effective COM48/COM47 campaign is complete and suitable for comparison.
All 76 planned steps are represented after one targeted continuous-RX recovery.
No further hardware measurement is required for this module pair.

- Packet measurements: 72 batches, 360 runs, 360 detected current events, and
  360 retained raw traces.
- Packet delivery: 299/360 logical transfers were complete. The 61 incomplete
  transfers are repeatable rate/payload behavior, not missing PPK2 events.
- Continuous measurements: three TX and nine RX points, all with status `ok`,
  with 12 accepted 60-second raw traces.
- Maximum packet PPK2 sample loss is 0.294737%; maximum accepted continuous
  sample loss is 0.002978%.
- Maximum packet-energy coefficient of variation is 3.571063% at TX, 128 B,
  30 dBm, 19.2 kbps.
- Maximum accepted continuous peak is 830.226 mA, below the PPK2 1 A hard
  measurement ceiling.

The requested TX powers are modem settings, not calibrated radiated-power
measurements. The delivery losses are retained as measured end-to-end behavior
of this E32 pair and its transparent UART path.

## Setup

- Measured device: COM48; peer: COM47.
- PPK2: COM11 in ampere-meter mode at 3300 mV, with external VIN -> VOUT.
- Packet payloads: 8/32/58/128/512/1024 B.
- Requested powers: 24/27/30 dBm.
- Air rates: 0.3/4.8/19.2 kbps.
- Packet repetitions: five per point and direction.
- Continuous measurement: 58 B frames, 15 ms gap, 60 seconds per point.

The 33 dBm setting was deliberately excluded. A quick preflight produced a
sustained current near 925 mA, leaving insufficient margin below the PPK2 1 A
limit. The retained 24/27/30 dBm matrix therefore avoids a known measurement
range risk rather than silently clipping it.

## Recovered continuous-RX point

The original 4.8 kbps continuous-RX batch failed on all three campaign attempts
with `Radio serial transmission did not finish in time`. The quiet-period UART
drain extended its deadline whenever bytes kept arriving, so sustained traffic
could prevent it from returning before the PPK2 capture trigger deadline.

The reader now uses an absolute deadline and preserves partial UART lines across
successive bounded windows. The authoritative targeted repeat is:

`recovery/continuous_rx_4p8/20260720_162053_radio_ebyte_e32_433t33d_continuous_rx`

| Peer power | Frames received | Loss | Mean current | Mean power |
|---:|---:|---:|---:|---:|
| 24 dBm | 220/271 | 18.8192% | 48.220 mA | 159.126 mW |
| 27 dBm | 220/271 | 18.8192% | 56.075 mA | 185.047 mW |
| 30 dBm | 221/271 | 18.4502% | 61.436 mA | 202.739 mW |

`recovery_overrides.json` records the substitution. The three original failure
logs and the earlier rejected diagnostic runs remain preserved as provenance;
they are not included in consolidated CSV/XLSX data or graphs.

## Continuous average power and delivery

The common TX comparison uses 4.8 kbps. Mean TX power rises monotonically with
the requested output setting:

| Direction / requested peer power | Mean current | Mean power | 60 s energy |
|---|---:|---:|---:|
| TX, 24 dBm | 619.801 mA | 2045.343 mW | 122720.555 mJ |
| TX, 27 dBm | 699.189 mA | 2307.325 mW | 138439.490 mJ |
| TX, 30 dBm | 765.112 mA | 2524.871 mW | 151492.246 mJ |
| RX, 24 dBm stimulus | 48.220 mA | 159.126 mW | 9547.588 mJ |
| RX, 27 dBm stimulus | 56.075 mA | 185.047 mW | 11102.835 mJ |
| RX, 30 dBm stimulus | 61.436 mA | 202.739 mW | 12164.367 mJ |

RX delivery depends strongly on rate and only weakly on requested peer power:

| Rate | 24 dBm | 27 dBm | 30 dBm |
|---:|---:|---:|---:|
| 0.3 kbps | 13/13 (0% loss) | 13/13 (0%) | 13/13 (0%) |
| 4.8 kbps | 220/271 (18.8192%) | 220/271 (18.8192%) | 221/271 (18.4502%) |
| 19.2 kbps | 270/569 (52.5483%) | 284/569 (50.0879%) | 268/569 (52.8998%) |

Across the nine RX windows, 1,522 of 2,559 offered logical frames were
received. All nine accepted power captures are complete, and the transmitter
reported zero serial errors. The loss curves therefore describe the tested
link, not absent measurement data.

## Packet observations

All 360 packet current events were detected. High-rate 19.2 kbps transfers with
128/512/1024 B payloads repeatedly contained shortened or partial frames in the
receiver response. An independent continuous-RX sweep at the same rate showed
50.09-52.90% loss, supporting a real transport/link limitation rather than a
CSV parser artifact. One additional TX 1024 B, 27 dBm, 0.3 kbps transfer was
incomplete.

Two packet captures briefly crossed the conservative 850 mA review threshold:
858.668 mA at 1024 B/30 dBm/0.3 kbps and 856.992 mA at
1024 B/30 dBm/4.8 kbps. Both were short crests, remained below 1 A, and showed
no sustained clipping plateau. They are retained as valid measurements.

## Deliverables

The directory contains consolidated CSV/XLSX files for packet TX, packet RX,
large payloads, continuous power, continuous delivery, and loss versus radio
rate. Six LaTeX sources have matching PDF and PNG plots. The campaign manifest,
session log, callback log, all per-attempt logs, accepted recovery metadata, and
the explicit recovery override are archived under `campaign_logs`.
