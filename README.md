# ESP32-C3 Radio

PlatformIO project for testing multiple radio modules with an ESP32-C3 board,
an optional SSD1306 OLED display, and serial/AT-command based firmware variants.

The project is organized as a single PlatformIO application. The active radio
module and firmware variant are selected from `src/main.cpp`, and the matching
source file is included by `src/module_selection.h`.

See `CHANGELOG.md` for notable project changes.

Hardware PDFs are collected temporarily under `Datasheets/`. Review the notes in
`Datasheets/README.md` before making the repository public.

## License

Project source code is released under the MIT License. See `LICENSE`.

Third-party libraries and vendor/manufacturer datasheets keep their own
licenses and redistribution terms. See `THIRD_PARTY_NOTICES.md` and
`Datasheets/README.md`.

## Hardware target

- MCU: ESP32-C3 DevKitC-02
- Framework: Arduino
- Build system: PlatformIO
- Optional display: SSD1306 128x64 OLED via U8g2

Common pins used by many sketches:

- OLED SDA: GPIO 5
- OLED SCL: GPIO 6
- Status LED: GPIO 8
- SPI CS/NSS: GPIO 7

The integrated OLED on the ESP32-C3 OLED devboard is wired to GPIO 5/GPIO 6.
Module schematics may expose other SDA/SCL labels for external headers, but that
does not change the onboard OLED wiring. If a future board/module variant uses a
different OLED wiring, document that exception in the module section below.

Some radio modules share GPIO 5/GPIO 6 with SPI MISO/MOSI. In the affected
firmware variants, the OLED I2C bus is released after the splash screen and the
SPI bus is reinitialized before starting the radio.

## Dependencies

Defined in `platformio.ini`:

- `jgromes/RadioLib`
- `olikraus/U8g2`
- `xreef/LoRa_E32_Series_Library`
- Arduino ESP32 built-in libraries such as `SPI`, `Wire`, and `EEPROM`

## Selecting firmware

Edit `src/main.cpp`:

```cpp
#define RADIO_MODULE  RADIO_EBYTE_E79_CC1352P
#define RADIO_PROGRAM BRIDGE
```

Keep this include after the two defines:

```cpp
#include "module_selection.h"
```

## Supported modules

Use these values for `RADIO_MODULE` in the ESP32 PlatformIO firmware:

| RADIO_MODULE | Folder | Radio/module |
| --- | --- | --- |
| `RADIO_CC1101` | `src/CC1101` | CC1101 |
| `RADIO_HC12` | `src/HC-12` | HC-12 UART radio |
| `RADIO_NRF24L01` | `src/NRF24L01` | nRF24L01/nRF24L01+ |
| `RADIO_RA01_SX1278` | `src/RA-01(SX1278)` | Ai-Thinker RA-01, SX1278 |
| `RADIO_RA01H_SX1276` | `src/RA-01H(SX1276)` | RA-01H, SX1276 |
| `RADIO_RA01SH_SX1262` | `src/RA-01SH(SX1262)` | RA-01SH, SX1262 |
| `RADIO_RA02_SX1278` | `src/RA-02(SX1278)` | RA-02, SX1278 |
| `RADIO_E28_SX1280` | `src/E28(SX1280)` | E28, SX1280 2.4 GHz |
| `RADIO_EBYTE` | `src/Ebyte` | Ebyte E32 UART LoRa module |
| `RADIO_EBYTE_E22_SX1268` | `src/Ebyte E22(SX1268)` | Ebyte E22 SPI LoRa module, SX1268 |
| `RADIO_EBYTE_E280_SX1280` | `src/Ebyte E280(SX1280)` | Ebyte E280-2G4T12S UART/TTL module, SX1280 |
| `RADIO_EBYTE_E79_CC1352P` | `src/Ebyte E79(CC1352P)` | Ebyte E79-400DM2005S, TI CC1352P wireless MCU |
| `RADIO_EBYTE_E07_400M10S` | `src/CC1101` | Ebyte E07-400M10S, CC1101, 10 dBm nominal |
| `RADIO_EBYTE_E07_400MM10S` | `src/CC1101` | Ebyte E07-400MM10S, CC1101, 10 dBm nominal |
| `RADIO_EBYTE_E07_433M20S` | `src/CC1101` | Ebyte E07-433M20S, CC1101 + PA/LNA, 20 dBm nominal |
| `RADIO_XL1276_D01_SX1276` | `src/XL1276-D01 (SX1276)` | XL1276-D01, SX1276 |

Standalone module-side radio firmware:

| Firmware | Primary repository | Local reference | Radio/module | Status |
| --- | --- | --- | --- | --- |
| RA08 AT modem | [victorstoica114/RA-08_AT-Commands](https://github.com/victorstoica114/RA-08_AT-Commands) | `src/RA-08(ASR6601)` | Ai-Thinker RA-08, ASR6601 LPWAN SoC | Functional and tested with two modules |
| E79 AT modem | [victorstoica114/Ebyte-E79-CC1352P-_AT_Modem_Firmware](https://github.com/victorstoica114/Ebyte-E79-CC1352P-_AT_Modem_Firmware) | `src/Ebyte E79(CC1352P)/CC1352P_AT_Modem_Firmware` | Ebyte E79-400DM2005S, TI CC1352P wireless MCU | Functional and tested with two modules |

## Firmware variants

Use these values for `RADIO_PROGRAM`:

| RADIO_PROGRAM | Meaning |
| --- | --- |
| `AT_COMMANDS` | AT-command shell and, for most modules, transparent TX mode |
| `BIDIRECTIONAL_RX_TX` | Bidirectional RX/TX example |
| `RECEIVE` | Receive-only example |
| `SETTINGS` | Radio settings/configuration example |
| `TRANSMIT` | Transmit-only example |
| `BRIDGE` | UART/Serial bridge example |

Availability by module:

| Module | AT_COMMANDS | BIDIRECTIONAL_RX_TX | RECEIVE | SETTINGS | TRANSMIT | BRIDGE |
| --- | --- | --- | --- | --- | --- | --- |
| `RADIO_CC1101` | yes | yes | yes | yes | yes | no |
| `RADIO_HC12` | yes | yes | no | no | no | no |
| `RADIO_NRF24L01` | yes | yes | no | no | no | no |
| `RADIO_RA01_SX1278` | yes | yes | no | yes | no | no |
| `RADIO_RA01H_SX1276` | yes | yes | no | no | no | no |
| `RADIO_RA01SH_SX1262` | yes | yes | no | yes | no | no |
| `RADIO_RA02_SX1278` | yes | yes | no | yes | no | no |
| `RADIO_E28_SX1280` | yes | yes | no | yes | no | no |
| `RADIO_EBYTE` | yes | no | no | no | no | yes |
| `RADIO_EBYTE_E22_SX1268` | yes | no | no | no | no | no |
| `RADIO_EBYTE_E280_SX1280` | yes | no | no | no | no | no |
| `RADIO_EBYTE_E79_CC1352P` | no | no | no | no | no | yes |
| `RADIO_EBYTE_E07_400M10S` | yes | no | no | no | no | no |
| `RADIO_EBYTE_E07_400MM10S` | yes | no | no | no | no | no |
| `RADIO_EBYTE_E07_433M20S` | yes | no | no | no | no | no |
| `RADIO_XL1276_D01_SX1276` | yes | no | yes | yes | yes | no |
| RA08 AT modem | yes | no | no | no | no | no |

If a module/program combination is not available, compilation stops with a clear
`#error` message from `src/module_selection.h`.

## Planned / In Development Modules

These modules still need their own module-side firmware or are planned for future
support:

| Module | Chipset | Status / expected approach |
| --- | --- | --- |
| Ai-Thinker RA-09 | STM32WLE5CCU6 wireless MCU | Planned; separate module firmware, then UART modem/AT bridge from ESP32 |

## External Module Firmware

Some modules are wireless MCUs rather than direct ESP32 radio peripherals. Their
module-side firmware is kept separately from the ESP32 PlatformIO firmware.

### Ai-Thinker RA-08

The RA-08 ASR6601 AT modem firmware lives in its own repository:
[victorstoica114/RA-08_AT-Commands](https://github.com/victorstoica114/RA-08_AT-Commands).
That project turns the RA-08 into a standalone UART AT radio modem. This
repository keeps only a small source reference under
`src/RA-08(ASR6601)` (`main.c`, `at_modem.c`, IRQ glue, and headers).
Build support, drivers, startup code, linker scripts, and the ARM GCC toolchain
belong in the separate RA-08 firmware repository.

The RA-08 modem was validated on two modules over USB serial at `115200` baud,
including AT command parsing, parameter validation, sleep/wake guardrails,
manual frequency mode, channel mode, and bidirectional packet exchange.

## Build

From the project root:

```sh
pio run
```

Upload:

```sh
pio run --target upload
```

Open serial monitor:

```sh
pio device monitor
```

The serial baud rate depends on the selected firmware. Many AT-command variants
use `9600`, while some bridge examples use `115200`.

## AT command reference

All AT-command firmware variants implement `AT` for a basic connectivity check
and `AT?`/`AT+HELP` for the firmware-local help text. Commands not implemented
by the selected module return `#ERROR`.

Error responses are intentionally easy to filter: they start with `#` and are
printed with a CRLF line ending. Generic failures return `#ERROR`; specific
runtime guardrails return messages such as `#ERROR: RADIO_SLEEPING (send
AT+WAKE)`, `#ERROR: BRIDGE_OFF (send AT+BRIDGE=ON)`, or `#ERROR:
RADIO_NOT_READY (set config and run AT+APPLY)`.

`AT+DEFAULT` is intentionally kept as the safety net command. It restores known
firmware defaults, saves them where EEPROM/module storage is used, and reapplies
the radio configuration so communication can be recovered after a bad setting.

`AT+RX=OFF` means standby/receive disabled. Low-power sleep is a separate state
entered with `AT+SLEEP` and left with `AT+WAKE` where supported.

For UART radio modules, changing the module baud also retunes the ESP32 hardware
UART connected to that module. The ESP32 USB CDC serial port exposed to the PC is
virtual and is not used as the radio-module baud reference.

### CC1101

The Ebyte E07-400M10S, E07-400MM10S, and E07-433M20S variants use the same
CC1101 AT firmware. Select the exact module with `RADIO_MODULE` so the splash,
configuration printout, and EEPROM namespace match the hardware.

These E07 selections compile, but have not been hardware-tested yet. Hardware
validation is planned next.

`E07-433M20S` includes an external PA/LNA and is rated around 20 dBm at module
level. `AT+PWR` still controls the CC1101 drive/PATABLE preset exposed by
RadioLib, not a separate PA gain setting.

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and full configuration/status printout |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, reset/reapply, or restore safe defaults |
| `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Control debug output |
| `AT+BRIDGE=ON\|OFF`, `AT+BRIDGE?` | Control transparent serial-to-radio bridge mode |
| `AT+RX=ON`, `AT+RX=OFF` | Start receive or stop receive into standby |
| `AT+SLEEP`, `AT+WAKE` | Enter low-power sleep or wake and restore RX state |
| `AT+RSSI?`, `AT+LQI?`, `AT+STATUS?`, `AT+RANDOM?` | Packet/link diagnostics and one RSSI-noise random byte |
| `AT+FREQ?`, `AT+FREQ=<MHz>` | Query/set carrier frequency |
| `AT+BR?`, `AT+BR=<kbps>`, `AT+BR1..11` | Query/set bit rate or use a preset |
| `AT+DEV?`, `AT+DEV=<kHz>` | Query/set frequency deviation |
| `AT+BW?`, `AT+BW=<kHz>`, `AT+BW1..16` | Query/set receive bandwidth or use a preset |
| `AT+PWR?`, `AT+PWR=<-30\|-20\|-15\|-10\|0\|5\|7\|10>`, `AT+PWR1..8` | Query/set CC1101 drive power or use a preset |
| `AT+PRE?`, `AT+PRE=<bits>` | Query/set preamble length |
| `AT+SYNC?`, `AT+SYNC=<hex>` | Query/set 2-byte sync word |
| `AT+SYNCERR?`, `AT+SYNCERR=0\|1` | Query/set allowed sync-word error bits |
| `AT+CRC?`, `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+MOD?`, `AT+MOD=2FSK\|GFSK\|OOK\|4FSK` | Query/set modulation |
| `AT+SHAPE?`, `AT+SHAPE=NONE\|0.5` | Query/set data shaping |
| `AT+ENC?`, `AT+ENC=NRZ\|MANCHESTER\|WHITENING` | Query/set encoding |
| `AT+PKT?`, `AT+PKT=VARIABLE,<1..64>`, `AT+PKT=FIXED,<1..64>` | Query/set packet length mode |
| `AT+ADDR?`, `AT+ADDR=OFF`, `AT+ADDR=<node>,<broadcasts>` | Query/set address filtering |
| `AT+PROMISC?`, `AT+PROMISC=ON\|OFF` | Query/set promiscuous mode |
| `AT+CS?`, `AT+CS=ON\|OFF` | Query/set carrier-sense requirement |
| `AT+SETRADIO=FREQ,BR,DEV,BW,PWR,PRE,SYNC,CRC` | One-shot legacy CC1101 setup |

### HC-12

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current firmware config |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, reset/reapply, or restore defaults |
| `AT+DEBUG`, `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Toggle/query debug output |
| `AT+BRIDGE=ON\|OFF`, `AT+BRIDGE?` | Control transparent USB Serial to HC-12 bridge |
| `AT+BAUD?`, `AT+BAUD=<1200..115200>` | Query/set HC-12 UART baud |
| `AT+UART?`, `AT+UART=8N1\|8O1\|8E1` | Query/set UART serial format |
| `AT+CHAN?`, `AT+CHAN=<0..127>` | Query/set HC-12 channel |
| `AT+POWER?`, `AT+POWER=<1..8>` | Query/set TX power level |
| `AT+FU?`, `AT+FU=<1..4>` | Query/set FU mode |
| `AT+V`, `AT+VERSION?` | Query module firmware version |
| `AT+INFO?` | Read module-side status/configuration |
| `AT+RAW=<cmd>` | Send a raw HC-12 AT command |
| `AT+SLEEP`, `AT+WAKE` | Put module to sleep or wake it |

### nRF24L01

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and full configuration/status printout |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, reinitialize, or restore safe defaults |
| `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Control debug output |
| `AT+STATUS?` | Print local RF/status information |
| `AT+RX=ON`, `AT+RX=OFF` | Start RX or enter standby |
| `AT+SLEEP`, `AT+WAKE` | Enter power-down or wake and restore RX state |
| `AT+FREQ?`, `AT+FREQ=<MHz>` | Query/set RF frequency |
| `AT+CHAN?`, `AT+CHAN=<0..125>` | Query/set 2.4 GHz channel |
| `AT+RATE?`, `AT+RATE=250\|1000\|2000` | Query/set data rate in kbps |
| `AT+PWR?`, `AT+PWR=<dBm>` | Query/set TX power |
| `AT+ADDR?`, `AT+ADDR=<hex>` | Query/set shared TX/RX pipe 0 address |
| `AT+ADDRWIDTH?`, `AT+ADDRWIDTH=3\|4\|5` | Query/set address width |
| `AT+TXADDR?`, `AT+TXADDR=<hex>` | Query/set TX address |
| `AT+RXADDR<n>?`, `AT+RXADDR<n>=<hex>` | Query/set RX pipe address, pipe `0..5` |
| `AT+PIPE<n>?`, `AT+PIPE<n>=ON\|OFF`, `AT+PIPES?` | Query/set pipe enable state |
| `AT+CRC?`, `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+AUTOACK?`, `AT+AUTOACK=<hexmask>` | Query/set auto-ack mask |
| `AT+AUTOACK<n>?`, `AT+AUTOACK<n>=ON\|OFF` | Query/set auto-ack for pipe `0..5` |
| `AT+RETRIES?`, `AT+RETRIES=<delay>,<count>` | Query/set retry delay/count |
| `AT+LNA?`, `AT+LNA=ON\|OFF` | Query/set LNA gain |
| `AT+DYN?`, `AT+DYN=ON\|OFF` | Query/set dynamic payloads |
| `AT+ACKPAY?`, `AT+ACKPAY=ON\|OFF` | Query/set ACK payload feature |
| `AT+PLEN?`, `AT+PLEN=<1..32>` | Query/set fixed payload length |

For transparent text payloads, nRF24L01 defaults to `AT+DYN=ON` so each serial
line can be sent at its actual length. If `AT+DYN=OFF` is selected, payload
lines must have exactly the configured `AT+PLEN` length; otherwise the firmware
returns `#ERROR: FIXED_PAYLOAD_LENGTH_MISMATCH`.

### SX1276/SX1278 modules

Applies to `RADIO_RA01_SX1278`, `RADIO_RA02_SX1278`,
`RADIO_RA01H_SX1276`, and `RADIO_XL1276_D01_SX1276`.

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current config/status |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, hardware reset/reapply, or restore defaults |
| `AT+DEBUG`, `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Toggle/query debug output |
| `AT+RX=ON`, `AT+RX=OFF` | Start RX or stop RX into standby |
| `AT+SLEEP`, `AT+WAKE` | Enter sleep or wake and restore RX state |
| `AT+RSSI?`, `AT+SNR?`, `AT+FERR?`, `AT+CAD?`, `AT+RANDOM?` | Packet diagnostics, channel activity detection, random byte |
| `AT+FREQ?`, `AT+FREQ=<MHz>` | Query/set frequency; SX1278: `137..175` or `395..525`, SX1276: those bands plus `862..1020` |
| `AT+BW?`, `AT+BW=<kHz>` | Query/set LoRa bandwidth: `7.8`, `10.4`, `15.6`, `20.8`, `31.25`, `41.7`, `62.5`, `125`, `250`, `500` |
| `AT+SF?`, `AT+SF=<value>` | Query/set spreading factor |
| `AT+CR?`, `AT+CR=<5..8>` | Query/set coding rate denominator |
| `AT+SYNC?`, `AT+SYNC=<hex>` | Query/set sync word |
| `AT+PWR?`, `AT+PWR=<-4..17\|20>` | Query/set TX power |
| `AT+CURR?`, `AT+CURR=<0\|45..240>` | Query/set current limit where supported |
| `AT+PREAMBLE?`, `AT+PREAMBLE=<6..65535>` | Query/set preamble length |
| `AT+GAIN?`, `AT+GAIN=<0..6>` | Query/set RX gain where supported |
| `AT+CRC?`, `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+HEADER?`, `AT+HEADER=EXPLICIT`, `AT+HEADER=IMPLICIT,<1..255>` | Query/set explicit or implicit header mode |
| `AT+IQ?`, `AT+IQ=ON\|OFF` | Query/set IQ inversion |
| `AT+FHSS?`, `AT+FHSS=<0..255>` | Query/set FHSS hopping period |
| `AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>` | Batch-set LoRa parameters; some SX127x variants use the shorter format without `CURR`/`GAIN` |

### SX1262 RA-01SH

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current config/status |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, hardware reset/reapply, or restore defaults |
| `AT+DEBUG`, `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Toggle/query debug output |
| `AT+RX=ON`, `AT+RX=OFF` | Start RX or stop RX into standby |
| `AT+SLEEP`, `AT+WAKE` | Enter sleep or wake and restore RX state |
| `AT+RSSI?`, `AT+SNR?`, `AT+FERR?`, `AT+CAD?`, `AT+RANDOM?`, `AT+STATUS?` | Packet/status diagnostics |
| `AT+FREQ?`, `AT+FREQ=<150..960 MHz>` | Query/set frequency |
| `AT+BW?`, `AT+BW=<kHz>` | Query/set bandwidth: `7.8`, `10.4`, `15.6`, `20.8`, `31.25`, `41.7`, `62.5`, `125`, `250`, `500` |
| `AT+SF?`, `AT+SF=<value>` | Query/set spreading factor |
| `AT+CR?`, `AT+CR=<5..8>` | Query/set coding rate denominator |
| `AT+SYNC?`, `AT+SYNC=<hex>` | Query/set sync word |
| `AT+PWR?`, `AT+PWR=<-9..22>` | Query/set TX power |
| `AT+CURR?`, `AT+CURR=<0..140>` | Query/set current limit |
| `AT+PREAMBLE?`, `AT+PREAMBLE=<1..65535>` | Query/set preamble length |
| `AT+GAIN?`, `AT+GAIN=<0..6>` | Query/set RX gain |
| `AT+CRC?`, `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+TCXO?`, `AT+TCXO=<0\|1.6..3.3>` | Query/set TCXO voltage, `0` for XTAL |
| `AT+REG?`, `AT+REG=LDO\|DCDC` | Query/set regulator mode |
| `AT+DIO2?`, `AT+DIO2=ON\|OFF` | Query/set DIO2 RF switch control |
| `AT+RXBOOST?`, `AT+RXBOOST=ON\|OFF` | Query/set boosted RX gain mode |
| `AT+HEADER?`, `AT+HEADER=EXPLICIT`, `AT+HEADER=IMPLICIT,<1..255>` | Query/set header mode |
| `AT+IQ?`, `AT+IQ=ON\|OFF` | Query/set IQ inversion |
| `AT+LDRO?`, `AT+LDRO=ON\|OFF` | Query/set forced low-data-rate optimization |
| `AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>` | Batch-set LoRa parameters |

### SX1268 Ebyte E22

This is the SPI E22 variant wired as `NSS=GPIO7`, `DIO1=GPIO1`,
`BUSY=GPIO3`, `RESET=GPIO10`, with SPI on `GPIO4/5/6`. The onboard OLED uses
the same devboard wiring as the SX1278 tests: `SDA=GPIO5`, `SCL=GPIO6`. Because
those pins are shared with SPI, the firmware initializes the radio, recovers the
OLED I2C bus, draws the OLED splash, releases I2C, then reinitializes SPI.

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current config/status |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, hardware reset/reapply, or restore defaults |
| `AT+DEBUG`, `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Toggle/query debug output |
| `AT+RX=ON`, `AT+RX=OFF` | Start RX or stop RX into standby |
| `AT+SLEEP`, `AT+WAKE` | Enter sleep or wake and restore RX state |
| `AT+RSSI?`, `AT+SNR?`, `AT+FERR?`, `AT+CAD?`, `AT+RANDOM?`, `AT+STATUS?` | Packet/status diagnostics |
| `AT+FREQ?`, `AT+FREQ=<410..493 MHz>` | Query/set frequency |
| `AT+BW?`, `AT+BW=<kHz>` | Query/set bandwidth: `7.8`, `10.4`, `15.6`, `20.8`, `31.25`, `41.7`, `62.5`, `125`, `250`, `500` |
| `AT+SF?`, `AT+SF=<7..12>` | Query/set spreading factor |
| `AT+CR?`, `AT+CR=<5..8>` | Query/set coding rate denominator |
| `AT+SYNC?`, `AT+SYNC=<hex>` | Query/set sync word |
| `AT+PWR?`, `AT+PWR=<-9..18>` | Query/set SX1268 front-stage TX power; E22 manual maps `18` to about `30 dBm` module output |
| `AT+CURR?`, `AT+CURR=<0..140>` | Query/set current limit |
| `AT+PREAMBLE?`, `AT+PREAMBLE=<1..65535>` | Query/set preamble length |
| `AT+GAIN?`, `AT+GAIN=<0..6>` | Stored for command compatibility; no SX126x-style gain control is applied |
| `AT+CRC?`, `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+TCXO?`, `AT+TCXO=<0\|1.6..3.3>` | Query/set TCXO voltage, `0` for XTAL |
| `AT+REG?`, `AT+REG=LDO\|DCDC` | Query/set regulator mode |
| `AT+DIO2?`, `AT+DIO2=ON\|OFF` | Query/set DIO2 RF switch control |
| `AT+RXBOOST?`, `AT+RXBOOST=ON\|OFF` | Query/set boosted RX gain mode |
| `AT+HEADER?`, `AT+HEADER=EXPLICIT`, `AT+HEADER=IMPLICIT,<1..255>` | Query/set header mode |
| `AT+IQ?`, `AT+IQ=ON\|OFF` | Query/set IQ inversion |
| `AT+LDRO?`, `AT+LDRO=ON\|OFF` | Query/set forced low-data-rate optimization |
| `AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>` | Batch-set LoRa parameters |

### Ebyte E280 UART SX1280

This is the `E280-2G4T12S` UART/TTL module from the local manual. It is based
on SX1280 internally, but the ESP32 talks to the module through UART and Ebyte's
binary configuration protocol, not through SPI/RadioLib. Current pin assumptions:
`RX=GPIO20`, `TX=GPIO21`, `M0=GPIO10`, `M1=GPIO3`, `M2=GPIO2`, `AUX=GPIO1`.

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current module config/status |
| `AT+APPLY`, `AT+APPLY=TEMP`, `AT+RESET`, `AT+DEFAULT` | Save/apply, temporary apply, reset, or restore factory-safe defaults |
| `AT+INFO?`, `AT+AUX?` | Read module version bytes or AUX pin state |
| `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Control debug output |
| `AT+BRIDGE=ON\|OFF`, `AT+BRIDGE?` | Control transparent USB Serial to E280 UART bridge |
| `AT+MODE?`, `AT+MODE=TRANSMISSION\|RSSI\|RANGING\|CONFIGURATION\|LOW_POWER` | Query/set M2/M1/M0 runtime mode |
| `AT+SLEEP`, `AT+WAKE` | Enter low-power mode or restore the previous normal mode |
| `AT+WINDOW=LOCAL\|REMOTE` | Send Ebyte `E2 E2 E2` or `E3 E3 E3` configuration-window command |
| `AT+ADDR?`, `AT+ADDR=<0..65535\|0x0000..0xFFFF>` | Query/set 16-bit module address |
| `AT+ADDH?`, `AT+ADDH=<0..255>` | Query/set high address byte |
| `AT+ADDL?`, `AT+ADDL=<0..255>` | Query/set low address byte |
| `AT+CHAN?`, `AT+CHAN=<0..39>` | Query/set channel; fixed-frequency `1M` is limited to `0..33`, fixed-frequency `2M` to `0..20` |
| `AT+FREQ?` | Print approximate channel frequency based on air-rate/frequency-hop mode |
| `AT+BAUD?`, `AT+BAUD=<1200\|4800\|9600\|19200\|57600\|115200\|460800\|921600>`, `AT+BAUD1..8` | Query/set module UART baud |
| `AT+PARITY?`, `AT+PARITY=8N1\|8O1\|8E1`, `AT+PARITY1..3` | Query/set UART format |
| `AT+AIR?`, `AT+AIR=ADAPTIVE\|1K\|5K\|10K\|50K\|100K\|1M\|2M`, `AT+AIR0..7` | Query/set air rate |
| `AT+POWER?`, `AT+POWER=<12\|10\|7\|4>`, `AT+POWER1..4` | Query/set transmit power |
| `AT+FIXED?`, `AT+FIXED=ON\|OFF` | Query/set fixed-point/class-Modbus transmission mode |
| `AT+RANGE?`, `AT+RANGE=HIGH\|LONG` | Query/set ranging precision/distance mode |
| `AT+FHSS?`, `AT+FHSS=ON\|OFF` | Query/set frequency hopping |
| `AT+ROLE?`, `AT+ROLE=SLAVE\|HOST` | Query/set ranging/test role bit |
| `AT+LBT?`, `AT+LBT=ON\|OFF` | Query/set listen-before-talk |
| `AT+IOMODE?`, `AT+IOMODE=PP\|OD` | Query/set TXD/AUX/RXD IO drive mode |
| `AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,FIXED,RANGE,FHSS,ROLE,LBT,IOMODE` | One-shot E280 configuration |

### Ebyte E79 CC1352P

`E79-400DM2005S` is a TI CC1352P wireless MCU module, not a direct ESP32
radio peripheral. The module runs its own CC1352P AT modem firmware, and the
ESP32-C3 board is used mainly as the USB CDC to UART bridge.

The CC1352P modem source is maintained primarily in
[victorstoica114/Ebyte-E79-CC1352P-_AT_Modem_Firmware](https://github.com/victorstoica114/Ebyte-E79-CC1352P-_AT_Modem_Firmware).
This repository keeps a compact source reference under
`src/Ebyte E79(CC1352P)/CC1352P_AT_Modem_Firmware`.

The ESP32 firmware for E79 is built in bridge mode:

- `RADIO_PROGRAM BRIDGE`: transparent USB CDC to CC1352P UART bridge. This is
  the validated mode for using the CC1352P AT modem from a PC serial terminal.

The bridge uses ESP32 `GPIO20` as RX from the CC1352P TX pin and `GPIO21` as TX
to the CC1352P RX pin. USB CDC stays on the ESP32 virtual COM port. The CC1352P
UART defaults to `1000000` baud. The PC-side USB CDC baud value is not the
important physical speed; the relevant link is the ESP32-C3 UART between
`GPIO20/GPIO21` and the CC1352P. Use `460800` as the validated fallback
if stress tests show rare timeout sensitivity at `1000000`.

CC1352P AT modem commands:

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+VERSION?`, `AT+CFG?` | Connectivity, identity, help, and current radio configuration |
| `AT+DEFAULT`, `AT+RESET` | Restore safe defaults or reset the modem |
| `AT+DEBUG?`, `AT+DEBUG=ON\|OFF` | Query/toggle debug output |
| `AT+FREQ?`, `AT+FREQ=<431000000..500000000>` | Query/set carrier frequency in Hz |
| `AT+PWR?`, `AT+PWR=<-20..13>` | Query/set TX power in dBm using supported CC1352P PA table entries |
| `AT+RATE?`, `AT+RATE=50000` | Query/set air data rate; validated firmware supports 50 kbps 2-GFSK |
| `AT+MOD?`, `AT+MOD=2GFSK` | Query/set modulation |
| `AT+SYNC?`, `AT+SYNC=<hex>` | Query/set sync word, 1..8 hex digits |
| `AT+ADDR?`, `AT+ADDR=<value>` | Address-query/set guard; address filtering is not enabled in the validated PHY |
| `AT+CHAN?`, `AT+CHAN=<n>` | Channel-query/set guard; use explicit frequency with `AT+FREQ` |
| `AT+RX=ON`, `AT+RX=OFF` | Enable receive mode or return to standby |
| `AT+SEND=<text>`, `AT+SENDHEX=<hex>` | Send text or hex payloads |
| `AT+SLEEP`, `AT+WAKE` | Enter low-power mode or wake and restore usable radio state |
| `AT+RSSI?`, `AT+STATUS?`, `AT+LASTPKT?`, `AT+RANDOM?`, `AT+UPTIME?` | Diagnostics and runtime status |
| `AT+SETRADIO=FREQ,RATE,PWR,MOD,SYNC` | One-shot radio configuration |

The E79 modem was validated with two modules on COM19 and COM22. The test
covered AT command handling, parameter validation, sleep/wake guardrails, RX/TX
control, text packets, hex packets, RSSI/LASTPKT diagnostics, and bidirectional
radio exchange.

ESP32 bridge local commands:

| Command | Meaning |
| --- | --- |
| `~CC1352P_BAUD=<9600\|38400\|57600\|115200\|230400\|460800\|500000\|921600\|1000000>` | Change the ESP32 UART baud used for the CC1352P link |
| `~CC1352P_RESET` | Pulse the ESP32 reset-control pin reserved for the CC1352P reset line |

### SX1280 E28

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current config/status |
| `AT+APPLY`, `AT+RESET`, `AT+DEFAULT` | Apply current config, hardware reset/reapply, or restore defaults |
| `AT+DEBUG`, `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Toggle/query debug output |
| `AT+RX=ON`, `AT+RX=OFF` | Start RX or stop RX into standby |
| `AT+SLEEP`, `AT+WAKE` | Enter sleep or wake and restore RX state |
| `AT+RSSI?`, `AT+SNR?`, `AT+FERR?`, `AT+CAD?`, `AT+RANDOM?`, `AT+STATUS?` | Packet/status diagnostics; `AT+RANDOM?` reports RadioLib's SX128x stub value |
| `AT+MODE?`, `AT+MODE=LORA\|GFSK\|FLRC\|BLE` | Query/set SX1280 packet modem |
| `AT+FREQ?`, `AT+FREQ=<MHz>` | Query/set 2.4 GHz carrier frequency |
| `AT+BW?`, `AT+BW=<203.125\|406.25\|812.5\|1625>` | Query/set LoRa bandwidth |
| `AT+SF?`, `AT+SF=<5..12>` | Query/set LoRa spreading factor |
| `AT+CR?`, `AT+CR=<4..8>` | Query/set LoRa coding rate denominator |
| `AT+SYNC?`, `AT+SYNC=<hex>` | Query/set LoRa sync word |
| `AT+PWR?`, `AT+PWR=<-18..13>` | Query/set TX power |
| `AT+PREAMBLE?`, `AT+PREAMBLE=<n>` | Query/set preamble length |
| `AT+CRC?`, `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+HEADER?`, `AT+HEADER=EXPLICIT`, `AT+HEADER=IMPLICIT,<1..255>` | Query/set LoRa header mode |
| `AT+IQ?`, `AT+IQ=ON\|OFF` | Query/set LoRa IQ inversion |
| `AT+BR?`, `AT+BR=<125\|250\|400\|500\|800\|1000\|1600\|2000>` | Query/set GFSK/BLE bit rate |
| `AT+DEV?`, `AT+DEV=<62.5..1000>` | Query/set GFSK/BLE frequency deviation |
| `AT+FLRCBR?`, `AT+FLRCBR=<260\|325\|520\|650\|1000\|1300>` | Query/set FLRC bit rate |
| `AT+FLRCCR?`, `AT+FLRCCR=<2..4>` | Query/set FLRC coding rate (`2=1/2`, `3=3/4`, `4=1/1`) |
| `AT+SHAPE?`, `AT+SHAPE=NONE\|0.5\|1.0` | Query/set Gaussian shaping for GFSK/FLRC/BLE |
| `AT+WHITE?`, `AT+WHITE=ON\|OFF` | Query/set whitening for GFSK/BLE |
| `AT+ACCESS?`, `AT+ACCESS=<hex32>` | Query/set BLE access address |
| `AT+PKT?`, `AT+PKT=VARIABLE,<1..255>`, `AT+PKT=FIXED,<1..255>` | Query/set GFSK/FLRC packet length mode |
| `AT+GFSKSYNC?`, `AT+GFSKSYNC=<hex 1..5 bytes>` | Query/set GFSK sync word |
| `AT+FLRCSYNC?`, `AT+FLRCSYNC=OFF\|<hex 4 bytes>` | Query/set FLRC sync word |
| `AT+HIGHSENS?`, `AT+HIGHSENS=ON\|OFF` | Query/set high-sensitivity RX mode |
| `AT+GAIN?`, `AT+GAIN=<0..13>` | Query/set manual RX gain, `0` for automatic |
| `AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<PRE>,<CRC>` | Batch-set LoRa parameters and switch mode to `LORA` |

### Ebyte E32

| Command | Meaning |
| --- | --- |
| `AT`, `AT?`, `AT+HELP`, `AT+CFG?` | Connectivity, help, and current E32 config/status |
| `AT+APPLY`, `AT+APPLY=TEMP`, `AT+RESET`, `AT+DEFAULT` | Save/apply, temporary apply, reset/reload, or restore defaults |
| `AT+DEBUG=ON\|OFF`, `AT+DEBUG?` | Control debug output |
| `AT+BRIDGE=ON\|OFF`, `AT+BRIDGE?` | Control transparent USB Serial to E32 bridge |
| `AT+AUX?` | Read AUX pin state |
| `AT+INFO?` | Print module/settings information |
| `AT+MODE?`, `AT+MODE=NORMAL\|WAKE\|POWER_SAVE\|SLEEP` | Query/set M0/M1 runtime mode |
| `AT+SLEEP`, `AT+WAKE` | Aliases for sleep and normal runtime mode |
| `AT+ADDH?`, `AT+ADDH=<0..255>` | Query/set high address byte |
| `AT+ADDL?`, `AT+ADDL=<0..255>` | Query/set low address byte |
| `AT+CHAN?`, `AT+CHAN=<0..31>` | Query/set channel |
| `AT+BAUD?`, `AT+BAUD1..8` | Query/select UART baud preset |
| `AT+PARITY?`, `AT+PARITY1..3` | Query/select parity preset |
| `AT+AIR?`, `AT+AIR1..6` | Query/select air data rate preset |
| `AT+POWER?`, `AT+POWER1..4` | Query/select TX power preset |
| `AT+WORT?`, `AT+WORT1..8` | Query/select WOR timing preset |
| `AT+FEC?`, `AT+FEC=ON\|OFF` | Query/set FEC |
| `AT+FIXED?`, `AT+FIXED=ON\|OFF` | Query/set fixed transmission mode |
| `AT+IOMODE?`, `AT+IOMODE=PP\|OD` | Query/set IO drive mode |
| `AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,WOR,FEC,FIXED,IOMODE` | One-shot E32 configuration |
| `AT+SENDTO=ADDH,ADDL,CHAN,TEXT` | Send fixed-mode payload to a target |
| `AT+BROADCAST=CHAN,TEXT` | Send fixed-mode broadcast payload |

## Transparent payload mode

Most `AT_COMMANDS` firmware variants treat any serial line that does not start
with `AT` as a payload to transmit over the radio.

For bridge-oriented firmware, non-AT serial data is forwarded between USB Serial
and the radio module UART.

If payload transmission is attempted while the radio is sleeping, the firmware
prints `#ERROR: RADIO_SLEEPING (send AT+WAKE)`. If a firmware has bridge mode and
the bridge is disabled, non-AT payload input prints `#ERROR: BRIDGE_OFF (send
AT+BRIDGE=ON)`.

## Local test scripts

Reusable PowerShell scripts live under `test/`.

```powershell
.\test\Upload-AtFirmware.ps1 -Module RADIO_RA02_SX1278 -Port COM4,COM5
.\test\Test-Sx127xAtPair.ps1 -Label SX1278 -PortA COM4 -PortB COM5
```

Generated test logs are written under `log/`, which is intentionally ignored by
git.

## Repository notes

- Build artifacts are ignored via `.gitignore`.
- Generated PlatformIO files live under `.pio/` and should not be committed.
- The selected firmware is controlled only from `src/main.cpp`.
- Module routing and compile-time validation live in `src/module_selection.h`.
