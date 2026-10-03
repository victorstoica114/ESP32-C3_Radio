# Verificarea independentă a campaniei E79 CH340 — 30 septembrie 2026

**Cele 315 capturi sunt complete și reproducibile din RAW. Montajul final este CH340, nu CH9340C.** Datele pot fi folosite ca serie TX distinctă pentru E79, fără a înlocui observațiile istorice CH9340C sau a impune automat alte capturi.

[Suplimentul CH340](../../comparisons/ebyte_e79_ch340_20260929/README.md) include cele 63 de agregate, toate cele 315 repetări, XLSX și graficele comparative cu ESP32. [Studiul PDF](../../study/radio_module_energy_study.pdf) include o secțiune distinctă pentru această campanie; inventarul principal de 28 de variante și datele istorice rămân neschimbate.

Codul și indexul campaniei au fost preluate din commit-ul `37599a2a5394de9aa3a84432e578dbcaadfd6da2`. Verificarea de aici este offline: nu au fost deschise porturi seriale, încărcate firmware-uri sau executate măsurători noi.

## Proveniență și integritate

[Arhiva publicată](https://github.com/victorstoica114/ESP32-C3_Radio/releases/download/e79-ch340-tx-recapture-20260929/e79_ch340_tx_recapture_20260929_full_session.zip) are exact **766.800.352 bytes** și SHA-256 `fe09b18b6332ba34362133ab4ca97297633f2f786a21d0af6377544787e6068a`. Cele **1.109 fișiere** din manifest au dimensiunile și hash-urile declarate; CRC-ul ZIP a fost verificat pentru fiecare intrare. Singurul fișier suplimentar față de manifest este manifestul însuși. [Dovada integrală](release-integrity.json) păstrează și căile locale de verificare, care nu sunt destinații portabile pentru descărcare.

Selecția acceptată conține două loturi complete, păstrate separat de tentativele diagnostice:

| Lot | Capturi | `ok` | `rx_missing` |
| --- | ---: | ---: | ---: |
| `lot45_gfsk200_consensus/20260929_185646_radio_ebyte_e79_cc1352p` | 45 | 37 | 8 |
| `lot270_other_profiles_final_candidate2/20260929_193856_radio_ebyte_e79_cc1352p` | 270 | 208 | 62 |
| Total | **315** | **245** | **70** |

Cele 70 de pierderi sunt observații păstrate, nu capturi înlocuite până la succes. Raportul dintre ele și total este **22,22% transferuri logice nerecepționate complet**, nu rata pierderilor cadrelor RF individuale și nici o măsurare izolată a sensibilității radioului.

## Ce a fost verificat din RAW

[Rezumatul numeric](ch340-verification-summary.json), [tabelul pe capturi](ch340-verification-runs.csv) și [diagnosticele complete](ch340-verification-runs.json) consemnează:

- Matrice exactă: 7 PHY × 3 puteri × 3 payload-uri × 5 repetări, 3,3 V, 100 kS/s, UART 1 Mbaud.
- Toate cele 315 gzip-uri citite integral, cu CRC, indici de eșantion, valori finite, un trigger și număr de eșantioane conforme: **55.967.744 eșantioane**.
- Ferestre distincte de 2/8/16 cadre, durate conforme modelului și baseline reprodus din pretrigger.
- Energia totală și excess reproduse direct din ferestrele arhivate, fără diferență numerică observată.
- Reanaliza cu algoritmul din `37599a2` acceptă toate cele 315 și reproduce exact toate ferestrele. Diferența maximă relativă de energie față de arhivă este sub `7,1e-11%`, la nivelul aritmeticii în virgulă mobilă.
- Pierdere maximă de eșantioane raportată: **0,833684%**. Eșantioanele lipsă nu au fost reconstruite; verificarea aritmetică nu elimină această limită de măsurare.

Comanda reproductibilă, după descărcarea și extragerea arhivei:

```powershell
python -B power_profiler/tools/verify_e79_ch340_release.py --session '<radacina-sesiunii-extrase>' --output '<director-separat-de-verificare>'
```

## Regula de detecție și examinarea excepțiilor

Formula de integrare a rămas suma ferestrelor modelate, dar politica de acceptare s-a schimbat față de auditul ESP32 din 29 septembrie: bin-uri adaptive de 1–2 ms, 4 MAD confirmat de cel puțin unul dintre 3/5 MAD și două intervale alternative de praguri. Eticheta `per_frame_modeled_airtime_v1` singură nu identifică această schimbare; commit-ul și hash-urile codului din dovadă trebuie păstrate.

**312 capturi** folosesc regula principală. Pentru celelalte trei au fost examinate și imaginile de inspecție din arhivă:

- `run_00009`, GFSK4K8, −20 dBm, 512 B: intervalul 2/2,25/2,5/2,75 MAD găsește opt cadre; la pragul principal o fereastră nu încape în regiunea delimitată de impulsurile vecine.
- `run_00012`, GFSK4K8, −20 dBm, 1024 B: pragurile 4/3/5 MAD găsesc 12/16/8 grupuri; toate cele patru praguri joase găsesc 16. Trasarea arată cele 16 platouri, separate de intervale de repaus, acoperite de ferestre.
- `run_00264`, IEEE154G50, +13 dBm, 512 B: regula principală respinge zgomotul pretrigger asemănător unui cadru; 4,5/5/5,5 MAD sunt conforme. Cele opt platouri posttrigger sunt vizibile și acoperite de ferestre; nu s-a identificat un al nouălea cadru RF omis în această captură.

Inspecția este un control al segmentării pe curent, fără un semnal RF de referință sincronizat. Toleranța de consens de 1% nu este incertitudinea PPK2.

## Limitele comparării cu seriile istorice

[Notele originale de banc](BENCH_NOTES.md) documentează două modificări de context: ambele adaptoare au devenit CH340, iar DUT-ul măsurat a fost schimbat din COM4/PPK COM12 în **COM16/PPK COM13**, cu COM4 ca receptor. Metadatele ambelor loturi acceptate confirmă configurația finală. Alegerea celui de-al doilea lanț s-a făcut pentru baseline mai curat. Au existat și iterații ale detectorului pe tentative păstrate separat.

Prin urmare, comparația cu ESP32 descrie două contexte experimentale. Nu izolează efectul adaptorului și nu măsoară consumul propriu al adaptorului USB. Seria CH340 nu furnizează măsurători de 8/32/64 B, RX sau continuous, iar o serie completă nu trebuie fabricată prin combinarea ei cu CH9340C.

O [regresie separată pe cele 315 RAW ESP32 fragmentate](esp32-detector-regression-summary.json) confirmă că toate rămân valide și trec toate pragurile 3/4/5 MAD. 294 ferestre sunt identice; 21 cazuri SLR2K5 de 512/1024 B se modifică puțin cu bin-urile adaptive: diferență maximă totală **0,001543018%**, maximum **1,093746 µJ**, și excess **0,002665103%**. O margine de fereastră se poate deplasa până la 9,07 ms. [Tabelul complet](esp32-detector-regression.csv) și [cazurile diferite](esp32-detector-regression-differences.json) păstrează rezultatele; exporturile ESP32 publicate nu au fost suprascrise.

Energia rămâne suma ferestrelor modelate ale cadrelor, excluzând pauzele host. Nu reprezintă energia întregii tranzacții.

## Observații de cod pentru achiziții viitoare

Cele **152 de teste existente trec**, dar revizuirea a identificat două limite care nu invalidează fișierele complete deja verificate:

1. Regula alternativă de prag superior din `frame_windows.py` poate accepta și un număr ambiguu de impulsuri: o probă sintetică cu trei impulsuri la 3/4 MAD și două la 4,5/5/5,5 MAD este acceptată pentru două cadre. Această situație nu este cazul capturii `run_00264`, examinată mai sus. Acceptarea unui viitor caz similar necesită păstrarea și examinarea diagnosticului.
2. În `ppk.py`, o excepție la repornirea eșantionării din `finally` poate împiedica returnarea unei capturi deja decodate către runner, înainte de salvarea RAW. Cazul a fost reprodus cu API simulat. Datele prezente în arhiva verificată nu sunt afectate retroactiv.

Aceste constatări nu justifică repetarea celor 315 capturi complete. Orice schimbare viitoare a detectorului trebuie însoțită de regresia pe RAW și de identificarea explicită a versiunii politicii de acceptare.
