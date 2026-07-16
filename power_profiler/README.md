# Măsurarea consumului modulelor radio cu Nordic PPK2

Acest folder este un proiect separat de firmware-ul PlatformIO principal. Programul de pe PC folosește interfața AT existentă a plăcii ESP32-C3, comandă Nordic Power Profiler Kit II în modul Ampere Meter și rulează automat o matrice de teste pentru fiecare modul radio.

Pentru fiecare combinație sunt variate:

- dimensiunea payload-ului predat radioului; preambulul/headerul/CRC-ul PHY nu sunt incluși în această valoare;
- puterea de transmisie sau treapta de putere expusă de modul;
- parametrul care influențează cel mai mult timpul pe aer: data rate pentru FSK/nRF24/CC1101, SF pentru LoRa și FU/air-rate pentru modulele UART;
- cinci repetări implicite, pentru medie și abatere standard.

Programul calculează curentul de repaus, curentul mediu și maxim în TX, durata evenimentului, sarcina electrică și energia pentru un pachet. Sunt raportate atât energia totală în fereastra TX, cât și energia suplimentară peste consumul de repaus.

## Ce module sunt incluse

Comanda `profiles` afișează catalogul complet. Sunt definite profile pentru toate selecțiile radio din proiect: CC1101 V1/V2, cele trei E07, HC-12, nRF24L01, RA-01/RA-01H/RA-01SH/RA-02, E28, E22, E32 T20/T30/T33, E280, E79, XL1276-D01 și firmware-ul extern RA-08.

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

Jumperul/legătura originală dintre alimentarea plăcii și VCC-ul modulului trebuie eliminată, altfel curentul ocolește PPK2. Valoarea dată prin `--voltage-mv` este tensiunea reală prezentă la VIN și este folosită pentru calibrare și calculul energiei; PPK2 nu generează tensiunea. Programul activează traseul DUT pentru a închide circuitul VIN→VOUT înainte de configurare și îl dezactivează la final. `--keep-power-on` îl lasă activ explicit.

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

E79 și RA-08 necesită și firmware-ul AT propriu al modulului, conform documentației lor din repository.

## Utilizare

1. Identifică porturile:

```powershell
python -m radio_power_profiler ports
python -m radio_power_profiler profiles
```

2. Inspectează matricea înainte de test:

```powershell
python -m radio_power_profiler plan --module RADIO_RA01_SX1278
```

3. Rulează testul în montaj Ampere Meter:

```powershell
python -m radio_power_profiler run `
  --module RADIO_RA01_SX1278 `
  --radio-port COM4 `
  --receiver-port COM5 `
  --ppk-port COM7 `
  --voltage-mv 3300
```

Dacă este conectat un singur PPK2, `--ppk-port` poate fi omis.

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

Opțiunea `--save-raw` salvează fiecare formă de undă la 100 kS/s în `raw/*.csv.gz`. Este dezactivată implicit, deoarece o matrice completă poate ocupa mult spațiu.

## Rezultate

Fiecare sesiune primește un folder propriu sub `results/`:

- `metadata.json`: profilul complet, porturile, tensiunea și rata de eșantionare;
- `summary.csv`: câte un rând pentru fiecare pachet transmis; este scris incremental și rămâne utilizabil după o întrerupere;
- `aggregates.csv`: medii și abateri standard pentru fiecare combinație;
- `raw/*.csv.gz`: formele de undă, numai cu `--save-raw`.

Câmpurile principale sunt:

- `tx_peak_uA` și `tx_mean_uA`: vârf și medie în evenimentul detectat;
- `charge_total_uC`, `energy_total_uJ`: consum total în fereastra evenimentului;
- `charge_excess_uC`, `energy_excess_uJ`: partea peste baseline;
- `event_duration_ms`: durata detectată;
- `sample_loss_percent`: indicator că PC-ul nu a preluat toate eșantioanele;
- `status`: `ok`, `no_event_detected`, `rx_missing` sau `radio_error`.
- `packet_received`: confirmarea că al doilea modul a livrat payload-ul așteptat; `status=rx_missing` dacă TX a fost măsurat, dar pachetul nu a ajuns.

Dimensiunea cerută este numărul de octeți din payload-ul predat radioului, înainte de framing-ul PHY. Pentru firmware-urile care adaugă `CRLF` în payload, programul generează automat cu doi octeți mai puțin în conținut, astfel încât valorile de 8/32/64 B să rămână comparabile.

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
