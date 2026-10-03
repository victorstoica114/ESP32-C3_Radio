# Datele măsurătorilor

Toate capturile PPK sunt păstrate local în `raw/`, exclus din Git.

| Folder | Conținut |
| --- | --- |
| `raw/archive/` | Campaniile vechi importate, cu rezultatele și metadatele originale |
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

Codul de achiziție este în `../power_profiler/radio_power_profiler/`, scripturile
de analiză în `../power_profiler/tools/`, rezultatele publicabile în
`../power_profiler/comparisons/`, auditurile în `../power_profiler/audits/`, iar
articolul și figurile în `../power_profiler/study/`.
