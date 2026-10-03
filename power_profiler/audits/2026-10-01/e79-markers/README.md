# E79: marcaje proprii TX și RX pe DIO17 pentru două PPK2

**Campania E79 pentru 8/32/64 B s-a încheiat la 1 octombrie 2026, 14:42:55.**
Pornită de la zero la 14:10:51, a validat **315/315 perechi, 63/63 loturi**,
fără loturi eșuate sau repetate, în 32 min 4 s.
[Manifestul sesiunii](../../../../measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/manifest.json)
documentează validarea. [Agregatele CSV](../../../../measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/analysis/aggregates.csv)
și [rezumatul complet](../../../../measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/analysis/summary.json)
includ mediile, abaterile standard și hashurile surselor.
[Auditul independent final](../../../../measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/diagnostics/full-campaign-independent-audit.json)
validează **630/630 capturi**, fără erori sau duplicate; energia, durata și
conversia ADC coincid exact cu rezultatele salvate.
Configurație: **TX COM16 → PPK COM10 (`E753C4E81F3D`)**, **RX COM15 →
PPK COM11 (`CD2D332DB09A`)**, sursă externă de **3,3 V** la ambele VIN,
modul ampermetru, firmware **0.3.2** pe ambele radiouri, marcaje locale
`radio_markers` și politica strictă total-only `total_only_with_direct_adc_proof`.
Seria folosește antenele actuale pentru toate loturile; debuggerul este deconectat.

Citirea metadatelor PPK acumulează fragmentele până la linia `END` și
validează strict cei **35 de coeficienți** și câmpurile de identificare,
fără fallback la valori implicite. După această corecție au trecut
**310/310 teste software**.

Rapoartele JSON ale sesiunilor anterioare enumerate mai jos sunt **dovezi istorice**:
[programarea inițială 0.3.1](flash-verification-20261001.json),
[programarea 0.3.2](radio-marker-0.3.2-flash-verification.json),
[primul audit](radio-marker-0.3.2-first-pilot-independent-audit.json),
[auditul pilotului de cinci transferuri](radio-marker-0.3.2-five-transfer-pilot-verification.json),
[diagnosticul USB](radio-marker-0.3.2-campaign-usb-diagnostic.json) și
[vechea mapare UART–PPK](radio-marker-0.3.2-usb-port-mapping-verification.json).
Hashurile și verdictele descriu verificările efectuate atunci. RAW-urile
sursă ale celor cinci sesiuni din 1 octombrie au fost șterse la cererea
operatorului și nu mai pot fi consultate la căile din aceste rapoarte.
Numerele COM din rapoartele vechi, inclusiv wrapperul de mapare COM16/COM14,
nu reprezintă configurația actuală.

Probele istorice au observat un puls TX de 1,78 ms în 0.3.1 și pulsuri locale
TX/RX în 0.3.2, inclusiv cinci recepții fără rearmarea RX. Aceste constatări
au susținut implementarea verificării independente a energiei totale;
campania încheiată are propriile capturi și dovezi de validare.

## Energie la schimbarea gamei PPK2

Versiunea `energy_relative_v2`, selectată explicit în UI, separă două criterii:

- Replay-ul întregii capturi trebuie să reproducă RAW cu diferență de cel mult
  **0,000001 µA**, ca înainte.
- Lățimea intervalului energetic calculat din istoricul posibil al filtrului
  trebuie să fie cel mult **0,01%** din limita inferioară pozitivă a energiei.
  Intervalul include și rotunjirea numerică. Energia nominală trebuie să fie
  pozitivă și cuprinsă în acest interval; intervalele care ating zero se resping.

Plafonul de 0,01% este un buget software fix pentru influența istoricului,
**nu precizia analogică a PPK2**. Nu se ajustează după rezultat. Dovada are
schema 2 și politica `total_only_with_bounded_filter_energy_proof_v2`, iar
agregatele păstrează maximul incertitudinii absolute și relative. Toate
verificările locale de contor, marcaj, recepție și integritate rămân obligatorii.
CLI necesită `--filter-aware-totals --filter-history-policy energy_relative_v2`.

Versiunea inițială este păstrată pentru reproducerea rezultatelor istorice.

Modul opțional `filter_aware_totals` folosește politica distinctă
`total_only_with_bounded_filter_replay_proof`. Necesită marcaje locale,
`marker_totals_only` și transferuri nefragmentate; se selectează explicit în UI.
Metoda ADC directă și rezultatele CH340 existente rămân neschimbate.

Calculul reproduce conversia calibrată și filtrul PPK pe întregul WIRE și
compară fiecare valoare cu RAW. Pentru istoricul dinaintea marcajului,
enumeră toate cele 81.920 valori ADC posibile și propagă intervale conservative
prin operațiile binary64, inclusiv blocarea temporară a filtrului în gama 4.
Suma erorii de replay și a lățimii intervalului de incertitudine trebuie să
fie cel mult toleranța fixă de 0,000001 µA. Discontinuitățile contorului,
cuvintele invalide și marcajele incomplete din intervalul verificat resping
în continuare captura. Nu se repară, elimină sau reindexează mostre.

Această verificare dovedește calculul asupra datelor înregistrate și limitează
influența istoricului; **nu demonstrează precizia analogică în timpul comutării
gamei**. Rezultatul reprezintă energia întregului E79 între fronturile marcajului
propriu, fără consumul ESP32 și fără scăderea consumului de repaus. Pentru RX,
marcajul acoperă sincronizarea detectată până la sfârșitul pachetului; nu include
ascultarea, preambulul și căutarea sincronizării.

La acceptarea lotului, interfața recitește RAW/WIRE și reface dovada; fiecare
dintre cele cinci pachete trebuie și recepționat. Prima eroare oprește lotul,
iar tentativele vechi nu sunt promovate. Auditorul separat este
`power_profiler/tools/audit_filter_marker_totals.py`; agregarea campaniilor
acceptate folosește `power_profiler/tools/summarize_paired_campaign.py` și
păstrează metoda în fiecare rând.

## Conexiuni

Pentru modul `radio_markers`, fiecare radio furnizează marcajul propriu
numai instrumentului care îi măsoară curentul:

```text
E79 TX DIO17 ───── PPK2 TX: port logic, D0
E79 RX DIO17 ───── PPK2 RX: port logic, D0

Referința logică 3,3 V ── VCC logic al ambelor PPK2
Masa comună           ── GND logic al ambelor PPK2
```

**Nu se unesc DIO17 ale celor două radiouri:** sunt două ieșiri distincte.
VCC din portul logic este referința intrărilor digitale. Nu se unesc ieșirile
VOUT ale PPK-urilor: fiecare modul rămâne alimentat exclusiv prin propriul
PPK2, în modul ampermetru, cu sursa externă de 3,3 V la VIN.

În schema montajului, DIO17 este **padul 19 al E79 și semnalul JTAG TDI**.
Un programator JTAG nu trebuie să conducă TDI în timpul folosirii marcajului.
Operatorul a confirmat prezența firelor DIO17/D0, referința logică și masa
comună și, înaintea programării 0.3.2, separarea exactă a celor două ieșiri.
După programarea 0.3.1, cablul debuggerului a fost scos din conectorul
țintei. Acest pas se repetă după orice programare, inclusiv cea pentru 0.3.2,
înainte de măsurare. Pentru marcaje proprii, ambele module necesită 0.3.2.

Asocierea verificată pentru campania pornită la 14:10:51:

| Rol | Radio CH340 | PPK2 | Seria PPK2 |
| --- | --- | --- | --- |
| TX | COM16 | COM10 | E753C4E81F3D |
| RX | COM15 | COM11 | CD2D332DB09A |

Asocierea este confirmată electric. Nu se deduce din ordinea numerelor COM
și nu se preia din mapările anterioare; se reverifică la modificarea conexiunilor.

## Firmware și compilare

Sursa canonică este
`D:\Documente\CC1352P\firmware\e79_at_modem\e79_at_modem.c`.
În 0.3.2, aceeași imagine permite `AT+MARKER=TX` sau `AT+MARKER=RX`:

| Rol | Rutare | Interval HIGH |
| --- | --- | --- |
| TX | `RAT_GPO0 → RFC_GPO2 → DIO17` | Inițierea până la terminarea transmisiei |
| RX | `RAT_GPO1 → RFC_GPO2 → DIO17` | Detectarea sync până la finalizarea sau abandonarea recepției |

Rolul implicit după reset/default este TX; runner-ul selectează explicit
rolul fiecărui modul. Pentru RX se adaugă override-ul TI `0x008F88B3`, păstrând
override-urile originale ale profilului. Rutarea se reaplică după pornirea
nucleului RF; inițializarea și oprirea sa readuc pinul LOW. Celelalte semnale
GPO folosite de traseul RF sunt păstrate.

Interogarea `AT+MARKER?` răspunde, pentru rolul RX:

```text
+MARKER:ROLE=RX,DIO=17,SOURCE=RAT_GPO1,ACTIVE=HIGH
OK
```

Pentru TX, răspunsul conține `ROLE=TX` și `SOURCE=RAT_GPO0`.

Aliasul compatibil `AT+TXMARKER?` răspunde numai în rolul TX:

```text
+TXMARKER:DIO=17,SOURCE=RAT_GPO0,ACTIVE=HIGH
OK
```

În rolul RX, aliasul întoarce eroarea `MARKER_NOT_TX`. Interogările confirmă
configurația firmware, nu prezența electrică a pulsurilor.

`bRepeatOk` și `bRepeatNok` rămân activate. Documentația TI descrie marcajul
[RAT_GPO1 și limitele sale](https://software-dl.ti.com/simplelink/esd/simplelink_cc13x2_26x2_sdk/3.40.00.02/exports/docs/proprietary-rf/proprietary-rf-users-guide/rf-core/signal-routing.html).
[Release notes TI](https://software-dl.ti.com/simplelink/esd/simplelink_cc13x0_sdk/2.20.00.38/exports/docs/driverlib_cc13xx_cc26xx/release_notes_driverlib_cc13xx_cc26xx.html)
documentează repararea problemei primului sync în repeat mode în patch-urile
CPE pentru CC13x2. Funcționarea repetată pe aceste module trebuie confirmată
cu mai multe pachete în aceeași armare RX.

Din `D:\Documente\CC1352P`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-e79-at-modem.ps1 -UartPinout CH340
powershell -ExecutionPolicy Bypass -File .\scripts\build-e79-at-modem.ps1 -UartPinout ESP32
```

Imaginile rezultate sunt în
`firmware\e79_at_modem\artifacts\0.3.2\ch340_1000000\e79_at_modem.bin`
și `esp32_1000000\e79_at_modem.bin`. Pentru montajul actual se folosește
**CH340: TX DIO12 / RX DIO13**; varianta ESP32 are pinii UART inversați.
Se alege explicit artefactul versionat, nu un binar generic rămas dintr-o
compilare anterioară.

### UART în bootloader față de aplicația CH340

Bootloaderul ROM CC1352P folosește pini UART fixați de TI, indiferent de
configurația aplicației. Pentru placa din schemă, cele două regimuri diferă:

| Regim | TX al adaptorului USB merge la | RX al adaptorului USB vine de la |
| --- | --- | --- |
| Aplicația CH340 actuală | E79 DIO13, pad 11 | E79 DIO12, pad 10 |
| Bootloader ROM | E79 DIO12, pad 10 | E79 DIO13, pad 11 |

Schema `Ebyte_E79_CH9340C.kicad_sch` și netlist-ul PCB arată trasee directe,
fără jumper pentru inversarea UART. J15 este pentru JTAG; JP24 ține de
alimentare. Posibilitatea inversării prin fire pe montajul CH340 actual
trebuie confirmată fizic. Nu se conectează o a doua ieșire UART peste ieșirea
adaptorului existent fără izolarea acesteia.

Probele ROM, inclusiv după BOOT + RESET manual, nu au primit ACK; nu au
efectuat ștergere/scriere. Inversarea pinilor explică lipsa comunicației
în ROM. Programarea 0.3.1 a fost realizată ulterior prin **J-Link PLUS, cJTAG,
CC1352P1F3, 1000 kHz**, fără modificarea cablării UART. Imaginea `.hex` a fost
scrisă, apoi `verifybin` a comparat cu succes întreaga imagine de **360448
bytes**. CCFG a rămas `C5FE0FC5`, iar UART confirmă 0.3.1 și DIO17/RAT_GPO0.
Operatorul a cerut să se omită salvarea firmware-ului existent, având backup
în Git; nu s-a creat o copie a firmware-ului citit de pe modul.

[Patch-ul](firmware.patch), [hashurile surselor](source-update-manifest.json)
și metadatele build-urilor [CH340](ch340-build-info.json) /
[ESP32](esp32-build-info.json) documentează versiunea 0.3.1 din proiectul extern.
Originalele au backup local în
`.tmp/e79_dio17_20261001/canonical-backup` din repository-ul radio.

Pentru 0.3.2 sunt păstrate [patch-ul](radio-marker-0.3.2.patch) și metadatele
build-urilor [CH340](radio-marker-0.3.2-ch340-build-info.json) /
[ESP32](radio-marker-0.3.2-esp32-build-info.json). Acestea documentează
compilarea, nu programarea sau validarea electrică pe banc.

## Interfață și interpretarea energiei

În **E79 paired 32 B → Energy integration**, se selectează
**Local TX/RX hardware markers (recommended)**, identificat în rezultate prin
`radio_markers`, după actualizarea ambelor module la 0.3.2. Runner-ul selectează
rolurile TX/RX și verifică răspunsurile `AT+MARKER?`. Receptorul rămâne activ
continuu de la warm-up până la sfârșitul celor cinci transferuri; nu este
rearmat între ele. Warm-up-ul este nemăsurat.

Fiecare PPK integrează curentul între fronturile marcajului radioului propriu.
Ceasurile rămân independente, la 100 kS/s. Se cere câte un puls complet și
neambiguu pe fiecare instrument, dar **duratele TX și RX nu trebuie să fie
egale**, fiind intervale diferite. Implicit, sunt verificate contoarele binare
PPK în fereastra markerului și în baseline, iar o anomalie relevantă respinge
calculul. Politica explicită total-only de mai jos validează separat dependențele
decodorului pentru energia totală.
Un marcaj lipsă/incomplet/
ambiguu sau o anomalie care afectează integrarea respinge perechea, păstrând
ambele RAW, fără înlocuire cu o fereastră modelată.

Rezultatul RX este **energia întregului modul receptor între detectarea
sync și finalul/abandonul recepției**. Exclude preambulul, ascultarea anterioară,
pornirea receptorului și procesarea ulterioară intervalului. Consumul
circuitelor care rămân active este inclus: rezultatul nu izolează energia
exclusivă a demodulatorului sau a altui bloc intern. Recepția corectă se
verifică separat prin UART; un puls poate exista și pentru un pachet abandonat.
`energy_total` integrează curentul măsurat fără rectificare. În politica implicită,
`energy_excess` păstrează definiția legacy: exces pozitiv peste mediana
pretrigger, rectificat, nu energie RF exclusivă.

Caseta **Total energy only · independently verified ADC**, dezactivată implicit,
activează o politică separată numai pentru `radio_markers` (CLI:
`--marker-totals-only`). Pentru fiecare rol, dovada cere gamă validă constantă
pe `[start−3, stop)`, integritatea contorului și cuvintelor binare inclusiv la
frontul final `stop`, concordanța markerului digital și o conversie ADC
independentă care coincide cu RAW în limita fixă de **0,000001 µA**.
Gama constantă dovedește că mostrele integrate nu depind de memoria filtrului
folosit la schimbările de gamă. Fără această dovadă, perechea este respinsă.
Sunt păstrate energia/sarcina totale, media, vârful și durata; **baseline-ul,
pragul și sarcina/energia excess sunt `null`**, chiar dacă baseline-ul este curat.
Anomaliile din afara intervalului rămân în diagnostice și avertizări; RAW-urile
și contoarele nu sunt corectate. Metadatele declară
`energy_policy=total_only_with_direct_adc_proof` și
`integration_method=independent_radio_hardware_marker_totals`.

Opțiunea **Common TX hardware marker · TX interval for both roles**
(`tx_marker`) rămâne disponibilă pentru o altă întrebare: energia ambelor
module în intervalul emisiei TX. Aceasta necesită DIO17 TX distribuit către
ambele D0, cu DIO17 RX separat, și compară lățimile aceluiași puls. Nu
delimitează intervalul propriu RX. `Modeled windows (legacy)` rămâne opțiunea
pentru reproducerea calculelor istorice.

## Validare și următorul test

- **Campanie ESP32 32 B completă, 2 octombrie 12:28:57:** **105/105 perechi,
  21/21 loturi**, toate cele șapte PHY la −20/0/+13 dBm, cinci repetări.
  [Manifestul final](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/manifest.json)
  și [agregatele finale](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis/aggregates.csv)
  folosesc PPK 1.2.4, marcaje locale și `energy_relative_v2`, cu E79 măsurat
  separat de ESP32 la 3,3 V. GFSK4K8/+13 și GFSK200/−20 au câte o tentativă
  anterioară exclusă, păstrată separat; toate celelalte loturi au o singură
  tentativă. Corecția validatorului UI a trecut 419 teste și nu a schimbat
  calculele energetice, pragurile sau replay-ul obligatoriu RAW/WIRE.
  [Auditul final independent](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/independent-final/summary.json)
  confirmă **210/210 capturi**, 20.414.464 mostre reproduse exact, zero
  anomalii de contor, diferențe energetice sau duplicate RAW/WIRE.
  [Verificarea finală](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/final-verification.json)
  confirmă manifestele CH340 neschimbate și ambele PPK active în UI.

- **Istoric: campanie ESP32, 2 octombrie 12:15:** **35/105 perechi,
  7/21 loturi acceptate** în [sesiunea nouă la 32 B](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/manifest.json).
  GFSK4K8 și GFSK50 au trecut la toate cele trei puteri, GFSK200 la +13 dBm.
  Oprirea era la warm-up GFSK200/−20 dBm (0/3 recepții), fără capturi în
  acel lot. [Diagnosticul RF](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/rf-power-diagnostic.json)
  confirmă recepția la 0/+13 dBm și absența ei la două probe −20 dBm.
  [Agregatele parțiale](../../../../measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis-after-resume-01/summary.json)
  includ numai loturile acceptate. A fost corectată o respingere UI falsă
  privind intervalele rotunjite în exterior; replay-ul RAW/WIRE și pragurile
  rămân neschimbate, **419 teste trecute**. Lotul GFSK4K8/+13 dBm afectat a
  fost repetat integral, cu tentativa inițială păstrată. Continuarea a pornit
  de la GFSK200/−20 dBm și a încheiat întreaga matrice.

- **Istoric diagnostic din 2 octombrie 10:46:** experimentul A/B cu 5 transferuri
  la hold 0,75 s și 5 la hold 10 s a primit 10/10 pachete; trec 2/5, respectiv
  3/5 perechi. Pauza lungă nu elimină anomaliile; niciun rezultat diagnostic
  nu este promovat în campanie. [Experiment A/B](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/spacing-ab/report.json).
  [Citirea directă pySerial, fără RF](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/direct-serial-idle/report.json)
  reproduce 1.555 de cuvinte izolate cu tiparul OR înaintea schimbării gamei,
  inclusiv cu RX OFF, fără `ppk2-api`, `capture_pair` sau decodarea curentului.
  Zero erori raportate de ClearCommError și D0 LOW pe toate cele șase capturi.
  Firmware-ul PPK2 la comutarea gamei este ipoteza principală, nu o cauză
  internă demonstrată. [Starea investigației](../../../../MASURATORI_DE_FACUT.md)
  păstrează limitele și următorul diagnostic. Campania rămâne 0/105;
  ambele PPK sunt active prin UI.
  [Analiza RAW completă](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/counter-cause-diagnostic-analysis.json)
  arată 153,0 cuvinte OR/s pe RX în A și 145,6/s în B; toate preced schimbarea
  gamei. [Auditul energetic independent](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/spacing-ab-independent-energy-audit.json)
  confirmă 20/20 verdicte și replay exact pentru 1.937.408 mostre.

- **ESP32, reluare din 2 octombrie 09:25:** tentativa 3 a primit ambele
  pachete executate. Prima pereche trece; al doilea RX are contorul WIRE
  **11 → 15 → 13** la mostrele 25387–25389, în pulsul [25322,25464).
  Intervalul energetic conservator [32,3545;4772,9650] µJ nu permite
  acceptarea energiei RX. **0/105 perechi acceptate**; toate cele trei
  tentative sunt păstrate, fără promovarea prefixelor valide sau schimbarea
  pragurilor. [Agregarea actualizată](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis-after-attempt-03/summary.json)
  confirmă starea incompletă.
  [Auditul independent al tentativei 3](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/attempt-03-energy-independent-audit.json)
  confirmă verdictul și replay-ul exact al celor patru capturi. Ambele PPK
  rămân active, fără erori raportate de UI după test.

- **Istoric: ESP32, reluare din 2 octombrie 09:02:** tentativa 2 a repetat primul
  lot GFSK200/+13 dBm cu aceleași setări și s-a oprit la primul transfer.
  Pachetul a fost primit; TX trece verificarea. RX are ultima abatere de
  contor cu 50 µs înaintea pulsului [25534,25676), fără abateri în puls
  sau în marja sa. Intervalul energetic conservator [34,4433;1091,6988] µJ
  depășește bugetul istoricului de 0,01%. **0/105 perechi acceptate**;
  ambele tentative sunt păstrate separat, fără promovarea prefixelor.
  [Agregarea actualizată](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis-after-attempt-02/summary.json)
  păstrează starea incompletă. Ambele PPK rămân active.
  [Auditul independent al tentativei 2](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/attempt-02-energy-independent-audit.json)
  confirmă verdictul și replay-ul exact pe ambele roluri.

- **Istoric: ESP32, campanie din 2 octombrie 08:57:** campania de 105 perechi la
  32 B a pornit din UI cu `energy_relative_v2` și s-a oprit la transferul 2
  din primul lot GFSK200/+13 dBm. Ambele pachete au fost primite; prima
  pereche este validă, inclusiv RX cu schimbări de gamă. Al doilea RX are
  contorul WIRE **21 → 23 → 23** la mostrele 25287–25289, în interiorul
  pulsului [25264,25406). Intervalul energetic conservator
  [30,0421;4605,7972] µJ nu permite acceptarea energiei RX.
  **0/21 loturi și 0/105 perechi acceptate**; lotul incomplet rămâne
  exclus din agregate. [Manifestul](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/manifest.json)
  și [agregarea](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis/summary.json)
  sunt păstrate împreună cu RAW/WIRE. Ambele PPK rămân active.
  [Auditul independent](../../../../measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/energy-independent-audit.json)
  confirmă verdictul și replay-ul exact al tuturor celor patru capturi.
  Codul coincide cu versiunea verificată prin 412/412 teste; fără retry
  automat sau modificarea criteriilor.

- **Istoric: ESP32, pilot din 1 octombrie 19:13:** politica energetică v2 este
  implementată și activă în UI, cu buget separat de **0,01%** pentru istoricul
  filtrului, replay strict și QA local neschimbate. **412/412 teste** și
  [regresia independentă pe 34 de capturi](esp32-20261001/energy-budget-regression.json)
  trec. Primul transfer nou este valid; al doilea pachet este primit, dar
  RX are abateri de contor în marja dinaintea pulsului, la 25351/25352,
  cu pulsul [25354,25496). În acest caz, intervalul energetic conservator
  [32,8843;1627,5975] µJ depășește mult bugetul. Toate cele 144 de abateri
  izolate ale capturii preced o schimbare de gamă și există deja în WIRE;
  cauza nu este încă demonstrată. Lotul rămâne neacceptat, campania de
  105 perechi nu pornește, PPK-urile rămân active și datele sunt păstrate.

- **Istoric: ESP32, pilot din 1 octombrie 18:58:** metoda care reproduce filtrul
  PPK este implementată și verificată prin **396/396 teste** și un audit
  independent pe 28 de capturi. Pilotul nou la 32 B/GFSK200/+13 dBm are
  două perechi valide, cu schimbări de gamă RX acceptate prin noua dovadă.
  Al treilea pachet este primit, dar istoricul RX nu converge suficient după
  o discontinuitate cu 1,08 ms înaintea pulsului: limita este 0,0044441 µA,
  peste pragul numeric fix de 0,000001 µA. Nu există anomalie în puls sau
  în marja lui, iar replay-ul coincide exact cu RAW. Lotul se oprește;
  campania de 105 perechi nu începe și prefixul valid nu este promovat.
  [Verificarea pilotului](esp32-20261001/filter-aware-pilot-verification.json),
  [regresia independentă](esp32-20261001/filter-replay-independent-regression.json)
  și [verificarea agregatelor CH340](esp32-20261001/filter-change-ch340-aggregation-verification.json)
  sunt păstrate. Ambele PPK sunt active în UI.

- **Istoric ESP32 până la 1 octombrie 18:31:** ambele E79 folosesc acum imaginea UART
  `0.3.2/esp32_1000000`, programată și verificată prin bootloader UART
  (CRC32 `0x7c66d6a3`). TX COM20 → PPK COM10; RX COM19 → PPK COM11,
  asociere demonstrată prin trepte de curent RX. PPK măsoară numai E79,
  cu sursă externă de 3,3 V. [Dovezile firmware](esp32-20261001/firmware-0.3.2-verification.json)
  și [driverului PPK](esp32-20261001/driver-verification.json) sunt păstrate.
  Driverul Nordic WinUSB a eliminat codul 28 de la MI_00; CDC/usbser este
  neschimbat. Cele patru tentative inițiale de pilot au recepționat primul pachet,
  dar au eșuat la D0 permanent HIGH pe ambele instrumente. Nu există încă
  perechi ESP32 acceptate; [auditul inițial](esp32-20261001/pilot-marker-audit.json)
  confirmă toate intrările D0–D7 HIGH și concordanță wire/CSV.
  Repetarea din 17:08 are același rezultat:
  97.280 mostre pe fiecare rol, D0–D7 HIGH permanent, zero fronturi.
  Pilotul din **17:17** are însă marcaje complete: TX **1,78 ms**, RX
  **1,43 ms**, pachet primit. Verificarea energiei RX eșuează deoarece gama
  PPK trece 3→2→3 în puls, cu șapte mostre în gama 2; dovada ADC directă
  presupune gamă constantă. Un diagnostic separat cu cinci transferuri
  primește **5/5**, toate cu marcaje complete, dar toate cele cinci RX schimbă
  gama în interval. Criteriile rămân neschimbate; niciun rezultat diagnostic
  nu este promovat. Testul D0→GND nu mai este necesar pentru verificarea
  fronturilor. Blocajul curent este validarea energiei la schimbarea gamei.
  Reîncercarea din **18:24**, cu aceleași setări și criterii, primește primul
  pachet și păstrează pulsuri complete TX/RX, dar RX eșuează din nou pentru
  gamele 2/3 și două discontinuități de contor în puls. Lotul CH340 echivalent
  de 32 B/GFSK200/+13 dBm a avut gamă 3 constantă în toate cele cinci perechi.
  Reîncercarea din **18:30** păstrează exact configurația: pachet primit,
  TX 1,79 ms valid, RX 1,43 ms cu gamă 2/3. Nu are abateri de contor în
  intervalele verificate; singurul motiv de respingere este gama RX.
  UI are acum un buton distinct pentru
  **32 B / 105 perechi**, cu reluare și criterii de acceptare neschimbate;
  campania rămâne nepornită până la validarea energiei. **360/360 teste
  software** trecute. Detaliile curente sunt în [lista măsurătorilor](../../../../MASURATORI_DE_FACUT.md).

- Campania pornită **de la zero** este încheiată: **63/63 loturi și 315/315
  perechi validate**, cu 630 de capturi auditate independent. Manifestul și
  rezultatele calculate sunt legate mai sus.
- Primul lot este **32 B, GFSK200, +13 dBm, cinci transferuri**, cu
  `radio_markers` și total-only explicit. Se verifică pulsul local al fiecărui
  rol, recepția, integritatea intervalelor și dovada ADC independentă.
- Se verifică reapariția pulsului RX pentru toate transferurile **fără
  rearmarea RX între pachete**, de la warm-up până la sfârșitul lotului.
  O probă cu repornirea RX înainte de fiecare transfer nu demonstrează
  funcționarea marcajului în repeat mode.
- Prima etapă disponibilă în UI este **315 perechi TX/RX pentru 8/32/64 B**:
  șapte PHY-uri × trei puteri (−20/0/+13 dBm) × cinci repetări × trei dimensiuni.
  Rulează 32 B întâi, apoi 8/64 B, în 63 de loturi; GFSK200/+13 dBm este primul.
  Se oprește la primul eșec și păstrează încercările, fără repetări selective
  ale recepțiilor lipsă. Acest restart folosește o sesiune nouă;
  vechea campanie ștearsă nu se reia.
- Celelalte **105 măsurători fragmentate de 128/512/1024 B**, la +13 dBm,
  au o comandă separată în UI: **E79 fragmented campaign**. Același firmware
  0.3.2 produce câte un marcaj local pentru fiecare dintre cele 2/8/16 cadre;
  hostul însumează numai ferestrele validate și exclude pauzele. Se măsoară
  simultan TX/RX și se verifică recepția fiecărui cadru, fără retry măsurat.
  Comparația CH340/ESP32 rămâne distinctă.
  Etapa fragmentată s-a încheiat la 1 octombrie, **16:27:38: 105/105 perechi
  acceptate, 21/21 loturi**, inclusiv ultimele OOK4K8 și IEEE154G50.
  [Starea, calculele și auditul](../../../../MASURATORI_DE_FACUT.md) confirmă
  210 capturi și 1820 de intervale locale. Cele cinci tentative eșuate sunt
  păstrate și excluse integral, fără reutilizarea prefixelor valide.
  Hostul oprește eșantionarea PPK în timpul salvării și analizei, păstrând
  alimentarea și aceleași criterii de acceptare. Cauza perturbărilor
  intermitente de marcaj nu este demonstrată; matricea completă nu dovedește
  eliminarea definitivă a problemei. D1 nu este conectat; ambele PPK rămân active.
  Un diagnostic separat, cu numai PPK RX în achiziție și ambele radiouri
  alimentate, a obținut două transferuri consecutive cu toate cadrele
  primite și câte 16 pulsuri RX. Nu contribuie la campanie; rutina de citire
  și procesarea diferită dintre capturi nu permit încă izolarea cauzei.
