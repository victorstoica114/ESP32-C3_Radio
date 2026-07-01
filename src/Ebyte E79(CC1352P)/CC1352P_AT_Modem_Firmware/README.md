# E79 AT modem firmware

Firmware pentru Ebyte E79-400DM2005S / TI CC1352P. Modulul ruleaza firmware propriu pe CC1352P si expune catre ESP32 un modem radio UART cu comenzi AT.

## Hardware

- UART: 115200 8N1, CC1352P `DIO12` = RX, `DIO13` = TX.
- Logica: 3.3 V, nu 5 V TTL.
- Programare: JTAG/cJTAG cu J-Link, device `CC1352P1F3`.
- RF switch E79: TX = `DIO5=1,DIO6=0`, RX = `DIO5=0,DIO6=1`, standby = ambele 0.

## RF

- Baza TI: Proprietary RF / 2-GFSK 50 kbps 433 MHz, generata din `CC1352P_4_LAUNCHXL`.
- Frecventa implicita: `433920000` Hz.
- Sync word implicit: `0x930B51DE`.
- Configuratia este RAM-only in aceasta versiune; nu se scrie in flash/NVS.
- `AT+DEFAULT` revine la RX off. Este varianta mai sigura pentru integrarea cu ESP32: modulul nu incepe sa livreze pachete nesolicitate dupa reset.

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
- `PWR`: `-20,-15,-10,-5,0,1,2,3,4,5,6,7,8,9,10,11,12,13` dBm. Valoarea de 14 dBm din tabelul TI nu este expusa in V1 deoarece cere configurare speciala `CCFG_FORCE_VDDR_HH=1`.
- `SYNC`: hex 1..8 cifre, cu sau fara prefix `0x`.
- `ADDR`: N/A in V1; PHY-ul generat ruleaza fara address check.
- `CHAN`: N/A in V1; se foloseste frecventa explicita prin `AT+FREQ`.
- Payload TX: maxim 64 octeti.

Toate erorile incep cu `#ERROR:` si se termina cu CRLF. Raspunsul simplu de succes este `OK\r\n`.

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

Rezultate:

```text
firmware\e79_at_modem\gcc\e79_at_modem.hex
firmware\e79_at_modem\gcc\e79_at_modem.bin
```

## Flash

Conecteaza J-Link la alimentare 3.3 V, GND, RESET, TCKC si TMSC. Apoi ruleaza task-ul:

```text
CC1352P: Flash E79 AT modem
```

Sau din PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem.ps1
```

## Flash prin USB-UART / ROM bootloader

Firmware-ul activeaza ROM serial bootloader backdoor pe `DIO15`, activ low. Pe schema E79, acesta este pinul `BOOT` cu pull-up si buton la GND.

Comportament important:

- ROM serial bootloader-ul exista in CC1352P din fabrica; nu este o componenta pe care o scriem noi in flash.
- Daca modulul nu are imagine valida in flash, ROM-ul poate porni serial bootloader-ul, cu conditia ca starea CCFG sa permita bootloader-ul.
- Dupa ce exista o imagine valida in flash, `BOOT` + `RESET` functioneaza doar daca imaginea curenta a configurat CCFG cu backdoor activ.
- Pentru development, imaginea aceasta seteaza `BL_CONFIG` pentru `BOOT/DIO15` active-low. Valoarea asteptata este `0xC5FE0FC5`.
- Un modul testat cu imagine valida, dar fara backdoor, a avut `BL_CONFIG = 0xC5FFFFFF`: bootloader enabled, backdoor disabled, pin BOOT neselectat. In acea stare UART SBL nu raspunde la `0x55 0x55`.

Conectare USB-UART 3.3 V:

- USB-UART TX -> E79 `DIO12/RX`
- USB-UART RX -> E79 `DIO13/TX`
- GND comun
- alimentare 3.3 V stabila pentru modul

Intrare in bootloader:

1. Tine `BOOT` apasat, adica `DIO15` low.
2. Apasa si elibereaza `RESET`.
3. Porneste scriptul de flash. Poti elibera `BOOT` dupa ce incepe sincronizarea.

Din PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem-uart.ps1 -Port COM5
```

Scriptul foloseste o copie locala a `ti-python-sbl.py` cu `--no-invoke-bootloader`, device `CC13X2`, baud implicit `115200`, erase + write + verify. Se foloseste imaginea raw `e79_at_modem.bin`, ca sa nu depindem de pachetul Python `intelhex`.

Prin ESP32-C3 bridge pe schema curenta:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-e79-at-modem-via-esp32.ps1 -Port COM22
```

In acest mod ESP32 este doar bridge USB CDC -> UART. Scriptul seteaza UART-ul bridge-ului la `115200`, apoi asteapta resetul manual al CC1352P cu `BOOT/DIO15` tinut low. Varianta validata pe modulul de test a terminat cu verify CRC OK (`0x4ef75cf7`).

Pentru proba non-distructiva a bootloaderului prin ESP32 bridge:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\probe-e79-bootloader-via-esp32.ps1 -Port COM22
```

Pentru productie, backdoor-ul permite unui host extern sa citeasca/stearga flash-ul daca are acces fizic la pini. Este convenabil pentru development, dar trebuie reevaluat inainte de firmware final blocat.

## Test cu doua module

1. Pe ambele module: `AT`, apoi `AT+CFG?`.
2. Pe ambele module: `AT+DEFAULT`.
3. Pe ambele module seteaza aceeasi frecventa, de exemplu `AT+FREQ=433920000`.
4. Pe modulul A: `AT+RX=ON`.
5. Pe modulul B: `AT+SEND=hello`.
6. Pe modulul A verifica linia `+RX:5,<rssi>,hello`.
7. Pe modulul A: `AT+RSSI?` si `AT+LASTPKT?`.
8. Test sleep: pe modulul B `AT+SLEEP`, apoi `AT+SEND=test` trebuie sa raspunda `#ERROR: RADIO_SLEEPING (send AT+WAKE)`.
9. Pe modulul B: `AT+WAKE`, apoi `AT+SEND=test`.
