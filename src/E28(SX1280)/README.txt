SX1280 AT COMMAND FIRMWARE
==========================

Overview
--------
This firmware implements an AT-command controlled LoRa transceiver
based on the Semtech SX1280 (2.4 GHz) using the RadioLib library.

The firmware provides:
- Persistent radio configuration stored in EEPROM
- AT command interface over Serial
- Runtime reconfiguration with automatic hardware reset and re-apply
- TX/RX operation with optional debug output
- Compatibility strictly limited to SX1280 (no SX127x legacy code)

Default configuration is known-good and matches the official RadioLib
SX1280 examples.


Hardware Requirements
---------------------
- MCU: ESP32-C3 (or compatible ESP32)
- Radio module: SX1280
- Connections:

  SX1280     ESP32
  ----------------
  NSS   ->  GPIO 7
  DIO1  ->  GPIO 1
  NRST  ->  GPIO 10
  BUSY  ->  GPIO 3

- Optional:
  LED on GPIO 8 (status blink)


Default Radio Configuration
---------------------------
The firmware boots with the following default settings
(also used as factory defaults):

- Frequency:        2410.5 MHz
- Bandwidth:        203.125 kHz
- Spreading Factor: 10
- Coding Rate:      6
- Sync Word:        0x12 (private network)
- Output Power:     -2 dBm
- Preamble Length:  16 symbols
- CRC:              OFF
- RX Mode:          ON
- Debug:            OFF

These defaults are fully compatible with SX1280 and were verified
to work in real TX/RX tests.


EEPROM Behavior
---------------
- Configuration is automatically stored in EEPROM after every change
- On boot:
  - If a valid EEPROM record exists, it is loaded and applied
  - Otherwise, defaults are used and saved
- EEPROM record is protected with:
  - Magic number
  - Version
  - Length check
  - CRC32 over configuration data


Boot Sequence
-------------
1. MCU starts
2. EEPROM is initialized
3. Last valid configuration is loaded (or defaults used)
4. SX1280 is hardware-reset via NRST
5. Radio is initialized with full LoRa parameter set
6. RX mode is started (if enabled)
7. AT interface becomes available


Serial Interface
----------------
- Baud rate: 9600
- Line endings: CR, LF, or CRLF
- Commands are case-insensitive
- Any line NOT starting with "AT" is treated as a TX payload


AT Command Summary
------------------

Core Commands
-------------
AT
  -> Responds with "OK"

AT?
AT+HELP
  -> Print full command list

AT+CFG?
  -> Print current configuration and runtime status

AT+APPLY
  -> Hardware reset + apply current configuration

AT+RESET
  -> Hardware reset + re-apply current configuration

AT+DEFAULT
  -> Load factory defaults, save to EEPROM, apply immediately


Parameter Commands (Set / Query)
--------------------------------
Each setter automatically:
- Saves to EEPROM
- Hardware-resets the radio
- Re-applies configuration

AT+FREQ=<MHz>       / AT+FREQ?
AT+BW=<kHz>         / AT+BW?
AT+SF=<num>         / AT+SF?
AT+CR=<5..8>        / AT+CR?
AT+SYNC=<hex>       / AT+SYNC?
AT+PWR=<dBm>        / AT+PWR?
AT+PREAMBLE=<n>     / AT+PREAMBLE?
AT+CRC=ON|OFF       / AT+CRC?


Batch Configuration
-------------------
AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<PRE>,<CRC>

Example:
AT+SET=2410.5,203.125,10,6,0x12,-2,16,OFF

This command:
- Updates all parameters at once
- Saves to EEPROM
- Applies immediately


RX Control
----------
AT+RX=ON
  -> Start receiver

AT+RX=OFF
  -> Stop receiver (standby)


Diagnostics
-----------
AT+RSSI?
  -> Print RSSI of last received packet

AT+DEBUG
  -> Toggle debug output

AT+DEBUG=ON
AT+DEBUG=OFF
AT+DEBUG?
  -> Control debug logging


TX / RX Behavior
----------------
- Any serial line that does NOT start with "AT" is transmitted as payload
- TX is blocking
- After TX:
  - RX is automatically restarted (if RX=ON)
- On RX:
  - Payload is printed directly when DEBUG=OFF
  - Full radio diagnostics are printed when DEBUG=ON


Typical Usage Example
---------------------
Initial setup (once):

AT
AT+DEBUG=ON
AT+SET=2410.5,203.125,10,6,0x12,-2,16,OFF
AT+APPLY
AT+CFG?

Normal operation:
- Type any text to transmit it
- Received packets are printed automatically


Known Notes
-----------
- This firmware is strictly for SX1280 (2.4 GHz)
- No SX127x compatibility code is included
- All radio reconfiguration is done via full re-initialization,
  which is the most reliable method for SX1280
- RX uses DIO1 interrupt (RadioLib recommended mode)


License
-------
Provided as-is for development, testing, and research purposes.
No warranty implied.


End of File
-----------
