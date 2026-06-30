# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Added

- Added a temporary `Datasheets/` folder with PDF documentation for supported modules and ESP32-C3 hardware.
- Added per-module AT command documentation to `README.md`, including module-specific command descriptions.
- Added `AT+SLEEP` and `AT+WAKE` support to AT-command firmware variants where the hardware/library supports sleep:
  - CC1101
  - nRF24L01
  - RA-01 / RA-02 SX1278
  - RA-01H / XL1276-D01 SX1276
  - RA-01SH SX1262
  - E28 SX1280
  - Ebyte E32
- Added runtime sleep-state tracking so transparent payload TX is blocked while a radio is sleeping.
- Added sleep status output to `AT+CFG?` for updated AT-command firmware variants.
- Expanded AT coverage for CC1101 with modulation, packet mode, address filtering, promiscuous mode, carrier sense, encoding, data shaping, sync error tolerance, status, and random-byte diagnostics.
- Expanded AT coverage for nRF24L01 with channel/frequency, data rate, TX power, address width, TX/RX pipe addresses, pipe enable state, CRC, auto-ack, retries, LNA, dynamic payloads, ACK payloads, payload length, and status commands.
- Expanded AT coverage for SX1276/SX1278 firmware with implicit/explicit header mode, IQ inversion, FHSS period, SNR/frequency-error diagnostics, CAD, and random-byte diagnostics.
- Expanded AT coverage for RA-01SH SX1262 with TCXO voltage, regulator mode, DIO2 RF switch, boosted RX gain, header mode, IQ inversion, LDRO, SNR/frequency-error diagnostics, CAD, random-byte diagnostics, and status commands.
- Expanded AT coverage for E28 SX1280 with LoRa/GFSK/FLRC/BLE mode selection, GFSK/BLE bitrate/deviation, FLRC bitrate/coding rate, shaping, whitening, BLE access address, packet length mode, GFSK/FLRC sync words, high-sensitivity mode, manual gain, header mode, IQ inversion, and diagnostics.
- Expanded AT coverage for HC-12 with UART format selection, raw command forwarding, module info, bridge state, and safer sleep-state handling.
- Expanded AT coverage for Ebyte E32 with runtime M0/M1 mode control, sleep/wake aliases, AUX/info diagnostics, temporary apply, fixed-send, and broadcast helpers.

### Changed

- Standardized AT error responses so generic failures return `#ERROR` and
  specific guardrail messages start with `#ERROR:`.
- Added explicit feedback when payload TX is blocked because the radio is in
  sleep or because bridge mode is disabled.
- Tightened SX1276/SX1278/SX1262 parameter validation for frequency, bandwidth,
  output power, current limit, and preamble length before saving to EEPROM.
- Aligned the OLED I2C release / radio SPI reinitialization workaround across
  SPI-based AT-command firmware variants.
- Documented that UART module baud changes retune the ESP32 hardware UART
  connected to the module, while the USB CDC serial port baud is not the module
  baud reference.
- Documented `AT+RX=OFF` as standby, separate from low-power sleep.
- Preserved previous RX state across `AT+SLEEP` / `AT+WAKE` where possible.
- Used RadioLib `sleep()` / `standby()` for SPI radio modules.
- Used Ebyte E32 M0/M1 mode control for sleep/wake behavior.
- Kept `AT+DEFAULT` as the documented recovery path for restoring known-safe settings.

### Verified

- Built all updated `AT_COMMANDS` firmware selections successfully:
  - `RADIO_CC1101`
  - `RADIO_HC12`
  - `RADIO_NRF24L01`
  - `RADIO_RA01_SX1278`
  - `RADIO_RA01H_SX1276`
  - `RADIO_RA01SH_SX1262`
  - `RADIO_RA02_SX1278`
  - `RADIO_E28_SX1280`
  - `RADIO_EBYTE`
  - `RADIO_XL1276_D01_SX1276`

## 2026-06-30

### Added

- Prepared the project as a GitHub-friendly PlatformIO repository.
- Added module/program selection through `src/main.cpp` and `src/module_selection.h`.
- Added a merged AT-command reference in `README.md`.
- Added `.gitignore` for PlatformIO, editor, and build artifacts.

### Organized

- Renamed the project to `ESP32-C3_Radio`.
- Moved radio module examples under `src/`.
- Converted copied sketch text files into compilable C++ sources.
- Added compile-time validation for unavailable module/program combinations.
