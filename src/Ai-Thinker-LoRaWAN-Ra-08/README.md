# Ai-Thinker RA-08 AT Modem Source

This folder intentionally contains only the source files for the RA-08 ASR6601
standalone UART AT modem.

Primary repository:
[victorstoica114/RA-08_AT-Commands](https://github.com/victorstoica114/RA-08_AT-Commands)

It is not a complete ASR6601 SDK checkout. To build it, place these files in the
separate RA-08 firmware/SDK project that provides the ASR6601 drivers, startup
code, linker script, and ARM GCC toolchain.

Kept here:

- `src/main.c`
- `src/at_modem.c`
- `src/tremo_it.c`
- `inc/at_modem.h`
- `inc/lora_config.h`
- `inc/tremo_it.h`

The modem was tested with two RA-08 modules at `115200` baud and supports AT
configuration, sleep/wake, RX/TX control, and bidirectional packet exchange.
