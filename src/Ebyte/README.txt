Ebyte E32 AT firmware
=====================

This firmware targets the ESP32-C3 radio test board and provides an AT command
shell plus a transparent USB-to-Ebyte-E32 UART bridge.

Hardware wiring:

- ESP32 UART RX GPIO20 <- E32 TX
- ESP32 UART TX GPIO21 -> E32 RX
- E32 M0 -> GPIO10
- E32 M1 -> GPIO3
- E32 AUX -> GPIO1, configured as INPUT_PULLUP
- OLED SDA -> GPIO5
- OLED SCL -> GPIO6
- Status LED -> GPIO8

The OLED splash shows "RADIO" on the first line and "E32" on the second line.

The firmware controls the E32 mode pins directly:

- NORMAL mode: M0=0, M1=0
- WAKE mode: M0=1, M1=0
- POWER_SAVE mode: M0=0, M1=1
- PROGRAM/SLEEP mode: M0=1, M1=1

Configuration reads/writes are done in PROGRAM mode at 9600 baud. After saved
configuration writes, including AT+CHAN and AT+SETRADIO, the firmware resets the
E32 module internally, returns M0/M1 to NORMAL mode, retunes Serial1 to the
module UART baud, and drains the UART. This was added because E32T20 modules can
otherwise return corrupted UART/RF data after channel changes.

Validated hardware:

- E32T20 433 MHz pair on COM47/COM48
- E32T20 868 MHz pair on COM49/COM50

Both pairs passed channel isolation and resync recovery with AT+CHAN=23/24.

Main commands:

- AT, AT?, AT+HELP
- AT+CFG?, AT+INFO?, AT+AUX?
- AT+DEFAULT, AT+RESET, AT+APPLY, AT+APPLY=TEMP
- AT+BRIDGE=ON/OFF, AT+BRIDGE?
- AT+MODE=NORMAL/WAKE/POWER_SAVE/SLEEP, AT+MODE?
- AT+SLEEP, AT+WAKE
- AT+ADDH, AT+ADDL, AT+CHAN
- AT+BAUD1..8, AT+PARITY1..3, AT+AIR1..6
- AT+POWER1..4
- AT+WORT1..8
- AT+FEC=ON/OFF, AT+FIXED=ON/OFF, AT+IOMODE=PP/OD
- AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,WOR,FEC,FIXED,IOMODE
- AT+SENDTO=ADDH,ADDL,CHAN,TEXT
- AT+BROADCAST=CHAN,TEXT

POWER is exposed as the E32 power preset index 1..4. The displayed dBm mapping
is firmware-side display text and depends on the exact E32 module variant; the
current code uses the E32T20-style 20/17/14/10 dBm mapping.

Non-AT serial lines are forwarded to the E32 module with CRLF when bridge mode is
enabled. If bridge mode is disabled, the firmware returns:

  #ERROR: BRIDGE_OFF (send AT+BRIDGE=ON)

If the module is in sleep/power-save mode and payload TX is attempted, the
firmware returns:

  #ERROR: RADIO_SLEEPING (send AT+WAKE)

Troubleshooting:

- If configuration commands time out, check M0, M1, AUX, and the 9600 baud
  PROGRAM-mode UART path.
- If radio traffic does not recover after changing channel, run AT+RESET once;
  current firmware should do this automatically after saved config writes.
- If the OLED does not display, check GPIO5/GPIO6 and the SSD1306 128x64 wiring.
