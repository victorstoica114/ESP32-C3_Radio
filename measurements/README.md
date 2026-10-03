# Datele măsurătorilor

Toate capturile PPK sunt păstrate local în `raw/`, exclus din Git.

| Folder | Conținut |
| --- | --- |
| `raw/archive/` | Campaniile vechi importate, cu rezultatele și metadatele de achiziție |
| `raw/sessions/` | Campaniile recente și cele noi pornite din interfață |
| `raw/packet/` | Capturi noi pornite cu comanda `run` |
| `raw/continuous/` | Capturi noi pornite cu comanda `continuous` |
| `raw/diagnostics/` | Capturi de diagnostic păstrate separat de campaniile acceptate |

Fișierele `raw/*.csv.gz` conțin mostrele de curent și marcajele digitale.
Fișierele `wire/*.ppk2.bin` conțin fluxul original PPK2, unde a fost salvat.
Arhiva istorică nu are WIRE pentru fiecare captură.

Manifestele, calibrările și rezumatele rămân lângă capturile lor. Mutarea nu
modifică mostrele sau rezultatele numerice. `relocation.json`, păstrat numai
local, înregistrează căile vechi, căile noi și hashurile capturilor. Scripturile
traduc căile istorice la citire, fără rescrierea dovezilor originale.

La 3 octombrie 2026 au fost curățate adnotările instrumentului din fișierele
text și din copiile de surse asociate măsurătorilor. Hashurile fișierelor
revizuite au fost actualizate; mostrele RAW/WIRE, calibrările și rezultatele
numerice au rămas identice. Detaliile sunt în
[raportul de curățare](../power_profiler/audits/2026-10-03/metadata-cleanup/README.md).

Codul de achiziție este în `../power_profiler/radio_power_profiler/`, scripturile
de analiză în `../power_profiler/tools/`, rezultatele publicabile în
`../power_profiler/comparisons/`, auditurile în `../power_profiler/audits/`, iar
articolul și figurile în `../power_profiler/study/`.

## Punctele de referință la 5 V

Etapa de 32 B din 3 octombrie 2026 este completă: opt montaje, 40 de perechi
TX/RX și 80 de capturi. Se păstrează separat încă un lot complet E32-433T33D,
fără combinarea agregatelor. Rapoartele includ configurația, energia, limitele
ferestrei RX și căile exacte către RAW/WIRE locale.

| Montaj | Rezultate |
| --- | --- |
| E22-400M30S | [Raport](../power_profiler/comparisons/ebyte_e22_paired_20261003/README.md) |
| E280-2G4T12S | [Raport](../power_profiler/comparisons/ebyte_e280_paired_20261003/README.md) |
| E32-433T20D | [Raport](../power_profiler/comparisons/ebyte_e32_433t20d_paired_20261003/README.md) |
| E32-433T33D | [Lot principal](../power_profiler/comparisons/ebyte_e32_433t33d_reversed_paired_20261003/README.md) · [Lot păstrat separat](../power_profiler/comparisons/ebyte_e32_433t33d_paired_20261003/README.md) |
| E32-868T20D | [Raport](../power_profiler/comparisons/ebyte_e32_868t20d_paired_20261003/README.md) |
| E32-868T30D | [Raport](../power_profiler/comparisons/ebyte_e32_868t30d_paired_20261003/README.md) |
| HC-12 | [Raport](../power_profiler/comparisons/hc12_paired_20261003/README.md) |
| SX1278, placă tip Adafruit cu level shifter | [Raport](../power_profiler/comparisons/sx1278_adafruit_paired_20261003/README.md) |
