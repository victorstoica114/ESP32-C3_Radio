# Ebyte E22-400M30S — punct de referință la 5 V

Încheiat la 3 octombrie 2026: **5/5 perechi TX/RX, 10 capturi**, din prima
încercare. Payload de 32 B, 433 MHz, SF7/BW125/CR4/5, preambul de 8 simboluri,
CRC activ, +18 dBm înaintea PA. Puterea RF radiată nu a fost măsurată.

PPK2 în serie numai cu E22, ampermetru și decodare la 5000 mV.
Tensiunea fizică este cea prevăzută în montajul de 5 V confirmat prin continuarea
operatorului după instrucțiunea de conectare; nu a fost înregistrată independent.
Asocierea a fost verificată prin variația curentului la activarea RX:
COM34 → PPK COM10 și COM35 → PPK COM11.

| Rol | Energie medie ± SD (mJ) | Durată medie (ms) | Curent mediu (mA) |
|---|---:|---:|---:|
| TX, eveniment detectat în curent | 21.180750 ± 0.004169 | 72.660 | 58.300995 |
| RX, ascultare în fereastră modelată | 1.938597 ± 0.007227 | 71.930 | 5.390231 |

RX nu reprezintă energia exclusivă a recepției RF. Fereastra începe la triggerul
hostului, pe ceasul propriu al PPK. Cele două ceasuri nu sunt sincronizate hardware.
SD folosește cinci repetări și numitorul n−1. Numele istoric `tx_mean_uA` din CSV
înseamnă curentul mediu al ferestrei pentru rolul indicat pe rând.

Fiecare payload a fost primit exact o dată, cu confirmare TX. Toate fluxurile
WIRE au trecut continuitatea modulo-64, verificarea formatului și replay-ul
independent al conversiei; curentul recalculat diferă cu cel mult 0,000001 µA.
Continuitatea modulo-64 nu poate exclude pierderi de multipli de 64 de eșantioane.
Hashurile celor 20 de fișiere RAW/WIRE acceptate au fost reverificate după lot.
Au trecut 436 de teste software. Controalele intenționate de asociere rămân local.

Acest punct înlocuiește numai condiția de 32 B convenită, fără a valida celelalte
curbe istorice și fără a estima fiabilitatea legăturii RF dintr-un lot acceptat.

[Agregate CSV](aggregates.csv) · [Rezumat](summary.json) · [Manifest surse](source_manifest.json).
Capturile sunt locale și excluse din Git, în
`measurements/raw/sessions/20261003_145111_308226_paired_reference_radio_ebyte_e22_sx1268/reference_result/`.
