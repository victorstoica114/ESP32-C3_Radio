# Ai-Thinker RA-02 (SX1278) campaign validation

## Verdict

The authoritative campaign `20260719_190544_campaign_radio_ra02_sx1278`
completed all 40 planned steps on their first attempt, with no failed batches
or recovery overrides. The dataset is accepted for packet-energy, continuous
average-power, and radio-loss analysis. No additional hardware test is
required.

The single `rx_missing` packet and the seven lost continuous frames are valid
radio-loss observations. They are retained in every consolidated table and
graph; rerunning only those points would bias the comparison.

## Pre-campaign verification and configuration

- DUT measured by PPK2: COM33; peer: COM34; PPK2: COM11 in Ampere Meter mode
  at 3300 mV. The DUT remained externally powered and PPK2 provided the
  guarded VIN-to-VOUT current path.
- Dedicated `RADIO_RA02_SX1278 + AT_COMMANDS` firmware was built and flashed
  to both boards. The complete bilateral AT/radio diagnostic passed 82/82
  checks.
- The hardware-free regression suite passed 59/59 tests.
- The final quick check passed all four TX/RX cases on their first attempt,
  including SF12 at -4 dBm. Its measured peak current was 69.672 mA.
- The profile explicitly selects 433 MHz, coding rate 4/5, explicit header,
  CRC, and the firmware's 15-symbol preamble. Continuous LoRa runs reopen and
  restore both serial radios between power levels.

Before flashing, the RA-02 profile was corrected to explicitly select coding
rate 4/5 and a 15-symbol preamble. The previous profile omitted the coding-rate
command and modeled an 8-symbol preamble, which would have made the planned
airtime inconsistent with the firmware. This was corrected before any
authoritative measurement.

## Coverage and raw-data integrity

- Packet TX: 27 aggregate points and 135 captures across three payloads,
  three spreading factors, and three configured powers (-4, +10, +20 dBm).
- Packet RX: 9 aggregate points and 45 captures at +20 dBm.
- Continuous: three TX power points at SF9 plus nine RX power/loss points
  across SF7, SF9, and SF12, each using a 60.0 s active window.
- Raw coverage: 192/192 gzip files (180 packet and 12 continuous), totalling
  617,097,650 compressed bytes.
- Every raw archive was fully decompressed and its CRC verified: the payload
  totals 4,373,866,831 bytes, with no invalid CSV header or decompression
  error.
- All 40 metadata files identify `RADIO_RA02_SX1278`, COM33, COM11, 3300 mV,
  100 ksample/s, and raw capture enabled.

## Metrology checks

- Current event detected: 180/180 packet captures.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum within-condition energy coefficient of variation: 0.598371%; mean
  coefficient of variation across all 36 packet points: 0.180838%.
- Maximum continuous-capture PPK2 sample loss: 0.002494%.
- All 12 continuous rows report `status=ok`, use a 60.0 s active analysis
  window, and contain zero transmitter serial errors.
- No payload-energy, spreading-factor-energy, or TX-current-versus-power
  inversion was found.
- All generated PDF, PNG, and XLSX files passed signature/workbook validation.
- After completion, the profiler server reported the PPK2 VIN-to-VOUT guard
  enabled on COM11.

## Packet delivery

- COM33 TX to COM34 RX: 134/135 packets received.
- COM34 TX to COM33 RX at +20 dBm: 45/45 packets received.
- Overall packet delivery: 179/180 (99.444%).

The only missing packet was repetition 2 of the 8-byte, SF9, +10 dBm COM33-to-
COM34 condition. The other four repetitions at that point succeeded, its
electrical event was captured normally, and the batch reported no serial or
PPK2 failure.

## Continuous average TX power

| Configured TX power | Mean current | Mean electrical power | 60 s energy |
|---:|---:|---:|---:|
| -4 dBm | 11.106 mA | 36.651 mW | 2199.085 mJ |
| +10 dBm | 26.666 mA | 87.997 mW | 5279.800 mJ |
| +20 dBm | 61.724 mA | 203.690 mW | 12221.394 mJ |

Continuous RX ranged from 11.300 to 12.479 mA (37.290 to 41.182 mW), with an
overall mean of 11.948 mA. Averaged across spreading factors, RX current was
11.335 mA at -4 dBm, 12.114 mA at +10 dBm, and 12.393 mA at +20 dBm peer
power. The increase is present independently in SF7, SF9, and SF12 while the
pre-capture baselines remain stable and sample loss is negligible. It is
therefore preserved as an observed characteristic rather than treated as a
capture artifact.

## Continuous RX loss

| SF | Effective payload speed | Result at -4 dBm | Result at +10 dBm | Result at +20 dBm |
|---:|---:|---:|---:|---:|
| 7 | 3.644 kbps | 427/427 | 427/427 | 423/427 |
| 9 | 1.186 kbps | 137/139 | 138/139 | 139/139 |
| 12 | 0.171 kbps | 20/20 | 20/20 | 20/20 |

Overall continuous delivery was 1,751/1,758 frames (99.602%). Loss is small,
not concentrated at the lowest configured power, and absent at the slowest
SF12 setting. Together with the clean quick check and zero serial errors, this
supports accepting it as measured RF behavior rather than an automation fault.

## Deliverables

- Consolidated CSV and XLSX files for TX energy, RX energy, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Authoritative manifest, session log, all 40 attempt logs, callback log, the
  82-check bilateral AT diagnostic, and compact final quick-check provenance.

The original raw traces remain in the web-session directory. The comparison
directory intentionally keeps compact logs and summaries suitable for the
repository backup.
