# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Added

- Added MIT project license and third-party notices for public repository preparation.
- Added Ebyte E22 SX1268 SPI module support with AT-command firmware, onboard OLED on GPIO5/GPIO6, and SX1268-safe parameter validation.
- Added Ebyte E280-2G4T12S UART/TTL module support with raw Ebyte binary configuration, bridge mode, RSSI/ranging/low-power runtime modes, and AT-command wrappers.
- Added a compact source reference for the validated Ebyte E79 CC1352P standalone UART AT modem firmware.
- Added selectable Ebyte E79 CC1352P ESP32 bridge firmware (`RADIO_EBYTE_E79_CC1352P` + `BRIDGE`) for USB CDC to CC1352P UART operation.
- Added `RADIO_EBYTE_E79_CC1352P` + `AT_COMMANDS` as the recommended selection alias for the validated E79 ESP32 bridge to the CC1352P AT modem.
- Added direct non-AT text payload transmission to the E79 CC1352P path, including ESP32 bridge-side wrapping, automatic RX enable, and payload-only receive output for the PlatformIO firmware.
- Documented the E79 transparent bridge control sequences that must not be sent as user payload.
- Added shared CC1101 AT-command support selections for Ebyte E07-400M10S, E07-400MM10S, and E07-433M20S.
- Added dedicated Ebyte E32 868T30D and E32 433T33D firmware selections
  with compact OLED labels and module-specific TX power display mappings.
- Renamed the local CC1101 selections to `RADIO_CC1101_V1_433` and
  `RADIO_CC1101_V2_868` so the tested hardware revision and band are explicit.
- Added the Ai-Thinker RA-08 ASR6601 standalone AT modem source under `src/RA-08(ASR6601)`, kept separate from the full SDK/toolchain.
- Added KiCad project source files and local symbol/footprint libraries; generated Gerbers, KiCad cache/history files, and local backups stay ignored.
- Added reusable PowerShell test/upload scripts under `test/`; generated logs go under ignored `log/`.
- Added `Invoke-AtProbe.ps1` for single-port AT diagnostics before running full
  pair tests.
- Added a focused CC1101 quick sweep script for local RF-band diagnostics.
- Added a `Datasheets/` reference index for supported modules and ESP32-C3 hardware documentation.
- Added per-module AT command documentation to `README.md`, including module-specific command descriptions.
- Added `AT+SLEEP` and `AT+WAKE` support to AT-command firmware variants where the hardware/library supports sleep:
  - CC1101
  - nRF24L01
  - RA-01 / RA-02 SX1278
  - RA-01H / XL1276-D01 SX1276
  - RA-01SH SX1262
  - Ebyte E22 SX1268
  - Ebyte E280 SX1280 UART
  - Ebyte E79 CC1352P AT modem
  - E28 SX1280
  - Ebyte E32
- Added runtime sleep-state tracking so transparent payload TX is blocked while a radio is sleeping.
- Added sleep status output to `AT+CFG?` for updated AT-command firmware variants.
- Expanded AT coverage for CC1101 with modulation, packet mode, address filtering, promiscuous mode, carrier sense, encoding, data shaping, sync error tolerance, status, and random-byte diagnostics.
- Expanded AT coverage for nRF24L01 with channel/frequency, data rate, TX power, address width, TX/RX pipe addresses, pipe enable state, CRC, auto-ack, retries, LNA, dynamic payloads, ACK payloads, payload length, and status commands.
- Expanded AT coverage for SX1276/SX1278 firmware with implicit/explicit header mode, IQ inversion, FHSS period, SNR/frequency-error diagnostics, CAD, and random-byte diagnostics.
- Expanded AT coverage for RA-01SH SX1262 with TCXO voltage, regulator mode, DIO2 RF switch, boosted RX gain, header mode, IQ inversion, LDRO, SNR/frequency-error diagnostics, CAD, random-byte diagnostics, and status commands.
- Added Ebyte E22 SX1268 AT coverage matching the SX126x command set, with E22 400 MHz frequency limits.
- Added Ebyte E280 AT coverage for address/channel, baud/parity, air rate, TX power, fixed/broadcast send, ranging mode, frequency hopping, LBT, IO mode, local/remote config windows, and module info/reset commands.
- Validated RA-08 AT modem firmware on two modules, including manual frequency mode, channel mode, sleep/wake guardrails, error formatting, and bidirectional radio traffic.
- Expanded AT coverage for E28 SX1280 with LoRa/GFSK/FLRC/BLE mode selection, GFSK/BLE bitrate/deviation, FLRC bitrate/coding rate, shaping, whitening, BLE access address, packet length mode, GFSK/FLRC sync words, high-sensitivity mode, manual gain, header mode, IQ inversion, and diagnostics.
- Expanded AT coverage for HC-12 with UART format selection, raw command forwarding, module info, bridge state, and safer sleep-state handling.
- Expanded AT coverage for Ebyte E32 with runtime M0/M1 mode control, sleep/wake aliases, AUX/info diagnostics, temporary apply, fixed-send, and broadcast helpers.

### Changed

- Standardized AT error responses so generic failures return `#ERROR` and
  specific guardrail messages start with `#ERROR:`.
- Added explicit feedback when payload TX is blocked because the radio is in
  sleep or because bridge mode is disabled.
- Fixed nRF24L01 transparent payload RX by reading the nRF24 payload directly
  and ignoring the SPI status byte returned before payload data.
- Changed nRF24L01 defaults to use dynamic payloads, which matches the
  variable-length text payload mode used by the serial bridge.
- Hardened nRF24L01 RX restart after channel/config changes and added a FIFO
  polling fallback for cases where the IRQ callback is missed.
- Added nRF24L01 payload length guardrails for static payload mode.
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
- Reset Ebyte E32 modules internally after saved configuration writes, then
  return M0/M1 to normal mode and drain the module UART. This prevents corrupted
  UART/RF state after channel changes.
- Hardened Ebyte E32 config/module-info reads so a failed module response does
  not try to free an invalid response buffer before returning to normal mode.
- Aligned the E79 ESP32 bridge default CC1352P UART baud with the CC1352P AT
  firmware default of `1000000`; `460800` remains the validated fallback.
- Moved the E79 ESP32 bridge under `src/Ebyte E79(CC1352P)/ESP32 Bridge` so all
  E79 integration files live under one module folder.
- Reorganized the local E79 CC1352P modem source reference into `inc/` and `src/`
  to mirror the standalone firmware repository layout.
- Renamed the RA-08 local source reference folder to `src/RA-08(ASR6601)`.
- Removed the obsolete E79 ESP32-side `AT_COMMANDS` helper; E79 `AT_COMMANDS`
  now aliases the validated ESP32 bridge to the CC1352P AT modem.
- Kept `AT+DEFAULT` as the documented recovery path for restoring known-safe settings.
- Removed datasheet PDFs from Git tracking; local PDF copies are ignored and the public repository keeps only reference notes/links.
- Hardened CC1101 OLED/SPI handoff so the SSD1306 splash is not put into
  power-save immediately after boot, then reinitializes the radio SPI bus.
- Changed the generic CC1101 default carrier from 433.000 MHz to 433.920 MHz,
  matching the stable local 433 MHz test pair.
- Added a CC1101 RX fallback that checks GDO0 and the RXBYTES/MARCSTATE status
  registers in the main loop, reducing dependence on a single interrupt edge.
- Hardened E28 SX1280 OLED startup with hardware-I2C bus recovery and OLED
  address detection before the radio SPI bus is reinitialized.
- Standardized OLED splash first lines back to `RADIO` for the compact 128x64
  display, keeping the module/chip name on the second line.
- Added the missing explicit `Wire.h` include to the E280 firmware so clean
  PlatformIO builds compile after the OLED hardware-I2C recovery code.

### Verified

- Built all updated `AT_COMMANDS` firmware selections successfully:
  - `RADIO_CC1101_V1_433`
  - `RADIO_HC12`
  - `RADIO_NRF24L01`
  - `RADIO_RA01_SX1278`
  - `RADIO_RA01H_SX1276`
  - `RADIO_RA01SH_SX1262`
  - `RADIO_RA02_SX1278`
  - `RADIO_E28_SX1280`
  - `RADIO_EBYTE`
  - `RADIO_EBYTE_E32_868T30D`
  - `RADIO_EBYTE_E32_433T33D`
  - `RADIO_EBYTE_E22_SX1268`
  - `RADIO_EBYTE_E280_SX1280`
  - `RADIO_EBYTE_E79_CC1352P`
  - `RADIO_XL1276_D01_SX1276`

- Validated E79 CC1352P AT modem communication on COM19 and COM22:
  - AT command coverage for identity, config, debug, frequency, power, rate,
    modulation, sync word, unsupported address/channel guards, diagnostics,
    `AT+SETRADIO`, sleep/wake, and reset.
  - Bidirectional RF traffic: text payload from COM22 to COM19 and hex payload
    from COM19 to COM22.
  - Latest frequency isolation retest used 433/434 MHz and passed desync/resync
    recovery (`PASS=18 FAIL=0`).

- Validated CC1101 pair A on COM23 and COM24 after the OLED/RX fallback update:
  boot log clean, bidirectional payload exchange passed, and 433.920/434.920 MHz
  frequency isolation passed (`PASS=18 FAIL=0`).
- Validated E28 SX1280 on COM37 and COM38 after OLED I2C recovery: boot log
  clean, bidirectional payload exchange passed, and 2410.5/2411.5 MHz
  frequency isolation passed (`PASS=18 FAIL=0`).
- Re-flashed and validated RA-01SH SX1262 on COM41 and COM42 after the OLED
  splash update: boot log clean, bidirectional payload exchange passed, and
  433/434 MHz frequency isolation passed (`PASS=18 FAIL=0`).
- Validated NRF24L01 on COM15 and COM16, and NRF24L01+ on COM10 and COM11:
  channel 80/81 isolation, bidirectional payload exchange, and resync recovery
  passed (`PASS=18 FAIL=0` for each pair).
- Validated Ebyte E32T20 pairs after the automatic post-config reset update:
  433 MHz modules on COM47/COM48 and 868 MHz modules on COM49/COM50 passed
  channel 23/24 isolation and resync recovery (`PASS=12 FAIL=0` for each pair).
- Re-flashed and tested Ebyte E32 433T33D modules on COM53 and COM54:
  channel 23/24 isolation and resync recovery passed at `AT+POWER1` / 33 dBm
  after improving the local power wiring (`PASS=18 FAIL=0`).
- Re-flashed and tested Ebyte E32 868T30D modules on COM51 and COM52:
  channel 23/24 isolation and resync recovery passed at `AT+POWER1` / 30 dBm
  after adding local VCC capacitors (`PASS=18 FAIL=0`).
- Re-flashed and validated Ebyte E280 on COM17 and COM18 after stale E79 splash
  text was observed: channel 23/24 isolation, bidirectional transparent payload
  exchange, and resync recovery passed (`PASS=18 FAIL=0`).
- Re-tested CC1101 pair B on COM39 and COM40 after alternate antennas, extra
  VCC capacitors, and replacing the COM40 V2 RF module with the spare. The pair
  remained unreliable at 433.920 MHz, but passed 868/869 MHz frequency isolation
  and bidirectional payload exchange with the original antennas (`PASS=18 FAIL=0`). Added the
  `RADIO_CC1101_V2_868` selection so `AT+DEFAULT` is correct for these local V2
  boards.

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
