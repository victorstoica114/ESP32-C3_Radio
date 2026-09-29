**Plan și calcule actualizate — 29 septembrie 2026**

**Pentru hardware rămâne E79 CH9340C, numai TX fragmentat: 63 configurații × 5 repetări = 315 capturi.** Calculul E79 ESP32 este finalizat din RAW-urile existente; celelalte campanii se păstrează cu protocolul și limitele explicite.

| Domeniu | Rezultat / acțiune |
| --- | --- |
| E79 ESP32, 315 TX monocadru | Energia totală și excess au fost reproduse din RAW; valorile originale sunt păstrate exact. |
| E79 ESP32, 315 TX fragmentate | Toate cadrele au fost integrate separat; toate cele 315 trec verificările. Cele 11 marcaje inițiale sunt rezolvate prin regula generală a impulsurilor susținute. |
| E79 ESP32, tabele și grafice | Cele 126 configurații, fiecare cu cinci repetări, sunt regenerate cu proveniență și ferestrele efective. |
| E79 CH9340C, TX fragmentat | Campanie nouă pentru energia ferestrelor tuturor cadrelor. Nu există RAW pentru a o recupera exact din summary. |
| Restul de 2.745 observații packet fără RAW | Păstrate, cu definițiile ferestrelor și rezultatele radio originale. Absența RAW nu impune singură repetarea. |
| RX și ferestre continuous existente | Cifre păstrate; interpretarea ferestrei și a baseline-ului este corectată după sesiune. |

Lista hardware exactă este [plan_e79_ch9340_tx.csv](plan_e79_ch9340_tx.csv): payload 128/512/1024 B, șapte PHY, puteri −20/0/+13 dBm, cinci repetări, 3,3 V. Integrarea aplicației este corectată, iar campania nouă trebuie să salveze RAW. Verificarea unui prim punct din matrice confirmă protocolul pe hardware înaintea continuării. Nu sunt incluse RX sau celelalte module în această campanie.

**Rezultate concrete ale recalculării:** GFSK200, +13 dBm, 512 B crește de la 857,300 la 1.204,723 µJ (+40,525%); 1024 B crește de la 1.660,322 la 2.410,810 µJ (+45,201%). La 8/32/64 B valorile sunt identice. Nu folosim aceste procente pentru CH9340C: sunt contexte de măsurare diferite.

[Raportul complet al celor 630 capturi](e79-tx-corrected/README.md) include formulele, ferestrele, sensibilitatea și proveniența. Toate cele 315 fragmentate trec verificările la 3/4/5 × MAD; variația maximă a energiei totale între praguri este 0,002735%. Acesta este un control al segmentării, nu incertitudinea PPK. Pierderea de eșantioane raportată rămâne o limită a măsurătorilor originale.

Energia corectată este suma ferestrelor modelate ale tuturor cadrelor. Pauzele host sunt excluse; ea nu reprezintă automat energia întregii tranzacții cu pornire, oprire și toate pauzele. RX modern rămâne energie pe fereastra definită, nu o măsurare nouă sincronizată cu RF. Baseline-ul este identificat după campanie: vechile CC1101 activau RX în trigger, iar campaniile moderne înaintea capturii. Detalii: [verificarea RX/continuous](rx-interpretation-review.md).

**De ce nu refacem 765 sau 3.060 de capturi:** cele 450 RX incluse în propunerea conservatoare rămân observații utilizabile ale ferestrelor istorice. Cele 2.745 observații packet fără RAW, în afara TX fragmentat CH9340C, nu au o necesitate demonstrată de refacere pentru metrica declarată. Cele 27 de ferestre continuous istorice fără RAW păstrează summary-uri coerente. Pierderile radio autentice, inclusiv `rx_missing` și `no_rx_data`, nu sunt înlocuite cu repetări selectate până la succes.

Lista veche de 765 și extensia RX de 720 sunt istorice, marcate `superseded_not_a_capture_queue`. [Inventarul fișierelor](README.md) rămâne disponibil. Nicio captură hardware nouă nu a fost executată în această reanaliză.
