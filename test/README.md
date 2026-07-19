# Test scripts

PowerShell scripts for quick local validation on two ESP32-C3 boards.

Logs are written under `log/` by default. The folder is local-only and ignored by git.

Stable local COM assignments are saved in [COM_PORT_MAP.md](COM_PORT_MAP.md).

## Test results snapshot

Last updated: 2026-07-20.

The `log/` folder is local-only, so the table below keeps the important pass/fail state in git.

### Channel / frequency isolation

Each PASS here means:

1. traffic works with both modules on the same channel/frequency;
2. traffic stops when the modules are intentionally desynchronized;
3. traffic recovers after both modules are synchronized again.

| Module | Firmware selection | Ports | Baud | Parameter tested | Result | Latest local log / notes |
| --- | --- | --- | --- | --- | --- | --- |
| SX1278, assumed RA-01 | `RADIO_RA01_SX1278` | COM4, COM5 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_SX1278_COM4_COM5_COM4_COM5_20260701_160144.txt`; frequency isolation passed; one I2C boot warning remains in serial log. |
| XL1276-D01 (SX1276) | `RADIO_XL1276_D01_SX1276` | COM6, COM7 | 115200 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_XL1276_COM6_COM7_20260701_135910.txt` |
| Ebyte E22 (SX1268) | `RADIO_EBYTE_E22_SX1268` | COM8, COM9 | 115200 | `AT+CHAN` | PASS 18/0 | `Test-AtPairChannelIsolation_E22_COM8_COM9_20260701_131443.txt` |
| NRF24L01+ | `RADIO_NRF24L01` | COM10, COM11 | 115200 | `AT+CHAN` | PASS 18/0 | `Test-AtPairChannelIsolation_N24P80_COM10_COM11_20260701_165118.txt`; channel 80/81 used to avoid 2.4 GHz low-channel noise. |
| NRF24L01 | `RADIO_NRF24L01` | COM15, COM16 | 115200 | `AT+CHAN` | PASS 18/0 | `Test-AtPairChannelIsolation_N24A80_COM15_COM16_20260701_164937.txt`; channel 80/81 passed after RX restart/polling fallback update. |
| Ebyte E280 (SX1280) | `RADIO_EBYTE_E280_SX1280` | COM17, COM18 | 115200 | `AT+CHAN` | PASS 18/0 | `Test-AtPairChannelIsolation_E280R_COM17_COM18_20260701_174251.txt`; firmware re-flashed after stale E79 splash was observed; channel isolation and bidirectional exchange passed. |
| Ebyte E79 (CC1352P) | `RADIO_EBYTE_E79_CC1352P` | COM19, COM22 | 115200 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_E79R_COM19_COM22_20260701_174519.txt`; COM18 probed as E280, so the active E79 pair is COM19/COM22. |
| CC1101 V1, 433 MHz | `RADIO_CC1101_V1_433` | COM23, COM24 | 115200 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_C11_RXBYTES_433920_COM23_COM24_20260701_195859.txt`; 433.920/434.920 MHz isolation passed after RXBYTES/MARCSTATE fallback. |
| RA-01 (SX1278) | `RADIO_RA01_SX1278` | COM25, COM26 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_RA01_COM25_COM26_20260701_131554.txt` |
| RA-02 (SX1278) | `RADIO_RA02_SX1278` | COM27, COM28 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_RA02_COM27_COM28_20260701_131705.txt` |
| RA-01H (SX1276) | `RADIO_RA01H_SX1276` | COM29, COM30 | 115200 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_RA01H_COM29_COM30_20260701_142553.txt`; OLED works, one I2C boot warning remains in serial log. |
| SX1278, assumed RA-01 | `RADIO_RA01_SX1278` | COM31, COM32 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_SX1278_COM31_COM32_COM31_COM32_20260701_142212.txt`; OLED boot log clean after init fix. |
| RA-02 (SX1278) | `RADIO_RA02_SX1278` | COM33, COM34 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_RA02_COM33_COM34_COM33_COM34_20260701_141531.txt` |
| HC-12 | `RADIO_HC12` | COM39, COM40 | 115200 | `AT+CHAN` | PASS 18/0 per FU mode | Power-campaign diagnostics passed for FU3 (15 kbps), FU4 (0.5 kbps), and FU1 (250 kbps); COM39 was the measured DUT and COM40 the peer. |
| E28 (SX1280) | `RADIO_E28_SX1280` | COM37, COM38 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_E28_COM37_COM38_OLED_RECOVERY_COM37_COM38_20260701_152037.txt`; OLED hardware-I2C recovery added, boot log clean, frequency isolation passed. |
| CC1101 V2, 868 MHz | `RADIO_CC1101_V2_868` | COM39, COM40 | 115200 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_C22_V2_868_ORIGINAL_ANTENNAS_FINAL_COM39_COM40_20260701_204309.txt`; passed cleanly at 868/869 MHz with the original antennas. The same boards are unreliable at 433.920 MHz, so this local V2 pair appears to be 868 MHz hardware/front-end. |
| RA-01SH (SX1262) | `RADIO_RA01SH_SX1262` | COM41, COM42 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_RA01SH_COM41_COM42_RADIO_SPLASH_COM41_COM42_20260701_162614.txt`; frequency isolation passed after RADIO/SX1262 OLED splash update; boot log clean. |
| RA-01 (SX1278) | `RADIO_RA01_SX1278` | COM43, COM44 | 9600 | `AT+FREQ` | PASS 18/0 | `Test-AtPairChannelIsolation_RA01_COM43_COM44_COM43_COM44_20260701_155943.txt`; frequency isolation passed; one I2C boot warning remains in serial log. |
| RA-08 (ASR6601) | External module-side firmware | COM45, COM46 | 115200 | `AT+CHAN` | PASS 102/0 | `Test-Ra08ChannelIsolation_RA08_COM45_COM46_REOPEN_COM45_COM46_20260701_160824.txt`; dedicated script reopens serial ports between directions because COM46 does not always echo after TX in long sessions. |
| Ebyte E32T20, 433 MHz | `RADIO_EBYTE` | COM47, COM48 | 115200 | `AT+CHAN` | PASS 12/0 | `Test-AtPairChannelIsolation_E32_433F_COM47_COM48_20260701_170632.txt`; channel change/resync passed after automatic E32 reset following saved config writes. |
| Ebyte E32T20, 868 MHz | `RADIO_EBYTE` | COM49, COM50 | 115200 | `AT+CHAN` | PASS 12/0 | `Test-AtPairChannelIsolation_E32_868F_COM49_COM50_20260701_170904.txt`; channel change/resync passed after automatic E32 reset following saved config writes. |
| Ebyte E32 868T30D | `RADIO_EBYTE_E32_868T30D` | COM51, COM52 | 115200 | `AT+CHAN` | PASS 18/0 at `AT+POWER1` | `Test-AtPairChannelIsolation_E32_868T30D_P1_RETEST_COM51_COM52_COM51_COM52_20260702_100237.txt`; channel 23/24 isolation and resync passed at 30 dBm after adding local VCC capacitors. |
| Ebyte E32 433T33D | `RADIO_EBYTE_E32_433T33D` | COM53, COM54 | 115200 | `AT+CHAN` | PASS 18/0 at `AT+POWER1` | `Test-AtPairChannelIsolation_E32_433T33D_P1_RETEST_COM53_COM54_COM53_COM54_20260702_094632.txt`; channel 23/24 isolation and resync passed at 33 dBm after improving the local power wiring. |

### Other validated pairs

| Module | Firmware selection | Ports | Test type | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| Ebyte E79 (CC1352P) | `RADIO_EBYTE_E79_CC1352P` | COM19, COM22 | AT command regression and bidirectional radio exchange | PASS | Tested commands included `AT`, `AT?`, `AT+HELP`, config commands, sleep/wake, send text/hex, desync/error validation, and 433/434 MHz frequency isolation. |
| RA-08 (ASR6601) | External module-side firmware | COM20, COM21 | AT regression and bidirectional exchange | PASS | Main firmware lives in the separate RA-08 AT Commands repository; this repo keeps test helpers and references. |

## Upload AT firmware

```powershell
.\test\Upload-AtFirmware.ps1 -Module RADIO_RA02_SX1278 -Port COM4,COM5
```

Useful module values are the same as `RADIO_MODULE` in `src/main.cpp`.

## Run SX127x AT pair test

```powershell
.\test\Test-Sx127xAtPair.ps1 -Label SX1278 -PortA COM4 -PortB COM5
```

The default parameters match the RA-02 SX1278 AT firmware. For another SX127x module, override the default tokens or the batch `AT+SET` command if its expected defaults differ.

## Run RA08 AT regression

```powershell
python .\test\ra08_regression.py
```

The script defaults to `COM20` and `COM21` at `115200` baud.

## Run generic AT pair channel/frequency isolation test

This checks one pair at a time:

1. set both modules to the same channel/frequency and verify traffic passes;
2. set the two modules to different channels/frequencies and verify traffic stops;
3. set them back to the same value and verify traffic recovers.

Raw text payload modules:

```powershell
.\test\Test-AtPairChannelIsolation.ps1 -Label SX1278 -PortA COM4 -PortB COM5 -Baud 9600 -SetCommandTemplate 'AT+FREQ={value}' -SameValue 433.000 -DifferentValueA 433.000 -DifferentValueB 434.000 -SendTemplate '{payload}'
```

E79 also supports direct text payloads after its CC1352P modem firmware is
updated:

```powershell
.\test\Test-AtPairChannelIsolation.ps1 -Label E79 -PortA COM19 -PortB COM22 -SetCommandTemplate 'AT+FREQ={value}' -SameValue 433000000 -DifferentValueA 433000000 -DifferentValueB 434000000 -SendTemplate '{payload}' -SkipRxOn
```

Hex payload modules, such as RA-08:

```powershell
.\test\Test-AtPairChannelIsolation.ps1 -Label RA08 -PortA COM20 -PortB COM21 -SetCommandTemplate 'AT+CHAN={value}' -SameValue 0 -DifferentValueA 0 -DifferentValueB 1 -PayloadKind Hex -SendTemplate 'AT+SEND={hex}'
```

RA-08 modules that reset or drop USB CDC after TX can use the dedicated reopen-per-direction test:

```powershell
.\test\Test-Ra08ChannelIsolation.ps1 -PortA COM45 -PortB COM46 -Label RA08_COM45_COM46_REOPEN
```

## Single-Port AT Probe

Use `Invoke-AtProbe.ps1` for quick diagnostics when one module in a pair looks
unhealthy and a full RF test would be misleading.

```powershell
.\test\Invoke-AtProbe.ps1 -Port COM51 -Command @('AT','AT+AUX?','AT+CFG?','AT+POWER?')
```
