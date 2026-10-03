# Neconcordanțe între alimentarea modulelor și calculele existente

Verificat la **3 octombrie 2026**, din fișierele existente și confirmarea
explicită a autorului privind montajul și alimentarea.

**Sunt confirmate opt neconcordanțe de tensiune:** aceste montaje sunt
alimentate la **5 V**, însă toate cele **2.256 de capturi canonice** ale
lor folosesc `voltage_mv=3300` în datele sursă. Valoarea greșită a fost
folosită în conversia curentului și în calculul energiei.

Autorul a confirmat că **PPK este montat în locul jumperului de măsurare,
în serie cu modulul radio**, iar tensiunea de alimentare este cea din
[tabelul alimentărilor](../../../../PCB/TENSIUNI_ALIMENTARE.md): 20 de
implementări la 3,3 V și opt la 5 V. Această confirmare stabilește referința
fizică pentru comparație și închide întrebarea despre montaj. Tensiunea
nu mai este tratată ca necunoscută. Fișierele de dovezi software/sesiune
păstrează observațiile făcute înaintea acestei confirmări; interpretarea
lor actuală este cea din prezentul raport și din `supply_reference.json`.

**Comparația acoperă toate cele 28 de implementări:** 20 sunt concordante
la 3,3 V, iar opt sunt neconcordante (alimentare 5 V, calcul 3,3 V).
[Matricea completă](all_modules.csv) leagă fiecare modul din tabel de
tensiunea folosită în calcule. Au fost verificate 8.511 rânduri sursă:
2.256 pentru cele opt neconcordanțe și 6.255 pentru celelalte 20 de
implementări. Acest verdict privește tensiunea; nu schimbă acceptarea
istorică a capturilor sau regulile de păstrare a RAW-urilor.

## Acoperirea verificării

| Modul / implementare | Alimentare confirmată | Tensiune folosită în calcul | Capturi TX | Capturi RX | Capturi continue TX/RX | RAW prezente |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ebyte E22-400M30S | 5 V | 3,3 V | 135 | 45 | 12 | 192/192 |
| Ebyte E280-2G4T12S | 5 V | 3,3 V | 135 | 45 | 12 | 192/192 |
| Ebyte E32-433T20D | 5 V | 3,3 V | 270 | 90 | 12 | 372/372 |
| Ebyte E32-433T33D | 5 V | 3,3 V | 270 | 90 | 12 | 372/372 |
| Ebyte E32-868T20D | 5 V | 3,3 V | 270 | 90 | 12 | 372/372 |
| Ebyte E32-868T30D | 5 V | 3,3 V | 270 | 90 | 12 | 372/372 |
| HC-12 | 5 V | 3,3 V | 135 | 45 | 12 | 192/192 |
| SX1278, placă tip Adafruit cu level shifter | 5 V la VIN-ul plăcii | 3,3 V | 135 | 45 | 12 | 192/192 |
| **Total** | | | **1.620** | **540** | **96** | **2.256/2.256** |

Cele 2.160 de capturi packet formează 432 de puncte agregate, cu cinci
repetări fiecare. Cele 96 de ferestre continue sunt alte observații, fără
a fi numărate încă o dată ca pachete. Exporturile de comparație conțin
**432 de puncte packet și 90 de rânduri continue**: la E32-868T30D sunt
publicate șase dintre cele 12 ferestre continue păstrate în sursă.
Toate cele 464 de fișiere de metadate de achiziție verificate indică modul
`ampere` și 3300 mV.

Selecția folosește [inventarul canonic din septembrie](../../2026-09-29/authoritative_coverage.csv),
care include recuperările acceptate și corecția de identificare
E32-433T20D pentru sesiunea denumită istoric `e32_868t20d`. Nu sunt adăugate
tentative respinse și nu se schimbă selecția capturilor.

## Ce demonstrează fișierele și codul

1. În rezumatele individuale, energia totală și energia peste baseline
   sunt `charge_uC × 3,3`. În ferestrele continue, puterea medie este
   `mean_current_uA × 3300 / 1.000.000`, iar energia este puterea înmulțită
   cu durata. **4.512 verificări numerice trec**, cu eroare relativă maximă
   de aproximativ `2,22e-16`. Separat, toate cele **432/432 de agregate
   packet publicate** coincid numeric cu mediile celor 2.160 de capturi
   sursă, prin asociere unică după direcție, payload și axele radio;
   abaterea relativă maximă este `2,22e-16`, iar deviațiile standard coincid.
2. Codul istoric [ppk.py](../../../../module%20radio/ESP32-C3_Radio/power_profiler/radio_power_profiler/ppk.py)
   setează `api.current_vdd = voltage_mv` înaintea conversiei eșantioanelor.
   Aceeași operație există în [codul actual](../../../radio_power_profiler/ppk.py).
   Parametrul este transmis decodorului; nu constituie o citire a tensiunii
   externe și nu comandă 3,3 V la ieșire în modul ampermetru.
3. Biblioteca `ppk2-api` include termenul `S[r] × V + I[r]` în
   calibrarea curentului, urmat de filtrarea dependentă de istoricul gamelor.
   Prin urmare, tensiunea influențează și curentul salvat, înainte de
   integrarea energiei. Versiunea mediului importat este păstrată în
   [metadatele importului](../../../../module%20radio/IMPORT_INFO/environment-metadata.json).
4. Interfața generică și CLI folosesc implicit 3300 mV. Exportatorul
   [generate_transfer_report.py](../../../tools/generate_transfer_report.py)
   copiază energiile deja calculate; nu rescrie o captură făcută cu 5000 mV
   ca și cum ar fi fost configurată la 3300 mV. Unele CSV-uri agregate
   omit coloana de tensiune, dar rezumatele sursă o păstrează.
5. Unele rapoarte vechi `VALIDATION.md` descriu aceste montaje drept
   alimentate extern la 3300 mV. Această descriere reproduce setarea
   software și contrazice alimentarea de 5 V confirmată de autor.
   În consecință, și descrierile respective necesită corectare.

## Ce se poate recalcula

RAW-urile istorice sunt CSV gzip cu coloanele
`sample_index,time_ms,current_uA,logic_bits,trigger`. Ele păstrează curentul
deja convertit. Nu oferă codurile ADC și gama fiecărui eșantion, iar
calibrarea specifică dispozitivului din momentul achiziției nu este salvată
în metadatele acestor campanii. În sesiunile verificate nu au fost găsite
fișiere WIRE pentru o reconversie completă.

Pentru cele **opt montaje alimentate la 5 V**, înmulțirea energiei și
puterii existente cu `5000 / 3300 = 1,515151…` reprezintă
**+51,515% față de valorile publicate**, păstrând curentul existent. Aceasta
corectează factorul de tensiune din integrare, dar nu și conversia inițială
a curentului. Nu poate fi prezentată drept recalculare completă, validată,
din ADC.

Tensiunea fizică este confirmată. Pentru o reconversie completă lipsesc
fluxul ADC cu informația de gamă, coeficienții originali și istoricul decodorului.
Coeficienții citiți acum de pe un PPK nu pot fi atribuiți automat vechilor
capturi. Nici o limită numerică a erorii de curent nu poate fi dedusă numai
din aceste CSV-uri.

Pentru cele **20 de implementări alimentate la 3,3 V**, valoarea de calcul
corectă este 3300 mV. Factorul 5/3,3 nu li se aplică. Confirmarea de tensiune
nu validează automat alte aspecte ale achiziției sau analizei.

Verificarea nu impune singură refacerea celor 2.256 de capturi. Datele de
livrare a pachetelor rămân observații ale montajului folosit. Necesitatea
unor măsurări suplimentare pentru energie depinde de precizia cerută și de
modul în care va fi tratată conversia istorică a curentului.

## Efect asupra studiului și starea rezultatelor

Sunt vizate energiile și puterile acestor opt implementări, inclusiv
comparațiile între E32, comparația variantelor SX1278 și graficele generale.
[Manuscrisul](../../../study/radio_module_energy_study.tex) descrie încă
global o tensiune înregistrată de 3,3 V, iar
[generatorul figurilor](../../../study/generate_study.py) are și etichete
fixe de 3,3 V. Pentru cele opt montaje de 5 V, aceste descrieri și rezultatele
energetice necesită corectare înaintea unei noi publicări.

Nu au fost rescrise capturi, exporturi numerice sau figuri. Tabelul
`PCB/TENSIUNI_ALIMENTARE.md` rămâne exclusiv tabel, conform cerinței autorului.
RA-08 și RA-09 sunt confirmate de autor la 3,3 V și nu fac parte din cele
opt implementări de mai sus.

## Dovezi și reproducere

- [supply_reference.json](supply_reference.json): cele 28 de tensiuni din
  tabel, confirmarea autorului și punctul de măsurare în serie cu radioul.
- [all_modules.csv](all_modules.csv) și [all_modules_summary.json](all_modules_summary.json):
  comparația completă, **20 concordante / 8 neconcordante**.
- [matching_3v3_evidence.json](matching_3v3_evidence.json): metadatele,
  rezumatele și verificările numerice pentru cele 20 de implementări de 3,3 V.
- [modules.csv](modules.csv): inventarul pe module.
- [evidence.json](evidence.json): asocierea celor 2.256 de rânduri cu RAW,
  verificările numerice și SHA-256 pentru cele 955 de fișiere de intrare,
  inclusiv confirmarea alimentării.
- [software_evidence.json](software_evidence.json): istoricul codului,
  conversia curentului, traseul parametrului și limitele formatului RAW.
- [session_evidence.json](session_evidence.json): verificarea legăturilor
  cu manifestele, recuperările și absența WIRE/calibrării în sesiunile sursă.
- [export_review.json](export_review.json): verificarea independentă a
  tuturor celor 432 de agregate packet publicate față de capturile sursă.
- [audit_supply_voltage.py](audit_supply_voltage.py): verificare reproductibilă,
  numai citire asupra surselor. Verifică existența RAW și un header per
  modul; nu repetă auditul integral gzip/CRC.

Din rădăcina repo-ului:

```powershell
.\power_profiler\.venv\Scripts\python.exe -X utf8 -B power_profiler/audits/2026-10-03/supply-voltage/audit_supply_voltage.py
```
