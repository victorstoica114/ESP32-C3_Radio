# E79 AT modem firmware

Firmware pentru Ebyte E79-400DM2005S / TI CC1352P. Modulul ruleaza firmware
propriu pe CC1352P si expune catre ESP32 un modem radio UART cu comenzi AT.

## Hardware

- UART: `1000000 8N1`, CC1352P `DIO12` = RX, `DIO13` = TX.
- Fallback validat pentru stress: `460800 8N1`.
- Logica: 3.3 V, nu 5 V TTL.
- Programare normala: TI ROM serial bootloader prin ESP32-C3 bridge.
- Recovery/fallback: JTAG/cJTAG cu J-Link, device `CC1352P1F3`.
- BOOT/update: `BOOT/DIO15`, active-low, controlat de ESP32 GPIO3 pe hardware-ul curent.
- RESET: `RESET_N`, active-low, controlat de ESP32 GPIO10 pe hardware-ul curent.
- RF switch E79: TX = `DIO5=1,DIO6=0`, RX = `DIO5=0,DIO6=1`, standby = ambele 0.

## RF

- Baza TI: Proprietary RF / 2-GFSK 50 kbps 433 MHz, generata din
  `CC1352P_4_LAUNCHXL`.
- Frecventa implicita: `433920000` Hz.
- Sync word implicit: `0x930B51DE`.
- Configuratia este RAM-only in aceasta versiune; nu se scrie in flash/NVS.
- `AT+DEFAULT` revine la RX off. Este varianta mai sigura pentru integrarea cu
  ESP32: modulul nu incepe sa livreze pachete nesolicitate dupa reset.

## Comenzi

- `AT`
- `AT?`
- `AT+HELP`
- `AT+CFG?`
- `AT+DEFAULT`
- `AT+RESET`
- `AT+VERSION?`
- `AT+DEBUG?`
- `AT+DEBUG=ON`
- `AT+DEBUG=OFF`
- `AT+FREQ?`
- `AT+FREQ=<Hz>`
- `AT+PWR?`
- `AT+PWR=<dBm>`
- `AT+RATE?`
- `AT+RATE=<bps>`
- `AT+MOD?`
- `AT+MOD=2GFSK`
- `AT+SYNC?`
- `AT+SYNC=<hex>`
- `AT+ADDR?`
- `AT+ADDR=<value>`
- `AT+CHAN?`
- `AT+CHAN=<n>`
- `AT+RX=ON`
- `AT+RX=OFF`
- `AT+SEND=<text>`
- `AT+SENDHEX=<hex>`
- `AT+SLEEP`
- `AT+WAKE`
- `AT+RSSI?`
- `AT+STATUS?`
- `AT+LASTPKT?`
- `AT+RANDOM?`
- `AT+UPTIME?`
- `AT+SETRADIO=FREQ,RATE,PWR,MOD,SYNC`

## Parametri validati

- `FREQ`: `431000000..500000000` Hz.
- `RATE`: doar `50000` bps in V1.
- `MOD`: doar `2GFSK` in V1.
- `PWR`: `-20,-15,-10,-5,0,1,2,3,4,5,6,7,8,9,10,11,12,13` dBm. Valoarea de
  14 dBm din tabelul TI nu este expusa in V1 deoarece cere configurare speciala
  `CCFG_FORCE_VDDR_HH=1`.
- `SYNC`: hex 1..8 cifre, cu sau fara prefix `0x`.
- `ADDR`: N/A in V1; PHY-ul generat ruleaza fara address check.
- `CHAN`: N/A in V1; se foloseste frecventa explicita prin `AT+FREQ`.
- Payload TX: maxim 64 octeti.

Toate erorile incep cu `#ERROR:` si se termina cu CRLF. Raspunsul simplu de
succes este `OK\r\n`.

Pachetele primite apar automat pe UART:

```text
+RX:<len>,<rssi>,<data>
+RXHEX:<len>,<rssi>,<hex>
```

## Build

Din VSCode ruleaza task-ul:

```text
CC1352P: Build E79 AT modem
```

Sau din PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-e79-at-modem.ps1
```

Pentru fallback-ul stabil la `460800`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-e79-at-modem.ps1 -UartBaud 460800
```

Rezultate:

```text
firmware\e79_at_modem\gcc\e79_at_modem.hex
firmware\e79_at_modem\gcc\e79_at_modem.bin
```

## Flash recomandat prin ESP32 bridge

Hardware-ul curent permite ESP32 sa controleze atat `BOOT/DIO15`, cat si
`RESET_N`. Fluxul normal de update nu mai cere J-Link si nu cere apasarea
manuala a butoanelor.

1. Flash bridge-ul pe ESP32 daca nu este deja instalat:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-esp32-cc1352-bridge.ps1 -Port COM19
```

2. Optional, probeaza non-distructiv intrarea in ROM bootloader:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\probe-e79-bootloader-auto-via-esp32.ps1 -Port COM19
```

Succes:

```text
ACK: 00 CC
```

3. Scrie firmware-ul CC1352P prin ESP32:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem-via-esp32.ps1 -Port COM19 -EnterBootloaderFromEsp32
```

Rezultat validat pe doua module:

```text
CC1352P1 PG2.0 (7x7mm): 352KB Flash, 20KB SRAM
Performing mass erase
Writing 360448 bytes starting at address 0x00000000
Verified (match: 0x29bd3083)
```

4. Verifica firmware-ul AT:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-e79-at-sequence-via-esp32.ps1 -Port COM19 -Baud 1000000 -Commands AT+VERSION?
```

Dupa verify, scriptul de flash automat elibereaza BOOT si pulseaza RESET prin
ESP32 GPIO10. Pentru debug se poate adauga `-NoResetAfterFlash`, caz in care
resetul ramane manual.

## ROM bootloader si CCFG

Firmware-ul activeaza ROM serial bootloader backdoor pe `DIO15`, activ low. Pe
schema E79, acesta este pinul `BOOT` cu pull-up si buton la GND.

Comportament important:

- ROM serial bootloader-ul exista in CC1352P din fabrica; nu este o componenta
  pe care o scriem noi in flash.
- Daca modulul nu are imagine valida in flash, ROM-ul poate porni serial
  bootloader-ul, cu conditia ca starea CCFG sa permita bootloader-ul.
- Dupa ce exista o imagine valida in flash, `BOOT` + `RESET` functioneaza doar
  daca imaginea curenta a configurat CCFG cu backdoor activ.
- Imaginea aceasta seteaza `BL_CONFIG` pentru `BOOT/DIO15` active-low. Valoarea
  asteptata este `0xC5FE0FC5`.
- Un modul testat cu imagine valida, dar fara backdoor, a avut
  `BL_CONFIG = 0xC5FFFFFF`: bootloader enabled, backdoor disabled, pin BOOT
  neselectat. In acea stare UART SBL nu raspunde la `0x55 0x55`.

Pentru productie, backdoor-ul permite unui host extern sa citeasca/stearga
flash-ul daca are acces fizic la pini. Este convenabil pentru development, dar
trebuie reevaluat inainte de firmware final blocat.

## Fallback J-Link si USB-UART manual

J-Link ramane metoda de recuperare daca un modul are CCFG necunoscut sau daca
imaginea curenta nu mai permite intrarea in ROM SBL:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem.ps1
```

Pentru hardware fara control ESP32 pe BOOT/RESET se poate folosi si intrarea
manuala in bootloader:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem-uart.ps1 -Port COM5
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem-via-esp32.ps1 -Port COM19
```

In modul manual, tine `BOOT/DIO15` low, pulseaza `RESET_N`, apoi porneste
sincronizarea SBL.

## Test cu doua module

Scriptul riguros validat:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-e79-at-rigorous-two-modules.ps1 -PortA COM19 -PortB COM22 -BridgeBaud 1000000
```

Rezultat validat dupa flash prin ESP32 bridge:

```text
PASS: 150
FAIL: 0
```

Testul acopera:

- toate comenzile AT obligatorii;
- validarile de eroare pentru frecventa, putere, rate, mod, sync si payload;
- RX/TX text si hex intre doua module;
- `RSSI`, `LASTPKT`, `STATUS`, `UPTIME`;
- `SLEEP`, `WAKE` si respingerea TX in sleep;
- `AT+RESET` si revenirea la configuratia implicita.
