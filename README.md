# ESP32-C3 Radio

PlatformIO project for testing multiple radio modules with an ESP32-C3 board,
an optional SSD1306 OLED display, and serial/AT-command based firmware variants.

The project is organized as a single PlatformIO application. The active radio
module and firmware variant are selected from `src/main.cpp`, and the matching
source file is included by `src/module_selection.h`.

See `CHANGELOG.md` for notable project changes.

Hardware PDFs are collected temporarily under `Datasheets/`. Review the notes in
`Datasheets/README.md` before making the repository public.

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
#define RADIO_MODULE  RADIO_RA02_SX1278
#define RADIO_PROGRAM AT_COMMANDS
```

Keep this include after the two defines:

```cpp
#include "module_selection.h"
```

## Supported modules

Use these values for `RADIO_MODULE`:

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
| `RADIO_XL1276_D01_SX1276` | `src/XL1276-D01 (SX1276)` | XL1276-D01, SX1276 |

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
| `RADIO_XL1276_D01_SX1276` | yes | no | yes | yes | yes | no |

If a module/program combination is not available, compilation stops with a clear
`#error` message from `src/module_selection.h`.

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
| `AT+PWR?`, `AT+PWR=<dBm>`, `AT+PWR1..10` | Query/set TX power or use a preset |
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
git except for its `.gitignore` placeholder.

## Repository notes

- Build artifacts are ignored via `.gitignore`.
- Generated PlatformIO files live under `.pio/` and should not be committed.
- The selected firmware is controlled only from `src/main.cpp`.
- Module routing and compile-time validation live in `src/module_selection.h`.
