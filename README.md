# ESP32-C3 Radio

PlatformIO project for testing multiple radio modules with an ESP32-C3 board,
an optional SSD1306 OLED display, and serial/AT-command based firmware variants.

The project is organized as a single PlatformIO application. The active radio
module and firmware variant are selected from `src/main.cpp`, and the matching
source file is included by `src/module_selection.h`.

See `CHANGELOG.md` for notable project changes.

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

This is a merged list from the AT-command firmware variants in the project.
Not every command exists on every module. If a command is not supported by the
selected firmware, the device normally returns `ERROR`.

### Core commands

| Command | Meaning |
| --- | --- |
| `AT` | Connectivity test, returns `OK` |
| `AT?` | Print help, where implemented |
| `AT+HELP` | Print help |
| `AT+CFG?` | Print current configuration/status |
| `AT+APPLY` | Apply current configuration to the radio/module |
| `AT+RESET` | Reset/reinitialize radio and reapply configuration |
| `AT+DEFAULT` | Restore firmware defaults and persist/apply if supported |

### Debug, bridge, RX and diagnostics

| Command | Meaning |
| --- | --- |
| `AT+DEBUG` | Toggle debug output, where implemented |
| `AT+DEBUG?` | Print debug state |
| `AT+DEBUG=ON` / `AT+DEBUG=OFF` | Enable/disable debug output |
| `AT+BRIDGE=ON` / `AT+BRIDGE=OFF` | Enable/disable UART bridge mode |
| `AT+BRIDGE?` | Print bridge state, where implemented |
| `AT+RX=ON` / `AT+RX=OFF` | Start/stop receive mode (`AT+RX=OFF` = standby) |
| `AT+SLEEP` | Put radio/module into low-power sleep, where supported |
| `AT+WAKE` | Wake radio/module and restore RX state, where supported |
| `AT+RSSI?` | Print last packet RSSI |
| `AT+SNR?` | Print last packet SNR, where implemented |
| `AT+LQI?` | Print last packet LQI, mainly CC1101 |

### RadioLib LoRa-style commands

Used by SX127x/SX126x/SX1280-style firmware variants.

| Command | Meaning |
| --- | --- |
| `AT+FREQ?` / `AT+FREQ=<MHz>` | Query/set frequency |
| `AT+BW?` / `AT+BW=<kHz>` | Query/set bandwidth |
| `AT+SF?` / `AT+SF=<value>` | Query/set spreading factor |
| `AT+CR?` / `AT+CR=<5..8>` | Query/set coding rate |
| `AT+SYNC?` / `AT+SYNC=<hex>` | Query/set sync word |
| `AT+PWR?` / `AT+PWR=<dBm>` | Query/set TX power |
| `AT+CURR?` / `AT+CURR=<mA\|0>` | Query/set current limit, where supported |
| `AT+PREAMBLE?` / `AT+PREAMBLE=<n>` | Query/set preamble length |
| `AT+GAIN?` / `AT+GAIN=<0..6>` | Query/set RX gain, where supported |
| `AT+CRC?` / `AT+CRC=ON\|OFF` | Query/set CRC |
| `AT+SET=<...>` | Batch-set radio parameters |

Common LoRa-style batch formats:

```text
AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>
AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<PRE>,<CRC>
```

The exact format depends on the selected module.

### CC1101-specific commands

| Command | Meaning |
| --- | --- |
| `AT+BR=<kbps>` | Set bit rate |
| `AT+DEV=<kHz>` | Set frequency deviation |
| `AT+PRE=<bytes>` | Set preamble length |
| `AT+BW1..16` | Select predefined RX bandwidth |
| `AT+BR1..11` | Select predefined bit rate |
| `AT+PWR1..10` | Select predefined TX power |
| `AT+SETRADIO=FREQ,BR,DEV,BW,PWR,PRE,SYNC,CRC` | One-shot CC1101 radio configuration |

### nRF24L01-specific commands

| Command | Meaning |
| --- | --- |
| `AT+ADDR?` | Print current 5-byte pipe address |
| `AT+ADDR=<10hex>` | Set shared TX/RX pipe address |

### HC-12-specific commands

| Command | Meaning |
| --- | --- |
| `AT+BAUD?` / `AT+BAUD=<1200..115200>` | Query/set UART baud |
| `AT+CHAN?` / `AT+CHAN=<0..127>` | Query/set channel |
| `AT+POWER?` / `AT+POWER=<1..8>` | Query/set power level |
| `AT+FU?` / `AT+FU=<1..4>` | Query/set FU mode |
| `AT+V` | Query module version |

### Ebyte E32-specific commands

| Command | Meaning |
| --- | --- |
| `AT+ADDH=<0..255>` | Set high address byte |
| `AT+ADDL=<0..255>` | Set low address byte |
| `AT+CHAN=<0..31>` | Set channel |
| `AT+BAUD1..8` | Select UART baud preset |
| `AT+PARITY1..3` | Select parity preset |
| `AT+AIR1..6` | Select air data rate preset |
| `AT+POWER1..4` | Select TX power preset |
| `AT+WORT1..8` | Select WOR timing preset |
| `AT+FEC=ON` / `AT+FEC=OFF` | Enable/disable FEC |
| `AT+FIXED=ON` / `AT+FIXED=OFF` | Enable/disable fixed mode |
| `AT+IOMODE=PP` / `AT+IOMODE=OD` | Set IO mode |
| `AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,WOR,FEC,FIXED,IOMODE` | One-shot E32 configuration |

## Transparent payload mode

Most `AT_COMMANDS` firmware variants treat any serial line that does not start
with `AT` as a payload to transmit over the radio.

For bridge-oriented firmware, non-AT serial data is forwarded between USB Serial
and the radio module UART.

## Repository notes

- Build artifacts are ignored via `.gitignore`.
- Generated PlatformIO files live under `.pio/` and should not be committed.
- The selected firmware is controlled only from `src/main.cpp`.
- Module routing and compile-time validation live in `src/module_selection.h`.
