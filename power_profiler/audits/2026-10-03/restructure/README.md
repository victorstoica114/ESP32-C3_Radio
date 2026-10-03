# Centralizarea capturilor — 3 octombrie 2026

Capturile locale sunt centralizate în [`measurements/raw/`](../../../../measurements/raw/).
Structura și destinațiile noilor achiziții sunt descrise în
[ghidul datelor](../../../../measurements/README.md).

Au fost mutate 21.391 de fișiere și au fost verificate integral prin SHA-256
față de inventarul anterior mutării. Cele 8.908 fișiere inițiale de captură
au 8.903 destinații păstrate; cinci copii dintr-un folder temporar au fost
eliminate numai după verificarea identității cu destinațiile lor.
Manifestul local `measurements/relocation.json` păstrează căile vechi, căile
noi și hashurile. Mostrele, calibrările, manifestele sursă și rezultatele
numerice nu au fost rescrise.

Au fost eliminate copia importată a proiectului, după păstrarea datelor și
verificarea că istoricul principal conține commit-ul sursă `11f296e`, pachetele
locale de actualizare PPK, notele despre versiunile PPK și logurile/snapshoturile
temporare ale browserului. Documentația marcajelor E79 și dovezile relevante
au fost mutate în `audits/2026-10-01/e79-markers/`.

Verificarea finală confirmă:

- Toate cele 8.903 fișiere RAW/WIRE sunt sub `measurements/raw/` și sunt ignorate
  de Git. Cele cinci RAW anterior urmărite au fost scoase din index.
- Toate cele 2.256 de capturi din auditul tensiunilor și rezumatele lor se
  găsesc prin noile căi.
- Campania E79/ESP32 reproduce 105/105 perechi și aceleași 42 de agregate CSV.
- Un lot real E79/ESP32 reproduce independent toate cele zece capturi RAW/WIRE
  și energiile/sarcinile salvate.
- 427 de teste software au trecut.

Inventarele detaliate ale operației sunt locale în `.tmp/restructure/`.
Căile din rapoartele istorice care sunt legate de hashuri rămân identificatori
originali; scripturile le traduc la citire, fără modificarea dovezilor.

## Curățarea suplimentară

Au fost eliminate cele 24 de copii din `power_profiler/continuous_results/`
și `power_profiler/loss_results/`, după verificarea identității SHA-256 cu
fișierele păstrate în `measurements/raw/archive/`. Generatoarele de rapoarte
rezolvă în continuare căile vechi. Au fost eliminate și directoarele `include/`
și `lib/`, care conțineau numai README-urile standard PlatformIO.

Cele opt teste pentru căi și cele 16 teste pentru rapoarte au trecut.
Inventarul copiilor eliminate este în
`.tmp/restructure/summary-cleanup-receipt.json`.
