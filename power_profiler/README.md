# Măsurarea consumului modulelor radio cu Nordic PPK2

Capturile brute sunt centralizate local în `../measurements/raw/`, exclus din
Git. Interfața salvează în `sessions/`, comanda `run` în `packet/`, iar
`continuous` în `continuous/`. Arhiva veche este în `archive/`; calculele
publicabile rămân în `comparisons/`. [Structura datelor](../measurements/README.md).


Auditul și reanaliza din 29 septembrie 2026 sunt publicate în [audits/2026-09-29](audits/2026-09-29/README.md). [Auditul necesarului inițial](audits/2026-09-29/NECESAR_REVIZUIT.md) și [calculul E79 ESP32 final](audits/2026-09-29/e79-tx-corrected/README.md) documentează rezultatele folosite în exporturi. Arhiva RAW importată este externă Git; căile sale locale din rapoarte sunt păstrate pentru proveniență.

**Actualizare 30 septembrie:** cele 315 capturi noi sunt complete pe montajul **CH340**, cu DUT schimbat, și au fost [verificate independent din RAW](audits/2026-09-30/README.md). Ele formează o serie distinctă de CH9340C.

Acest folder este un proiect separat de firmware-ul PlatformIO principal. Programul de pe PC folosește interfața AT existentă a plăcii ESP32-C3, comandă Nordic Power Profiler Kit II în modul Ampere Meter și rulează automat o matrice de teste pentru fiecare modul radio.

Pentru fiecare combinație sunt variate:

- dimensiunea payload-ului predat radioului; preambulul/headerul/CRC-ul PHY nu sunt incluși în această valoare;
- puterea de transmisie sau treapta de putere expusă de modul;
- parametrul care influențează cel mai mult timpul pe aer: data rate pentru FSK/nRF24/CC1101, SF pentru LoRa și FU/air-rate pentru modulele UART;
- cinci repetări implicite, pentru medie și abatere standard.

Programul poate măsura separat TX sau RX. Calculează curentul de repaus, curentul mediu și maxim în eveniment, durata, sarcina electrică și energia pentru un pachet sau transfer fragmentat. Sunt raportate atât energia totală în fereastra măsurată, cât și energia suplimentară peste consumul de repaus.

## Ce module sunt incluse

Comanda `profiles` afișează catalogul complet. Sunt definite profile pentru toate selecțiile radio din proiect: CC1101 V1/V2, cele trei E07, HC-12, nRF24L01 și nRF24L01+PA, RA-01/RA-01H/RA-01SH/RA-02, E28, E22, E32 T20/T30/T33, E280, E79, XL1276-D01 și firmware-ul extern RA-08.

Profilele sunt date editabile în `radio_power_profiler/profiles.json`. Acolo pot fi schimbate valorile implicite, comenzile AT, limitele pachetului și timpul de răcire.

## Siguranță și montaj RF

Nu porni un test înainte de a verifica următoarele:

- PPK2 măsoară maximum 1 A. Oprește testul dacă modulul, în special unul de 30/33 dBm, poate depăși limita instrumentului sau a firelor.
- Tensiunea selectată trebuie să fie admisă de modulul testat. Implicit este 3,3 V.
- Alimentarea modulului trebuie să treacă numai prin traseul `VIN -> PPK2 -> VOUT`; elimină orice jumper sau traseu paralel direct către VCC-ul modulului.
- Leagă toate masele împreună.
- Montează o antenă potrivită sau, preferabil pentru banc, o sarcină RF de 50 Ω dimensionată pentru puterea modulului. Nu transmite fără sarcină RF.
- Folosește ecranare/atenuare și numai frecvențe, puteri și duty-cycle permise local. Testele produc emisii RF reale.
- Închide aplicația Power Profiler din nRF Connect înainte de script; numai un program poate deschide portul PPK2.

PPK2 lucrează la 100 kS/s, are domeniu configurabil 0,8–5,0 V și o limită de măsurare de 1 A, conform [ghidului Nordic PPK2](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_user_guide_intro.html).

### Montaj folosit: Ampere Meter

Placa pe care se află radioul furnizează alimentarea către `PPK2 VIN`, iar `PPK2 VOUT` alimentează modulul radio. PPK2 este inserat în serie:

```text
alimentare de pe placă (+) -> PPK2 VIN
PPK2 VOUT                -> VCC modul radio
GND placă                -> PPK2 GND -> GND modul radio
```

Jumperul/legătura originală dintre alimentarea plăcii și VCC-ul modulului trebuie eliminată, altfel curentul ocolește PPK2. Valoarea dată prin `--voltage-mv` este tensiunea reală prezentă la VIN și este folosită pentru calibrare și calculul energiei; PPK2 nu generează tensiunea. Programul activează traseul DUT pentru a închide circuitul VIN→VOUT înainte de configurare și îl menține activ între pași și după terminarea testului, evitând resetările modulului. Numai opțiunea explicită `--power-off-after-run` dezactivează traseul la final.

Pentru ambele variante, verifică să nu existe alimentare parazită prin GPIO atunci când modulul este oprit. Dacă apare, corectează montajul înainte de a considera consumul de repaus valid.

## Instalare pe Windows

Din acest folder:

```powershell
cd power_profiler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Biblioteca `ppk2-api` folosită pentru automatizare este [API-ul Python neoficial IRNAS](https://github.com/IRNAS/ppk2-api-python); aplicația Nordic rămâne utilă pentru verificarea vizuală a montajului.

## Pregătirea firmware-ului

În `src/main.cpp`, selectează modulul care va fi măsurat și varianta `AT_COMMANDS`, apoi încarcă firmware-ul pe ESP32-C3. Exemplu:

```cpp
#define RADIO_MODULE  RADIO_RA01_SX1278
#define RADIO_PROGRAM AT_COMMANDS
```

Pentru varianta fizică fără shield, firmware-ul compatibil rămâne
`RADIO_RA01_SX1278`, iar profilul de măsurare este `RADIO_SX1278_NAKED`
(`SX1278-Naked`).

Varianta cu shield folosește același firmware și profilul separat
`RADIO_SX1278_SHIELDED` (`SX1278-Shielded`), pentru comparații directe cu
varianta Naked.

Varianta montată pe un PCB purtător cu doi condensatori suplimentari folosește
tot firmware-ul `RADIO_RA01_SX1278`, dar are profilul separat
`RADIO_SX1278_PCB_2CAP` (`SX1278-PCB-2Cap`). Parametrii radio sunt identici cu
cei ai celorlalte variante SX1278, astfel încât diferențele de alimentare și RF
să poată fi comparate direct.

Plăcile Adafruit bazate pe același SX1278, dar care includ și un level shifter,
folosesc profilul separat `RADIO_SX1278_ADAFRUIT_LEVEL_SHIFTER`
(`SX1278-Adafruit-LevelShifter`). Parametrii radio rămân identici, iar separarea
profilului permite compararea influenței layout-ului și a level shifter-ului.

E79 și RA-08 necesită și firmware-ul AT propriu al modulului, conform documentației lor din repository.

## Interfață web pentru teste nesupravegheate

Interfața locală pornește din mediul virtual și nu necesită Flask sau alte
dependențe web:

```powershell
.\.venv\Scripts\python.exe .\run_web_ui.py
```

Se deschide implicit `http://127.0.0.1:8765/`. PC-ul trebuie să rămână pornit,
fără sleep/hibernare, iar procesul Python trebuie lăsat activ până la terminarea
jobului.

În VS Code poți porni serverul din **Tasks: Run Task → Radio profiler: Start web
interface**, apoi **Browser: Open Integrated Browser** și adresa
`http://127.0.0.1:8765/`. Dacă serverul este deja pornit, deschide doar adresa.
Task-ul este definit separat în `.vscode/tasks.json`; configurațiile PlatformIO
rămân disponibile.

Deschiderea paginii nu deschide porturi și nu activează alimentarea PPK2.
Secțiunea **Connected instruments** afișează porturile și seriile USB, inclusiv
PPK2 cu driverul Windows generic `USB Serial Device`. Porturile pentru un test
trebuie introduse explicit; nu se reutilizează automat cele de pe vechiul PC.

În **Power radios before initialization**, selectează cele două porturi PPK2
detectate și tensiunea reală de la VIN, apoi apasă **Enable current through both
PPK2** înainte de conectarea sau resetarea controlerelor radio. Butonul activează
trecerea `VIN → VOUT` în modul ampermetru, fără să necesite porturi radio sau să
modifice tensiunea sursei externe. **Release ports, keep power on** eliberează
porturile pentru alt script și lasă alimentarea activă. Pentru măsurare, asociază
corect PPK A/B cu TX/RX și completează tensiunea și în configurația testului;
activarea alimentării nu configurează automat campania.

**Puncte la 5 V:** secțiunea **Paired reference point** permite alegerea E22,
E280, E32-433T20D, E32-433T33D, E32-868T20D, E32-868T30D, HC-12
sau SX1278 pe placa tip Adafruit cu level shifter.
Pentru E32 rulează 19,2 kbps, cu +20 dBm pe T20D sau +30 dBm pe T33D/T30D, și verifică
configurația citită din modul, inclusiv UART la 115200 bps și FEC activ.
La T33D, +30 dBm folosește treapta 2 (`code 1`); treapta de +33 dBm nu intră
în acest punct de referință.
Pentru E32-868T20D și E32-868T30D verifică identificatorul de bandă `45` și canalul 6.
Acesta corespunde la 868 MHz conform planului `862 + CHAN` din
[manualul Ebyte, secțiunea 7.5](https://manualzz.com/doc/69984414/ebyte-e32-868t20d-user-manual).
Pentru E280 rulează presetul 2 Mbps/+12 dBm. Ambele modemuri folosesc 30 de octeți ASCII
plus CRLF adăugat de modem: 32 de octeți trimiși prin interfața transparentă.
Asocierea cu PPK se verifică prin sleep/wake. Livrarea exactă la RX confirmă
transferul; modemul transparent nu emite o confirmare TX separată și nu dovedește
numărul cadrelor PHY interne. Energia RX rămâne ascultare într-o fereastră modelată.

Pentru HC-12 rulează FU1, preset 250 kbps, +20 dBm, UART 9600 bps și canal 10.
Verifică separat răspunsurile modulului la `AT+RB`, `AT+RF`, `AT+RP` și `AT+RC`,
prin `AT+RAW`; `AT+CFG?` singur descrie configurația memorată de ESP32.
Canalul 10 corespunde nominal la 437,0 MHz, conform pasului de 400 kHz pornind
de la canalul 1 = 433,4 MHz din
[manualul producătorului HC-12](https://www.hc01.com/downloads/HC-12%20english%20datasheets.pdf).
Frecvența afișată de firmware la `AT+CFG?` are un decalaj de +0,4 MHz;
achiziția folosește canalul citit direct din modul, fără modificarea firmware-ului.

Pentru SX1278 cu level shifter configurează 433 MHz, SF7, BW 125 kHz, CR 4/5,
+20 dBm și preambul de 8 simboluri, CRC activ, header explicit, sync 0x14,
gain 1, IQ normal și FHSS oprit. Verifică configurația raportată înaintea lotului.
TX rămâne în standby între pachete, RX în ascultare; fiecare transfer necesită
confirmarea `[SX1278] TX OK` și payloadul exact la receptor. Sunt 32 de octeți
payload RF, fără CRLF suplimentar; RX păstrează fereastra modelată de ascultare.

Pentru E22 rulează punctul de 32 B,
SF7/BW125/CR4/5, +18 dBm înaintea PA, cu cinci perechi TX/RX simultane.
Folosește cele două PPK A/B, verifică asocierea prin variația curentului la
activarea RX și setează 5000 mV înainte de decodarea curentului. Validează
configurația AT, livrarea exactă a fiecărui payload și replay-ul WIRE.
Încearcă cel mult trei loturi complete; RAW/WIRE din loturile dovedite
nereușite sunt eliminate, iar rapoartele mici și controalele intenționate de
asociere rămân. Energia RX descrie ascultarea într-o fereastră modelată;
nu este o măsurare separată a recepției RF. Rezultatele sunt în sesiunea
afișată de interfață, sub `measurements/raw/sessions/`.

**Campaniile E79 încheiate:** panoul temporar pentru pilot, campanii simultane
și reluarea acestora a fost eliminat din interfață. Capturile complete,
calculele și dovezile rămân păstrate; analiza offline și runner-ul CLI rămân
disponibile pentru reproducerea rezultatelor. Conexiunile și marcajele locale
sunt documentate în [ghidul DIO17](audits/2026-10-01/e79-markers/README.md).
Pentru datele salvate, `tools/summarize_paired_campaign.py` și
`tools/summarize_fragmented_campaign.py` generează agregatele din manifest.
Validarea formatului E79 este separată în `radio_power_profiler/paired_validation.py`.

Cele opt puncte de referință la 5 V sunt complete: 40 de perechi TX/RX și
80 de capturi, plus un lot T33D complet păstrat separat. Rapoartele și
locațiile RAW sunt în [ghidul măsurătorilor](../measurements/README.md).

Pentru verificarea celor două PPK2 fără module radio, din `power_profiler`:

```powershell
.\.venv\Scripts\python.exe -m radio_power_profiler ports
.\.venv\Scripts\python.exe tools\check_dual_ppk.py --tx-ppk-port COM10 --rx-ppk-port COM11 --capture-seconds 3 --output diagnostics\dual-ppk-check.json
```

Înlocuiește porturile cu cele detectate și folosește un nume nou pentru fiecare
raport. Fără `--capture-seconds`, utilitarul citește doar metadatele. Nu transmite
comenzi radio și nu comută ieșirea DUT; selectează modul ampermetru, oprește
eșantionarea existentă și închide ambele porturi la final. Parametrii
`--tx-voltage-mv` și `--rx-voltage-mv` reprezintă tensiunile externe folosite
pentru conversia curentului, fără a genera tensiune. Cu instrumentele fără
sarcină, testul confirmă comunicarea și fluxurile de date, nu precizia energetică
a montajului. Rolurile TX/RX sunt etichete ale testului; asocierea fizică se face
după seria de pe cablul fiecărui PPK2. Ceasurile instrumentelor sunt independente.

Cele două fluxuri principale sunt:

- **Check rapid**: TX și RX la viteza maximă plus TX și RX fragmentat la viteza
  minimă. Salvează automat trace-urile raw și produce un verdict pentru vârful
  de curent, recepție, sample loss și disponibilitatea campaniei lungi.
- **Campanie completă**: împarte matricea în loturi independente și recuperabile,
  rulează TX pentru toate puterile/vitezele/dimensiunile, RX la puterea maximă a
  emițătorului și testele continue TX/RX de putere medie și loss-vs-viteză.
  `no_event_detected`, erorile de proces și rezultatele incomplete sunt
  reîncercate; `rx_missing` rămâne loss măsurat și nu este ascuns prin retry.

Fiecare sesiune este salvată sub `web_sessions/<timestamp>_<tip>_<profil>/`:

- `manifest.json` conține configurația, progresul, toate încercările, verdictul
  check-ului și directorul acceptat pentru fiecare lot;
- `session.log` conține jurnalul cronologic complet;
- `logs/<pas>_attempt_<n>.log` păstrează ieșirea integrală a fiecărui subprocess,
  inclusiv a încercărilor respinse;
- directoarele `packet_tx`, `packet_rx`, `packet_results` și `continuous` conțin
  datele produse de profiler. Încercările eșuate nu sunt șterse.

Dacă serverul este pornit dintr-un thread Codex activ, opțiunea
`Notify Codex and continue this thread when the test finishes` este activată
automat. La final, orchestratorul folosește ID-ul explicit al threadului și
`codex exec resume` pentru a trimite promptul de analiză în aceeași conversație.
După ce callback-ul se încheie cu succes, serverul deschide ruta locală a
threadului în extensia Codex pentru VS Code, aducând fereastra și conversația în
prim-plan.
Callback-ul rulează în două etape: publică mai întâi un mesaj scurt în conversație,
apoi pornește analiza completă și revine cu verdictul și prelucrarea rezultatelor.
Astfel, finalizarea măsurătorilor devine vizibilă fără a aștepta analiza de durată.
Callback-ul are maximum trei încercări pentru fiecare etapă, iar ieșirea completă este păstrată în
`codex_callback.log` în directorul sesiunii. Dacă ID-ul threadului sau Codex CLI
nu este disponibil, opțiunea este dezactivată în interfață.

Trace-urile PPK2 raw ale campaniei complete sunt activate implicit și pot fi
dezactivate din interfață. La 100 kS/s pot ocupa zeci de GB; fără ele rămân salvate toate logurile,
`metadata.json`, `summary.csv` și `aggregates.csv`. Butonul de oprire termină
subprocesul activ, păstrează loturile finalizate și încearcă să dezactiveze
alimentarea DUT din PPK2.

Serverul poate fi pornit și prin CLI, fără deschiderea automată a browserului:

```powershell
python -m radio_power_profiler web --no-browser --port 8765
```

## Utilizare

1. Identifică porturile:

```powershell
python -m radio_power_profiler ports
python -m radio_power_profiler profiles
```

2. Inspectează matricea înainte de test:

```powershell
python -m radio_power_profiler plan --module RADIO_SX1278_NAKED
```

3. Rulează testul în montaj Ampere Meter:

```powershell
python -m radio_power_profiler run `
  --module RADIO_SX1278_NAKED `
  --radio-port COM4 `
  --receiver-port COM5 `
  --ppk-port COM7 `
  --voltage-mv 3300
```

Dacă este conectat un singur PPK2, `--ppk-port` poate fi omis.

### Test de consum în recepție

În modul RX, `--radio-port` este întotdeauna receptorul măsurat și alimentat prin
PPK2, iar `--transmitter-port` este al doilea modul, alimentat separat, care
generează pachetele de stimul. Ambele module trebuie să folosească același profil
și același firmware AT.

```powershell
python -m radio_power_profiler plan `
  --module RADIO_CC1101_V2_868 `
  --direction rx

python -m radio_power_profiler run `
  --module RADIO_CC1101_V2_868 `
  --direction rx `
  --radio-port COM4 `
  --transmitter-port COM5 `
  --ppk-port COM7 `
  --voltage-mv 3300
```

În protocolul curent, receptorul este activat înainte de captură, iar baseline-ul
pretrigger este RX fără trafic. Energia RX este integrată într-o fereastră cu
durata airtime modelată, începând la trigger; nu include automat pornirea,
oprirea receptorului sau toate pauzele dintre cadre. Campaniile CC1101 istorice
din 17 iulie foloseau activarea RX în trigger și un alt protocol de integrare;
interpretarea lor se păstrează după versiunea și metadatele sesiunii.
Puterea de transmisie din matrice este puterea modulului de stimul, nu o setare
care ar modifica lanțul RX al dispozitivului măsurat.

Pentru TX cu `align_tx_airtime_window`, transferurile fragmentate folosesc câte
o fereastră de airtime modelat pentru fiecare cadru detectat în RAW-ul complet.
Pauzele dintre comenzi nu sunt incluse în suma energiilor cadrelor. Numărul
cadrelor, geometria și sensibilitatea segmentării trebuie să treacă verificările;
altfel rezultatul este `analysis_review_required`, fără energie publicabilă.
Ferestrele și diagnosticele sunt salvate pentru verificare. Folosiți `--save-raw`
pentru campaniile noi; o captură cu eroare de analiză este păstrată automat și
când opțiunea nu a fost activată.

Pentru un test scurt, axele și dimensiunile pot fi suprascrise fără editarea catalogului:

```powershell
python -m radio_power_profiler run `
  --module RADIO_NRF24L01 `
  --radio-port COM8 `
  --sizes 8,32 `
  --repetitions 3 `
  --axis "tx_power_dbm=-18,0" `
  --axis "data_rate_kbps=250,2000"
```

### Putere medie în flux continuu

Comanda `continuous` repetă cadre radio pe o fereastră de 60 s și calculează
curentul mediu, puterea electrică medie la tensiunea declarată, energia ferestrei
și variația curentului. Implicit sunt testate puterile `-30/0/10 dBm`, cu cadre
de 32 B la 38,4 kbps și 15 ms între cadre.

```powershell
python -m radio_power_profiler continuous `
  --module RADIO_CC1101_V2_868 `
  --direction tx `
  --radio-port COM12 `
  --ppk-port COM11 `
  --voltage-mv 3300

python -m radio_power_profiler continuous `
  --module RADIO_CC1101_V2_868 `
  --direction rx `
  --radio-port COM12 `
  --transmitter-port COM16 `
  --ppk-port COM11 `
  --voltage-mv 3300
```

În RX, `--radio-port` este receptorul măsurat, iar `--transmitter-port` generează
fluxul. Rezultatele incrementale sunt scrise în `../measurements/raw/continuous/*/summary.csv`.

Profilul `RADIO_EBYTE_E79_CC1352P` folosește o buclă host-driven de comenzi
`AT+SEND` pentru fluxul continuu și transferuri logice fragmentate în cadre de
maximum 64 B. Firmware-ul E79 0.3.0 expune șapte profiluri RF între 2,5 și
200 kbps: `GFSK4K8`, `GFSK50`, `GFSK200`, `SLR2K5`, `SLR5`, `OOK4K8` și
`IEEE154G50`. Campania selectează explicit fiecare profil cu `AT+PROFILE`, astfel
încât variantele cu aceeași viteză, dar modulații diferite, rămân puncte de
măsurare distincte în CSV, Excel și graficele loss-vs-viteză.

Opțiunea `--save-raw` salvează fiecare formă de undă la 100 kS/s în `raw/*.csv.gz`. Este dezactivată implicit, deoarece o matrice completă poate ocupa mult spațiu.

## Rezultate

Fiecare sesiune primește un folder propriu sub `results/`:

- `metadata.json`: profilul complet, porturile, tensiunea și rata de eșantionare;
- `summary.csv`: câte un rând pentru fiecare transfer TX sau RX; este scris incremental și rămâne utilizabil după o întrerupere;
- `aggregates.csv`: medii și abateri standard pentru fiecare combinație;
- `raw/*.csv.gz`: formele de undă, numai cu `--save-raw`.

Câmpurile principale sunt:

- `measurement_direction`: `tx` sau `rx`;
- `event_peak_uA` și `event_mean_uA`: vârf și medie generică în evenimentul detectat;
- `rx_peak_uA` și `rx_mean_uA`: valorile explicite pentru sesiunile RX; câmpurile istorice `tx_*` sunt păstrate ca aliasuri pentru compatibilitatea rapoartelor;
- `charge_total_uC`, `energy_total_uJ`: consum total în fereastra evenimentului;
- `charge_excess_uC`, `energy_excess_uJ`: partea peste baseline;
- `event_duration_ms`: durata detectată;
- `sample_loss_percent`: indicator că PC-ul nu a preluat toate eșantioanele;
- `status`: `ok`, `no_event_detected`, `rx_missing` sau `radio_error`.
- `packet_received`: confirmarea că receptorul a livrat toate cadrele așteptate; este obligatorie în sesiunile RX și opțională în sesiunile TX cu `--receiver-port`.

Dimensiunea cerută este numărul de octeți din payload-ul predat radioului, înainte de framing-ul PHY. Pentru firmware-urile care adaugă `CRLF` în payload, programul generează automat cu doi octeți mai puțin în conținut, astfel încât valorile de 8/32/64 B să rămână comparabile.

Pentru CC1101, transferurile logice mai mari de 64 B sunt fragmentate în cadre
fizice de câte 64 B. Astfel, 128/512/1024 B sunt măsurate ca rafale de
2/8/16 cadre. Coloanele `frame_count` și `max_frame_payload_bytes` păstrează
această distincție explicită în `summary.csv` și `aggregates.csv`; energia este
integrată pe întreaga rafală, inclusiv overhead-ul și tranzițiile fiecărui cadru.
Rafala este generată local de firmware prin `AT+TXBURST`, astfel încât bufferul
USB CDC nu poate pierde cadre la viteze radio mici.

## Alegeri experimentale

- nRF24 are Auto ACK dezactivat implicit. Fără un receptor, ACK/retry ar transforma un test de „un pachet” într-o serie necunoscută de retransmisii. Un studiu separat ACK/retry trebuie făcut cu receptor controlat.
- Pentru LoRa este variat SF la bandwidth fix. Pentru a studia și bandwidth, suprascrie axa, de exemplu `--axis "bandwidth_khz=125,250,500"`.
- Frecvența este ținută constantă: are de regulă impact mult mai mic asupra energiei decât puterea și timpul pe aer, iar schimbarea ei complică legalitatea și adaptarea RF.
- Compară modulele la aceeași tensiune, temperatură, sarcină RF, lungime de cablu și stare de repaus. Un rezultat care include placa ESP32 nu este direct comparabil cu unul care măsoară numai rail-ul modulului.
- Detectorul de eveniment folosește baseline robust și prag specific profilului. Dacă `status=no_event_detected`, salvează raw trace, inspectează montajul și ajustează `threshold_margin_uA` în profil.
- Energia este calculată ca sarcină × valoarea `--voltage-mv`; programul nu măsoară variația instantanee a tensiunii. Pentru module cu cădere importantă pe alimentare, măsoară tensiunea la modul și folosește valoarea reală.

## Teste software

Testele nu necesită hardware:

```powershell
python -m unittest discover -s tests -v
```
