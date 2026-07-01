[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PortA,

  [Parameter(Mandatory = $true)]
  [string]$PortB,

  [int]$Baud = 115200,
  [string]$Label = 'CC1101QuickSweep',
  [double[]]$Frequencies = @(433.000, 433.500, 433.920, 434.000, 434.500),
  [string[]]$ExtraSetup = @(),
  [int]$Attempts = 3,
  [int]$CommandWaitMs = 650,
  [int]$RxWaitMs = 1300,
  [switch]$ResetOnOpen,
  [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$invariantCulture = [Globalization.CultureInfo]::InvariantCulture

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $safeLabel = $Label -replace '[^A-Za-z0-9_.-]', '_'
  $safeA = $PortA -replace '[^A-Za-z0-9_.-]', '_'
  $safeB = $PortB -replace '[^A-Za-z0-9_.-]', '_'
  $LogPath = Join-Path 'log' "Test-Cc1101QuickSweep_${safeLabel}_${safeA}_${safeB}_$stamp.txt"
}

$logDir = Split-Path -Parent $LogPath
if (-not [string]::IsNullOrWhiteSpace($logDir)) {
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

function Write-Log {
  param([string]$Message = '')
  [Console]::Out.WriteLine($Message)
  Add-Content -Path $script:LogPath -Value $Message
}

function Clean-Text {
  param($Text)
  if ($null -eq $Text) { return '' }
  return (([string]$Text -replace "`0", '<NUL>') -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', '').Trim()
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
    }
    Start-Sleep -Milliseconds 20
  }
  return Clean-Text $sb.ToString()
}

function Open-Port {
  param([string]$PortName)

  $serial = [System.IO.Ports.SerialPort]::new($PortName, $script:Baud, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
  $serial.Encoding = [System.Text.Encoding]::ASCII
  $serial.NewLine = "`n"
  $serial.ReadTimeout = 100
  $serial.WriteTimeout = 1000
  $serial.DtrEnable = $true
  $serial.RtsEnable = $false
  $serial.Open()

  if ($script:ResetOnOpen) {
    $serial.DtrEnable = $false
    $serial.RtsEnable = $true
    Start-Sleep -Milliseconds 120
    $serial.RtsEnable = $false
    $serial.DtrEnable = $true
  }

  Start-Sleep -Milliseconds 900
  [void](Read-For $serial 400)
  return $serial
}

function Send-Line {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Line,
    [int]$WaitMs = $script:CommandWaitMs
  )

  try {
    $SerialPort.DiscardInBuffer()
  } catch {
  }
  $SerialPort.Write($Line + "`r`n")
  return Read-For $SerialPort $WaitMs
}

function Setup-Node {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Name
  )

  foreach ($cmd in @('AT', 'AT+DEFAULT', 'AT+WAKE', 'AT+DEBUG=OFF') + $script:ExtraSetup) {
    $out = Send-Line $SerialPort $cmd
    Write-Log "--- $Name >> $cmd ---"
    Write-Log $(if ($out) { $out } else { '<no output>' })
  }
}

function Set-Frequency {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Name,
    [double]$Frequency
  )

  $freqText = $Frequency.ToString('0.000', [Globalization.CultureInfo]::InvariantCulture)
  foreach ($cmd in @("AT+FREQ=$freqText", 'AT+RX=ON', 'AT+FREQ?')) {
    $out = Send-Line $SerialPort $cmd
    Write-Log "--- $Name >> $cmd ---"
    Write-Log $(if ($out) { $out } else { '<no output>' })
  }
}

function Send-Payload {
  param(
    [System.IO.Ports.SerialPort]$Tx,
    [System.IO.Ports.SerialPort]$Rx,
    [string]$TxName,
    [string]$RxName,
    [string]$Payload
  )

  try { $Rx.DiscardInBuffer() } catch {}
  $txOut = Send-Line $Tx $Payload 250
  $rxOut = Read-For $Rx $script:RxWaitMs
  $ok = $rxOut.Contains($Payload)

  Write-Log "--- $TxName -> $RxName : $Payload ---"
  Write-Log "TX: $(if ($txOut) { $txOut } else { '<no output>' })"
  Write-Log "RX: $(if ($rxOut) { $rxOut } else { '<no output>' })"
  Write-Log "$(if ($ok) { 'PASS' } else { 'FAIL' }) $TxName->$RxName"

  return $ok
}

$script:LogPath = $LogPath
$script:Baud = $Baud
$script:ResetOnOpen = $ResetOnOpen
$script:ExtraSetup = $ExtraSetup
$script:CommandWaitMs = $CommandWaitMs
$script:RxWaitMs = $RxWaitMs

$pass = 0
$fail = 0

Write-Log "Test: $Label"
Write-Log "Ports: $PortA / $PortB"
Write-Log "Baud: $Baud"
Write-Log "Frequencies: $(($Frequencies | ForEach-Object { $_.ToString('0.000', $invariantCulture) }) -join ', ')"
Write-Log "Attempts per direction: $Attempts"
Write-Log "Extra setup: $($ExtraSetup -join ', ')"
Write-Log "Log: $LogPath"
Write-Log ''

$a = $null
$b = $null
try {
  $a = Open-Port $PortA
  $b = Open-Port $PortB

  Setup-Node $a $PortA
  Setup-Node $b $PortB

  foreach ($freq in $Frequencies) {
    Write-Log ''
    Write-Log "=== FREQ $($freq.ToString('0.000', $invariantCulture)) MHz ==="
    Set-Frequency $a $PortA $freq
    Set-Frequency $b $PortB $freq

    for ($i = 1; $i -le $Attempts; $i++) {
      [void](Send-Line $a 'AT+RX=ON' 250)
      [void](Send-Line $b 'AT+RX=ON' 250)
      Start-Sleep -Milliseconds 150

      $tokenAB = "${Label}_${($freq.ToString('0.000', $invariantCulture))}_A${i}" -replace '[^A-Za-z0-9_.-]', '_'
      if (Send-Payload $a $b $PortA $PortB $tokenAB) { $pass++ } else { $fail++ }

      [void](Send-Line $a 'AT+RX=ON' 250)
      [void](Send-Line $b 'AT+RX=ON' 250)
      Start-Sleep -Milliseconds 150

      $tokenBA = "${Label}_${($freq.ToString('0.000', $invariantCulture))}_B${i}" -replace '[^A-Za-z0-9_.-]', '_'
      if (Send-Payload $b $a $PortB $PortA $tokenBA) { $pass++ } else { $fail++ }
    }
  }
} finally {
  if ($null -ne $a) { $a.Close(); $a.Dispose() }
  if ($null -ne $b) { $b.Close(); $b.Dispose() }
}

Write-Log ''
Write-Log "=== SUMMARY ==="
Write-Log "PASS=$pass FAIL=$fail"

if ($fail -gt 0) {
  [Environment]::Exit(1)
}
