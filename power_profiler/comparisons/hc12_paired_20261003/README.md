# HC-12 — punct de referință la 5 V

**5/5 perechi TX/RX, 10 capturi**, 1 încercare/încercări.
32 B, FU1 (250 kbps preset), +20 dBm, channel 10; frecvență nominală 437,0 MHz.
PPK în serie numai cu radioul, cu decodare și calcul la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul convenit la 5 V; operatorul a
confirmat conectarea după instrucțiunea de alimentare. Nu a fost măsurată independent.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, evenimentul principal detectat în curent | 7.643791 ± 0.017607 | 58.612 | 26.082870 |
| RX, ascultare în fereastră modelată | 0.422870 ± 0.089286 | 21.020 | 4.023497 |

TX folosește evenimentul cu cea mai mare sarcină peste curentul de repaus,
conform definiției istorice. Nu este energia întregii tranzacții UART–RF.
RX nu este energia exclusivă a recepției RF; fereastra începe la triggerul
hostului, pe ceasul propriu al PPK. Ceasurile PPK nu sunt sincronizate hardware.
SD folosește cinci repetări și numitorul n−1. În CSV, câmpul istoric
`tx_mean_uA` reprezintă curentul mediu pentru rolul indicat pe rând.

Au fost trimiși 30 octeți ASCII plus
2 octeți adăugați de firmware. Fiecare payload a
fost primit exact o dată. Confirmarea TX: UART write/flush and exact RX payload; transparent modem has no per-packet TX acknowledgment.
Modemul transparent nu dovedește numărul cadrelor PHY interne.

Toate fluxurile WIRE au trecut verificarea formatului, continuitatea modulo-64
și replay-ul independent al conversiei, cu diferență de cel mult 0,000001 µA.
Modulo-64 nu poate exclude pierderi de multipli de 64 de eșantioane. Hashurile
celor 20 de fișiere RAW/WIRE au fost reverificate după lot. Controalele
intenționate de asociere rămân local. Acest punct înlocuiește doar condiția
de 32 B convenită, fără a valida alte curbe istorice sau fiabilitatea RF.

[Agregate CSV](aggregates.csv) · [Rezumat](summary.json) · [Manifest surse](source_manifest.json).
Capturile rămân locale, excluse din Git, în
`measurements/raw/sessions/20261003_161045_338790_paired_reference_radio_hc12/reference_result/`.

Configurația fizică a fost verificată separat pe ambele module: `OK+B9600`,
`OK+FU1`, `OK+RP:+20dBm` și `OK+RC010`. `AT+CFG?` descrie configurația memorată
de ESP32; valoarea afișată de 437,4 MHz are un decalaj de +0,4 MHz în formula
firmware-ului. Canalul 10 citit din module corespunde nominal la 437,0 MHz:
`433,4 + (10 − 1) × 0,4`, conform
[manualului producătorului HC-12](https://www.hc01.com/downloads/HC-12%20english%20datasheets.pdf).
Frecvența RF nu a fost măsurată independent. Răspunsurile originale sunt păstrate
în raport, iar firmware-ul încărcat nu a fost schimbat.

Fereastra RX de 21,020 ms păstrează modelul istoric. Durata medie TX detectată
în curent este 58,612 ms; fereastra RX nu delimitează acest eveniment TX sau
pachetul recepționat. Energia RX se folosește numai cu această definiție.

Asocierea verificată prin sleep/wake: TX COM46 → PPK COM11;
RX COM47 → PPK COM10. Vârful maxim TX este 61,574 mA.
