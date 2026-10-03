# Ebyte E32-433T20D — punct de referință la 5 V

**5/5 perechi TX/RX, 10 capturi**, 1 încercare/încercări.
32 B, 19.2 kbps, +20 dBm; frecvență 433 MHz.
PPK în serie numai cu radioul, cu decodare și calcul la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul convenit la 5 V; operatorul a
confirmat conectarea după instrucțiunea de alimentare. Nu a fost măsurată independent.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, evenimentul principal detectat în curent | 25.481412 ± 0.080554 | 53.050 | 96.065646 |
| RX, ascultare în fereastră modelată | 5.372608 ± 0.010616 | 64.000 | 16.789401 |

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
`measurements/raw/sessions/20261003_151950_038736_paired_reference_radio_ebyte_e32_433t20d/reference_result/`.
