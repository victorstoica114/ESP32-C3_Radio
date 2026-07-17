# Măsurarea consumului modulelor radio cu Nordic PPK2

Acest folder este un proiect separat de firmware-ul PlatformIO principal. Programul de pe PC folosește interfața AT existentă a plăcii ESP32-C3, comandă Nordic Power Profiler Kit II în modul Ampere Meter și rulează automat o matrice de teste pentru fiecare modul radio.

Pentru fiecare combinație sunt variate:

- dimensiunea payload-ului predat radioului; preambulul/headerul/CRC-ul PHY nu sunt incluși în această valoare;
- puterea de transmisie sau treapta de putere expusă de modul;
- parametrul care influențează cel mai mult timpul pe aer: data rate pentru FSK/nRF24/CC1101, SF pentru LoRa și FU/air-rate pentru modulele UART;
- cinci repetări implicite, pentru medie și abatere standard.

Programul poate măsura separat TX sau RX. Calculează curentul de repaus, curentul mediu și maxim în eveniment, durata, sarcina electrică și energia pentru un pachet sau transfer fragmentat. Sunt raportate atât energia totală în fereastra măsurată, cât și energia suplimentară peste consumul de repaus.

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

Pentru fiecare caz, receptorul măsurat pornește din standby, este trecut în RX,
primește transferul și revine în standby înainte de terminarea capturii. Energia
include pornirea receptorului, recepția și procesarea cadrelor. La transferurile
CC1101 de 128/512/1024 B, emițătorul introduce implicit 15 ms între cadre pentru
ca receptorul să se poată rearma; această perioadă face parte din fereastra RX.
Puterea de transmisie din matrice este puterea modulului de stimul, nu o setare
care ar modifica lanțul RX al dispozitivului măsurat.

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
fluxul. Rezultatele incrementale sunt scrise în `continuous_results/*/summary.csv`.

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
