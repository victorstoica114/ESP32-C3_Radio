README
======

Project: SX1278 AT Command Shell with Persistent Configuration
Platform: ESP32-C3
Radio: SX1278 (LoRa)
Library: RadioLib

-------------------------------------------------------------------------------

1. Overview
-----------
This firmware implements an AT-style command shell over the Serial (USB)
interface for configuring and operating an SX1278 LoRa radio module using
the RadioLib library.

Main features:
- AT command interface for full radio configuration
- Transparent LoRa TX mode (non-AT input is transmitted over radio)
- Continuous RX with interrupt-driven packet reception
- Optional DEBUG mode for verbose diagnostics
- Persistent radio configuration stored in EEPROM
- Automatic hardware reset of the radio after each configuration change
- Automatic restoration and application of the last valid configuration
  after every ESP reset or power cycle

-------------------------------------------------------------------------------

2. Hardware Pinout
-----------------
SX1278 connections used by this firmware:

  NSS     = GPIO 7   (SPI Chip Select)
  DIO0    = GPIO 3   (RX done interrupt)
  RESET   = GPIO 10  (Hardware reset)
  DIO1    = GPIO 1   (Auxiliary interrupt)

Status LED:
  LED_GPIO = GPIO 8  (1 Hz blink, toggles every 500 ms)

Pin roles:
- NSS / CS : SPI device selection
- DIO0     : Interrupt asserted when a packet is received
- RESET    : Forces a full radio hardware reset
- DIO1     : Secondary interrupt line used internally by RadioLib

-------------------------------------------------------------------------------

3. Default Radio Configuration
------------------------------
The following configuration is the COMPILE-TIME DEFAULT and MUST NOT CHANGE:

  Frequency      : 433.0 MHz
  Bandwidth      : 125.0 kHz
  SpreadingFactor: 11
  CodingRate     : 8  (RadioLib format)
  Sync Word      : 0x14
  TX Power       : 10 dBm
  Current Limit  : 0 mA (0 = do not set)
  Preamble       : 8 symbols
  RX Gain        : 0 (AGC enabled)
  CRC            : ON

These defaults are used only if:
- EEPROM does not contain a valid configuration
- EEPROM data is corrupted (CRC mismatch)
- EEPROM version is incompatible

-------------------------------------------------------------------------------

4. Persistent Configuration (EEPROM)
------------------------------------
The firmware stores the *last valid radio configuration* in EEPROM.

EEPROM behavior:
- Configuration is saved after EVERY valid configuration change
- Configuration is validated using:
  - Magic number
  - Version field
  - Payload length
  - CRC32 checksum
- On boot:
  - If EEPROM data is valid → configuration is loaded
  - If EEPROM data is invalid → defaults are used and written to EEPROM

EEPROM contents:
- Only ONE configuration record is stored
- No wear-leveling (acceptable for configuration use cases)

-------------------------------------------------------------------------------

5. Boot Sequence
----------------
On every ESP32 reset or power-up:

1. Serial interface is initialized (9600 baud)
2. EEPROM is initialized
3. Last valid configuration is loaded from EEPROM
4. SX1278 is HARDWARE RESET via RESET pin
5. radio.begin() is executed
6. RX interrupt callback is attached
7. Loaded configuration is applied to the radio
8. Continuous RX mode is started (unless RX was disabled)

This guarantees that the radio ALWAYS runs with the last known valid
configuration.

-------------------------------------------------------------------------------

6. Hardware Reset Policy
------------------------
To ensure reliable configuration changes:

- EVERY configuration change triggers:
  1. EEPROM save
  2. Hardware reset of SX1278
  3. radio.begin()
  4. Re-application of configuration
  5. RX restart (if enabled)

This applies to:
- AT+FREQ=...
- AT+BW=...
- AT+SF=...
- AT+CR=...
- AT+SYNC=...
- AT+PWR=...
- AT+CURR=...
- AT+PREAMBLE=...
- AT+GAIN=...
- AT+CRC=...
- AT+SET=...
- AT+DEFAULT
- AT+DEFRST
- AT+APPLY

-------------------------------------------------------------------------------

7. Serial Interface Rules
------------------------
- Commands are case-insensitive
- Commands are terminated by newline ('\n')
- Recommended Serial Monitor setting: "Newline"
- Responses:
  OK      → command executed successfully
  ERROR   → invalid command or invalid parameter

IMPORTANT:
- Configuration setters automatically SAVE and APPLY
- No manual AT+APPLY is required after setting parameters
  (AT+APPLY still exists as a forced re-apply command)

-------------------------------------------------------------------------------

8. AT Command Reference
-----------------------

8.1 Core Commands
-----------------
AT
  Ping / interface test

AT? or AT+HELP
  Show command list and usage

AT+CFG?
  Print current configuration

AT+APPLY
  Force hardware reset and re-apply current configuration

AT+DEFAULT
  Load default configuration, save to EEPROM, reset and apply

AT+DEFRST
  Same as AT+DEFAULT (explicit load + apply)

AT+RESET
  Hardware reset of radio and re-apply current configuration

-------------------------------------------------------------------------------

8.2 RX Control
--------------
AT+RX=OFF
  Disable RX and put radio into standby

NOTE:
RX can only be disabled via AT command in this firmware version.
RX is automatically enabled on boot.

-------------------------------------------------------------------------------

8.3 RSSI
--------
AT+RSSI?
  Show RSSI of the last successfully received packet

-------------------------------------------------------------------------------

8.4 Debug
---------
AT+DEBUG?
  Show debug state

AT+DEBUG
  Toggle debug ON/OFF

AT+DEBUG=ON
  Enable verbose TX/RX output

AT+DEBUG=OFF
  Disable verbose output (payload only)

-------------------------------------------------------------------------------

8.5 Radio Parameters
--------------------
Each setter automatically saves to EEPROM and re-applies configuration.

AT+FREQ? / AT+FREQ=<MHz>
  Carrier frequency in MHz

AT+BW? / AT+BW=<kHz>
  Bandwidth in kHz

AT+SF? / AT+SF=<7..12>
  Spreading Factor

AT+CR? / AT+CR=<5..8>
  Coding Rate (RadioLib format)

AT+SYNC? / AT+SYNC=<hex>
  LoRa Sync Word (hexadecimal)

AT+PWR? / AT+PWR=<dBm>
  TX output power in dBm

AT+CURR? / AT+CURR=<mA|0>
  Current limit in mA (0 = skip)

AT+PREAMBLE? / AT+PREAMBLE=<1..65535>
  Preamble length

AT+GAIN? / AT+GAIN=<0..6>
  RX gain (0 = AGC)

AT+CRC? / AT+CRC=ON|OFF
  Enable or disable LoRa CRC

-------------------------------------------------------------------------------

8.6 Batch Configuration
-----------------------
AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>

Example:
  AT+SET=433.5,125,11,8,0x14,10,0,8,0,ON

Behavior:
- All parameters are validated
- Configuration is saved to EEPROM
- Radio is hardware reset
- Configuration is applied
- RX is restarted

-------------------------------------------------------------------------------

9. LoRa TX Mode (Transparent Mode)
----------------------------------
Any Serial line NOT starting with "AT" is transmitted as a LoRa packet.

Example:
  Hello from node A

TX behavior:
- RX interrupt is temporarily disabled during TX
- Payload is transmitted
- RX is restored automatically

-------------------------------------------------------------------------------

10. RX Output
-------------
DEBUG = OFF:
- Only payload is printed

DEBUG = ON:
- Payload
- RSSI (dBm)
- SNR (dB)
- Frequency Error (Hz)
- Status messages

-------------------------------------------------------------------------------

11. Abbreviation Glossary
------------------------
AT       = Modem-style command interface
NSS / CS = SPI Chip Select
DIO0     = Digital I/O 0 (RX done interrupt)
DIO1     = Digital I/O 1 (auxiliary interrupt)
FREQ     = Frequency (MHz)
BW       = Bandwidth (kHz)
SF       = Spreading Factor
CR       = Coding Rate
SYNC     = LoRa Sync Word
PWR      = Output Power (dBm)
CURR     = Current Limit (mA)
PREAMBLE = LoRa preamble length
GAIN     = RX Gain (0 = AGC)
AGC      = Automatic Gain Control
CRC      = Cyclic Redundancy Check
RSSI     = Received Signal Strength Indicator
SNR      = Signal-to-Noise Ratio

-------------------------------------------------------------------------------

12. Notes and Limitations
------------------------
- RX can only be disabled, not re-enabled via AT command
- EEPROM wear-leveling is not implemented
- Parameter validity depends on SX1278 hardware and RadioLib
- RESET pin must be correctly wired for reliable operation

-------------------------------------------------------------------------------

End of README
