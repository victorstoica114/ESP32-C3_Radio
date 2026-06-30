This firmware targets an **ESP32-C3** and provides a complete **AT command shell** plus a **USB↔Ebyte E32 UART bridge**, with **EEPROM persistence (CRC32)** and an **SSD1306 128×64 OLED splash screen** (U8g2). It is designed to make E32 configuration reliable by automatically switching the module between **NORMAL mode** (for transparent UART/data) and **PROGRAM mode** (for reading/writing configuration at 9600 baud), while using the **AUX pin** to avoid timing/timeout issues during configuration writes.

The system uses the following hardware connections. For the Ebyte E32 module: **ESP32 UART RX = GPIO20 (UART1_RX_PIN) connected to E32 TX**, and **ESP32 UART TX = GPIO21 (UART1_TX_PIN) connected to E32 RX**. Mode pins are **M0 = GPIO10** and **M1 = GPIO3**, and the **AUX pin must be connected to GPIO1** (configured as `INPUT_PULLUP`) because the firmware waits for AUX to go HIGH to ensure the radio is ready before and after configuration operations. A status LED is connected to **GPIO8** and is toggled periodically as a “heartbeat” while `loop()` runs. For the OLED display, an **SSD1306 128×64** I2C panel is used with **SDA = GPIO5** and **SCL = GPIO6**; reset is disabled (`U8X8_PIN_NONE`). On boot, the OLED shows a splash screen (“EBYTE / E32T33”), serving as a quick visual confirmation that the device powered up and I2C is functional.

Software dependencies are: **LoRa_E32** (for Ebyte E32 configuration and module info), **U8g2** (for OLED rendering), and **EEPROM** (from Arduino-ESP32). The firmware maintains two configurations: `cfgDefault` (compiled “firmware defaults”) and `cfgCurrent` (the active “shadow config”). On startup it attempts to load `cfgCurrent` from EEPROM; the EEPROM payload includes a magic value, version, stored length, the `Configuration` struct, and a CRC32. If EEPROM content fails validation, the firmware tries to read the configuration from the E32 module in PROGRAM mode; if that also fails, it falls back to the compiled defaults and stores them.

At runtime, the firmware provides two main behaviors over USB Serial (115200 baud). First, it runs an **AT shell**: any line that starts with “AT” is handled locally and returns `OK` or `#ERROR` plus optional output. Second, it runs a **UART bridge**: any line that does not start with “AT” is forwarded to the E32 module over Serial1, terminated with **CRLF (`\r\n`)**, matching serial monitors configured for CRLF end-of-line. Data coming from the E32 module is forwarded back to USB **raw** (byte-for-byte). The bridge can be enabled or disabled via an AT command, and it is enabled by default at boot.

The E32 module is configured using the standard Ebyte two-mode approach. In **NORMAL mode** (M0=0, M1=0), the module is used for normal radio UART operations and bridging. In **PROGRAM mode** (M0=1, M1=1), the module accepts configuration commands and responds at **9600 baud**, which is why this firmware forces Serial1 to 9600 only during configuration reads/writes. To prevent `setConfiguration()` timeouts, the firmware (1) sets AUX as an input with pull-up, (2) adds generous delays after mode switching, and (3) waits for AUX to be HIGH before/after config operations. After a configuration write, it returns to NORMAL mode and reconfigures Serial1 to the UART baud rate specified by the newly applied config.

The firmware uses “raw code” fields for E32 configuration (stable bitfield codes typically used by E32 tooling). UART baud is stored as a code 0..7 (1200..115200), parity is a code 0..2 (8N1/8O1/8E1), and air data rate is a code 0..5 (0.3..19.2 kbps). WOR timing is a code 0..7 mapped to 250..2000 ms (step 250 ms). TX power is a code 0..3; the firmware prints an explicit dBm value using a configurable mapping array `POWER_DBM_BY_CODE`. The current mapping is the common one for many “T30D”-style modules: code 0..3 corresponds to **30/27/24/21 dBm**. If your exact module variant differs, adjust `POWER_DBM_BY_CODE` accordingly.

AT command interface (USB side) is line-based; it accepts CR, LF, or CRLF line endings. Commands are case-insensitive. If the command is valid, the device prints any requested information and returns `OK`; on errors it returns `#ERROR`. The available AT commands are:

**Core commands**
- `AT`  
  Basic connectivity check. Returns `OK`.
- `AT+HELP` or `AT?`  
  Prints the full help text, including all commands and indexed mappings. Returns `OK`.
- `AT+CFG?`  
  Reads the configuration from the E32 module (PROGRAM mode @9600), prints it in a human-readable format, reads and prints module information (if available), then returns to NORMAL mode and re-syncs Serial1 to the module UART baud. Returns `OK` on success, `#ERROR` on failure.
- `AT+APPLY`  
  Writes the current shadow configuration (`cfgCurrent`) into the E32 module using SAVE mode, then stores it into EEPROM (CRC protected). Returns `OK` on success, `#ERROR` on failure.
- `AT+DEFAULT`  
  Restores compiled firmware defaults into `cfgCurrent`, writes them into the E32 module using SAVE mode, and stores them into EEPROM. Returns `OK` on success, `#ERROR` on failure.
- `AT+BRIDGE=ON` / `AT+BRIDGE=OFF`  
  Enables or disables UART bridging for non-AT lines. Returns `OK`.
- `AT+DEBUG=ON` / `AT+DEBUG=OFF`  
  Enables or disables debug prints (minimal in this version). Returns `OK`.

**Address and channel setters**
- `AT+ADDH=<0..255>`  
  Sets the high byte of the module address in the shadow config, applies to module (SAVE), persists to EEPROM. Returns `OK`/`#ERROR`.
- `AT+ADDL=<0..255>`  
  Sets the low byte of the module address in the shadow config, applies to module (SAVE), persists to EEPROM. Returns `OK`/`#ERROR`.
- `AT+CHAN=<0..31>`  
  Sets the channel (sub-band) in the shadow config, applies to module (SAVE), persists to EEPROM. Returns `OK`/`#ERROR`.

**Indexed setters (fast configuration)**
- `AT+BAUD1..8`  
  Sets UART baud code based on index and applies immediately (SAVE + EEPROM):  
  1=1200, 2=2400, 3=4800, 4=9600, 5=19200, 6=38400, 7=57600, 8=115200.
- `AT+PARITY1..3`  
  Sets UART parity and applies immediately:  
  1=8N1, 2=8O1, 3=8E1.
- `AT+AIR1..6`  
  Sets air data rate and applies immediately:  
  1=0.3 kbps, 2=1.2 kbps, 3=2.4 kbps, 4=4.8 kbps, 5=9.6 kbps, 6=19.2 kbps.
- `AT+POWER1..4`  
  Sets TX power and applies immediately. Index 1..4 maps to power code 0..3 (1=max, 4=min). The firmware prints the explicit dBm values using the mapping array; with the default mapping:  
  1=30 dBm, 2=27 dBm, 3=24 dBm, 4=21 dBm.
- `AT+WORT1..8`  
  Sets WOR timing and applies immediately. Explicit mapping in milliseconds:  
  1=250 ms, 2=500 ms, 3=750 ms, 4=1000 ms, 5=1250 ms, 6=1500 ms, 7=1750 ms, 8=2000 ms.
- `AT+FEC=ON` / `AT+FEC=OFF`  
  Enables or disables forward error correction (FEC) and applies immediately.
- `AT+FIXED=ON` / `AT+FIXED=OFF`  
  Enables fixed transmission mode (fixed addressing) or sets transparent mode; applies immediately.
- `AT+IOMODE=PP` / `AT+IOMODE=OD`  
  Sets IO drive mode to push-pull (PP) or open-drain (OD); applies immediately.

**One-shot full radio configuration**
- `AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,WOR,FEC,FIXED,IOMODE`  
  Sets all major parameters from a single command, then applies (SAVE) and persists to EEPROM. Fields are comma-separated:
  - `ADDH` 0..255
  - `ADDL` 0..255
  - `CHAN` 0..31
  - `BAUD` 1..8 (see BAUD mapping above)
  - `PARITY` 1..3 (see PARITY mapping above)
  - `AIR` 1..6 (see AIR mapping above)
  - `POWER` 1..4 (see POWER mapping above)
  - `WOR` 1..8 (see WORT mapping above)
  - `FEC` 0/1
  - `FIXED` 0/1
  - `IOMODE` `PP` or `OD`  
  Example: `AT+SETRADIO=0,1,23,8,1,6,1,1,1,0,PP`

If an AT command is not recognized, the device responds with `#ERROR`. If a line does not start with “AT” and the bridge is enabled, it is forwarded to the E32 as a line ending in CRLF; if the bridge is disabled, the device responds with `#ERROR: BRIDGE_OFF (send AT+BRIDGE=ON)`.

Troubleshooting: if you see `setConfiguration: Timeout`, verify that AUX is correctly wired to the configured GPIO and that it transitions HIGH when the module is ready; also verify M0 and M1 wiring and that the module enters PROGRAM mode (M0=1, M1=1). Ensure the module is powered at the correct voltage (typically 3.3V logic) and that Serial1 pins match your board’s routing. If the OLED does not display, verify SDA/SCL pins, I2C wiring, and that the display is the SSD1306 128×64 variant expected by the selected U8g2 constructor. Finally, note that the current heartbeat implementation toggles the LED based on a `millis()` interval; you can adjust the blink behavior by changing the threshold in `led1HzService()`.

License: covered by the repository MIT License unless a file says otherwise. Third-party libraries remain under their own licenses.
