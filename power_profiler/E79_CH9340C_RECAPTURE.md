# Instrucțiuni pentru GPT/operator: recaptură E79 CH9340C TX

**Actualizare 30 septembrie 2026:** campania a fost executată pe un montaj alternativ **CH340**, cu schimbarea DUT-ului măsurat. Toate cele 315 capturi au fost [verificate independent din RAW](audits/2026-09-30/README.md). Protocolul de mai jos păstrează planul inițial; nu este o cerere de repetare a campaniei deja încheiate. Datele CH340 rămân distincte de seria istorică CH9340C.

Continuă pe PC-ul conectat la bancul PPK2. Obiectivul este obținerea și păstrarea a **315 capturi TX E79 pe montajul cu CH9340C**, cu date RAW și analiza fragmentelor. Folosește codul actual din acest repository, care raportează `per_frame_modeled_airtime_v1`. Acest document descrie operațiile de executat; redactarea și verificarea lui nu au pornit hardware și nu reprezintă măsurători noi.

## Context și limite

În campania istorică E79 CH9340C, cele 315 transferuri TX de peste 64 B au fost fragmentate, dar energia publicată a fost calculată într-o singură fereastră. Aceasta poate omite energia unor cadre. Campania a avut `save_raw=false`, deci energia tuturor cadrelor nu poate fi recalculată exact din rezumatele existente. Valorile istorice rămân păstrate și interpretate ca energie a ferestrei originale.

Recaptura acoperă numai această problemă. Nu relua TX de 8/32/64 B, RX, continuous sau alte module numai pentru că lipsesc RAW istorice. Pentru varianta E79 cu ESP32, RAW existente au permis recalcularea; nu o substitui variantei CH9340C și nu o măsura din nou în acest protocol.

Noua energie este **suma integrărilor în ferestrele modelate ale cadrelor detectate**. `energy_excess_uJ` scade baseline-ul pretrigger în aceste ferestre. Nu prezenta rezultatul drept energie a întregii tranzacții: intervalele dintre cadre, așteptarea UART/ACK și un ciclu complet de trezire nu sunt incluse automat. `event_duration_ms` este suma duratelor ferestrelor, nu timpul de la începutul primului cadru până la sfârșitul ultimului.

## Matrice exactă

| Parametru | Valori |
| --- | --- |
| Profil software | `RADIO_EBYTE_E79_CC1352P` |
| Direcție măsurată | `tx` |
| Payload logic | `128,512,1024` B |
| Profiluri RF | `GFSK4K8,GFSK50,GFSK200,SLR2K5,SLR5,OOK4K8,IEEE154G50` |
| Putere TX | `-20,0,13` dBm |
| Repetări | `5` pentru fiecare combinație |
| Pauză între capturi | `0.75` s |
| Cadre fizice / ferestre așteptate | 128 B → **2**; 512 B → **8**; 1024 B → **16** |

Total: **63 combinații × 5 repetări = 315 capturi**. Nu înlocui axa `rf_profile` cu bitrate: unele profiluri au aceeași rată, dar modulații diferite.

Rulează întâi **GFSK200: 45 capturi**, verifică rezultatele, apoi **celelalte șase profiluri: 270 capturi**. Loturile nu se suprapun. Estimarea minimă a planificatorului pentru total este circa 13,3 minute; configurarea, warm-up, serializarea RAW și verificarea adaugă timp. Profilul execută și câte un transfer warm-up verificat, nemăsurat, la schimbarea combinației RF/putere. Cele 315 reprezintă capturi salvate, nu numărul tuturor transmisiilor de pe banc.

## Montaj și firmware

- DUT este E79-400DM2005S / CC1352P pe traseul **CH9340C**, conectat direct prin UART. Păstrează montajul de măsurare; nu îl înlocui cu puntea ESP32. Receptorul peer verifică recepția, iar consumul său nu intră în traseul PPK al DUT.
- Ambele radiouri trebuie să aibă modemul AT E79 **0.3.0**, compatibil cu toate cele șapte profiluri. UART este **1.000.000 baud**, selectat din profil; CLI nu are argument `--baud` sau `--ppk-mode`. Înregistrează identitatea firmware-ului și orice diferență de montaj înainte de capturi.
- PPK2 lucrează în **Ampere Meter**, la **100 kS/s**. Alimentarea reală a DUT trebuie să fie **3,3 V**: sursa de 3,3 V → PPK2 VIN → PPK2 VOUT → VCC radio; mase comune. Elimină jumperul sau orice alimentare paralelă care ocolește măsurarea. CH9340C nu trebuie să alimenteze separat VCC-ul radioului ocolind PPK.
- `--voltage-mv 3300` declară tensiunea folosită la calcul; **PPK nu generează 3,3 V în acest mod**. Confirmă tensiunea reală și păstrează antenele, atenuarea/distanța și orientarea stabile între loturi. Folosește montajul RF de banc deja validat, cu antenă/sarcină adecvată.
- Închide Nordic Power Profiler / nRF Connect și terminalele seriale care ocupă porturile înainte de `run`. PC-ul trebuie să rămână pornit, fără suspendare automată.
- Scriptul execută `AT+DEFAULT`, `AT+DEBUG=OFF`, configurează RF/puterea, pune DUT în `AT+RX=OFF` și peer în `AT+RX=ON`. Nu este nevoie de configurări RF manuale pe care `AT+DEFAULT` le-ar reseta. Folosește transmiterea din profil, `AT+SEND` cu cadre de 64 B și confirmare; nu o înlocui cu o comandă hex pentru întregul payload.
- Traseul de alimentare DUT rămâne activ implicit după rulare, inclusiv după întrerupere; oprirea procesului nu trebuie confundată cu oprirea alimentării.

Porturile istorice au fost **COM10 = DUT/TX**, **COM56 = peer/RX**, **COM11 = PPK2**. Sunt doar referințe: **identifică și confirmă porturile actuale pe celălalt PC înainte de rulare**. Comanda `ports` poate identifica PPK2, dar nu poate deduce singură care radio este DUT și care este receptor.

## Instalare și identificare porturi

Folosește PowerShell și Python **3.10 sau mai nou**. Repository-ul poate fi în orice director; nu presupune existența discului sau căii folosite pe PC-ul de audit. Înlocuiește calea din prima comandă cu checkout-ul local actualizat. Comenzile următoare presupun că rămâi în `<repo>/power_profiler`.

```powershell
Set-Location 'C:\calea-ta\ESP32-C3_Radio\power_profiler'
python --version
python -m venv .venv
$py = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Instalarea dependențelor a eșuat.' }
& $py -m radio_power_profiler ports
if ($LASTEXITCODE -ne 0) { throw 'Identificarea porturilor a eșuat.' }
```

Nu este necesară activarea `Activate.ps1`: folosirea explicită a `$py` evită problemele de execution policy. Nu copia un mediu virtual de pe alt PC.

```powershell
$radioPort = (Read-Host 'Port DUT/TX CH9340C confirmat fizic (istoric COM10)').Trim()
$receiverPort = (Read-Host 'Port peer/RX confirmat fizic (istoric COM56)').Trim()
$ppkPort = (Read-Host 'Port de date PPK2 confirmat (istoric COM11)').Trim()
if (-not $radioPort -or -not $receiverPort -or -not $ppkPort) {
    throw 'Completează toate cele trei porturi confirmate.'
}
if (@($radioPort, $receiverPort, $ppkPort | Sort-Object -Unique).Count -ne 3) {
    throw 'Cele trei porturi trebuie să fie distincte.'
}

$testArgs = @(
    '--module', 'RADIO_EBYTE_E79_CC1352P',
    '--direction', 'tx',
    '--sizes', '128,512,1024',
    '--repetitions', '5',
    '--cooldown-s', '0.75',
    '--axis', 'tx_power_dbm=-20,0,13'
)
$otherProfiles = 'GFSK4K8,GFSK50,SLR2K5,SLR5,OOK4K8,IEEE154G50'
$lot45Args = $testArgs + @('--axis', 'rf_profile=GFSK200')
$lot270Args = $testArgs + @('--axis', "rf_profile=$otherProfiles")
$captureArgs = @(
    '--radio-port', $radioPort,
    '--receiver-port', $receiverPort,
    '--ppk-port', $ppkPort,
    '--voltage-mv', '3300',
    '--save-raw'
)

# Aceste două comenzi planifică; nu operează hardware.
& $py -m radio_power_profiler plan @lot45Args
if ($LASTEXITCODE -ne 0) { throw 'Planul de 45 a eșuat.' }
& $py -m radio_power_profiler plan @lot270Args
if ($LASTEXITCODE -ne 0) { throw 'Planul de 270 a eșuat.' }
```

Confirmă în ieșire **Measurements: 45**, respectiv **Measurements: 270**, TX, 1.000.000 baud, cele trei dimensiuni și cele trei puteri. `--receiver-port` este necesar în acest protocol pentru verificarea recepției. Nu folosi `--transmitter-port`, destinat măsurării RX. `--save-raw` este esențial; implicit este dezactivat.

## Primul lot: 45 capturi GFSK200

Comenzile `run` de mai jos operează hardware. Execută-le numai după verificările de montaj și porturi. Urmărește consola în timpul capturilor: la **`analysis_review_required`**, **`radio_error`**, `no_event_detected` sau excepție, oprește lotul cu **Ctrl+C**, păstrează toate fișierele și investighează cauza. CLI nu oprește automat lotul pentru fiecare statut de rând. Nu porni lotul de 270 înainte de rezolvarea problemei.

`rx_missing` singur reprezintă pierdere de recepție măsurată. **Nu repeta selectiv aceste rânduri și nu le șterge** ca să obții cinci recepții reușite. Păstrează exact cinci încercări pentru fiecare condiție și raportează loss separat. Dacă descoperi o problemă de banc care invalidează un lot, documentează cauza și o eventuală reluare completă într-un director nou; păstrează și încercarea inițială.

```powershell
$sessionRoot = Join-Path 'results' ('e79_ch9340c_tx_recapture_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Path $sessionRoot -ErrorAction Stop | Out-Null
$lot45Root = Join-Path $sessionRoot 'lot45_gfsk200'
$lot270Root = Join-Path $sessionRoot 'lot270_other_profiles'
& $py -u -m radio_power_profiler run @lot45Args @captureArgs --output $lot45Root 2>&1 |
    Tee-Object -FilePath (Join-Path $sessionRoot 'lot45_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Lotul de 45 a fost întrerupt sau a eșuat; păstrează datele și investighează.' }
```

Înregistrează lângă rezultate configurația fizică, porturile confirmate, tensiunea măsurată, firmware-ul, versiunea/commit-ul codului folosit și orice incident. Nu deduce că hardware-ul a funcționat numai din codul de ieșire zero.

## Verificarea lotului înainte de continuare

Fiecare `--output` conține un subdirector datat cu `metadata.json`, `summary.csv`, `aggregates.csv`, `raw/run_*.csv.gz` și diagnostice `analysis/run_*.json`. Verifică lotul întreg. RAW trebuie să existe pentru fiecare rând, iar ferestrele trebuie să fie separate, în ordine și în numărul corect: **2/8/16**.

Definește o dată funcția următoare în aceeași sesiune PowerShell. Ea nu accesează hardware, nu modifică datele și citește integral fiecare gzip pentru a verifica inclusiv CRC/trailer-ul și numărul de eșantioane. Verifică și acoperirea exactă a matricei, metoda de integrare și erorile de analiză. Nu înlocuiește inspecția vizuală a traselor.

```powershell
function Test-RecaptureLot {
    param([string]$Path, [int]$ExpectedCount, [string]$Profiles)
    @'
import csv, gzip, itertools, json, math, sys
from collections import Counter
from pathlib import Path

root, expected_count, profiles = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3].split(',')
def require(condition, message):
    if not condition:
        raise SystemExit('STOP: ' + message)

summaries = list(root.rglob('summary.csv'))
require(len(summaries) == 1, 'Astept exact o incercare/summary.csv in acest lot.')
folder = summaries[0].parent
meta = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
require(meta['save_raw'] is True and meta['test_count'] == expected_count, 'Metadate RAW/count incorecte.')
require(meta['measurement_direction'] == 'tx' and meta['ppk_mode'] == 'ampere', 'Directie/mod PPK incorect.')
require(meta['voltage_mv'] == 3300 and meta['sample_rate_hz'] == 100000, 'Tensiune/rata declarata incorecta.')
require(meta['profile']['baudrate'] == 1000000, 'Baud incorect.')
with summaries[0].open(encoding='utf-8-sig', newline='') as stream:
    rows = list(csv.DictReader(stream))
require(len(rows) == expected_count, f'Capturi incomplete: {len(rows)}/{expected_count}.')
expected = Counter(itertools.product(profiles, [-20, 0, 13], [128, 512, 1024], range(1, 6)))
actual = Counter()
run_ids = set()
losses = []
for row in rows:
    run = row['run_id']
    require(run not in run_ids, 'run_id duplicat: ' + run)
    run_ids.add(run)
    params = json.loads(row['parameters_json'])
    size = int(row['payload_bytes'])
    actual[(params['rf_profile'], params['tx_power_dbm'], size, int(row['repetition']))] += 1
    require(row['profile_id'] == 'RADIO_EBYTE_E79_CC1352P' and row['measurement_direction'] == 'tx', run + ': profil/directie')
    require(row['status'] in ('ok', 'rx_missing'), run + ': status=' + row['status'])
    require(not row['analysis_error'], run + ': ' + row['analysis_error'])
    require(row['integration_method'] == 'per_frame_modeled_airtime_v1', run + ': metoda veche/incorecta')
    windows = json.loads(row['integration_windows_ms'])
    require(size in (128, 512, 1024), run + ': payload neasteptat')
    require(int(row['frame_count']) == size // 64 == len(windows), run + ': numar cadre/ferestre')
    require(all(len(w) == 2 and all(math.isfinite(v) for v in w) and 0 <= w[0] < w[1] for w in windows), run + ': ferestre invalide')
    require(all(a[1] <= b[0] for a, b in zip(windows, windows[1:])), run + ': ferestre suprapuse/dezordonate')
    require(abs(sum(b - a for a, b in windows) - float(row['event_duration_ms'])) < 0.02, run + ': durata ferestrelor')
    require(all(math.isfinite(float(row[k])) and float(row[k]) >= 0 for k in ('energy_total_uJ', 'energy_excess_uJ')), run + ': energie invalida')
    with gzip.open(folder / 'raw' / (run + '.csv.gz'), 'rt', encoding='utf-8', newline='') as stream:
        require(next(stream).strip() == 'sample_index,time_ms,current_uA,logic_bits,trigger', run + ': header RAW')
        count = sum(1 for _ in stream)
    require(count == int(row['captured_samples']) and count > 0, run + ': numar esantioane RAW')
    diagnostic = json.loads((folder / 'analysis' / (run + '.json')).read_text(encoding='utf-8'))
    require(diagnostic['raw_retained'] and not diagnostic['analysis_error'], run + ': diagnostic invalid')
    require(diagnostic['integration_windows_ms'] == windows, run + ': diagnostic/CSV diferite')
    losses.append(float(row['sample_loss_percent']))
require(actual == expected, 'Matrice incompleta, duplicata sau cu parametri neasteptati.')
require({p.stem.removesuffix('.csv') for p in (folder / 'raw').glob('*.csv.gz')} == run_ids, 'Set RAW diferit de setul run_id.')
require((folder / 'aggregates.csv').is_file(), 'Lipseste aggregates.csv: lot posibil intrerupt.')
print(f'PASS structural: {len(rows)} capturi, matrice exacta, RAW gzip valide, ferestre 2/8/16.')
print('Statusuri:', dict(Counter(row['status'] for row in rows)))
print('sample_loss_percent maxim:', max(losses))
print('Director verificat:', folder)
'@ | & $py -B - $Path $ExpectedCount $Profiles
    if ($LASTEXITCODE -ne 0) { throw 'Verificarea lotului a esuat. Nu continua capturile.' }
}

Test-RecaptureLot -Path $lot45Root -ExpectedCount 45 -Profiles 'GFSK200'
```

După acest control, inspectează RAW și diagnosticele pentru cel puțin câte o captură de **128, 512 și 1024 B**, inclusiv puterea de **−20 dBm**, unde detecția este mai dificilă. Confirmă că ferestrele urmăresc cele 2/8/16 cadre fizice, fără cadre omise sau vârfuri UART numărate drept cadre. Verifică `sample_loss_percent` și eventualele anomalii înainte de continuare; un rezultat structural PASS nu certifică automat calitatea bancului. La ferestre neconvingătoare păstrează RAW pentru analiză, fără a forța manual numărul de cadre sau a schimba pragurile ca să treacă testul.

## Al doilea lot: 270 capturi

Execută numai după verificarea primului lot și a traselor. Rămân valabile regulile de oprire și păstrare a tuturor încercărilor.

```powershell
& $py -u -m radio_power_profiler run @lot270Args @captureArgs --output $lot270Root 2>&1 |
    Tee-Object -FilePath (Join-Path $sessionRoot 'lot270_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Lotul de 270 a fost intrerupt sau a esuat; pastreaza datele si investigheaza.' }
Test-RecaptureLot -Path $lot270Root -ExpectedCount 270 -Profiles $otherProfiles
```

Inspectează eșantionat și cadrele din acest lot, mai ales transferurile lente de 1024 B și puterea −20 dBm. Raportează separat validitatea analizei și recepția; `rx_missing` nu înseamnă că RAW trebuie eliminat sau recapturat selectiv.

## Ce trebuie predat înapoi

Păstrează și transferă **întregul `$sessionRoot`**, inclusiv ambele foldere datate, toate `raw/*.csv.gz`, `metadata.json`, `summary.csv`, `aggregates.csv`, `analysis/*.json`, logurile consolei și notele de banc. Păstrează și loturile întrerupte sau respinse; nu trimite numai XLSX, medii, grafice sau rânduri reușite. Nu suprascrie arhiva ori comparațiile publicate înainte de verificarea noilor date.

Mesajul de predare trebuie să precizeze: numărul capturilor și RAW pe lot, acoperirea 45+270, distribuția statusurilor, orice `analysis_error`/sample loss, verificarea ferestrelor 2/8/16, porturile și tensiunea reale, firmware-ul, versiunea codului și locația întregului set. Distinge explicit ce a fost executat fizic de ce a fost doar planificat sau verificat offline.

Referințe în repository: [necesarul revizuit și explicația celor 315 capturi](audits/2026-09-29/NECESAR_REVIZUIT.md), [matricea de recaptură CSV](audits/2026-09-29/plan_e79_ch9340_tx.csv), [profilul E79](radio_power_profiler/profiles.json), [CLI](radio_power_profiler/cli.py), [execuția și statusurile](radio_power_profiler/runner.py), [analiza ferestrelor](radio_power_profiler/frame_windows.py), [montajul PPK](README.md). Arhiva RAW importată pe PC-ul de audit nu este necesară pentru executarea acestui protocol.
