# Ebyte E32-433T33D — punct de referință la 5 V

La 3 octombrie, operatorul a confirmat păstrarea ambelor loturi complete.
RAW/WIRE rămân locale, iar rezultatele și observațiile de mai jos se păstrează.

**Energia TX este provizorie:** vârful observat este 997,218 mA, la numai
2,782 mA de limita nominală de 1 A. Nu apar coduri ADC de capăt de scară
sau eșantioane ≥1 A, dar asta nu validează comportamentul analogic la limită.
[Auditul intervalului de curent](current_range_audit.json).

**5/5 perechi TX/RX, 10 capturi**, 1 încercare/încercări.
32 B, 19.2 kbps, +30 dBm; frecvență 433 MHz.
PPK în serie numai cu radioul, cu decodare și calcul la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul convenit la 5 V; operatorul a
confirmat conectarea după instrucțiunea de alimentare. Nu a fost măsurată independent.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, evenimentul principal detectat în curent | 290.728382 ± 0.142834 | 62.076 | 936.685408 |
| RX, ascultare în fereastră modelată | 12.371367 ± 0.317659 | 64.000 | 38.660520 |

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
`measurements/raw/sessions/20261003_152942_859662_paired_reference_radio_ebyte_e32_433t33d/reference_result/`.
