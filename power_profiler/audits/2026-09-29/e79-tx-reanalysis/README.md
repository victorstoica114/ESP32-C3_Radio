**Historical first screening. All 32 initial review flags are resolved in the [completed reanalysis](../e79-tx-corrected/README.md). The figures and exports have since been updated. This file preserves the earlier screening results.**

**Reanaliză offline E79 prin ESP32 — 29 septembrie 2026**

Au fost citite integral toate cele **630 RAW-uri TX acceptate**: 315 transferuri monocadru și 315 fragmentate. Energia din fereastra originală a fost reprodusă pentru fiecare captură; abaterea absolută maximă este 7,42×10⁻⁸ µJ. Fișierele originale și exporturile publicate nu au fost suprascrise.

| Categorie | Procesate | Trec verificarea automată | Verificare manuală a delimitării |
| --- | ---: | ---: | ---: |
| Monocadru: 8/32/64 B | 315 | 294 | 21 |
| Fragmentat: 128/512/1024 B | 315 | 304 | 11 |
| **Total** | **630** | **598** | **32** |

Cele 294 de controale monocadru acceptate reproduc energia publicată la precizie numerică (diferența relativă maximă absolută sub 7×10⁻¹²%). La cele 304 fragmentate acceptate, diferența mediană este **+5,148%**, cu interval **−0,0043%…+45,990%**. Media unei configurații este emisă numai dacă toate cele cinci repetări trec verificarea: **103/126 configurații**, dintre care **55/63 fragmentate**. Nu eliminăm repetările problematice pentru a obține artificial o medie acceptată.

**Exemple cu toate cele cinci repetări acceptate, GFSK200, +13 dBm:**

| Payload | Energie veche, µJ | Energie recalculată, µJ | Diferență |
| --- | ---: | ---: | ---: |
| 32 B, un cadru | 107,882 | 107,882 | ≈0% |
| 128 B, două cadre | 245,744 | 304,150 | +23,767% |
| 512 B, opt cadre | 857,300 | 1.204,723 | +40,525% |

Sunt medii pe cinci repetări, în aceeași metrică de durată modelată; nu energie a întregii tranzacții cu pauze. Exemplul preliminar GFSK200/+13 dBm/1024 B indica +44–46%, dar două dintre cele cinci repetări sunt marcate pentru verificare manuală. De aceea nu publicăm încă o medie recalculată acceptată pentru această configurație.

**Efectul depinde de PHY.** Intervalele de mai jos folosesc numai repetările fragmentate care trec verificarea, fără a reprezenta intervale de încredere:

| PHY | Repetări acceptate / 45 | Diferență minimă…maximă |
| --- | ---: | ---: |
| SLR2K5 | 45 | −0,0043…+1,7925% |
| SLR5 | 45 | +0,9918…+7,4144% |
| OOK4K8 | 45 | +0,8453…+5,1774% |
| GFSK4K8 | 45 | +1,0924…+8,0265% |
| GFSK50 | 41 | +8,9160…+34,8302% |
| IEEE154G50 | 45 | +9,3328…+36,6238% |
| GFSK200 | 38 | +8,9300…+45,9898% |

Acest rezultat nu justifică aplicarea unui procent unic de corecție și nu se transferă automat la contextul CH9340C.

**Metoda și controalele**

1. Detectorul parcurge RAW-ul complet, folosind medii de 1 ms și prag calculat numai din baseline-ul pretrigger: mediană + maximul dintre 150 µA și `4 × 1,4826 × MAD`. Reunește goluri de cel mult aproximativ 5 ms și cere o lățime minimă de `max(2 ms, 0,4 × durata modelată a cadrului)`. Numărul așteptat de cadre nu este impus detectorului.
2. Numărul observat trebuie să coincidă cu metadatele. Grupurile prea lungi, zgomotul de baseline asemănător unui cadru sau activitatea lângă capătul capturii cer verificare manuală.
3. Fiecărui impuls i se asociază o fereastră de durată modelată, aliniată prin maximizarea sarcinii peste baseline în zona sa. Ferestrele nu se suprapun și nu trec dincolo de mijlocul golului către vecini. Suma duratelor rămâne exact cea din summary, inclusiv distribuirea cuantizării la eșantion.
4. Se repetă detecția la multiplicatori 3 și 5. Count-ul și diagnosticele trebuie să rămână acceptabile, iar energia să varieze cu cel mult 1% față de setarea nominală. Acesta este un criteriu de screening al metodei, nu incertitudinea metrologică a PPK. Variația maximă observată în lotul acceptat este 0,498%.

Ancorele de aproximativ 1 ms nu sunt timestampuri RF. Fereastra folosește modelul airtime existent, inclusiv ramp-ul de 3 ms/cadru; nu pretindem că măsurăm exact durata emisiei RF. Pauzele host dintre cadre sunt excluse din energia recalculată. Energia wake-up/shutdown și energia completă a tranzacției sunt alte cantități.

Rata nominală este 100 kHz, tensiunea 3,3 V. Pierderea PPK declarată este 0…0,294737%; analiza nu recuperează eșantioanele nesalvate. RAW-ul reconstruiește timpul din indice, deci nu oferă localizarea temporală exactă a acestor pierderi. Cel mai mic interval între sfârșitul ultimei ferestre acceptate și sfârșitul RAW este 115,98 ms. Captura TX cu `rx_missing` rămâne în date și nu este înlocuită cu un succes.

**Cazurile marcate nu sunt o listă de recapturi.** Pentru cele 11 fragmentate, verificarea suplimentară a recitit RAW-ul și a confirmat numărul de eșantioane, SHA-256, recepția raportată, rezervă de minimum 138,64 ms după ultimul grup și revenire la baseline în coada capturii. Nu a găsit dovezi de final de transfer lipsă. Ambiguitatea este în separarea zgomotului de impulsuri. Păstrăm `review_required`; nu schimbăm pragul până obținem numărul dorit și nu promovăm automat estimările candidate. Vezi [verificarea cazurilor marcate](flagged-fragmented-review.json).

**Fișiere**

- [runs.json](runs.json): ferestrele efective, diagnostice, sensibilitate, status și SHA-256 pentru fiecare RAW.
- [runs.csv](runs.csv): comparație pe repetare. Valorile candidate cu `quality=review_required` nu sunt rezultate acceptate.
- [aggregates.csv](aggregates.csv): medii/stdev numai pentru configurațiile cu toate cele cinci repetări acceptate.
- [review_required.csv](review_required.csv): cele 32 de cazuri pentru analiză suplimentară; nu coadă de achiziție.
- [summary.json](summary.json) și [verification.json](verification.json): rezumat și verificări de proveniență.
- [sursele originale](../e79-source-check.json) și [duratele modelate](../e79-modeled-frame-durations.csv).

Reproducere din rădăcina repository-ului, numai biblioteca standard Python:


Comanda necesită arhiva RAW locală externă Git în `measurements/raw/archive`, cu manifestele și metadatele originale. Această arhivă nu este inclusă în rapoartele publicate. Directorul `.tmp` primește o reproducere separată.
Scriptul curent folosește detectorul final; comanda produce o reanaliză actuală, nu o reproducere a screeningului istoric păstrat aici.

```powershell
python -B power_profiler/tools/reanalyze_e79_tx.py --workers 1 --output ".tmp/e79-tx-reanalysis-reproduced"
```

Au trecut șapte teste ale detectorului/integrării offline și cele șase teste existente ale integrării. Aplicația de achiziție nu a fost modificată; problema ei de integrare trebuie reparată înainte de o eventuală campanie nouă. Exporturile studiului păstrează valorile istorice; această reanaliză separată documentează corecțiile și limitele necesare înaintea regenerării publicației.
