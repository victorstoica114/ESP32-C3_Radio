# ESP32-C3 CC1352P UART Bootloader Bridge

This firmware turns the ESP32-C3 into a USB CDC to CC1352P UART bridge and also
controls the CC1352P TI ROM bootloader entry pins.

Current validated connections:

- ESP32 `GPIO20` = RX from CC1352P TX
- ESP32 `GPIO21` = TX to CC1352P RX
- ESP32 `GPIO3` = CC1352P bootloader backdoor pin, E79 `BOOT` / `DIO15`, active low
- ESP32 `GPIO10` = CC1352P `RESET_N`, active low

The GPIO3/GPIO10 path is validated on two modules. The bridge can enter the TI
ROM serial bootloader automatically, and the CC1352P firmware can be erased,
written and verified through UART without J-Link.

The firmware treats BOOT and RESET_N as active-low control lines by default and
releases them as Hi-Z/open-drain-style outputs, relying on the target pull-ups.
If another hardware spin uses inverting transistors, override the build flags
`CC1352_BOOT_ACTIVE_LOW`, `CC1352_RESET_ACTIVE_LOW`, `CC1352_BOOT_OPEN_DRAIN`,
or `CC1352_RESET_OPEN_DRAIN`.

The bridge normally forwards bytes unchanged. Its default target UART baud
toward the CC1352P is `1000000`, matching the E79 AT modem firmware.

The PC-side USB CDC baud selected by a terminal or script is not the important
physical link speed here. Native USB CDC is packet-based; the critical baud is
the internal ESP32-C3 UART to CC1352P (`GPIO20/GPIO21`), controlled by
`CC1352_BRIDGE_HOST_BAUD` and currently set to `1000000`. Use `460800` as the
validated fallback when maximum stress stability matters more than peak speed.

## Local Bridge Commands

The bridge consumes only commands starting with `~CC1352P_`; all other bytes are
forwarded to CC1352P.

```text
~CC1352P_RESET\n
~CC1352P_BOOT=LOW\n
~CC1352P_BOOT=HIGH\n
~CC1352P_ENTER_BOOTLOADER\n
~CC1352P_BAUD=<baud>\n
```

- `RESET` pulses `GPIO10`, then the bridge returns to transparent mode.
- `BOOT=LOW` holds E79 `BOOT/DIO15` active.
- `BOOT=HIGH` releases E79 `BOOT/DIO15`.
- `ENTER_BOOTLOADER` holds BOOT low, pulses RESET, waits for the CC1352P to
  sample the backdoor pin, then releases BOOT. The host can then send TI ROM
  SBL sync bytes `55 55` through the transparent bridge.
- `BAUD` changes the ESP32 UART baud rate toward CC1352P when a non-default
  rate is needed for experiments.

Supported target UART baud values:

```text
9600,38400,57600,115200,230400,460800,500000,921600,1000000
```

## Build

```powershell
.\scripts\build-esp32-cc1352-bridge.ps1
```

## Flash ESP32 Bridge

Pick the ESP32 native USB COM port from `pio device list`, then:

```powershell
.\scripts\flash-esp32-cc1352-bridge.ps1 -Port COM19
```

## Probe Automatic BOOT + RESET

Test the automatic bootloader entry path with:

```powershell
.\scripts\probe-e79-bootloader-auto-via-esp32.ps1 -Port COM19
```

Expected success:

```text
ACK: 00 CC
```

## Flash CC1352P Through ESP32

Normal update flow, no J-Link and no manual buttons:

```powershell
.\scripts\flash-e79-at-modem-via-esp32.ps1 -Port COM19 -EnterBootloaderFromEsp32
```

The current validated result on both modules is:

```text
CC1352P1 PG2.0 (7x7mm): 352KB Flash, 20KB SRAM
Performing mass erase
Writing 360448 bytes starting at address 0x00000000
Verified (match: 0x29bd3083)
```

After a successful automatic flash, the script releases BOOT and pulses RESET
through GPIO10 so the CC1352P returns to the AT firmware. Use
`-NoResetAfterFlash` only when debugging the bootloader session.

Verify the AT firmware:

```powershell
.\scripts\test-e79-at-sequence-via-esp32.ps1 -Port COM19 -Baud 1000000 -Commands AT+VERSION?
```

## Fallback Modes

For old/manual hardware, hold BOOT low, run the same script without
`-EnterBootloaderFromEsp32`, then pulse RESET during the countdown.

J-Link is still useful for recovery or register inspection, but it is no longer
required for the normal ESP32 bridge update path once the CC1352P image has the
bootloader backdoor enabled in CCFG.
