# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Added

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

### Changed

- Documented `AT+RX=OFF` as standby, separate from low-power sleep.
- Preserved previous RX state across `AT+SLEEP` / `AT+WAKE` where possible.
- Used RadioLib `sleep()` / `standby()` for SPI radio modules.
- Used Ebyte E32 M0/M1 mode control for sleep/wake behavior.

### Verified

- Built all updated `AT_COMMANDS` firmware selections successfully:
  - `RADIO_CC1101`
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
