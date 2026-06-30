[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PortA,

  [Parameter(Mandatory = $true)]
  [string]$PortB,

  [int]$Baud = 9600,
  [string]$Label = 'SX127x',

  [string[]]$DefaultTokens = @(
    'FREQ=433.000',
    'BW=250.0',
    'SF=10',
    'CR=6',
    'SYNC=0x14',
    'PWR=10',
    'RX=ON',
    'SLEEP=NO'
  ),

  [string]$ChangedSetCommand = 'AT+SET=433.500,125,9,6,0x14,10,0,8,0,ON',

  [string[]]$ChangedTokens = @(
    'FREQ=433.500',
    'BW=125.0',
    'SF=9',
    'PREAMBLE=8',
    'GAIN=0',
    'CRC=ON'
  ),

  [string[]]$RestoredTokens = @(
    'FREQ=433.000',
    'BW=250.0',
    'SF=10',
    'PREAMBLE=15',
    'GAIN=1',
    'CRC=ON'
  ),

  [string]$LogPath = '',
  [switch]$SkipFinalRestore
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $safeLabel = $Label -replace '[^A-Za-z0-9_.-]', '_'
  $LogPath = Join-Path 'log' "Test-Sx127xAtPair_${safeLabel}_${PortA}_${PortB}_$stamp.txt"
}

$logDir = Split-Path -Parent $LogPath
if (-not [string]::IsNullOrWhiteSpace($logDir)) {
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

$results = [System.Collections.Generic.List[string]]::new()
$failures = [System.Collections.Generic.List[string]]::new()
$restoreDone = $false
$exitCode = 0

function Write-Log {
  param([string]$Message = '')
  [Console]::Out.WriteLine($Message)
  Add-Content -Path $script:LogPath -Value $Message
}

function As-Text {
  param($Value)
  if ($null -eq $Value) { return '' }
  if ($Value -is [array]) {
    return (($Value | ForEach-Object { [string]$_ }) -join "`n")
  }
  return [string]$Value
}

function Add-Result {
  param(
    [string]$Name,
    $Ok,
    [string]$Detail = ''
  )

  $isOk = [bool]$Ok
  $status = if ($isOk) { 'PASS' } else { 'FAIL' }
  $line = if ($Detail) { "$status`t$Name`t$Detail" } else { "$status`t$Name" }

  [void]$script:results.Add($line)
  if (-not $isOk) {
    [void]$script:failures.Add($line)
  }
}

function Read-For {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [int]$Milliseconds
  )

  $deadline = [DateTime]::UtcNow.AddMilliseconds($Milliseconds)
  $sb = [System.Text.StringBuilder]::new()

  while ([DateTime]::UtcNow -lt $deadline) {
    try {
      $chunk = $SerialPort.ReadExisting()
      if ($chunk.Length -gt 0) {
        [void]$sb.Append($chunk)
      }
    } catch {
      # Some USB CDC ports briefly throw during reset; keep reading until timeout.
    }
    Start-Sleep -Milliseconds 35
  }

  return (($sb.ToString() -replace "`0", '<NUL>').Trim())
}

function Clean-Text {
  param($Text)
  $value = As-Text $Text
  return (($value -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')).Trim()
}

function Open-And-Reset {
  param([string]$Name)

  $serialPort = [System.IO.Ports.SerialPort]::new(
    $Name,
    $script:Baud,
    [System.IO.Ports.Parity]::None,
    8,
    [System.IO.Ports.StopBits]::One
  )

  $serialPort.ReadTimeout = 200
  $serialPort.WriteTimeout = 1000
  $serialPort.NewLine = "`n"
  $serialPort.Open()

  Pulse-Reset $serialPort
  return $serialPort
}

function Pulse-Reset {
  param([System.IO.Ports.SerialPort]$SerialPort)

  $SerialPort.DtrEnable = $false
  $SerialPort.RtsEnable = $true
  Start-Sleep -Milliseconds 150
  $SerialPort.RtsEnable = $false
  Start-Sleep -Milliseconds 2800
}

function Send-Cmd {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Name,
    [string]$Command,
    [int]$Milliseconds = 1400
  )

  [void](Read-For $SerialPort 120)
  $SerialPort.Write($Command + "`n")
  $out = Clean-Text (Read-For $SerialPort $Milliseconds)

  Write-Log "--- $Name >> $Command ---"
  if ([string]::IsNullOrWhiteSpace($out)) {
    Write-Log '<no output>'
  } else {
    Write-Log $out
  }

  return $out
}

function Expect-Contains {
  param(
    [string]$Name,
    $Text,
    [string]$Needle
  )

  $value = As-Text $Text
  Add-Result $Name ($value.Contains($Needle)) "expected '$Needle'"
}

function Expect-NotContains {
  param(
    [string]$Name,
    $Text,
    [string]$Needle
  )

  $value = As-Text $Text
  Add-Result $Name (-not $value.Contains($Needle)) "not expected '$Needle'"
}

function Send-Payload {
  param(
    [System.IO.Ports.SerialPort]$TxPort,
    [System.IO.Ports.SerialPort]$RxPort,
    [string]$TxName,
    [string]$RxName,
    [string]$Payload,
    [int]$Milliseconds = 1900
  )

  [void](Read-For $TxPort 120)
  [void](Read-For $RxPort 120)
  $TxPort.Write($Payload + "`n")
  Start-Sleep -Milliseconds $Milliseconds

  $rxOut = Clean-Text (Read-For $RxPort 700)
  $txOut = Clean-Text (Read-For $TxPort 300)

  Write-Log "--- ${TxName} payload -> ${RxName}: $Payload ---"
  if ([string]::IsNullOrWhiteSpace($rxOut)) {
    Write-Log "${RxName}: <no output>"
  } else {
    Write-Log "${RxName}: $rxOut"
  }
  if (-not [string]::IsNullOrWhiteSpace($txOut)) {
    Write-Log "${TxName}: $txOut"
  }

  return $rxOut
}

function Restore-Defaults {
  param(
    [System.IO.Ports.SerialPort]$PortAHandle,
    [System.IO.Ports.SerialPort]$PortBHandle
  )

  foreach ($pair in @(@($PortAHandle, 'A'), @($PortBHandle, 'B'))) {
    $handle = $pair[0]
    $name = $pair[1]
    if ($null -eq $handle -or -not $handle.IsOpen) {
      continue
    }

    try {
      [void](Send-Cmd $handle $name 'AT+WAKE' 1600)
      [void](Send-Cmd $handle $name 'AT+DEFAULT' 2000)
      [void](Send-Cmd $handle $name 'AT+RX=ON' 1400)
    } catch {
      Write-Log "#ERROR: RESTORE_DEFAULTS_$name $($_.Exception.Message)"
    }
  }

  $script:restoreDone = $true
}

function Test-SerialPair {
  $portAHandle = $null
  $portBHandle = $null

  try {
    Write-Log "Test: $script:Label"
    Write-Log "Ports: $script:PortA / $script:PortB"
    Write-Log "Baud: $script:Baud"
    Write-Log "Log: $script:LogPath"
    Write-Log ''

    $portAHandle = Open-And-Reset $script:PortA
    $portBHandle = Open-And-Reset $script:PortB

    $bootA = Clean-Text (Read-For $portAHandle 700)
    $bootB = Clean-Text (Read-For $portBHandle 700)
    Write-Log "--- $script:PortA boot ---"
    Write-Log $bootA
    Write-Log "--- $script:PortB boot ---"
    Write-Log $bootB
    Expect-Contains "$script:PortA boot init" $bootA 'success!'
    Expect-Contains "$script:PortB boot init" $bootB 'success!'

    foreach ($pair in @(@($portAHandle, $script:PortA), @($portBHandle, $script:PortB))) {
      $out = Send-Cmd $pair[0] $pair[1] 'AT'
      Expect-Contains "$($pair[1]) AT" $out 'OK'

      $out = Send-Cmd $pair[0] $pair[1] 'AT+DEFAULT' 1900
      Expect-Contains "$($pair[1]) AT+DEFAULT" $out 'OK'

      $out = Send-Cmd $pair[0] $pair[1] 'AT+DEBUG=OFF'
      Expect-Contains "$($pair[1]) AT+DEBUG=OFF" $out 'OK'

      $out = Send-Cmd $pair[0] $pair[1] 'AT+RX=ON'
      Expect-Contains "$($pair[1]) AT+RX=ON" $out 'OK'
    }

    $cfgA = Send-Cmd $portAHandle $script:PortA 'AT+CFG?' 1800
    $cfgB = Send-Cmd $portBHandle $script:PortB 'AT+CFG?' 1800
    foreach ($token in $script:DefaultTokens) {
      Expect-Contains "$script:PortA default cfg $token" $cfgA $token
      Expect-Contains "$script:PortB default cfg $token" $cfgB $token
    }

    $payload = "${script:Label}_BASE_${script:PortA}_TO_${script:PortB}"
    $rx = Send-Payload $portAHandle $portBHandle $script:PortA $script:PortB $payload
    Expect-Contains "Default payload $script:PortA to $script:PortB" $rx $payload

    $payload = "${script:Label}_BASE_${script:PortB}_TO_${script:PortA}"
    $rx = Send-Payload $portBHandle $portAHandle $script:PortB $script:PortA $payload
    Expect-Contains "Default payload $script:PortB to $script:PortA" $rx $payload

    $rssi = Send-Cmd $portAHandle $script:PortA 'AT+RSSI?'
    Expect-Contains 'RSSI after packet' $rssi 'RSSI='

    $snr = Send-Cmd $portAHandle $script:PortA 'AT+SNR?'
    Expect-Contains 'SNR after packet' $snr 'SNR='

    $ferr = Send-Cmd $portAHandle $script:PortA 'AT+FERR?'
    Expect-Contains 'FERR after packet' $ferr 'FERR='

    $cad = Send-Cmd $portAHandle $script:PortA 'AT+CAD?' 2200
    Add-Result 'CAD command returns usable status' (((As-Text $cad).Contains('CAD=FREE')) -or ((As-Text $cad).Contains('CAD=DETECTED'))) $cad

    $random = Send-Cmd $portAHandle $script:PortA 'AT+RANDOM?'
    Expect-Contains 'Random byte command' $random 'RANDOM=0x'

    $out = Send-Cmd $portBHandle $script:PortB 'AT+RX=OFF'
    Expect-Contains "$script:PortB RX off command" $out 'OK'

    $payload = "${script:Label}_SHOULD_NOT_APPEAR_RX_OFF"
    $rx = Send-Payload $portAHandle $portBHandle $script:PortA $script:PortB $payload 1600
    Expect-NotContains "$script:PortB does not receive while RX off" $rx $payload

    $out = Send-Cmd $portBHandle $script:PortB 'AT+RX=ON'
    Expect-Contains "$script:PortB RX on after standby" $out 'OK'

    $payload = "${script:Label}_RX_RESTORED"
    $rx = Send-Payload $portAHandle $portBHandle $script:PortA $script:PortB $payload
    Expect-Contains 'Payload after RX restore' $rx $payload

    $out = Send-Cmd $portAHandle $script:PortA 'AT+SLEEP'
    Expect-Contains "$script:PortA sleep command" $out 'OK'

    [void](Read-For $portAHandle 120)
    $portAHandle.Write("${script:Label}_SLEEP_BLOCK_CHECK`n")
    $sleepOut = Clean-Text (Read-For $portAHandle 900)
    Write-Log "--- $script:PortA payload while sleeping ---"
    Write-Log $sleepOut
    Expect-Contains 'TX blocked while sleeping' $sleepOut '#ERROR: RADIO_SLEEPING'

    $out = Send-Cmd $portAHandle $script:PortA 'AT+WAKE' 1800
    Expect-Contains "$script:PortA wake command" $out 'OK'

    $badSf = Send-Cmd $portAHandle $script:PortA 'AT+SF=13'
    Expect-Contains 'Invalid SF rejected' $badSf '#ERROR'

    $badFreq = Send-Cmd $portAHandle $script:PortA 'AT+FREQ=300'
    Expect-Contains 'Invalid FREQ rejected' $badFreq '#ERROR'

    $badPwr = Send-Cmd $portAHandle $script:PortA 'AT+PWR=18'
    Expect-Contains 'Invalid PWR rejected' $badPwr '#ERROR'

    foreach ($pair in @(@($portAHandle, $script:PortA), @($portBHandle, $script:PortB))) {
      $out = Send-Cmd $pair[0] $pair[1] $script:ChangedSetCommand 2200
      Expect-Contains "$($pair[1]) AT+SET batch" $out 'OK'

      $out = Send-Cmd $pair[0] $pair[1] 'AT+RX=ON'
      Expect-Contains "$($pair[1]) RX on after AT+SET" $out 'OK'
    }

    $cfgA = Send-Cmd $portAHandle $script:PortA 'AT+CFG?' 1800
    $cfgB = Send-Cmd $portBHandle $script:PortB 'AT+CFG?' 1800
    foreach ($token in $script:ChangedTokens) {
      Expect-Contains "$script:PortA changed cfg $token" $cfgA $token
      Expect-Contains "$script:PortB changed cfg $token" $cfgB $token
    }

    $payload = "${script:Label}_SET_${script:PortA}_TO_${script:PortB}"
    $rx = Send-Payload $portAHandle $portBHandle $script:PortA $script:PortB $payload
    Expect-Contains "Batch config payload $script:PortA to $script:PortB" $rx $payload

    $payload = "${script:Label}_SET_${script:PortB}_TO_${script:PortA}"
    $rx = Send-Payload $portBHandle $portAHandle $script:PortB $script:PortA $payload
    Expect-Contains "Batch config payload $script:PortB to $script:PortA" $rx $payload

    Pulse-Reset $portAHandle
    Pulse-Reset $portBHandle

    $bootA = Clean-Text (Read-For $portAHandle 900)
    $bootB = Clean-Text (Read-For $portBHandle 900)
    Write-Log "--- $script:PortA boot after persistence reset ---"
    Write-Log $bootA
    Write-Log "--- $script:PortB boot after persistence reset ---"
    Write-Log $bootB
    Expect-Contains "$script:PortA EEPROM loaded after changed cfg reset" $bootA 'Loaded config = YES'
    Expect-Contains "$script:PortB EEPROM loaded after changed cfg reset" $bootB 'Loaded config = YES'

    $cfgA = Send-Cmd $portAHandle $script:PortA 'AT+CFG?' 1800
    $cfgB = Send-Cmd $portBHandle $script:PortB 'AT+CFG?' 1800
    $persistTokens = $script:ChangedTokens | Select-Object -First 3
    foreach ($token in $persistTokens) {
      Expect-Contains "$script:PortA persisted cfg $token" $cfgA $token
      Expect-Contains "$script:PortB persisted cfg $token" $cfgB $token
    }

    if (-not $script:SkipFinalRestore) {
      Restore-Defaults $portAHandle $portBHandle

      $cfgA = Send-Cmd $portAHandle $script:PortA 'AT+CFG?' 1800
      $cfgB = Send-Cmd $portBHandle $script:PortB 'AT+CFG?' 1800
      foreach ($token in $script:RestoredTokens) {
        Expect-Contains "$script:PortA restored cfg $token" $cfgA $token
        Expect-Contains "$script:PortB restored cfg $token" $cfgB $token
      }

      $payload = "${script:Label}_FINAL_${script:PortA}_TO_${script:PortB}"
      $rx = Send-Payload $portAHandle $portBHandle $script:PortA $script:PortB $payload
      Expect-Contains "Final default payload $script:PortA to $script:PortB" $rx $payload
    }

    Write-Log '=== RESULTS ==='
    foreach ($result in $script:results) {
      Write-Log $result
    }
    Write-Log '=== SUMMARY ==='
    Write-Log "PASS=$($script:results.Count - $script:failures.Count) FAIL=$($script:failures.Count)"

    if ($script:failures.Count -gt 0) {
      Write-Log '=== FAILURES ==='
      foreach ($failure in $script:failures) {
        Write-Log $failure
      }
      $script:exitCode = 2
    }
  } finally {
    if (-not $script:SkipFinalRestore -and -not $script:restoreDone) {
      Restore-Defaults $portAHandle $portBHandle
    }

    if ($null -ne $portAHandle -and $portAHandle.IsOpen) {
      $portAHandle.Close()
    }
    if ($null -ne $portBHandle -and $portBHandle.IsOpen) {
      $portBHandle.Close()
    }
  }
}

try {
  Test-SerialPair
} catch {
  Write-Log "#ERROR: TEST_ABORTED $($_.Exception.Message)"
  $exitCode = 1
}

exit $exitCode
