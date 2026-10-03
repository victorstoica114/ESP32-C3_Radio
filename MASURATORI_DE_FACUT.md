# Măsurători de făcut pentru MARTA

Lista convenită la 30 septembrie 2026.

## Organizarea noilor măsurători

- Folosim perechi de câte două module identice și **două PPK2**, pentru achiziția simultană TX și RX.
- Cele două înregistrări trebuie asociate aceluiași transfer, cu identificarea modulului și PPK2 de la fiecare capăt și documentarea sincronizării.
- Instanța care lucrează la articol formulează cerințele și folosește rezultatele livrate. Nu execută măsurători sau recalculări.
- Măsurătorile și calculele sunt gestionate separat, de operator și cealaltă instanță Codex. Calculele existente se păstrează; o problemă identificată se transmite pentru verificare/recalculare.
- Datele RAW sunt disponibile și se consultă țintit când trebuie lămurită o problemă.

**Politica de păstrare actualizată la 2 octombrie 2026:** la cererea
operatorului, păstrăm capturile complete/validate și eliminăm RAW/WIRE din
tentativele dovedite nereușite sau incomplete, inclusiv cele istorice.
Rapoartele mici și rezultatele interpretate rămân, fără a transforma
încercările nereușite în succese. Controalele intenționate și capturile
validate ulterior sunt protejate. Formulările istorice de mai jos despre
păstrarea tuturor RAW descriu situația de la momentul respectiv; disponibilitatea
actuală este consemnată în [raportul de curățare](power_profiler/audits/2026-10-02/capture-cleanup/summary.json).
Au fost eliminate **404 fișiere de captură nereușite și o arhivă ZIP locală
redundantă**, în total **1.659.338.091 bytes**. Datele complete din ZIP aveau
deja copii extrase identice, verificate prin SHA256. Seturile complete E79 și
nRF24 rămân disponibile; 16 capturi istorice fără dovadă suficientă de eșec
sunt păstrate, alături de controalele valide.

## E79

**Campanie E79/ESP32 32 B încheiată la 2 octombrie 2026, 12:28:57:**
**105/105 perechi TX/RX acceptate, 21/21 loturi**, toate cele șapte profile PHY
la −20/0/+13 dBm, câte cinci repetări. Numai E79 este alimentat prin PPK, la sursa externă de
3,3 V. Politica energetică rămâne `energy_relative_v2`, cu marcaje locale
TX/RX pe DIO17 și replay obligatoriu din fișierele originale.
[Manifest final](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/manifest.json),
[agregate CSV](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis/aggregates.csv)
și [rezumatul calculelor](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis/summary.json)
sunt salvate. Agregatele conțin 42 de rânduri condiție/rol, cu media și abaterea
standard a celor cinci repetări. Energia RX acoperă marcajul local de la
sincronizare la finalul pachetului; nu include preambulul sau ascultarea.

[Auditul independent final](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/independent-final/summary.json)
confirmă **210/210 capturi**, **20.414.464 mostre reproduse exact**, zero
anomalii de contor, zero duplicate RAW/WIRE și zero diferențe de energie
sau sarcină față de CSV. [Verificarea finală](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/final-verification.json)
leagă prin hashuri manifestul, agregatele și auditul;
confirmă păstrarea seriilor CH340 și starea activă a ambelor PPK prin UI.
**419/419 teste software au trecut.**

Cele două loturi reluate sunt GFSK4K8/+13 dBm (respingere UI falsă corectată)
și GFSK200/−20 dBm (warm-up fără recepție). Fiecare lot reluat a fost măsurat
integral; tentativele inițiale sunt păstrate și excluse din agregate. Cele
35 de perechi deja acceptate înaintea ultimei reluări au fost păstrate.
Rezultatele CH340 și diagnosticele anterioare nu au fost modificate.

**Istoric campanie E79/ESP32, 2 octombrie 2026, 12:15:**
noua sesiune de 32 B are **35/105 perechi acceptate, 7/21 loturi**.
Au trecut GFSK4K8 și GFSK50 la −20/0/+13 dBm, plus GFSK200 la +13 dBm.
[Manifestul campaniei](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/manifest.json)
și [agregatele calculate](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis-after-resume-01/summary.json)
păstrează marcajele locale și politica
`energy_relative_v2`. Nu s-au importat capturi de diagnostic sau din seria veche.

Oprirea de atunci era la **GFSK200/−20 dBm**, înaintea capturilor: niciunul
dintre cele trei pachete de warm-up nu a fost primit. Un
[diagnostic RF separat](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/rf-power-diagnostic.json),
cu ordinea fixă −20/0/+13/−20 dBm, a obținut **neprimit/primit/primit/neprimit**.
Configurațiile citite de la radiouri corespund; cauza fizică sau internă a
acestei dependențe de putere nu este demonstrată. Nu există capturi energetice
pentru tentativa oprită. Reluarea a păstrat cele șapte loturi acceptate și a
început din nou cu GFSK200/−20 dBm, încheind ulterior întreaga matrice.

În această sesiune a fost corectată și o eroare a validatorului UI: compara
lățimile intervalelor Q/E ca și când rotunjirea în exterior ar fi liniară și
limita separat intervalul Q printr-o aproximație care omitea rotunjirea sumei
și diviziei. La GFSK4K8/+13 dBm, această verificare respingea eronat un lot
cu zece capturi corecte. [Diagnosticul numeric](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/ui-rounding-rejection.json)
și [revalidarea fișierelor originale](measurements/raw/sessions/20261002_120020_798930_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/ui-revalidation-after-rounding-fix.json)
documentează cauza. Codul de achiziție, calculele energetice, replay-ul exact
obligatoriu și bugetul de 0,01% rămân neschimbate. **419/419 teste software
au trecut**, inclusiv respingerea intervalelor falsificate. Lotul a fost
repetat integral și acceptat; prima încercare se păstrează separat.

**Istoric diagnostic E79/ESP32, 2 octombrie 2026, 10:46:** pauza mai mare nu a
eliminat anomalia. Un experiment separat, cu ordinea fixă A,B,B,A,A,B,B,A,A,B,
a primit **10/10 pachete**. Așteptarea în eșantionare dintre capturi a fost
de **0,75 s pentru A** și **10 s pentru B**, cu aceleași setări RF și aceeași
verificare `energy_relative_v2`. Au trecut **2/5 perechi A** și **3/5 perechi B**.
Intervalele reale între comenzile TX, exceptând primul transfer după warm-up,
au fost 4,03–4,10 s și respectiv 13,23–13,43 s. Eșantionul este prea mic
pentru a demonstra o îmbunătățire statistică; B conține inclusiv un caz cu
discontinuități în puls. [Datele experimentului A/B](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/spacing-ab/report.json)
sunt exclusiv diagnostice; criteriile și acceptarea campaniei nu s-au schimbat.
[Auditul energetic independent](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/spacing-ab-independent-energy-audit.json)
confirmă toate cele 20 de verdicte TX/RX și replay-ul exact al celor 1.937.408
mostre; toate cele 15 capturi individuale cu dovadă validă au aceleași energii
și sarcini calculate independent.
[Analiza integrală a anomaliilor](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/counter-cause-diagnostic-analysis.json)
numără pe RX **153,0 cuvinte OR/s în A** și **145,6/s în B**, respectiv
2,78% și 2,63% raportat la schimbările gamei. Anomaliile persistă în ambele
condiții; diferența de 2/5 față de 3/5 capturi valide nu demonstrează o remediere.

O [captură directă fără transmisii](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/direct-serial-idle/report.json),
prin pySerial fără `ppk2-api`, fără `capture_pair` și fără decodor de curent,
a reprodus **1.555 de cuvinte izolate cu tiparul OR**, toate imediat înaintea
unei schimbări de gamă. Secvența RX ON/OFF/ON a durat câte 3 s, pe ambele PPK;
anomaliile apar inclusiv cu RX OFF. D0 a rămas LOW în toate cele șase capturi.
Apelurile Windows `ClearCommError` observate nu au raportat erori.
Acest rezultat exclude biblioteca PPK și decodorul nostru drept condiție
necesară a anomaliei; nu exclude absolut întregul driver USB/Windows.

[Comparația cu capturi CH340 existente](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/counter-cause-existing-captures.json)
arată același tipar în cele trei capturi TX CH340 verificate: 163 de triplete,
toate în afara pulsurilor TX. Cele trei capturi RX CH340 nu schimbă gama și
nu au acest tipar; RX ESP32 schimbă gama frecvent. Prin urmare, semnătura
nu este specifică interfeței ESP32. Comparația este observațională, pe montajele
și plăcile respective; rezultatele acceptate CH340 și manifestele sunt neschimbate.

**Ipoteza principală este reutilizarea/împachetarea unei mostre în firmware-ul
PPK2 la comutarea gamei**, pe baza relației exacte dintre cuvintele consecutive;
cauza internă nu este demonstrată încă. De exemplu, în locul contorului
11→12→13 apare 11→15→13, iar 15 este exact `11 OR 12`; cuvântul suspect
păstrează și ADC-ul, gama și logica mostrei precedente. În 1.551/1.555 cazuri
ale probei directe, întregul triplet este în același apel de citire serială,
deci concatenarea blocurilor nu este necesară pentru apariția tiparului.
Nordic documentează comportamente
ale firmware-ului legate de mostrele de la tranzițiile gamei, dar nu confirmă
acest tipar specific: [explicația Nordic](https://devzone.nordicsemi.com/f/nordic-q-a/123067/incorrect-current-measurements-with-ppk2-when-using-an-npm2100/547370).
Campania rămânea la
**0/105 perechi acceptate**; ambele PPK au fost readuse în hold activ prin UI.

**Istoric E79/ESP32, 2 octombrie 2026, 09:26:** tentativa 3, reluată explicit
din UI cu aceleași setări, a primit ambele pachete executate. Prima pereche
trece; la al doilea RX, contorul WIRE are secvența **11 → 15 → 13** la
mostrele 25387–25389, în interiorul pulsului **[25322,25464)**. Intervalul
energetic conservator este **[32,3545;4772,9650] µJ**; energia RX este
respinsă, iar campania se oprește. **0/105 perechi acceptate**, fără
promovarea prefixului valid. Toate cele trei tentative și RAW/WIRE sunt păstrate.
[Agregarea după tentativa 3](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis-after-attempt-03/summary.json)
exclude loturile incomplete. Configurația și pragurile nu s-au modificat.
[Auditul independent al tentativei 3](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/attempt-03-energy-independent-audit.json)
confirmă verdictul și replay-ul exact al celor patru capturi. Ambele PPK
au rămas active după test, fără erori raportate de UI.

**Istoric E79/ESP32, 2 octombrie 2026, 09:03:** reluarea explicită din UI
a repetat primul lot GFSK200/+13 dBm cu aceleași setări, ca tentativa 2.
Primul pachet a fost primit, dar RX nu trece bugetul istoricului filtrului:
contorul WIRE are secvența **19 → 23 → 21** la mostrele 25527–25529,
cu ultima abatere la **50 µs înaintea pulsului [25534,25676)**. Pulsul și
marja sa nu conțin abateri de contor. Intervalul energetic conservator
**[34,4433;1091,6988] µJ** depășește bugetul de 0,01%; energia RX rămâne
neacceptată. TX trece verificarea. Campania s-a oprit din nou, fără alte
reluări automate: **0/105 perechi acceptate**, ambele tentative păstrate.
[Agregarea după tentativa 2](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis-after-attempt-02/summary.json)
exclude loturile incomplete. Ambele PPK rămân active; pragurile sunt neschimbate.
[Auditul independent al tentativei 2](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/attempt-02-energy-independent-audit.json)
confirmă verdictul și reproducerea exactă a RAW din WIRE pe ambele roluri.

**Istoric E79/ESP32, 2 octombrie 2026, 08:58:** campania de **105 perechi la
32 B** a fost pornită din UI la 08:57:54, cu `energy_relative_v2`, și s-a
oprit la al doilea transfer din primul lot **GFSK200 / +13 dBm**. Ambele
pachete executate au fost primite. Prima pereche trece verificarea, inclusiv
RX cu schimbări de gamă. La al doilea RX, contorul WIRE are secvența
**21 → 23 → 23**, la mostrele **25287–25289**, în interiorul pulsului
**[25264, 25406)**. Intervalul energetic conservator este
**[30,0421; 4605,7972] µJ**; energia RX nu se acceptă. Lotul incomplet
nu contribuie la agregate: **0/21 loturi și 0/105 perechi acceptate**.
Celelalte 20 de condiții nu au fost executate; nu s-a făcut retry automat.

[Manifestul campaniei](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/manifest.json)
și [rezumatul agregării](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/analysis/summary.json)
păstrează rezultatul și configurația. [Auditul independent al celor patru capturi](measurements/raw/sessions/20261002_085754_457290_paired_32b_campaign_radio_ebyte_e79_cc1352p/diagnostics/energy-independent-audit.json)
confirmă verdictul și reproducerea exactă a RAW din WIRE; energiile și
sarcinile acceptate ale primei perechi coincid exact. RAW/WIRE sunt păstrate; ambele PPK
au rămas alimentate și în eșantionare prin UI. Sursele sunt identice cu
versiunea verificată prin **412/412 teste**; criteriile nu au fost modificate.

**Istoric E79/ESP32, 1 octombrie 2026, după pilotul din 19:13:** versiunea
`energy_relative_v2` este implementată și activă în UI. Verificarea decodorului
rămâne la 0,000001 µA; influența istoricului filtrului are un buget energetic
separat, fix, de **0,01%**, fără modificarea verificărilor locale de integritate.
**412/412 teste software** au trecut. [Regresia independentă pe 34 de capturi](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/energy-budget-regression.json)
coincide cu implementarea; cele șase dovezi v1 arhivate sunt reproduse identic.
Cazul anterior cu incertitudine de 0,00000135% trece regula nouă, fără
promovarea pilotului istoric sau modificarea datelor CH340.

[Pilotul nou din UI](measurements/raw/sessions/20261001_191322_933884_paired_pilot_radio_ebyte_e79_cc1352p/manifest.json)
primește **2/2 pachete executate**, dar se oprește la al doilea transfer.
Prima pereche este validă. La al doilea RX, contorul brut are secvența
**53 → 55 → 55**, cu abateri la mostrele **25351/25352**, în marja de trei
mostre dinaintea pulsului **[25354, 25496)**. Ultima abatere este la numai
**20 µs** de front. Intervalul energetic conservator calculat este acum
**[32,8843; 1627,5975] µJ**: nu este cazul cu incertitudine neglijabilă.
Verificarea locală respinge captura indiferent de bugetul energetic.

[Auditul independent](measurements/raw/sessions/20261001_191322_933884_paired_pilot_radio_ebyte_e79_cc1352p/diagnostics/energy-independent-audit.json)
confirmă toate cele patru capturi și reproducerea exactă a RAW. În întregul RX
al transferului 2, toate cele 144 de cuvinte cu abatere izolată preced o schimbare
de gamă și au tiparul `previous_word OR (expected_counter << 18)`; secvența
normală revine după o mostră. Acest tipar este deja în WIRE, înainte de parser.
Nu demonstrează singur cauza firmware sau un defect de transport; nu se aplică
o corecție asupra datelor. **Pilotul este neacceptat, campania de 105 perechi
nu a început, iar ambele PPK rămân active.**

**Istoric: pilotul din 18:58, înaintea politicii energetice v2:** metoda opțională
care reproduce filtrul PPK și limitează influența istoricului este implementată
în interfață. **396/396 teste software** trecute; auditul independent coincide
cu implementarea pe 28 de capturi de regresie. Cele 1.008 valori agregate ale
campaniei CH340 sunt identice, iar manifestele CH340 sunt neschimbate.

[Pilotul nou, pornit prin UI](measurements/raw/sessions/20261001_185824_162955_paired_pilot_radio_ebyte_e79_cc1352p/manifest.json),
la **32 B / GFSK200 / +13 dBm**, a primit corect toate cele trei pachete executate.
Primele **două perechi trec**, inclusiv RX cu schimbări de gamă. Al treilea
transfer oprește lotul: RX are o discontinuitate de contor cu **1,08 ms înaintea
pulsului**, fără anomalii în puls și în marja sa. Replay-ul reproduce exact RAW,
dar influența maximă rămasă a istoricului este **0,0044441 µA**, peste toleranța
numerică fixă de **0,000001 µA**. Lățimea intervalului energetic este numai
**0,000000473644 µJ**; această limită numerică nu reprezintă precizia analogică
a PPK. Pragul nu a fost relaxat.

[Auditul independent al celor șase capturi](measurements/raw/sessions/20261001_185824_162955_paired_pilot_radio_ebyte_e79_cc1352p/diagnostics/filter-independent-audit.json)
confirmă toate verdictele. [Verificarea completă](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/filter-aware-pilot-verification.json)
păstrează metoda, configurația, limitele și hashurile codului/datelor.
Pilotul rămâne **incomplet și neacceptat**; primele două perechi nu sunt
promovate în campanie. **Campania ESP32 de 105 perechi nu a început**, iar
ambele PPK rămân alimentate și în eșantionare prin UI.

**Istoric până la 1 octombrie 2026, 18:31:** interfața permite acum
ESP32 și o campanie separată numai la **32 B: 21 condiții × 5 = 105 perechi**
(șapte PHY-uri, −20/0/+13 dBm), cu aceleași verificări stricte și oprire la
primul eșec. Cele **360 de teste software** au trecut. Campania nu a început.
**Marcajele TX și RX sunt acum complete, iar comunicația funcționează.**
Pilotul din 17:17 a primit primul pachet, cu puls TX de **1,78 ms** și puls RX
de **1,43 ms**, dar validarea energiei RX a eșuat: gama PPK a trecut 3→2→3
în interiorul pulsului (șapte mostre în gama 2). Metoda actuală cere gamă
constantă pentru a demonstra energia direct din ADC, fără dependența de
filtrul folosit la comutarea gamei. Nu au fost modificate criteriile.

Un [diagnostic separat, cu cinci transferuri prestabilite](measurements/raw/sessions/20261001_171738_633948_paired_pilot_radio_ebyte_e79_cc1352p/diagnostics/range-repeatability-five/report.json)
a primit **5/5 pachete**, cu marcaje complete pe ambele roluri. Toate cele
cinci capturi RX schimbă gama în intervalul local; patru TX trec verificarea,
iar al cincilea schimbă și el gama. RX are și discontinuități ale contorului
în intervalele transferurilor 1 și 5. [Auditul independent al celor zece capturi](measurements/raw/sessions/20261001_171738_633948_paired_pilot_radio_ebyte_e79_cc1352p/diagnostics/range-repeatability-five/independent-audit.json)
confirmă RAW/wire identice, zece pulsuri complete și aceleași verdicte.
Datele sunt exclusiv diagnostice și nu
se promovează în campanie. **Zero perechi ESP32 acceptate.** Blocajul curent
este validarea energiei la tranzițiile de gamă; nu mai este lipsa marcajelor.
[Auditul pilotului curent](measurements/raw/sessions/20261001_171738_633948_paired_pilot_radio_ebyte_e79_cc1352p/diagnostics/pilot-independent-audit.json)
reproduce independent pulsul TX și respinge justificat intervalul RX.

[Reîncercarea din 18:24](measurements/raw/sessions/20261001_182450_545613_paired_pilot_radio_ebyte_e79_cc1352p/manifest.json),
cu aceleași setări, s-a oprit la primul transfer: pachet primit, puls TX
**1,78 ms** valid și puls RX **1,43 ms** complet, dar dovada RX este respinsă
din nou pentru gamele 2/3 și discontinuități de contor la mostrele 25206/25207,
în interiorul pulsului. Nu s-au schimbat pragurile, decodorul sau firmware-ul.
Lotul CH340 de referință **32 B/GFSK200/+13 dBm** are toate cele cinci
intervale TX/RX și marjele lor în gama 3 constantă; această comparație
confirmă diferența de date, fără a demonstra cauza ei. Campania ESP32 rămâne
nepornită, cu zero perechi acceptate; ambele PPK sunt active.

[Reîncercarea din 18:30](measurements/raw/sessions/20261001_183050_580578_paired_pilot_radio_ebyte_e79_cc1352p/manifest.json)
păstrează exact configurația precedentă și se oprește la primul transfer,
primit corect. TX are puls complet de **1,79 ms** și dovadă ADC validă;
RX are puls complet de **1,43 ms**, dar gama se schimbă din nou între 2 și 3.
De această dată nu apar abateri de contor în niciun interval verificat;
singurul motiv de respingere este gama neconstantă la RX. Captura este
păstrată integral și nu adaugă perechi acceptate în campanie.

Istoric: cele patru tentative de pilot anterioare au primit primul pachet, dar au fost
respinse deoarece D0 rămâne HIGH pe ambele PPK, inclusiv la marginile capturii.
A doua tentativă urmează confirmării
operatorului că a verificat/corectat VCC digital, GND și DIO17; a treia este
repetarea explicit cerută cu modulele conectate. A patra, după strângerea
contactelor de către operator, confirmă tot D0–D7 permanent HIGH pe ambele
PPK: 97.280 mostre pe rol, zero fronturi, RAW/wire identice și pachet primit.
[Auditul după strângerea contactelor](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/pilot-after-contact-tightening-audit.json)
confirmă respingerea ambelor intervale fără corectarea datelor.
Testul de izolare D0→GND
nu a fost efectuat. RAW și tentativele sunt păstrate, fără integrare modelată
în locul marcajelor lipsă.

Asocierea noului montaj, verificată prin variația curentului la RX ON/OFF:
**TX COM20 → PPK COM10 (`E753C4E81F3D`)**, **RX COM19 → PPK COM11
(`CD2D332DB09A`)**. Operatorul confirmă surse externe de **3,3 V** și
alimentarea prin PPK numai a E79; consumul ESP32 nu este inclus.
Ambele E79 au fost programate prin UART cu imaginea **0.3.2 / esp32_1000000**,
CRC32 verificat `0x7c66d6a3`, fără backup sau debugger. Interfața auxiliară
PPK2 fără driver (MI_00, cod 28) a primit driverul oficial Nordic WinUSB;
ambele dispozitive sunt acum OK, cod 0, iar COM10/COM11 păstrează `usbser.inf`.
Această remediere nu explică prin ea însăși problema marcajelor.

[Dovada driverului](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/driver-verification.json),
[asocierea electrică](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/fixture-current-mapping.json),
[verificarea firmware-ului](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/firmware-0.3.2-verification.json)
și [auditul primului pilot](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/pilot-marker-audit.json)
sunt păstrate. [Auditul repetărilor 2 și 3](power_profiler/audits/2026-10-01/e79-markers/esp32-20261001/pilot-retries-audit.json)
confirmă din nou toate cele opt intrări digitale permanent HIGH, fără fronturi,
cu RAW și wire identice. [Tentativa din 17:08](measurements/raw/sessions/20261001_170839_911142_paired_pilot_radio_ebyte_e79_cc1352p/manifest.json)
este o sesiune distinctă; datele CH340 acceptate nu au fost schimbate.
Testul D0 separat de E79 și legat la GND nu a fost efectuat; capturile curente
dovedesc deja fronturile locale, deci această verificare nu mai este cerută.
Ambele PPK rămân
alimentate și în achiziție prin interfață.

**Prioritatea de măsurare la 32 B este completă:** există TX și RX pentru
ambele interfețe ESP32 și CH340. Urmează comparația numerică pentru figura 3,
cu versiunile PPK și politicile de analiză declarate separat.

- [x] **E79 / CH340 — TX:** măsurători la 8, 32 și 64 B.
- [x] **E79 / CH340 — RX:** măsurători la 8, 32 și 64 B.
- [x] **E79 / CH340 — RX fragmentat:** 128, 512 și 1024 B complete, cu TX/RX măsurate simultan.
- [x] **E79 / ESP32 — TX și RX la 32 B:** 105/105 perechi, șapte PHY și trei puteri, finalizate la 2 octombrie 12:28:57.
- [ ] **E79 / ESP32 versus CH340:** comparația numerică la 32 B, cu verificarea comparabilității și provenienței seriilor.

Progres la 30 septembrie 2026: pilotul **E79 / CH340, 32 B, GFSK200 (200 kbps), +13 dBm** a fost executat prin interfață cu achiziție simultană pe două PPK2: **5/5 pachete recepționate, 10 RAW verificate independent**. Alimentare confirmată de operator: sursă externă de **3,3 V la VIN**, ambele PPK2 în modul ampermetru și activate înaintea accesului UART. Asocierea a fost verificată prin variația curentului la activarea/dezactivarea RX: TX COM12 → PPK2 COM10 (`E753C4E81F3D`); RX COM13 → PPK2 COM11 (`CD2D332DB09A`).

[Rezultatele pilotului](measurements/raw/sessions/20260930_213239_043901_paired_pilot_radio_ebyte_e79_cc1352p/paired_result/20260930_213239_188258_e79_paired_pilot/pairing.json), [verificarea independentă](measurements/raw/sessions/20260930_213239_043901_paired_pilot_radio_ebyte_e79_cc1352p/paired_result/20260930_213239_188258_e79_paired_pilot/independent_verification.json) și [inspecția traseelor](measurements/raw/sessions/20260930_213239_043901_paired_pilot_radio_ebyte_e79_cc1352p/paired_result/20260930_213239_188258_e79_paired_pilot/diagnostics/pilot_trace_inspection.pdf) sunt păstrate local; directorul `web_sessions` este exclus din Git.

**Calcule încheiate la 1 octombrie 2026:** [raport, CSV și verificare independentă](power_profiler/comparisons/ebyte_e79_paired_20260930/README.md). Cele 10 RAW reproduc valorile originale: TX **114,213 µJ** într-o fereastră modelată de 4,76 ms și RX **116,817 µJ** într-o fereastră de ascultare de aceeași durată. Analiza confirmă că **energia exclusiv RF a recepției nu poate fi izolată riguros** din aceste marcaje software. Bugetul suplimentar semnat în intervalul local de 200 ms, față de media pretrigger, este TX **42,521 ± 6,320 µJ**, RX **−2,119 ± 5,544 µJ** (media ± SD, cinci transferuri); RX nu se separă convingător de variația consumului de ascultare.

Auditul binar suplimentar a identificat abateri izolate ale contorului PPK TX. Impactul numeric în verificarea de sensibilitate este mic, dar cauza rămâne de diagnosticat înaintea următoarei campanii. Nu s-au eliminat sau corectat eșantioane și nu se impune, doar pe baza acestei constatări, refacerea tuturor capturilor. Lista de mai sus rămâne deschisă: pilotul nu încheie matricea CH340 sau comparația cu ESP32.

**Campania E79 pentru 8/32/64 B s-a încheiat la 1 octombrie 2026, 14:42:55.**
Pornită de la zero la 14:10:51, a validat **315/315 perechi TX/RX, 63/63 loturi**,
fără loturi eșuate sau repetate, în 32 min 4 s.
[Manifestul sesiunii](measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/manifest.json)
documentează capturile și validarea. [Tabelul calculat](measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/analysis/aggregates.csv)
conține media și abaterea standard de eșantion (cinci repetări) pentru energie,
sarcină, durata marcajului și curentul mediu; [rezumatul complet](measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/analysis/summary.json)
include acoperirea și hashurile surselor.
[Auditul independent final](measurements/raw/sessions/20261001_141051_449664_paired_campaign_radio_ebyte_e79_cc1352p/diagnostics/full-campaign-independent-audit.json)
a verificat **630/630 capturi**, fără erori sau duplicate; energia, durata
și conversia ADC coincid exact cu rezultatele salvate. Ambele PPK rămân active.
Configurație: **TX COM16 → PPK COM10 (`E753C4E81F3D`)**, **RX COM15 →
PPK COM11 (`CD2D332DB09A`)**, sursă externă de **3,3 V** la ambele VIN,
modul ampermetru, firmware **0.3.2** pe ambele radiouri, marcaje locale
`radio_markers` și politica strictă total-only `total_only_with_direct_adc_proof`.
Seria a folosit aceeași configurație de antene pentru toate loturile; debuggerul a fost deconectat.

Citirea metadatelor PPK acumulează fragmentele până la linia `END` și
validează strict cei **35 de coeficienți** și câmpurile de identificare,
fără fallback la valori implicite. După această corecție au trecut
**310/310 teste software**.

Pilotul din **30 septembrie**, calculele lui și comparațiile istorice rămân
păstrate. [Ghidul DIO17](power_profiler/audits/2026-10-01/e79-markers/README.md)
descrie firmware-ul, conexiunile și dovezile istorice.

Ambele module au firmware-ul **0.3.2 programat și verificat prin J-Link/cJTAG**,
iar debuggerul a fost deconectat. Aceeași imagine permite `AT+MARKER=TX` sau
`AT+MARKER=RX`; variantele CH340 și ESP32 sunt compilate. Fiecare radio leagă
**DIO17 numai către D0 al PPK-ului propriu**, fără unirea ieșirilor. Modul
`radio_markers` integrează RX de la detectarea sync până la finalul/abandonul
recepției, excluzând preambulul și ascultarea anterioară; nu izolează energia
unui circuit intern. Politica explicită `total_only_with_direct_adc_proof`
cere gamă constantă și integritate în fiecare puls și marja sa. Baseline-ul,
pragul și energia excedentară rămân necompletate; RAW-urile nu se corectează.

Prima etapă are **315 transferuri**: 7 PHY × 3 puteri (−20/0/+13 dBm) ×
3 dimensiuni (8/32/64 B) × 5 repetiții, cu achiziție simultană TX/RX.
Se începe cu **32 B, GFSK200, +13 dBm**, verificând pulsul local al fiecărui
rol și recepția, cu RX activ continuu de la warm-up până la sfârșitul lotului,
fără rearmare între pachete. Noua campanie se oprește la primul eșec și
păstrează încercările, fără repetări selective ale recepțiilor lipsă.

Etapa separată de **105 transferuri la 128/512/1024 B**, numai +13 dBm,
este disponibilă în interfață prin **E79 fragmented campaign**. Achiziția
simultană TX/RX verifică fiecare dintre cele 2/8/16 cadre de 64 B și însumează
numai ferestrele locale dovedite din ADC; exclude pauzele dintre cadre.
Un cadru lipsă sau o probă invalidă oprește campania fără repetări automate.
Matricea 8/32/64 B și etapa fragmentată sunt complete; comparația CH340/ESP32
rămâne distinctă și deschisă. Marcajul TX comun este disponibil opțional pentru energia
ambelor module în intervalul emisiei TX; nu delimitează independent RX.

**Etapa fragmentată s-a încheiat la 1 octombrie, 16:27:38: 105/105 perechi acceptate, 21/21 loturi.**
Sunt complete toate cele șapte PHY-uri la 128, 512 și 1024 B, numai +13 dBm,
cu cinci repetări pentru fiecare condiție. [Calculele finale](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/analysis/aggregates.csv)
conțin 42 de rânduri, cu media și SD pentru fiecare rol și condiție;
[rezumatul](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/analysis/summary.json)
confirmă acoperirea completă, fără condiții lipsă.
[Auditul independent final](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/full-fragmented-independent-audit.json)
confirmă 210 capturi, 1820 de intervale locale și 525 de surse reverificate
prin SHA256; diferențele ADC, energie și durată sunt zero. Implementarea
fragmentată, reluarea și pauza achiziției în procesare au trecut **353/353 teste software**.
Împreună cu etapa 8/32/64 B, sunt **420/420 perechi E79/CH340 acceptate**.
Comparația cu ESP32 și măsurătorile celorlalte module rămân de făcut.

La 1024 B/GFSK4K8, al treilea transfer a livrat toate cele 16 cadre, dar
marcajul RX s-a fragmentat în 28 de pulsuri, cu întreruperi de 30–40 µs.
Campania s-a oprit și a păstrat RAW, wire și cele trei rânduri ale tentativei;
lotul întreg este exclus din agregatele acceptate. [Diagnosticul digital](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/paired_result/paired_fragment_s1024_GFSK4K8_p13/20261001_151445_559151_e79_paired_pilot/diagnostics/marker-count-diagnostic.json)
confirmă concordanța RAW/wire și legarea unor întreruperi la faza contorului
PPK; cauza fizică sau de achiziție digitală rămâne neconfirmată.

La cererea explicită a operatorului, reluarea din 15:33:31 a păstrat cele
75 acceptate și tentativa inițială, apoi a încheiat GFSK4K8 și GFSK50.
La 1024 B/SLR2K5, transferul 2 a livrat din nou toate cele 16 cadre, însă
RX prezintă 32 de pulsuri. [Diagnosticul celei de-a doua opriri](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/paired_result/paired_fragment_s1024_SLR2K5_p13/20261001_153553_103278_e79_paired_pilot/diagnostics/marker-count-diagnostic.json)
confirmă perturbarea în regiunile cadrelor 13–16 și alinierea întreruperilor
la blocuri de 16 mostre. RAW și wire coincid; cauza nu este demonstrată.
Între primele două încercări nu a fost confirmată vreo modificare fizică
a conexiunilor.

Operatorul a fixat mai bine firele existente și a cerut o nouă reluare,
**fără conexiuni suplimentare**. Reluarea din 15:48:34 s-a oprit la 15:49:37,
tot la transferul 2 de 1024 B/SLR2K5: toate cele 16 cadre au fost primite,
TX are 16 pulsuri, însă RX are **22 de pulsuri**, în loc de 16.
[Auditul noii încercări](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/failed-1024-slr2k5-retry-audit.json)
confirmă primul transfer valid individual și al doilea respins; întregul
lot rămâne exclus. Nu s-au unit pulsuri și nu s-au corectat RAW-urile.
Fixarea firelor nu a eliminat problema; cauza rămâne neconfirmată.

După repoziționarea antenelor de către operator, reluarea din 15:58:54
s-a oprit la 15:59:55, din nou la transferul 2 de 1024 B/SLR2K5.
Cele 16 cadre au fost primite, însă marcajele au **58 de pulsuri TX și
23 RX**, în loc de 16 pe fiecare rol. Primul transfer are marcaje valide.
[Auditul acestei încercări](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/failed-1024-slr2k5-attempt03-audit.json)
respinge întregul lot. Repoziționarea nu a eliminat problema și nu dovedește
că multipath-ul este cauza. Poziția exactă a antenelor nu a fost precizată;
loturile acceptate anterior păstrează condițiile lor originale.

**Diagnostic separat, 16:05:56–16:06:34, fără fire noi:** ambele radiouri
au rămas alimentate prin PPK, însă numai PPK RX a eșantionat. După un
warm-up unic, două transferuri consecutive de 1024 B/SLR2K5 au livrat
toate cele 16 cadre fiecare și au **16 pulsuri RX fiecare**, complete,
de 217,90–217,92 ms. [Raportul și capturile](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/rx-only-after-antenna-reposition/report.json)
sunt păstrate separat, împreună cu scriptul rulat. Acest rezultat orientează
investigația către achiziție/procesare, dar nu dovedește că simultaneitatea
este cauza: s-au schimbat și rutina de citire și durata procesării dintre
capturi. Nu s-a calculat energie și nu s-au adăugat perechi în campanie.
După diagnostic, interfața a reluat menținerea ambelor PPK active.

La 16:13:05, campania a fost reluată după mutarea repornirii achiziției PPK
după salvare și analiză. Radiourile rămân alimentate, iar politica este
consemnată în fiecare nou `pairing.json` și în metadata. SLR2K5 și SLR5
au trecut câte 5/5 transferuri și auditul independent. Totuși, la OOK4K8,
transferul 5 a primit toate cele 16 cadre, dar are **16 pulsuri TX și
73 RX**. [Auditul lotului OOK4K8](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/failed-1024-ook4k8-audit.json)
documentează eșecul; întregul lot, inclusiv primele patru transferuri,
rămâne exclus. Modificarea nu a eliminat complet problema și nu dovedește
o cauză unică. Codul și logul celor 353 teste sunt păstrate într-un
[snapshot software](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/software-sampling-pause-snapshot/manifest.json).

Ultima reluare, cerută explicit de operator la 16:25, a păstrat cele 95
de perechi acceptate și a repetat integral OOK4K8, apoi a rulat IEEE154G50:
ambele loturi au trecut 5/5 și auditul independent. Nu mai sunt condiții
lipsă în etapa fragmentată. Cele cinci tentative eșuate sunt păstrate și
excluse integral; capturile valide individual dintr-un lot eșuat nu au fost
promovate. Calculele parțiale anterioare și manifestele istorice sunt păstrate.
[Verificarea conservării](measurements/raw/sessions/20261001_150445_661901_paired_fragmented_campaign_radio_ebyte_e79_cc1352p/diagnostics/final-two-resume-preservation-check.json)
confirmă cele 475 de surse acceptate anterior și toate cele cinci tentative
eșuate, fără diferențe. Încheierea matricei nu demonstrează remedierea
definitivă a problemei intermitente de marcaj sau o cauză multipath.
Conexiunea D1 propusă anterior nu a fost realizată și nu este cerută pentru
această verificare. Campania este încheiată; ambele PPK rămân active.
Cele 315 perechi anterioare sunt neschimbate.

## Punctele cu recepție incompletă sau necunoscută din figura 3

- [x] **E07-400M10S:** punctul RX anterior cu 0/5 repetat la 32 B / GFSK 250 kbps / +10 dBm, cu **5/5 recepții și 10/10 capturi TX/RX verificate**, la 2 octombrie 2026.
- [x] **E07-900MM10S:** punctele TX/RX anterioare cu 0/5 repetate la 32 B / GFSK 250 kbps / +10 dBm / 915 MHz, cu **5/5 recepții și 10/10 capturi verificate**, la 2 octombrie 2026.
- [x] **nRF24L01 PA/LNA:** punctul de 32 B / 2 Mbps / 0 dBm la cip repetat cu **5/5 recepții și 10/10 capturi TX/RX verificate**, la 2 octombrie 2026. RX păstrează definiția de ascultare de mai jos.
- [x] **CC1101 V2 (868 MHz):** punctul TX anterior marcat `?` repetat la 32 B / 2FSK 250 kbps / +10 dBm, cu **5/5 recepții și 10/10 capturi TX/RX verificate**, la 2 octombrie 2026.

**CC1101 V2, punctul încheiat la 2 octombrie 2026:** configurație
32 B RF, 868 MHz, 2FSK/NONE/NRZ, 250 kbps, +10 dBm, preambul 128 biți,
DEV127/BW541,67, SYNC `D391`, CRC activ, sursă externă de 3,3 V.
TX COM32 → PPK COM10; RX COM31 → PPK COM11; numai radioul este măsurat.
După repornirea completă a ambelor ESP32 prin USB, confirmată de mesajele
de boot și fără rescrierea firmware-ului, reluarea a produs loturile
**4/5, 3/5 și 5/5**. Numai ultimul lot este acceptat; nu sunt combinate
pachete din loturi diferite. Cauza pierderilor intermitente rămâne
nedeterminată, iar lotul ales după repetare nu dovedește fiabilitate RF 100%.

Auditul confirmă **10/10 capturi, 724.992 eșantioane**, reproducere exactă
din WIRE, zero erori de contor, logică, bit rezervat sau gamă invalidă,
zero duplicate și zero pierderi estimate. Energia medie ± SD, n = 5:
**TX 198,775 ± 3,376 µJ**, fereastră prin prag de **3,980 ± 0,398 ms**;
**RX 264,363 ± 0,894 µJ**, fereastră convențională de **ascultare de 4,69 ms**.
Toate cele cinci repetări sunt incluse, inclusiv TX cu fereastra mai scurtă.
RX nu izolează energia exclusivă a recepției și nu este direct comparabil
cu intervalul RX istoric de 112,746 ms. Achizițiile sunt coordonate de PC,
fără sincronizare hardware; tensiunea nu este înregistrată simultan,
iar SD nu reprezintă precizia absolută a PPK.

[Rezultatele și proveniența](power_profiler/comparisons/cc1101_v2_868_paired_20261002/summary.json),
[agregatele CSV](power_profiler/comparisons/cc1101_v2_868_paired_20261002/aggregates.csv)
și [auditul numeric](power_profiler/comparisons/cc1101_v2_868_paired_20261002/audit.json)
sunt salvate separat de interpretările istorice. Sunt păstrate cele zece
capturi acceptate și fluxurile WIRE asociate. RAW/WIRE ale celor două loturi
incomplete din reluare au fost eliminate: **40 fișiere, 13.984.183 bytes**;
rapoartele și hashurile rămân. Ambele PPK sunt alimentate, cu porturile
deschise și eșantionare continuă. Toate cele patru puncte din această listă
sunt încheiate; comparația numerică E79 ESP32/CH340 rămâne separată.

**Istoric CC1101 V2, verificarea inițială din 2 octombrie 2026:** ambele module
răspund pe UART și raportează cipul `0x14`. Asocierea fizică prin variația
curentului la RX ON/OFF este **TX COM32 → PPK COM10**,
**RX COM31 → PPK COM11**, cu sursa externă de 3,3 V confirmată anterior;
numai radioul este măsurat prin PPK. Ținta este 32 B RF, 868 MHz,
2FSK/NONE/NRZ, 250 kbps, +10 dBm, preambul 128 biți, DEV127/BW541,67,
SYNC `D391`, CRC activ. Configurația citită coincide la ambele capete.

Cele patru loturi executate au **20/20 confirmări locale TX și 0/20
recepții**, fără niciun octet UART de payload la receptor. Primele trei
loturi au verificări înainte/după; al patrulea a fost oprit după cele cinci
capturi, înaintea verificării finale. Nu există un lot acceptat și nu se
publică energii pentru campanie. Punctul istoric `?` desemna absența
monitorizării receptorului, nu o nerecepție demonstrată în acel experiment.

[Probele RF separate](measurements/raw/sessions/20261002_163643_130385_cc1101_v2_868_paired/rf_controls_02.json)
au primit **0/14 pachete**: puteri +10/−30 dBm, viteze 250/38,4/1,2 kbps,
roluri inversate și o probă GFSK. Configurația țintă a fost restaurată.
Un răspuns lung `AT+CFG?` s-a trunchiat la 512 bytes în primul diagnostic;
probele următoare au folosit interogări scurte pentru fiecare parametru.
Aceasta nu demonstrează cauza lipsei recepției. Firmware-ul V2 folosește
GDO0 pe **GPIO10**, față de GPIO1 la E07; verificarea legăturilor este
solicitată operatorului. Cauza rămâne nedeterminată.

[Auditul tentativelor inițiale](measurements/raw/sessions/20261002_163643_130385_cc1101_v2_868_paired/initial_attempts_review.json)
păstrează verificarea UART, configurațiile și hashurile capturilor nereușite.
Au fost eliminate exact **80 fișiere RAW/WIRE, 28.027.057 bytes**, conform
[jurnalului de curățare](measurements/raw/sessions/20261002_163643_130385_cc1101_v2_868_paired/failed_capture_cleanup_execution.json);
rapoartele mici rămân, iar sesiunile validate anterior sunt păstrate.
Ambele PPK sunt active, cu porturile deschise și fluxurile citite continuu
de worker-ul pregătit pentru reluare, fără transmisii automate în așteptare.

**E07-900MM10S, punctele TX/RX încheiate la 2 octombrie 2026:** 32 B RF,
GFSK 250 kbps, +10 dBm la CC1101, 915 MHz, deviație 127 kHz, bandă RX
541,67 kHz, preambul 64 biți, SYNC `D391`, CRC activ. Sursa externă de
3,3 V confirmată anterior este păstrată; prin PPK este măsurat radioul,
fără ESP32. Asocierea prin variația curentului RX ON/OFF este
**TX COM30 → PPK COM10**, **RX COM29 → PPK COM11**. Ambele PPK au fost
activate înaintea accesului UART și au rămas deschise între pregătire și capturi.

**Primul lot a trecut 5/5**, cu 10/10 capturi și **720.896 eșantioane**.
Replay-ul independent și integrarea reproduc exact RAW și energiile;
zero erori de contor, logică, bit rezervat sau gamă invalidă, zero duplicate
și zero pierderi estimate. Transcrierile UART coincid cu octeții salvați;
configurația și versiunea cipului `0x14` sunt confirmate înainte și după lot.

Media ± SD pentru cinci transferuri: **TX 234,338 ± 1,422 µJ**, fereastră
prin prag de **3,036 ± 0,009 ms**; **RX 247,513 ± 0,821 µJ**, fereastră
convențională de **ascultare de 4,44 ms**, fără delimitare RF exclusivă.
Transferul bridge conține 30 caractere ASCII unice plus CRLF, în total 32 B RF;
modelul istoric `AT+TXBURST=32,32` avea alt conținut, cu aceeași lungime.
Achizițiile sunt coordonate de PC, fără sincronizare hardware; tensiunea
nu este înregistrată simultan, iar SD nu exprimă precizia absolută a PPK.

[Rezultatele și proveniența](power_profiler/comparisons/ebyte_e07_900mm10s_paired_20261002/summary.json),
[agregatele CSV](power_profiler/comparisons/ebyte_e07_900mm10s_paired_20261002/aggregates.csv),
[auditul independent](power_profiler/comparisons/ebyte_e07_900mm10s_paired_20261002/audit.json)
și [auditul istoricului decodorului](power_profiler/comparisons/ebyte_e07_900mm10s_paired_20261002/window_history_audit.json)
sunt salvate separat de rezultatele istorice. Sunt păstrate numai cele zece
capturi complete și fluxurile lor WIRE; nu au fost necesare loturi repetate.
PPK-urile au rămas alimentate și în achiziție continuă. Punctul CC1101 V2
a fost ulterior încheiat, conform rezultatului documentat mai sus.

**E07-400M10S, punctul încheiat la 2 octombrie 2026:** **32 B RF, GFSK
250 kbps, +10 dBm la CC1101, 433,92 MHz**, deviație 127 kHz, bandă RX
541,67 kHz, preambul 64 biți, SYNC `D391`, CRC activ. Sursa externă de
3,3 V confirmată anterior este păstrată; numai radioul este măsurat prin PPK.
Asocierea a fost verificată prin variația curentului la RX ON/OFF:
**TX COM28 → PPK COM10**, **RX COM27 → PPK COM11**.

Primul lot cu achiziție simultană a trecut integral: **5/5 transmisii și
recepții confirmate, 10/10 capturi, 723.968 eșantioane**. Replay-ul din WIRE
reproduce exact RAW și energiile; zero erori de contor, logică, bit rezervat
sau gamă invalidă, zero duplicate și zero pierderi estimate. Configurația și
identitatea cipului `0x14` au fost verificate înainte și după lot; citirile
parametrilor reprezintă configurația firmware, nu un dump complet al registrelor RF.

Media ± SD, cinci transferuri: **TX 174,063 ± 0,757 µJ**, fereastră prin prag
de curent de **3,044 ± 0,015 ms**; **RX 263,302 ± 0,528 µJ**, fereastră
convențională de **ascultare de 4,44 ms**. RX nu reprezintă energia exclusivă
a recepției RF. Achizițiile sunt coordonate de PC, fără sincronizare hardware;
tensiunea nu a fost măsurată simultan, iar SD nu exprimă incertitudinea
absolută a instrumentului. Pentru identificarea unică a fiecărui transfer,
bridge-ul a transmis 30 caractere ASCII plus CRLF, în total 32 B RF;
seria istorică folosea modelul fix de payload al `AT+TXBURST=32,32`.

[Rezultatele și proveniența](power_profiler/comparisons/ebyte_e07_400m10s_paired_20261002/summary.json),
[agregatele CSV](power_profiler/comparisons/ebyte_e07_400m10s_paired_20261002/aggregates.csv)
și [auditul independent](power_profiler/comparisons/ebyte_e07_400m10s_paired_20261002/audit.json)
sunt salvate separat de interpretările istorice.
[Auditul istoricului decodorului](power_profiler/comparisons/ebyte_e07_400m10s_paired_20261002/window_history_audit.json)
trece pentru toate cele zece ferestre fixe. Sunt păstrate numai RAW/WIRE ale
lotului complet; verificările RF preliminare au produs doar rapoarte mici,
fără capturi energetice. Ambele PPK rămân cu alimentarea activă și fluxurile
citite continuu. E07-900MM10S și CC1101 V2 sunt încheiate mai sus.

**nRF24 PA/LNA, punctul de măsurare încheiat la 2 octombrie 2026:** 32 B,
2 Mbps, 0 dBm la cip, canal 80, AUTOACK oprit, sursă externă de **3,3 V**
confirmată de operator. TX COM25 → PPK COM10; RX COM26 → PPK COM11.
PPK-urile măsoară radiourile, fără ESP32, și rămân cu porturile deschise,
alimentarea activă și fluxurile citite continuu după capturi.

S-au rulat **două loturi de câte cinci transferuri: 3/5, apoi 5/5**. Numai
al doilea lot intră în calcule; nu s-au combinat pachete din tentative diferite.
Cele **10 capturi RAW și fluxurile WIRE ale lotului acceptat** sunt păstrate.
RAW/WIRE din prima tentativă și din diagnosticul anterior cu 0/5 au fost
eliminate la cererea operatorului; rezumatele lor rămân disponibile.
Succesul lotului ales după repetare **nu demonstrează remedierea pierderilor
intermitente** și nu este o estimare a fiabilității legăturii; în această
reluare, totalul observat este 8/10. Diagnosticele anterioare rămân separate.

| Rezultat, media ± SD de eșantion, n = 5 | TX | RX |
|---|---:|---:|
| Energie totală | **104,694 ± 6,027 µJ** | **93,942 ± 0,129 µJ** |
| Durata ferestrei | 0,858 ± 0,146 ms | 1,160 ms |

TX folosește evenimentul delimitat prin prag de curent, conform metodei
istorice. RX reprezintă **energia ascultării într-o fereastră modelată de
1,16 ms**, începută la marcajul software local; nu izolează exclusiv recepția
RF. Cele două achiziții sunt coordonate de PC, fără sincronizare hardware.
Tensiunea nu a fost înregistrată simultan; SD descrie variația între cele
cinci transferuri, nu incertitudinea absolută a instrumentului.

[Calculele și proveniența](power_profiler/comparisons/nrf24_pa_paired_20261002/summary.json),
[tabelul agregat](power_profiler/comparisons/nrf24_pa_paired_20261002/aggregates.csv)
și [auditul independent](power_profiler/comparisons/nrf24_pa_paired_20261002/audit.json)
confirmă **10/10 capturi, 722.944 eșantioane**, fără erori de contor,
logică, bit rezervat sau gamă invalidă, fără duplicate, cu reproducere
exactă a curenților și energiilor din WIRE. Registrele radio efective au fost
verificate înainte și după fiecare lot; payloadurile și mesajele TX OK
coincid cu octeții UART arhivați.
[Auditul istoricului decodorului](power_profiler/comparisons/nrf24_pa_paired_20261002/window_history_audit.json)
trece pentru toate cele zece ferestre software fixe; nu dovedește fronturi RF
și nici invarianta selecției ferestrei TX la alte istorii de filtrare.
[Manifestul RAW/WIRE și al scripturilor](power_profiler/comparisons/nrf24_pa_paired_20261002/source_manifest.json)
permite verificarea surselor locale; RAW-urile rămân în directorul `web_sessions`,
exclus din Git.

[Rapoartele diagnosticelor anterioare](measurements/raw/sessions/20261002_130611_934700_nrf24_pa_diagnostic/diagnostic_summary.json)
nu intră în agregate; hashurile istorice descriu fișierele existente înainte
de curățarea documentată. Citirile istorice `0xFF` după eliberarea porturilor PPK,
fără alimentare efectivă confirmată, nu demonstrează o defecțiune SPI.

Se documentează cauza și orice remediere. Se păstrează seturile complete și
rapoartele tentativelor, iar RAW/WIRE nereușite urmează politica de curățare
de mai sus; lotul vechi rămâne separat în rezumate. `?` indică lipsa telemetriei,
nu o nerecepție demonstrată.

## Alimentarea

- [x] Alimentarea fizică a fost confirmată explicit de operator la
  **3 octombrie 2026**, conform [tabelului montajelor](PCB/TENSIUNI_ALIMENTARE.md):
  **20 de implementări la 3,3 V și 8 la 5 V**, cu PPK în serie prin jumpere.
- [x] [Auditul din 3 octombrie](power_profiler/audits/2026-10-03/supply-voltage/README.md)
  confirmă **8 neconcordanțe din 28 de implementări**: alimentare fizică
  de **5 V**, dar valoare de calcul **3300 mV** în toate cele **2.256 de
  capturi sursă**. Toate RAW-urile există; cele **432 de agregate packet**
  și **90 de rânduri continue publicate** provin din această cohortă.
- [ ] Corectarea rezultatelor numerice, a metadatelor și a descrierii din
  articol, cu documentarea limitelor reconversiei curentului.

Confirmarea operatorului înlocuiește presupunerea globală de 3,3 V;
RA-08 și RA-09 sunt confirmate la 3,3 V. Fișierul separat
`RA-08.kicad_sch` nu descrie platforma utilizată.

RAW-ul istoric păstrează curentul deja convertit; fluxul ADC/WIRE și
calibrarea originală nu sunt disponibile pentru o reconversie completă.
Tensiunea introdusă influența și decodorul de curent PPK, astfel că simpla
înmulțire a energiei cu 5/3,3 nu validează conversia inițială. Corecțiile
numerice rămân în așteptare; energiile nu au fost modificate de acest audit.
