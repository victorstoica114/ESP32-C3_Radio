# Curățarea adnotărilor măsurătorilor — 3 octombrie 2026

La cererea autorului au fost eliminate adnotările instrumentului din
documentație, identitățile capturilor, manifestele și rapoartele locale,
precum și din copiile de surse asociate măsurătorilor. Numele diagnosticelor
și legăturile aferente au fost actualizate. Scriptul auxiliar de arhivare
a pachetelor deja eliminate a fost șters.

Fișierele text revizuite au amprente noi. Manifestele curente folosesc
hashurile și dimensiunile actualizate; inventarele istorice ale mutării
rămân înregistrări ale stării de la momentul operației.

Verificările consemnate în [rezumatul operației](summary.json) confirmă:

- **8.903 capturi RAW/WIRE**, în total **34.786.411.898 bytes**, au același
  SHA-256 ca înaintea curățării.
- Curenții, energiile, numărul de mostre și coeficienții de calibrare din
  JSON-urile revizuite au rămas neschimbate; diferențele numerice admise
  în manifeste privesc numai dimensiunile fișierelor text.
- **1.928 de referințe către fișiere text existente** au hashuri verificate.
  Curățarea nu a introdus neconcordanțe noi. Cele 81 de referințe istorice
  care diferă de fișierele curente erau diferite și înaintea acestei operații.
- **264 de PDF-uri** au fost verificate prin extragerea textului; nu conțin
  adnotările căutate.
- **427 de teste software** au trecut după curățarea principală; cele
  **11 teste ale diagnosticului PPK** au trecut după eliminarea adnotării
  automate din acel script.

RAW-urile rămân locale, excluse din Git. Politicile de acceptare, rezultatele
energetice și lista măsurătorilor de refăcut nu au fost schimbate de această
operație. Inventarul detaliat al fișierelor revizuite este păstrat local în
`.tmp/ppk-reference-cleanup/receipt.json`.
