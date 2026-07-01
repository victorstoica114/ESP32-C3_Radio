# Ebyte E79(CC1352P) AT Modem Source

This folder intentionally contains only the important source files for the Ebyte E79-400DM2005S standalone UART AT modem firmware running on the TI CC1352P.

Primary repository:
[victorstoica114/Ebyte-E79-CC1352P-_AT_Modem_Firmware](https://github.com/victorstoica114/Ebyte-E79-CC1352P-_AT_Modem_Firmware)

It is not a complete TI SimpleLink SDK checkout. To build it, place these files in the separate CC1352P firmware workspace that provides the TI SimpleLink Low Power F2 SDK, SysConfig, startup code, linker script, generated TI driver/radio config, and ARM GCC toolchain.

Kept here:

- `src/e79_at_modem.c`
- `src/main_nortos.c`
- `src/RFQueue.c`
- `src/e79_at_modem.syscfg`
- `inc/RFQueue.h`

Important hardware notes:

- CC1352P UART modem baud: `115200` 8N1.
- E79/CC1352P logic is 3.3 V, not 5 V TTL.
- ESP32-C3 bridge default UART toward CC1352P must be `115200`.
- PC-side USB CDC baud is not the important physical speed; the relevant link is ESP32-C3 `GPIO20/GPIO21` <-> CC1352P UART.
- CC1352P is programmed by JTAG/cJTAG or by TI ROM serial bootloader when the `BOOT/DIO15` active-low backdoor is enabled.

The modem was validated with two E79 modules at `115200` baud. AT command handling, parameter validation, sleep/wake, RX/TX control, text packets, hex packets, RSSI/LASTPKT diagnostics, and bidirectional radio exchange passed the rigorous two-module test.
