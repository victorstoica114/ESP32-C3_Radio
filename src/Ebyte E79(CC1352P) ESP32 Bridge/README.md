# ESP32 bridge pentru Ebyte E79 / CC1352P

Acest folder contine firmware-ul ESP32-C3 care face bridge USB CDC <-> UART catre firmware-ul AT rulat pe CC1352P.

Selectie in `src/main.cpp`:

```cpp
#define RADIO_MODULE  RADIO_EBYTE_E79_CC1352P
#define RADIO_PROGRAM BRIDGE
```

Functii incluse:

- UART bridge pe ESP32 `GPIO20` RX si `GPIO21` TX.
- Comenzi locale ESP32:
  - `~CC1352P_BAUD=<baud>`
  - `~CC1352P_RESET`
- OLED SSD1306 pe `SDA=5`, `SCL=6`, afisaj simplu `EBYTE` / `E79`.
- LED heartbeat 1 Hz pe `GPIO8`.

Nota hardware: pe placa testata, resetul CC1352P prin ESP32 `GPIO10` nu produce reset valid. Pastrez comanda in firmware pentru revizia hardware urmatoare, unde `RESET_N` va fi controlat corect.

Pentru build direct in proiectul `CC1352P`, sursa originala este in:

```text
D:\Documente\CC1352P\firmware\esp32_cc1352_bridge
```
