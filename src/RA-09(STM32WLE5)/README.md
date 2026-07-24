# RA-09 (STM32WLE5) AT Modem Source

This folder contains a compact source reference for the Ai-Thinker RA-09
standalone UART AT modem.

Primary repository:
[victorstoica114/RA-09_AT-Commands](https://github.com/victorstoica114/RA-09_AT-Commands)

It is not a complete STM32CubeWL project. The dedicated repository contains
the build system, STM32 HAL and CMSIS dependencies, radio middleware, startup
code, linker script, flash utilities, and license details required to build
and program the firmware.

Kept here:

- the modem application and transparent-data implementation;
- Sub-GHz application and command glue;
- RA-09 RF-switch control;
- LPUART1 configuration for PA2/PA3 (`TX2`/`RX2`);
- the relevant interrupt and UART interface files;
- the applicable ST and third-party license notices.

The modem receives continuously after boot. Plain UART payloads are sent over
LoRa without requiring `AT+SEND`, while AT commands configure frequency,
power, spreading factor, bandwidth, coding rate, preamble, CRC, IQ, sync word,
RX state, and sleep state.

The validated image was programmed through the STM32 UART bootloader on two
RA-09 carriers, one with CH340C and one with CH9340C. A bidirectional test
delivered 10 of 10 frames in each direction without corruption.
