# Datasheets

Temporary PDF collection for the supported radio modules and the ESP32-C3
development board.

These PDF files are vendor/manufacturer documentation and are not covered by the
project MIT License. For a public repository, prefer linking to official source
pages unless redistribution is explicitly allowed or otherwise acceptable.

This repository is currently private, so the PDFs are kept here for convenience.
Before making the repository public, review each file for redistribution terms
and remove anything that should be linked instead of committed.

## Files

| File | Covers | Source/status |
| --- | --- | --- |
| `CC1101_TI_Datasheet.pdf` | CC1101 | Official TI datasheet: https://www.ti.com/lit/ds/symlink/cc1101.pdf |
| `ESP32-C3_Datasheet_Espressif.pdf` | ESP32-C3 chip | Official Espressif datasheet: https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf |
| `ESP32-C3-WROOM-02_Datasheet_Espressif.pdf` | ESP32-C3-WROOM-02 module | Official Espressif datasheet: https://www.espressif.com/sites/default/files/documentation/esp32-c3-wroom-02_datasheet_en.pdf |
| `ESP32-C3-DevKitC-02_Schematic_Espressif.pdf` | ESP32-C3-DevKitC-02 board | Official Espressif schematic: https://dl.espressif.com/dl/schematics/SCH_ESP32-C3-DEVKITC-02_V1_1_20210126A.pdf |
| `Ebyte_E28-2G4M20S_Manual.pdf` | E28 SX1280/SX128x family module | Official CDEBYTE download: https://www.cdebyte.com/pdf-down.aspx?id=3657 |
| `E22-400M30S_UserManual_EN_v1.8.pdf` | Ebyte E22 SPI LoRa module, SX1268 | Added manually from Ebyte documentation. |
| `E280-2G4T12S_UserManual_EN_v1.2.pdf` | Ebyte E280-2G4T12S UART/TTL module, SX1280 | Added manually from Ebyte documentation. |
| `E79-400DM2005S.pdf` | Ebyte E79-400DM2005S module, TI CC1352P | Added manually from Ebyte documentation. |
| `Ebyte_E32-433T30D_Manual.pdf` | Ebyte E32 UART LoRa module | Official CDEBYTE download: https://www.cdebyte.com/pdf-down.aspx?id=4218 |
| `HC-12_english_datasheets.pdf` | HC-12 module | Added manually; source still needs confirmation before public release. |
| `HC-12_Si446x_SiliconLabs_Datasheet.pdf` | Si446x radio chip used by HC-12-style modules | Official Silicon Labs datasheet: https://www.silabs.com/documents/public/data-sheets/Si4464-63-61-60.pdf |
| `NRF24L01P_Product_Specification_SparkFun_Mirror.pdf` | nRF24L01+ | Temporary SparkFun mirror of Nordic product specification. Direct Nordic PDF download returned HTTP 403 during setup. |
| `ra-08_v1-1-0_specification.pdf` | Ai-Thinker RA-08 module, ASR6601 LPWAN SoC | Added manually from Ai-Thinker documentation. |
| `RA-09_Specification_V1.0.0.pdf` | Ai-Thinker RA-09 module, STM32WLE5CCU6 wireless MCU | Added manually from Ai-Thinker documentation. |
| `RA-02-M_EN_10046319.pdf` | RA-02-M module | Added manually; source still needs confirmation before public release. |
| `SX1262_datasheet.pdf` | SX1262 chip, used by RA-01SH-style modules | Added manually; source still needs confirmation before public release. |
| `SX1276-SX1277-SX1278-SX1279_Semtech_Datasheet_SparkFun_Mirror.pdf` | SX1276/SX1277/SX1278/SX1279 chips, used by RA-01/RA-02/RA-01H/XL1276-D01-style modules | Sufficient chip-level reference for the SX127x modules. Temporary SparkFun mirror of Semtech datasheet; official Semtech product pages use dynamic Salesforce downloads. |
| `SX128x.pdf` | SX1280/SX128x chip family | Added manually; source still needs confirmation before public release. |
| `cc1352p.pdf` | TI CC1352P wireless MCU used by E79 | Added manually from TI documentation. |

## Still Worth Verifying

- Optional module-level PDF links for `RA-01`, `RA-02`, `RA-01H`, and `XL1276-D01` if exact mechanical/module documentation is needed later.
- Official Ai-Thinker PDF link for `RA-01SH`.
- Direct official Nordic PDF link for `nRF24L01+`.
- Direct official Semtech PDF links for `SX1262` and `SX128x`.
