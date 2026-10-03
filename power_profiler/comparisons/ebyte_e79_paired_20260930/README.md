# Calculele pilotului E79 cu două PPK2

Recalculare la 1 octombrie 2026 a celor **cinci transferuri E79/CH340** capturate la 30 septembrie. Configurație: **32 B, GFSK200 / 200 kbps, +13 dBm, 433,92 MHz, 3,3 V extern la VIN**, ambele PPK2 în modul ampermetru. Firmware E79: `0.3.0`. Toate cele cinci pachete au fost recepționate.

**Calculele sunt încheiate și reproductibile.** Ele păstrează definițiile ferestrelor și limitele datelor. Energia exclusiv RF a recepției nu poate fi identificată riguros din aceste capturi. Auditul fluxului binar TX necesită un diagnostic înainte de acceptarea metrologică finală; verificarea aritmetică nu rezolvă cauza abaterilor contorului. Nu s-au eliminat rulări sau reparat eșantioane.

## Rezultate

Valorile sunt **media ± deviația standard de eșantion, n = 5**. SD descrie variația între transferuri, nu incertitudinea absolută a instrumentului sau a tensiunii. Tensiunea de 3,3 V este confirmată de operator și presupusă constantă; nu a fost înregistrată simultan cu curentul.

| Metrică | TX | RX |
|---|---:|---:|
| Energia ferestrei originale de 4,76 ms | 114,213 ± 1,121 µJ | 116,817 ± 0,142 µJ |
| Aceeași energie, în mJ | 0,114213 ± 0,001121 mJ | 0,116817 ± 0,000142 mJ |
| Puterea medie înaintea transferului | 15,940 ± 0,034 mW | 24,499 ± 0,012 mW |
| Energia totală în intervalul local 0–200 ms | 3230,616 ± 2,914 µJ | 4897,645 ± 3,617 µJ |
| Diferența semnată față de starea anterioară, 0–200 ms | **42,521 ± 6,320 µJ** | **−2,119 ± 5,544 µJ** |

TX era în starea RX-off, iar RX era deja în ascultare. Valoarea RX negativă după scăderea baseline-ului indică o mică diferență de medie față de intervalul de referință; **nu reprezintă energie fizică negativă sau absența recepției**. Aceste date nu separă convingător costul suplimentar RX de variația curentului de ascultare.

Suma bugetelor locale TX și RX pe 200 ms este **8128,261 ± 4,748 µJ**, din care diferența semnată față de cele două stări anterioare este **40,402 ± 11,176 µJ**. SD al sumei este calculat din cele cinci perechi, păstrând covariația. Suma nu descrie două ferestre sincronizate hardware și nu este energie exclusiv RF.

## Definiții și interpretare

Calculul folosește ferestre semi-deschise, la rata nominală de 100 kS/s:

```text
E [µJ] = V [V] × sum(I [µA]) / rata_de_eșantionare [Hz]
baseline = media curentului din intervalul local [−180, −20) ms
ΔE [µJ] = E − V × baseline × durata [s]
```

Diferența nouă este semnată: valorile negative nu sunt trunchiate la zero. Metoda originală `energy_excess_uJ` integrează `max(I − mediana_baseline, 0)`, deci include și contribuția fluctuațiilor pozitive din repaus. Ea se reproduce exact, dar nu se confundă cu diferența nouă: în ferestrele originale, rezultă TX **44,601 µJ** și RX **4,887 µJ** prin metoda originală, față de TX **38,336 µJ** și RX **0,203 µJ** cu baseline mediu și diferență semnată. Valorile originale rămân intacte.

Fereastra TX de **4,76 ms** provine din modelul `(32 + 12) × 8 / 200000 + 0,003` secunde: 1,76 ms pentru payload și overhead modelat, plus 3 ms pentru pornire. Poziția ferestrei maximizează sarcina pozitivă în traseul TX. Durata RF efectivă nu a fost măsurată separat.

Fereastra RX originală **[0, 4,76) ms** începe la marcajul software local și măsoară ascultarea. Apelul de trimitere așteaptă aproximativ 20 ms pentru golirea UART înainte de scrierea comenzii AT, iar excursiile RX din trasee apar mai târziu. Nu folosim maximul de curent sau deplasarea arbitrară a curbelor pentru a inventa începutul și sfârșitul recepției. Canalele logice sunt constante (`255`) și nu furnizează repere RF.

Fereastra complementară **[0, 200) ms** este un buget al intervalului local de observație, incluzând ascultare/repaus, comandă, firmware și activitate radio. Callback-ul host se încheie în cel mult **125,0722 ms** față de marcajele host locale. Această marjă susține alegerea ferestrei, dar nu calibrează întârzierea USB sau ceasurile PPK. Valorile de 100 ms de mai jos sunt verificări de sensibilitate; callback-ul host încă nu s-a închis la 100 ms.

## Sensibilitate

Aceeași medie pretrigger [−180, −20) ms este folosită pentru toate duratele. Nu s-a ales ulterior durata care produce rezultatul dorit.

| Durata intervalului local | ΔE TX medie, µJ | ΔE RX medie, µJ |
|---|---:|---:|
| 100 ms | 39,558 | −0,664 |
| 150 ms | 39,536 | −1,753 |
| **200 ms** | **42,521** | **−2,119** |
| 300 ms | 45,376 | −4,055 |
| 500 ms | 54,460 | −6,481 |

La durata fixă de 200 ms, înlocuirea baseline-ului cu prima sau a doua jumătate a intervalului pretrigger modifică media ΔE TX la **39,841 / 45,201 µJ**, iar RX la **−1,554 / −2,684 µJ**. Dependența de durată și baseline trebuie păstrată în interpretare; ΔE nu este o constantă RF a cipului.

## Verificarea datelor

- Toate cele **10 RAW** sunt citite integral, cu CRC gzip, indici, timpi nominali, valori finite și marcaje verificate. Cele cinci identități de transfer corespund între endpoint-uri. Lungimea fiecărui flux binar este de patru octeți pentru fiecare eșantion decodat.
- Energiile originale se reproduc din RAW. Integrarea complementară a fost verificată separat, fără importarea calculatorului principal; comparația numerică și hashurile sunt în [verification](verification/).
- Verificarea independentă trece **66 de comparații numerice**, cu diferență maximă de **1,21 × 10⁻¹² µJ**. Cele **13 teste** ale noului calculator trec, inclusiv integrarea cu rezultat cunoscut, păstrarea diferențelor negative și respingerea datelor/metadatelor corupte.
- Hashurile celor 23 de fișiere de intrare și ale scriptului sunt în [calculation.json](calculation.json). Raportul nu modifică RAW, rezumatele originale, calculele istorice sau articolul.
- Deficitul nominal de **0,2543%** din TX/rularea 3 este un estimator bazat pe durată și numărul mostrelor. Nu demonstrează pierderea exactă a 248 de mostre. Nu s-a făcut completare, rescalare sau excludere selectivă.

Auditul suplimentar folosește contorul de șase biți definit în [codul Nordic, la o revizie fixă](https://github.com/nordicsemi/pc-nrfconnect-ppk/blob/881d596480f60dea045ad6f3643afdc3f9d5a0a6/src/device/serialDevice.ts). RX are succesiune continuă modulo 64 în toate cele cinci fluxuri. TX are abateri izolate și unele schimbări inițiale de fază. Continuitatea modulo 64 nu detectează pierderile de multipli de 64 de mostre, iar o abatere de contor nu identifică automat o valoare ADC coruptă.

| Rulare TX | Tranziții neconforme ale contorului, întregul flux | Abateri față de faza dominantă, după eșantionul 1000 | Abateri în fereastra TX de 4,76 ms |
|---|---:|---:|---:|
| 1 | 154 | 76 | 0 |
| 2 | 135 | 67 | 0 |
| 3 | 136 | 67 | 1 |
| 4 | 132 | 65 | 2 |
| 5 | 159 | 78 | 0 |

Schimbările persistente de fază sunt înaintea baseline-ului ales. Ca simplă verificare de sensibilitate, interpolarea ipotetică a eșantioanelor cu abateri izolate schimbă ΔE TX pe 200 ms cu cel mult **0,593 µJ** într-o rulare și media cu circa **+0,035 µJ**. **Aceasta nu este o corecție aplicată sau o limită garantată a erorii.** Cauza contorului rămâne de diagnosticat înaintea următoarei campanii; constatarea singură nu justifică refacerea tuturor capturilor.

## Fișiere și reproducere

- [aggregates.csv](aggregates.csv): medii, SD, minime și maxime pentru toate definițiile.
- [legacy_reproduced.csv](legacy_reproduced.csv): ferestrele originale, normalizarea pe bit util și diferența semnată în aceleași ferestre.
- [observations.csv](observations.csv), [paired_budgets.csv](paired_budgets.csv): calcule per transfer și sumele perechilor.
- [baseline_sensitivity.csv](baseline_sensitivity.csv), [baseline_reference_windows.csv](baseline_reference_windows.csv): sensibilitatea la baseline și ferestre de referință fără transfer.
- [diagnostics](diagnostics/): inspecția RX, contorul binar, analiza TX și [figura traseelor](diagnostics/pilot_trace_inspection.pdf).
- [source_pairing.json](source_pairing.json): asocierea fizică verificată, configurația și proveniența tensiunii.

Din rădăcina repository-ului, către un director nou/gol:

```powershell
$pilotSource = 'measurements/raw/sessions/20260930_213239_043901_paired_pilot_radio_ebyte_e79_cc1352p/paired_result/20260930_213239_188258_e79_paired_pilot'
power_profiler/.venv/Scripts/python.exe power_profiler/tools/recalculate_paired_pilot.py $pilotSource --output .tmp/e79-recalculation-check
```

Scriptul folosește biblioteca standard Python și nu accesează hardware. Rezultatele compacte din acest director pot fi urmărite în Git; RAW-urile rămân în `web_sessions`, exclus din Git. Nu s-a făcut publicare în această etapă.

Verificarea separată se poate reproduce cu `verification/calculate_independently.py <directorul_RAW_al_pilotului>`, apoi `verification/compare_independently.py`. Scriptul `diagnostics/reproduce_model_and_signed_window_review.py`, rulat din rădăcina repository-ului, reproduce analiza de sensibilitate TX și scrie doar raportul său diagnostic în directorul local al pilotului.

Pentru articol: TX poate fi prezentat provizoriu numai ca energie a ferestrei modelate, cu observația QA de mai sus; RX poate fi prezentat ca energie de ascultare pe 4,76 ms. Câmpul pentru energia exclusiv RF RX rămâne **neidentificat**, nu zero. Comparația ESP32/CH340 și restul matricei E79 rămân deschise. Calculul acestui pilot nu impune repetarea întregii campanii.
