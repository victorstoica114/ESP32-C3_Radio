**Acoperirea RAW și necesarul de lucru — 29 septembrie 2026**

**Actualizare 30 septembrie:** [315 capturi CH340 verificate independent](../2026-09-30/README.md). Campania a folosit alte adaptoare și alt DUT decât planul istoric CH9340C; cele două contexte rămân distincte. Planurile de mai jos nu reprezintă o solicitare automată de noi capturi.

Acest director publică rapoartele, inventarele și calculele derivate ale auditului. Arhiva RAW importată nu este inclusă în Git: sursele experimentale se află separat, local, în `measurements/raw/archive`. Căile absolute și relative din JSON/CSV sunt păstrate ca identificatori de proveniență ai acelei arhive; nu reprezintă fișiere distribuite în acest director. Reproducerea din eșantioane necesită acces separat la arhiva RAW. Rezultatele curente sunt [NECESAR_REVIZUIT.md](NECESAR_REVIZUIT.md) și [e79-tx-corrected](e79-tx-corrected/README.md); `e79-tx-reanalysis` păstrează screeningul istoric, înlocuit de calculul final.

**Current result: completed reanalysis of all 630 E79 ESP32 TX captures; no pending segmentation cases. The current hardware plan is 315 E79 CH9340C TX captures. See [the final calculation](e79-tx-corrected/README.md) and [current plan](NECESAR_REVIZUIT.md).**

**Inventarul verificat**

Referința este matricea publicată pentru 28 de variante: 8.220 de măsurători packet. Au fost corelate exporturile, sesiunile sursă, metadatele, manifestele și înlocuirile din `recovery_overrides.json`. Tentativele înlocuite nu sunt numărate ca lipsuri ale campaniei acceptate.

Au fost citite integral toate cele **6.278 de fișiere RAW gzip**: CRC/trailer, header CSV, număr de rânduri față de summary și indicii de început/sfârșit. **6.277 sunt valide; unul este trunchiat într-o tentativă înlocuită. Toate cele 5.424 de capturi acceptate ale celor 21 de campanii cu RAW sunt prezente și valide la nivel de fișier:** 3.870 packet TX, 1.290 packet RX, 63 continuous TX, 201 continuous RX.

Verificarea integrală a parcurs 33.235.292.883 bytes comprimați, 188.188.276.772 bytes decomprimați și 4.769.930.208 rânduri de eșantioane. Ea nu a verificat individual toate valorile numerice interioare și nu certifică metoda de integrare. Dovezile sunt în [raw-full-integrity-summary.json](raw-full-integrity-summary.json), [raw-full-integrity.jsonl](raw-full-integrity.jsonl) și [authoritative_coverage.json](authoritative_coverage.json).

**RAW nesalvat pentru rezultate publicate**

| Modul / context | TX | RX | Total packet |
| --- | ---: | ---: | ---: |
| CC1101 V1, 433 MHz | 270 | 90 | 360 |
| CC1101 V2, 868 MHz | 270 | 90 | 360 |
| E07-400M10S | 135 | 135 | 270 |
| E07-433M20S | 135 | 135 | 270 |
| E07-900MM10S | 135 | 135 | 270 |
| E79 prin CH9340C | 630 | 630 | 1.260 |
| RA-09 / STM32WLE5 | 135 | 135 | 270 |
| **Total** | **1.710** | **1.350** | **3.060** |

Cele 14 sesiuni packet sursă au `save_raw=false`; summary și agregatele există. Concordanța sursă–export a fost verificată pe matrice, repetări și energie medie. Nu sunt fișiere eliminate la curățare. Capturile ESP32 nu substituie hardware-ul/contextul CH9340C; pilotul CC1101 V2 nu substituie campania sa publicată.

Parametrii exacți și sesiunile fiecărei repetări sunt în [missing_packet_runs.csv](missing_packet_runs.csv). Gruparea pe cele 612 configurații este în [missing_packet_conditions.csv](missing_packet_conditions.csv), iar acoperirea celor 28 de variante în [acoperire_28_module.csv](acoperire_28_module.csv).

Mai lipsesc RAW-urile a **27 de ferestre continue istorice de 60 s**: 12 CC1101 V1 și 15 CC1101 V2, însumând 24 de condiții distincte. Rezumatele există; nu cer repetare doar pentru completarea arhivei. Vezi [missing_continuous_runs.csv](missing_continuous_runs.csv) și [analiza protocolului RX/continuous](rx-interpretation-review.md). Baseline-ul se identifică după sesiune: vechile CC1101 activau RX după baseline, sesiunile moderne înaintea capturii.

Singurul RAW trunchiat aparține tentativei oprite RA-01H `20260719_155301`, TX 32 B, SF7/BW125, +2 dBm, repetiția 4: 49.712 rânduri complete din 70.144 declarate. Captura acceptată ulterioară, din `20260719_155432`, este validă. **Nu necesită repetare.** Detalii: [raw-gzip-exception-details.json](raw-gzip-exception-details.json).

Cele trei E07, RA-09 și E79 CH9340C au numai campanii packet în studiu; o campanie continuous nouă ar fi o extindere a scopului. Pierderile radio autentice sunt păstrate ca rezultate.

**Fișierele planului anterior**

[plan_refacere_fragmentare.csv](plan_refacere_fragmentare.csv) și [plan_rx_optional.csv](plan_rx_optional.csv) sunt păstrate pentru trasabilitate, cu `plan_status=superseded_not_a_capture_queue`. Nu reprezintă instrucțiuni de achiziție. [summary.json](summary.json) și [NECESAR_REVIZUIT.md](NECESAR_REVIZUIT.md) conțin decizia curentă.
