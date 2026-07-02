# COM Port Map

Last updated: 2026-07-02.

Stable COM-port assignments used for local radio pair tests.

| Module / firmware selection | Ports | Notes |
| --- | --- | --- |
| SX1278, assumed RA-01 / `RADIO_RA01_SX1278` | COM4, COM5 | Tested: frequency isolation passed; one I2C boot warning remains in serial log. |
| XL1276-D01 (SX1276) / `RADIO_XL1276_D01_SX1276` | COM6, COM7 | Tested: frequency isolation passed. |
| Ebyte E22 (SX1268) / `RADIO_EBYTE_E22_SX1268` | COM8, COM9 | Tested: channel isolation passed. |
| NRF24L01+ / `RADIO_NRF24L01` | COM10, COM11 | Tested: channel isolation and bidirectional exchange passed on channel 80/81. |
| NRF24L01 / `RADIO_NRF24L01` | COM15, COM16 | Tested: channel isolation and bidirectional exchange passed on channel 80/81. |
| Ebyte E280 (SX1280) / `RADIO_EBYTE_E280_SX1280` | COM17, COM18 | Tested: channel isolation and bidirectional exchange passed after E280 firmware reflash; COM18 probed as E280. |
| Ebyte E79 (CC1352P) bridge / `RADIO_EBYTE_E79_CC1352P` | COM19, COM22 | Tested: AT commands, 433/434 MHz frequency isolation, and bidirectional radio exchange passed. |
| CC1101 V1 433 MHz / `RADIO_CC1101_V1_433` | COM23, COM24 | Tested at 433.920 MHz after the RXBYTES/MARCSTATE fallback: frequency isolation and bidirectional exchange passed; boot log clean. |
| RA-01 (SX1278) / `RADIO_RA01_SX1278` | COM25, COM26 | Tested: frequency isolation passed. |
| RA-02 (SX1278) / `RADIO_RA02_SX1278` | COM27, COM28 | Tested: frequency isolation passed. |
| RA-01H (SX1276) / `RADIO_RA01H_SX1276` | COM29, COM30 | Tested: frequency isolation passed; OLED observed working; one I2C boot warning remains in serial log. |
| SX1278, assumed RA-01 / `RADIO_RA01_SX1278` | COM31, COM32 | Tested: frequency isolation passed; OLED boot log clean after init fix. |
| RA-02 (SX1278) / `RADIO_RA02_SX1278` | COM33, COM34 | Tested: frequency isolation passed. |
| HC-12 / `RADIO_HC12` | COM35, COM36 | Tested: channel isolation and bidirectional exchange passed. |
| E28 (SX1280) / `RADIO_E28_SX1280` | COM37, COM38 | Tested: frequency isolation and bidirectional exchange passed; OLED hardware-I2C recovery applied and boot log is clean. |
| CC1101 V2 868 MHz / `RADIO_CC1101_V2_868` | COM39, COM40 | Confirmed as 868 MHz hardware in this local set: 868/869 MHz isolation passed 18/0 with the original antennas; 433.920 MHz remains unreliable, matching a wrong-band/front-end mismatch rather than a firmware fault. |
| RA-01SH (SX1262) / `RADIO_RA01SH_SX1262` | COM41, COM42 | Tested after RADIO/SX1262 OLED splash update: frequency isolation and bidirectional exchange passed; boot log clean. |
| RA-01 (SX1278) / `RADIO_RA01_SX1278` | COM43, COM44 | Tested: frequency isolation passed; one I2C boot warning remains in serial log. |
| RA-08 (ASR6601) / external AT modem firmware | COM45, COM46 | Tested with dedicated RA-08 script: channel isolation and bidirectional exchange passed. COM46 does not always echo after TX in long sessions, so the script reopens serial ports between directions. |
| Ebyte E32T20 433 MHz / `RADIO_EBYTE` | COM47, COM48 | Tested: channel isolation passed after automatic module reset on saved config writes. |
| Ebyte E32T20 868 MHz / `RADIO_EBYTE` | COM49, COM50 | Tested: channel isolation passed after automatic module reset on saved config writes. |
| Ebyte E32 868T30D / `RADIO_EBYTE_E32_868T30D` | COM51, COM52 | Tested: channel isolation passed at `AT+POWER1` / 30 dBm after adding local VCC capacitors. |
| Ebyte E32 433T33D / `RADIO_EBYTE_E32_433T33D` | COM53, COM54 | Tested: channel isolation passed at `AT+POWER1` / 33 dBm after improving local power wiring. |
