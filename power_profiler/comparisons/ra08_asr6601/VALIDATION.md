# RA-08 (ASR6601) validation

## Hardware and campaign

- Measured device: `COM54`
- Peer device: `COM53`
- PPK2: `COM11`, ampere-meter mode at 3300 mV, external VIN to VOUT current path
- Authoritative campaign: `20260721_201429_campaign_ra08_asr6601`
- Packet campaign: 36 parameter points, 180 runs, all accepted on the first attempt
- Packet result: 0 lost packets, no missing events, maximum PPK2 sample loss 0.525714%, maximum energy CV 0.303987%

## Continuous-test anomaly and recovery

The original continuous sweeps were invalid because the host issued `AT+SEND` again while the previous LoRa frame was still on air. Every missing RX frame was accounted for by a rejected serial command: `frames_received + SERIAL_ERRORS == frames_transmitted`. The apparent loss was independent of TX power, so it was not RF packet loss.

Continuous pacing now includes calculated LoRa airtime only for profiles that opt into it. The RA-08 profile enables this behavior, and validators reject continuous results whenever the transmitter reports a non-zero `SERIAL_ERRORS` value. The report generator also normalizes RA-08 bandwidth values from hertz to kilohertz.

Targeted recovery produced 12/12 valid continuous points with `SERIAL_ERRORS=0`:

- RX SF7: 394/394 frames at 2, 12, and 22 dBm; 12.865-12.901 mA and 42.456-42.573 mW
- RX SF9: 142/142 frames at 2, 12, and 22 dBm; 12.826-12.853 mA and 42.324-42.414 mW
- RX SF12: 22/22 frames at 2, 12, and 22 dBm; 12.794-12.830 mA and 42.221-42.340 mW
- TX SF9: 52.469, 92.011, and 125.887 mA at 2, 12, and 22 dBm; 173.147, 303.638, and 415.427 mW

The corrected TX means are 10.0%, 10.9%, and 11.4% higher than the original invalid results because rejected commands had incorrectly reduced the RF duty cycle. Recovery overrides make the generated CSV, XLSX, LaTeX, PDF, and PNG files use only the corrected continuous measurements. The original invalid continuous data remain preserved for forensic traceability but are not included in the reports.

## File integrity

- Authoritative raw captures: 192 total (180 packet and 12 recovered continuous captures)
- Compressed size: 613,177,076 bytes
- Decompressed data checked: 4,275,438,675 bytes
- Gzip CRC failures: 0
- Every authoritative result directory has matching CSV rows, raw captures, and parseable metadata
- All four XLSX workbooks load successfully
- All generated PDFs have valid PDF headers and EOF markers
- All generated PNGs have valid signatures; all LaTeX sources and CSV files are non-empty
- Automated test suite: 96 tests passed

The complete original and recovery logs are included under `campaign_logs`.
