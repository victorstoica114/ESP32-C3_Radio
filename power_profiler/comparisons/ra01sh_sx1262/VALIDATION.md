# RA-01SH (SX1262) campaign validation

## Verdict

The authoritative campaign `20260719_175320_campaign_radio_ra01sh_sx1262`
completed all 40 planned steps on the first attempt, with no failed batches or
recovery overrides. The measurement set is accepted for packet energy,
continuous average-power, and radio-loss analysis. No additional hardware test
is required.

The initial quick check exposed a real firmware configuration defect at the
slowest LoRa setting. That defect was diagnosed and corrected before this
campaign; the targeted control, final quick check, packet campaign, and
continuous campaign all confirm the correction.

## Configuration and coverage

- Profile: `RADIO_RA01SH_SX1262`, explicitly configured for 868 MHz, coding
  rate 4/5, explicit header, CRC, a 15-symbol preamble, 1.8 V TCXO, DCDC
  regulation, DIO2-controlled RF switch, and automatic LDRO selection.
- Measured DUT: COM31; peer: COM32; PPK2: COM11 in Ampere Meter mode at
  3300 mV. The DUT remained externally powered; PPK2 provided the guarded
  VIN-to-VOUT current path.
- Packet TX: 27 aggregate points and 135 raw captures across three payloads,
  three spreading factors, and three TX powers (-9, +10, and +22 dBm).
- Packet RX: 9 aggregate points and 45 raw captures at +22 dBm.
- Continuous tests: three TX power points at SF9 and nine RX power/loss points
  across SF7, SF9, and SF12, each measured over exactly 60 active seconds.
- Full campaign raw coverage: 192/192 gzip traces (180 packet and 12
  continuous), totalling 736,251,489 compressed bytes. No file is empty and
  every raw file has the expected gzip signature.

## Metrology checks

- Current event detected: 180/180 packet captures.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum within-condition energy coefficient of variation: 0.616531%; the
  mean coefficient of variation across all packet points is 0.172179%.
- Continuous-capture PPK2 sample loss: at most 0.002494%.
- All continuous rows use a 60.0 s active analysis window, report status `ok`,
  and contain no transmitter serial errors.
- No payload-energy, spreading-factor-energy, or TX-current-versus-power
  inversion was found.
- All 40 metadata files identify COM31, COM11, 3300 mV, 100 ksample/s, raw
  capture enabled, and the `RADIO_RA01SH_SX1262` profile.
- The profiler server still reports the PPK2 VIN-to-VOUT guard enabled on
  COM11 after campaign completion.

## LDRO diagnosis before the campaign

The first quick check passed both SF7 directions but failed its SF12/-9 dBm
slow-link criterion. A four-way, ten-packet control isolated the asymmetry:

| Direction and condition | Received / transmitted |
|---|---:|
| COM31 TX to COM32 RX, SF12/-9 dBm | 10 / 10 |
| COM32 TX to COM31 RX, SF12/-9 dBm | 0 / 10 |
| COM31 TX to COM32 RX, SF7/-9 dBm | 10 / 10 |
| COM32 TX to COM31 RX, SF7/-9 dBm | 10 / 10 |

The RA-01SH firmware used `forceLDRO(false)` when the profile requested
`AT+LDRO=OFF`. In RadioLib this forces low-data-rate optimization off; it does
not restore automatic selection. The firmware now calls `autoLDRO()` for the
OFF/automatic profile state. After reflashing both radios, the previously
failing COM32-to-COM31 SF12/-9 dBm control delivered 10/10 packets. The final
four-part quick check then passed completely before the campaign started.

## Packet delivery

- COM31 TX to COM32 RX: 135/135 packets received.
- COM32 TX to COM31 RX at +22 dBm: 45/45 packets received.
- Overall campaign packet delivery: 180/180 packets (100%).

All packet points also contain five detected current events, so delivery and
electrical-event coverage agree.

## Continuous average TX power

| Configured TX power | Mean current | Mean electrical power | 60 s energy |
|---:|---:|---:|---:|
| -9 dBm | 15.648 mA | 51.638 mW | 3098.262 mJ |
| +10 dBm | 38.090 mA | 125.698 mW | 7541.888 mJ |
| +22 dBm | 65.792 mA | 217.114 mW | 13026.855 mJ |

Continuous RX remained nearly independent of peer TX power and spreading
factor: 4.473--4.531 mA and 14.760--14.953 mW across all nine points. The mean
continuous RX current was 4.488 mA.

## Continuous RX loss

| SF | Effective payload speed | Result at -9 dBm | Result at +10 dBm | Result at +22 dBm |
|---:|---:|---:|---:|---:|
| 7 | 3.644 kbps | 427/427 | 427/427 | 427/427 |
| 9 | 1.186 kbps | 139/139 | 139/139 | 139/139 |
| 12 | 0.171 kbps | 20/20 | 20/20 | 20/20 |

All 1,758 continuously transmitted frames were received. The loss-versus-speed
graph is therefore a valid zero-loss result across the tested matrix rather
than a missing-data graph.

## Deliverables

- Consolidated CSV and XLSX files for TX energy, RX energy, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Authoritative manifest, session log, 40 attempt logs, callback log, and
  compact provenance from the initial quick check, the four-way low-power
  matrix, the LDRO-fix validation, and the final quick check.

The PDF/PNG renderings use the same generated CSV series as the LaTeX sources.
The original raw traces remain in the source sessions and diagnostic folders;
the comparison directory intentionally keeps compact logs and summaries for
version-control backup.
