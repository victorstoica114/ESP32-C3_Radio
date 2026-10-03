# Ebyte E32-868T30D — punct de referință la 5 V

**5/5 perechi TX/RX, 10 capturi**, 1 încercare/încercări.
32 B, 19.2 kbps, +30 dBm, channel 6; frecvență 868 MHz.
PPK în serie numai cu radioul, cu decodare și calcul la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul convenit la 5 V; operatorul a
confirmat conectarea după instrucțiunea de alimentare. Nu a fost măsurată independent.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, evenimentul principal detectat în curent | 185.529516 ± 0.060293 | 58.004 | 639.713101 |
| RX, ascultare în fereastră modelată | 6.745364 ± 0.017769 | 64.000 | 21.079262 |

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
`measurements/raw/sessions/20261003_155452_233651_paired_reference_radio_ebyte_e32_868t30d/reference_result/`.

Frecvența nominală de 868 MHz este dedusă din canalul 6 citit din ambele
module și formula `862 + CHAN` din [manualul Ebyte, secțiunea 7.5](https://manualzz.com/doc/69984414/ebyte-e32-868t20d-user-manual).
Frecvența RF nu a fost măsurată independent. Configurația citită înainte de
pregătirea lotului avea canalul 23; noile capturi folosesc explicit canalul 6.
