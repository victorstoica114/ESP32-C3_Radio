# PCB

Acest director contine fisierele KiCad pentru adaptoarele radio folosite in
proiectul ESP32-C3 Radio.

## Continut

- `module_radio.kicad_pro`, `module_radio.kicad_sch` si
  `module_radio.kicad_pcb`: proiectul KiCad principal.
- `*.kicad_sch`: foi de schema pentru modulele radio individuale.
- `Librarys/`: simboluri, footprint-uri si modele 3D folosite de proiect.
- `Pictures/`: randari/poze ale cablajelor, afisate mai jos.
- `Gerbers/`: exporturi Gerber arhivate local. Acest director este tratat ca
  artefact generat si este ignorat de Git; pentru distributie publica este mai
  potrivit sa fie publicat ca release asset.

Fisierele locale generate de KiCad, cum ar fi `fp-info-cache`, `*.kicad_prl`,
`untitled.kicad_sch` si `desktop.ini`, sunt ignorate.

## Poze cablaje

| Modul | Poza |
| --- | --- |
| Ai-Thinker-Ra-01 | <img src="Pictures/Ai-Thinker-Ra-01.png" width="220" alt="Ai-Thinker-Ra-01"> |
| Ai-Thinker-Ra-02 | <img src="Pictures/Ai-Thinker-Ra-02.png" width="220" alt="Ai-Thinker-Ra-02"> |
| CC1101 | <img src="Pictures/CC1101.png" width="220" alt="CC1101"> |
| E07_400M10S | <img src="Pictures/E07_400M10S.png" width="220" alt="E07_400M10S"> |
| E07_433M20S | <img src="Pictures/E07_433M20S.png" width="220" alt="E07_433M20S"> |
| E07_900MM10S | <img src="Pictures/E07_900MM10S.png" width="220" alt="E07_900MM10S"> |
| E22 (SX1262) | <img src="Pictures/E22%20(SX1262).png" width="220" alt="E22 (SX1262)"> |
| E280 | <img src="Pictures/E280.png" width="220" alt="E280"> |
| E32-433T20D | <img src="Pictures/E32-433T20D.png" width="220" alt="E32-433T20D"> |
| E32-433T33D | <img src="Pictures/E32-433T33D.png" width="220" alt="E32-433T33D"> |
| E79-400DM2005S | <img src="Pictures/E79-400DM2005S.png" width="220" alt="E79-400DM2005S"> |
| E79-400DM2005S_V2.0 | <img src="Pictures/E79-400DM2005S_V2.0.png" width="220" alt="E79-400DM2005S_V2.0"> |
| Ebyte-E28 | <img src="Pictures/Ebyte-E28.png" width="220" alt="Ebyte-E28"> |
| Ebyte-E79 | <img src="Pictures/Ebyte-E79.png" width="220" alt="Ebyte-E79"> |
| HC-12 | <img src="Pictures/HC-12.png" width="220" alt="HC-12"> |
| NRF24L01 | <img src="Pictures/NRF24L01.png" width="220" alt="NRF24L01"> |
| nRF24L01-PA-LNA | <img src="Pictures/nRF24L01-PA-LNA.png" width="220" alt="nRF24L01-PA-LNA"> |
| RA-01 | <img src="Pictures/RA-01.png" width="220" alt="RA-01"> |
| RA-02 | <img src="Pictures/RA-02.png" width="220" alt="RA-02"> |
| RA-09 | <img src="Pictures/RA-09.png" width="220" alt="RA-09"> |
| RFM69HCW | <img src="Pictures/RFM69HCW.png" width="220" alt="RFM69HCW"> |
| SX127X | <img src="Pictures/SX127X.png" width="220" alt="SX127X"> |
| TI-CC1101 | <img src="Pictures/TI-CC1101.png" width="220" alt="TI-CC1101"> |
| XL1276-D01 | <img src="Pictures/XL1276-D01.png" width="220" alt="XL1276-D01"> |

## Acoperire poze vs Gerbers

Comparatia de mai jos este facuta pe numele fisierului, fara extensie:
`PCB/Gerbers/*.zip` vs `PCB/Pictures/*.png`.

Rezumat local curent:

- Gerbere: 25 arhive `.zip`.
- Poze: 24 fisiere `.png`.
- Potriviri exacte dupa nume: 24.

Gerbere care nu au poza cu acelasi nume:

- `E32-433T20D_V2`

Poze care nu au Gerber cu acelasi nume:

Nu exista in acest moment.
