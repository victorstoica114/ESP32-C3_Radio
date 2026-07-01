# ESP32-C3 CC1352P UART Bootloader Bridge

This temporary firmware turns the ESP32-C3 into a mostly transparent USB CDC to
CC1352P UART bridge for testing the TI ROM serial bootloader.

Connections used by the current schematic:

- ESP32 `GPIO20` = RX from CC1352P TX
- ESP32 `GPIO21` = TX to CC1352P RX
- ESP32 `GPIO3` = CC1352P bootloader backdoor pin, E79 `BOOT` / `DIO15`, active low
- ESP32 `GPIO10` = CC1352P `RESET_N`, active low

Current hardware note: the GPIO10 reset pulse path was tested and did not reset
the CC1352P. This was repeated with J-Link physically disconnected: manual reset
brought the AT firmware back, but `~CC1352P_RESET` did not drop `AT+UPTIME?`.
With J-Link connected, readback of `AON_PMCTL:RESETCTL` also stayed at
`RESET_SRC=SYSRESET` instead of changing to `PIN_RESET`. The next hardware spin
is expected to connect BOOT to GPIO3 and RESET to GPIO10 so the ESP32 can enter
the TI ROM bootloader automatically.

The firmware treats BOOT and RESET_N as active-low control lines by default and
releases them as Hi-Z/open-drain-style outputs, relying on the target pull-ups.
If the final hardware uses inverting transistors, override the build flags
`CC1352_BOOT_ACTIVE_LOW`, `CC1352_RESET_ACTIVE_LOW`, `CC1352_BOOT_OPEN_DRAIN`,
or `CC1352_RESET_OPEN_DRAIN`.

The bridge normally forwards bytes unchanged. Its default target UART baud
toward the CC1352P is `115200`, matching the E79 AT modem firmware.

The PC-side USB CDC baud selected by a terminal or script is not the important
physical link speed here. Native USB CDC is packet-based; the critical baud is
the internal ESP32-C3 UART to CC1352P (`GPIO20/GPIO21`), controlled by
`CC1352_BRIDGE_HOST_BAUD` and currently set to `115200`.

The only local commands the bridge consumes are:

```text
~CC1352P_RESET\n
~CC1352P_BOOT=LOW\n
~CC1352P_BOOT=HIGH\n
~CC1352P_ENTER_BOOTLOADER\n
~CC1352P_BAUD=<baud>\n
```

`RESET` pulses `GPIO10`, then the bridge returns to transparent mode.
`BOOT=LOW` holds E79 `BOOT/DIO15` active; `BOOT=HIGH` releases it.
`ENTER_BOOTLOADER` holds BOOT low, pulses RESET, waits for the CC1352P to sample
the backdoor pin, then releases BOOT. The host can then send the TI ROM SBL sync
bytes `55 55` through the transparent bridge.
`BAUD` changes the ESP32 UART baud rate toward CC1352P when a non-default rate
is needed for experiments. Supported values are
`9600`, `38400`, `57600`, `115200`, `230400`, `460800`, `500000`, `921600`, and
`1000000`.

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

After GPIO3 -> BOOT and GPIO10 -> RESET_N are wired, test the automatic
bootloader entry path with:

```powershell
.\scripts\probe-e79-bootloader-auto-via-esp32.ps1 -Port COM19
```

Expected success:

```text
ACK: 00 CC
```

## Flash CC1352P Through ESP32

The CC1352P application must already have the TI ROM bootloader/backdoor enabled
in CCFG. For the current dev firmware that means one initial J-Link flash of
`e79_at_modem` after the bootloader-backdoor SysConfig change.

With automatic BOOT + RESET hardware:

```powershell
.\scripts\flash-e79-at-modem-via-esp32.ps1 -Port COM19 -EnterBootloaderFromEsp32
```

For old/manual hardware, hold BOOT, run the same script without
`-EnterBootloaderFromEsp32`, then pulse RESET during the countdown.
