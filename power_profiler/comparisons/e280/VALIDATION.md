# Ebyte E280-2G4T12S (SX1280) power-campaign validation

## Verdict

The effective COM45/COM46 campaign is complete and suitable as the electrical
baseline for this exact module pair and bench layout. All 40 planned steps are
represented after three continuous-RX and six packet recovery overrides.

- Packet measurements: 36 points, 180/180 detected current events, 180/180
  delivered frames, and 180 retained raw traces.
- Continuous measurements: three TX and nine RX points, all with status `ok`,
  with 12 retained 60-second raw traces.
- Raw-data audit: all 192 effective gzip streams pass CRC validation;
  573,969,475 compressed bytes expand to 3,606,142,963 bytes.
- Maximum packet PPK2 sample loss is 0.294737%; maximum continuous sample loss
  is 0.002494%.
- Maximum packet-energy coefficient of variation is 5.387485% at TX, 32 B,
  4 dBm, 2M. The maximum RX value is 0.564611%.

The continuous delivery-loss measurements are valid observations of the tested
transparent-UART/RF path, but they are not a clean-link reference. Configured
TX powers are requested modem settings, not calibrated radiated-power readings.

## Setup and campaign recovery

- Measured device: COM45; peer: COM46.
- PPK2: COM11 in ampere-meter mode at 3300 mV, with external VIN -> VOUT.
- Radio channel: 10 for the 1K, 100K, and 2M E280 modes.
- Packet matrix: 8/32/64 B, 4/7/12 dBm, three air rates, five repetitions in
  each direction as planned by the campaign.
- Continuous matrix: 64 B logical frames, 15 ms gap, 60 seconds per point.

The original campaign completed its 36 packet batches and continuous TX sweep,
but grouped continuous RX failed after the first power at each rate. Nine
independent RX processes recovered the complete 3 x 3 rate/power matrix on the
first attempt. Each merged directory retains source provenance.

Six original TX packet points contained shortened transmissions and eight
missing frames. They were replaced only after the configuration and transport
faults described below were understood and corrected. `recovery_overrides.json`
records all nine substitutions explicitly; original attempt logs remain
preserved.

## Packet anomaly and root cause

The initial packet matrix delivered 172/180 frames. Every missing frame matched
a shortened COM45 current event, so this was not a missed PPK2 trigger. Targeted
diagnostics first appeared power-dependent, but physical readback then showed
that COM45 and COM46 did not hold the settings reported by the ESP32 firmware.

The firmware updated its in-memory E280 configuration before a verified
persistent write completed. If the E280 returned `#ERROR`, a retry could compare
against that stale shadow value and return a false success while the physical
modem stayed at its previous rate or power. The E280 command handlers now apply
candidate configurations transactionally and restore the previous shadow state
after any failed verified write.

After correcting that bug and verifying both physical modems, the pair still
showed a periodic truncated frame at 1K/32 B unless the E280 was reset between
repetitions. Packet tests now issue `AT+RESET` between measured runs and restore
the full configuration outside the measurement window. The six affected points
were then repeated:

| Recovery point | Delivered | Mean energy | Energy CV |
|---|---:|---:|---:|
| 1K, 32 B, 4 dBm | 5/5 | 53,921.282 uJ | 0.0403% |
| 1K, 32 B, 7 dBm | 5/5 | 58,580.092 uJ | 0.0410% |
| 1K, 32 B, 12 dBm | 5/5 | 73,921.376 uJ | 0.0723% |
| 2M, 8 B, 7 dBm | 5/5 | 20.251 uJ | 1.6886% |
| 2M, 32 B, 7 dBm | 5/5 | 28.409 uJ | 1.0372% |
| 2M, 64 B, 7 dBm | 5/5 | 39.605 uJ | 0.4298% |

The final 30/30 packet recovery demonstrates that the earlier apparent
7 dBm-specific loss was a configuration/state artifact, not evidence of an RF
output-power defect.

## Continuous average power

The common TX comparison uses 100K, 64 B logical frames, and a 15 ms gap.

| Direction / configured peer power | Mean current | Mean power | 60 s energy |
|---|---:|---:|---:|
| TX, 4 dBm | 19.305 mA | 63.707 mW | 3822.441 mJ |
| TX, 7 dBm | 19.485 mA | 64.300 mW | 3857.991 mJ |
| TX, 12 dBm | 20.071 mA | 66.234 mW | 3974.030 mJ |
| RX, 4 dBm stimulus | 19.049 mA | 62.863 mW | 3771.770 mJ |
| RX, 7 dBm stimulus | 19.084 mA | 62.978 mW | 3778.657 mJ |
| RX, 12 dBm stimulus | 19.071 mA | 62.935 mW | 3776.111 mJ |

RX consumption depends more on air-rate mode than on requested peer power. The
three-power mean is 57.703 mW at 1K, 62.925 mW at 100K, and 59.208 mW at 2M.
At the common 100K setting, duty-cycled TX is only slightly above RX and rises
monotonically with requested TX power.

## Continuous RX delivery

| Rate | 4 dBm | 7 dBm | 12 dBm |
|---:|---:|---:|---:|
| 1 kbps | 37/95 (61.0526% loss) | 34/95 (64.2105%) | 37/95 (61.0526%) |
| 100 kbps | 892/1899 (53.0279%) | 893/1899 (52.9753%) | 892/1899 (53.0279%) |
| 2000 kbps | 761/2324 (67.2547%) | 781/2324 (66.3941%) | 892/2324 (61.6179%) |

Across the nine RX windows, 5,219 of 12,954 offered logical frames were
received. The transmitter reported zero serial errors and all nine PPK2 windows
are complete. The values are therefore retained as measured end-to-end
transparent-UART/RF behavior, not classified as missing measurement data.
Because these RX runs predate the shadow-state firmware correction, their
requested power labels should not be interpreted as calibrated or independently
read-back RF power. The rate-dependent current levels do, however, distinguish
the three requested air modes.

## Channel validation, cleanup, and deliverables

Channel isolation passed 12/12 at 1K and 100K. The first 2M probe used channels
21/22, which are invalid for that mode; the valid 10/11/12 repeat passed 12/12.
Channel 10 is now explicit in the power profile.

Thirty superseded original packet raw traces were removed after the recovery
overrides were verified, leaving exactly the 192 effective raw traces. Compact
CSV/JSON evidence from the shadow-configuration diagnostics is archived under
`diagnostic_logs/shadow_config_rechecks`. The rejected 08:11 session was
removed after its final callback log was copied into the comparison archive and
verified byte-for-byte.

Deliverables include consolidated CSV/XLSX files for packet TX, packet RX,
continuous power, continuous delivery, and loss versus radio rate, plus six
LaTeX sources and matching PDF/PNG plots. Campaign logs, quick-check records,
recovery provenance, and diagnostic summaries are retained beside them.
