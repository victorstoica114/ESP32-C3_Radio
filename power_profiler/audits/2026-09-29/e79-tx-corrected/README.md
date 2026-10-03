**E79 ESP32: calcule finalizate — 29 septembrie 2026**

Toate cele **630 capturi TX** au fost procesate din RAW. Cele **315 monocadru** păstrează exact valorile originale, după reproducerea energiei totale și excess din eșantioane. Pentru cele **315 fragmentate** au fost validate și integrate separat toate cadrele. **Nu mai există cazuri `review_required` în acest lot.** Cele 32 de marcaje ale screeningului inițial sunt rezolvate; rezultatele istorice ale screeningului rămân în `../e79-tx-reanalysis` pentru trasabilitate.

Regula generală a detectorului cere minimum două bin-uri consecutive de 1 ms peste prag. Un vârf izolat nu poate crea sau prelungi un impuls. Pragul se calibrează din baseline, iar numărul de cadre este verificat după detecție; nu selectăm artificial cele mai puternice N grupuri. Aceeași regulă este folosită în aplicația de achiziție și în reanaliza offline.

La 3/4/5 × MAD toate cele 315 transferuri fragmentate păstrează numărul corect de cadre și ferestre valide. Variația maximă a energiei totale între praguri este **0,002735%**. Acesta este un test de sensibilitate al segmentării, nu incertitudinea metrologică a PPK2.

| GFSK200, +13 dBm | Energie originală, µJ | Energie recalculată, µJ | Diferență |
| --- | ---: | ---: | ---: |
| 8 B | 75,653 | 75,653 | 0% |
| 32 B | 107,882 | 107,882 | 0% |
| 64 B | 151,541 | 151,541 | 0% |
| 128 B | 245,744 | 304,150 | +23,767% |
| 512 B | 857,300 | 1.204,723 | +40,525% |
| 1024 B | 1.660,322 | 2.410,810 | +45,201% |

Sunt medii pe cinci repetări pentru fiecare configurație. În întreg lotul fragmentat, diferența mediană pe repetare este +5,386%; intervalul este −0,002145%…+45,990%. Efectul este mult mai mic în modurile lente decât în cele rapide. Nu aplicăm un factor de corecție unic și nu transferăm rezultatele ESP32 la CH9340C.

**Ce măsoară energia corectată:** suma ferestrelor modelate ale tuturor cadrelor, aliniate pe impulsurile de curent, fără pauzele host dintre cadre. Suma duratelor este păstrată la eșantion față de analiza istorică. Modelul include ramp-ul configurat de 3 ms/cadru. Nu este o măsurare sincronizată a airtime-ului RF și nu include automat startup/shutdown sau energia întregii tranzacții cu toate pauzele.

Au fost parcurse 85.969.920 de eșantioane. Energia din fereastra istorică este reprodusă pentru toate cele 630 de RAW-uri; abaterea absolută maximă este 7,42×10⁻⁸ µJ. Rata nominală este 100 kHz, alimentarea 3,3 V. Pierderea PPK raportată, de până la 0,294737%, rămâne o limită a achiziției; reanaliza nu recreează eșantioanele lipsă. Se păstrează și captura cu `rx_missing`; nu înlocuim o pierdere radio cu o repetare reușită.

**Fișiere și reproducere**

- `runs.json`: date pe repetare, ferestre, praguri, sensibilitate, SHA-256 și rândul summary corectat.
- `runs.csv`: comparația original–recalculat pe repetare.
- `aggregates.csv`: toate cele 126 de configurații, fiecare cu cinci repetări.
- `summary.json`: rezultatul complet al calculului.
- `verification.json`: verificare independentă de proveniență și concordanță cu integrarea aplicației.


Comanda necesită arhiva RAW locală externă Git în `measurements/raw/archive`, cu manifestele și metadatele originale. Această arhivă nu este inclusă în rapoartele publicate. Directorul `.tmp` primește o reproducere separată.

```powershell
python -B power_profiler/tools/reanalyze_e79_tx.py --workers 1 --output ".tmp/e79-tx-corrected-reproduced"
python -B power_profiler/tools/publish_e79_reanalysis.py --help
```

Sursa RAW, summary-urile și metadatele experimentale originale sunt păstrate în arhiva importată. Exporturile curente E79 din `power_profiler/comparisons/ebyte_e79_400dm2005s` sunt regenerate separat, cu rezultate derivate și proveniență. Datele RX/continuous păstrează cifrele originale; descrierea ferestrei și a baseline-ului este corectată. E79 CH9340C, TX fragmentat, rămâne în așteptarea campaniei noi.

În summary-ul corectat, `event_duration_ms` este suma ferestrelor, iar `event_start_ms` indică începutul primei ferestre. Sfârșitul ultimului cadru se citește din `integration_windows_ms`, nu din suma acestor două câmpuri. Rata derivată `effective_payload_rate_kbps` folosește durata integrată și nu reprezintă goodput-ul întregii tranzacții cu pauze.

Au trecut **140 de teste** ale aplicației, integrării și exportului. Verificarea independentă confirmă toate cele 630 de SHA-256 RAW, 315 rezultate monocadru păstrate exact, 126 agregate complete și concordanța numerică dintre calculul offline și integrarea aplicației. Studiul și cele 27 de planșe au fost regenerate; PDF-ul manuscrisului este recompilat din datele actualizate.
