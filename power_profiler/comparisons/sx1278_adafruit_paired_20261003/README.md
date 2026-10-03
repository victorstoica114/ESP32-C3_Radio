# SX1278, placă tip Adafruit cu level shifter — punct de referință la 5 V

**5/5 perechi TX/RX, 10 capturi**, 1 încercare/încercări.
32 B, level shifter, SF7/BW125/CR4/5, +20 dBm; frecvență configurată 433 MHz,
preambul de 8 simboluri, CRC activ și header explicit.
PPK în serie numai cu radioul, cu decodare și calcul la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul convenit la 5 V; operatorul a
confirmat conectarea după instrucțiunea de alimentare. Nu a fost măsurată independent.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, evenimentul principal detectat în curent | 21.564301 ± 0.049412 | 72.526 | 59.466394 |
| RX, ascultare în fereastră modelată | 4.207520 ± 0.006593 | 71.930 | 11.698931 |

TX folosește evenimentul cu cea mai mare sarcină peste curentul de repaus,
conform definiției istorice. Nu este energia întregii tranzacții UART–RF.
RX nu este energia exclusivă a recepției RF; fereastra începe la triggerul
hostului, pe ceasul propriu al PPK. Ceasurile PPK nu sunt sincronizate hardware.
SD folosește cinci repetări și numitorul n−1. În CSV, câmpul istoric
`tx_mean_uA` reprezintă curentul mediu pentru rolul indicat pe rând.

Au fost trimiși 32 octeți ASCII plus
0 octeți adăugați de firmware. Fiecare payload a
fost primit exact o dată, împreună cu o singură confirmare `[SX1278] TX OK`
pentru fiecare transfer. Firmware-ul comunică prin SPI cu radioul.

Toate fluxurile WIRE au trecut verificarea formatului, continuitatea modulo-64
și replay-ul independent al conversiei, cu diferență de cel mult 0,000001 µA.
Modulo-64 nu poate exclude pierderi de multipli de 64 de eșantioane. Hashurile
celor 20 de fișiere RAW/WIRE au fost reverificate după lot. Controalele
intenționate de asociere rămân local. Acest punct înlocuiește doar condiția
de 32 B convenită, fără a valida alte curbe istorice sau fiabilitatea RF.

[Agregate CSV](aggregates.csv) · [Rezumat](summary.json) · [Manifest surse](source_manifest.json).
Capturile rămân locale, excluse din Git, în
`measurements/raw/sessions/20261003_161631_880029_paired_reference_radio_sx1278_adafruit_level_shifter/reference_result/`.

Asocierea verificată prin standby/RX: TX COM48 → PPK COM11;
RX COM49 → PPK COM10. TX rămâne în standby între pachete; RX în ascultare.
Vârful maxim TX este 70,956 mA. Configurația raportată are gain 1, sync 0x14,
IQ normal și FHSS oprit pe ambele radiouri. Frecvența și puterea RF nu au fost
măsurate independent; valorile de 433 MHz și +20 dBm sunt setările firmware-ului.

Modelul estimează 71,936 ms pentru 32 B; integrarea discretă RX are 71,930 ms.
Evenimentul TX detectat în curent are în medie 72,526 ms. Energia RX descrie
fereastra modelată începând la triggerul hostului, fără marcaj RF local.
