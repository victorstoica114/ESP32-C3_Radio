# E28 (SX1280) campaign validation

Authoritative campaign: `20260719_214712_campaign_radio_e28_sx1280`

## Verdict

The E28 measurement set is complete and accepted for packet-energy,
continuous average-power, and loss-versus-speed analysis. The original
campaign completed 39 of 40 batches before COM37 and COM38 were physically
disconnected during the last continuous-RX batch. The complete SF12 batch was
rerun after reconnecting the same pair and is selected by the documented
recovery override. No radio measurement point is missing.

The unusually high continuous-RX loss at SF12 is reproducible, but a targeted
gap diagnostic shows that it is not caused by insufficient RF power or the
PPK2 path. Increasing the host inter-frame gap from 15 ms to 100 ms at SF12
and +13 dBm reduced loss from 17.886% to 0.952%. This is consistent with the
receiver/firmware needing more rearm time after the long SF12 frames. The
standard 15 ms result remains in the comparison graph so that this campaign
uses the same test conditions as the other modules.

## Configuration and coverage

- Profile: `RADIO_E28_SX1280` at 2410.5 MHz, LoRa bandwidth 812.5 kHz,
  coding-rate denominator 6, explicit header, CRC disabled, 16-symbol
  preamble, sync word `0x12`, and controlled RX enable/disable commands.
- Measured DUT: COM37; peer: COM38; PPK2: COM11 in Ampere Meter mode at
  3300 mV. The DUT remained externally powered and the PPK2 VIN-to-VOUT path
  remained guarded.
- Packet TX: 27 aggregate points and 135 raw captures across three payloads,
  three spreading factors, and three TX powers (-18, 0, and +13 dBm).
- Packet RX: 9 aggregate points and 45 raw captures at +13 dBm.
- Continuous tests: three TX-power points at SF8 and nine RX power/loss points
  across SF5, SF8, and SF12, each using a 60 s active window.
- Accepted raw coverage: 192/192 gzip traces, comprising 180 packet and 12
  continuous captures. Every stream was decompressed fully and passed its
  gzip CRC check: 828,529,776 compressed bytes and 3,453,076,077 uncompressed
  bytes.

## Integrity checks

- Full bidirectional AT/RF isolation diagnostic: 18/18 checks passed.
- Quick check: 4/4 batches passed on the first attempt.
- Packet current events: 180/180 detected.
- Packet delivery: 180/180 packets received, with zero packet loss.
- Continuous rows: 12/12 have status `ok`, a 60 s active analysis window, and
  zero transmitter serial errors.
- Maximum packet-energy coefficient of variation: 2.615432%.
- Maximum packet-capture PPK2 sample loss: 0.525714%.
- Maximum continuous-capture PPK2 sample loss: 0.002494%.
- All 40 accepted metadata files identify COM37, COM11, 3300 mV,
  100 ksample/s, raw capture enabled, and the E28 profile.
- The profiler server reports the PPK2 VIN-to-VOUT guard enabled on COM11
  after recovery and diagnostics.

Both ESP32-C3 boot logs showed a ROM message about comparing the application
hash against an unset expected hash. The flashed binaries themselves passed
the esptool write verification, booted normally, and then passed the RF
diagnostic and quick check; the ROM message therefore does not invalidate the
measurements.

## Continuous average power

| Direction / configured TX power | Mean current | Mean electrical power | 60 s energy |
|---|---:|---:|---:|
| TX, -18 dBm | 5.727 mA | 18.898 mW | 1133.906 mJ |
| TX, 0 dBm | 10.375 mA | 34.237 mW | 2054.243 mJ |
| TX, +13 dBm | 21.002 mA | 69.306 mW | 4158.387 mJ |

Across the nine standard RX points, mean current ranged from 6.078 to
6.576 mA and mean power from 20.057 to 21.702 mW. As expected for RX, these
values are nearly independent of the peer's configured TX power.

## Continuous RX loss

| SF | Effective payload speed | -18 dBm | 0 dBm | +13 dBm |
|---:|---:|---:|---:|---:|
| 5 | 22.41 kbps | 2606/2626 (0.762%) | 2605/2626 (0.800%) | 2606/2627 (0.799%) |
| 8 | 9.35 kbps | 1090/1097 (0.638%) | 1088/1096 (0.730%) | 1087/1096 (0.821%) |
| 12 | 1.050 kbps | 100/123 (18.699%) | 101/123 (17.886%) | 101/123 (17.886%) |

The standard continuous RX measurements received 11,384 of 11,537 frames.
The SF12 loss is almost independent of TX power, while the +13 dBm control
with a 100 ms gap received 104/105 frames (0.952% loss). This combination is
strong evidence for an inter-frame rearm limitation at the standard 15 ms gap,
not an RF-sensitivity or power-supply failure.

## Deliverables

- Consolidated CSV and XLSX files for packet TX, packet RX, continuous power,
  and loss versus effective payload speed.
- Four LaTeX sources and matching PDF/PNG renderings.
- Campaign manifest, session log, callback log, all attempt logs, recovery
  summaries, the SF12 gap diagnostic, the quick-check provenance, and the
  full pair-isolation diagnostic.

The dependency-free renderer was also corrected to choose logarithmic energy
limits from the measured values. This prevents the E28 sub-millijoule SF5
points from being clipped below the former fixed 1 mJ lower limit. The local
MiKTeX executable is present but its first-run setup is unfinished, so a local
TeX recompilation could not be performed; the generated PDF and PNG files
have valid signatures and all four PNG plots were inspected visually.
