[CmdletBinding()]
param(
  [string]$PortA = 'COM45',
  [string]$PortB = 'COM46',
  [int]$Baud = 115200,
  [string]$Label = 'RA08',
  [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $safeLabel = $Label -replace '[^A-Za-z0-9_.-]', '_'
  $safeA = $PortA -replace '[^A-Za-z0-9_.-]', '_'
  $safeB = $PortB -replace '[^A-Za-z0-9_.-]', '_'
  $LogPath = Join-Path 'log' "Test-Ra08ChannelIsolation_${safeLabel}_${safeA}_${safeB}_$stamp.txt"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

$script:results = [System.Collections.Generic.List[string]]::new()
$script:failures = [System.Collections.Generic.List[string]]::new()

function Write-Log {
  param([string]$Message = '')
  [Console]::Out.WriteLine($Message)
  Add-Content -Path $script:LogPath -Value $Message
}

function To-Hex {
  param([string]$Text)
  $bytes = [System.Text.Encoding]::ASCII.GetBytes($Text)
  return (($bytes | ForEach-Object { $_.ToString('X2') }) -join '')
}

function Read-For {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [int]$Milliseconds = 500
  )

  $deadline = [DateTime]::UtcNow.AddMilliseconds($Milliseconds)
  $data = New-Object System.Text.StringBuilder

  while ([DateTime]::UtcNow -lt $deadline) {
    try {
      if ($SerialPort.IsOpen -and $SerialPort.BytesToRead -gt 0) {
        [void]$data.Append($SerialPort.ReadExisting())
      } else {
        Start-Sleep -Milliseconds 20
      }
    } catch {
      [void]$data.Append("`r`n#SERIAL_READ_ERROR: $($_.Exception.Message)`r`n")
      break
    }
  }

  return $data.ToString()
}

function Open-Ra08Port {
  param([string]$Port)

  $sp = [System.IO.Ports.SerialPort]::new($Port, $script:Baud)
  $sp.ReadTimeout = 250
  $sp.WriteTimeout = 700
  $sp.NewLine = "`r`n"
  $sp.DtrEnable = $false
  $sp.RtsEnable = $false
  $sp.Open()
  [void](Read-For $sp 500)
  return $sp
}

function Close-Ra08Port {
  param($SerialPort)

  if ($null -ne $SerialPort) {
    try {
      if ($SerialPort.IsOpen) {
        $SerialPort.Close()
      }
      $SerialPort.Dispose()
    } catch {
    }
  }
}

function Send-Cmd {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Name,
    [string]$Command,
    [int]$WaitMs = 500
  )

  Write-Log "--- $Name >> $Command ---"
  try {
    if (-not $SerialPort.IsOpen) {
      $out = "#SERIAL_CLOSED_BEFORE_WRITE"
      Write-Log $out
      return $out
    }
    [void](Read-For $SerialPort 80)
    $SerialPort.Write($Command + "`r`n")
    $out = Read-For $SerialPort $WaitMs
  } catch {
    $out = "#SERIAL_WRITE_ERROR: $($_.Exception.Message)"
  }

  if ([string]::IsNullOrWhiteSpace($out)) {
    Write-Log '<no output>'
  } else {
    Write-Log $out
  }
  return $out
}

function Add-Result {
  param(
    [string]$Label,
    [bool]$Pass,
    [string]$Detail
  )

  $line = "$(if ($Pass) { 'PASS' } else { 'FAIL' })`t$Label`t$Detail"
  $script:results.Add($line)
  if (-not $Pass) {
    $script:failures.Add($line)
  }
}

function Expect-Contains {
  param([string]$Label, [string]$Output, [string]$Token)
  Add-Result $Label ($Output -like "*$Token*") "expected '$Token'"
}

function Expect-NotContains {
  param([string]$Label, [string]$Output, [string]$Token)
  Add-Result $Label (-not ($Output -like "*$Token*")) "not expected '$Token'"
}

function Configure-Stage {
  param(
    [System.IO.Ports.SerialPort]$A,
    [System.IO.Ports.SerialPort]$B,
    [int]$ChanA,
    [int]$ChanB
  )

  foreach ($item in @(
      @{ Port = $A; Name = $script:PortA; Chan = $ChanA },
      @{ Port = $B; Name = $script:PortB; Chan = $ChanB }
    )) {
    foreach ($cmd in @('AT', 'AT+WAKE', 'AT+PWR=2', 'AT+SF=7', 'AT+BW=125000', 'AT+CR=4/5')) {
      $out = Send-Cmd $item.Port $item.Name $cmd 600
      Expect-Contains "$($item.Name) setup $cmd" $out 'OK'
    }

    $out = Send-Cmd $item.Port $item.Name "AT+CHAN=$($item.Chan)" 800
    Expect-Contains "$($item.Name) set channel $($item.Chan)" $out 'OK'

    $out = Send-Cmd $item.Port $item.Name 'AT+RX=ON' 800
    Expect-Contains "$($item.Name) RX on" $out 'OK'

    [void](Send-Cmd $item.Port $item.Name 'AT+CHAN?' 500)
  }
}

function Run-OneDirection {
  param(
    [string]$Stage,
    [bool]$ShouldReceive,
    [bool]$AtoB,
    [int]$ChanA,
    [int]$ChanB
  )

  $a = $null
  $b = $null
  try {
    Start-Sleep -Milliseconds 800
    $a = Open-Ra08Port $script:PortA
    $b = Open-Ra08Port $script:PortB

    Configure-Stage $a $b $ChanA $ChanB

    $tx = if ($AtoB) { $a } else { $b }
    $rx = if ($AtoB) { $b } else { $a }
    $txName = if ($AtoB) { $script:PortA } else { $script:PortB }
    $rxName = if ($AtoB) { $script:PortB } else { $script:PortA }
    $suffix = if ($AtoB) { 'A_TO_B' } else { 'B_TO_A' }
    $payload = "${script:Label}_${Stage}_${suffix}"
    $hex = To-Hex $payload

    [void](Read-For $tx 80)
    [void](Read-For $rx 80)

    $txOut = Send-Cmd $tx $txName "AT+SEND=$hex" 1400
    $rxOut = Read-For $rx 4500

    Write-Log "--- $txName payload -> $rxName ---"
    Write-Log "payload: $payload"
    Write-Log "expected hex: $hex"
    Write-Log "$rxName rx output:"
    if ([string]::IsNullOrWhiteSpace($rxOut)) { Write-Log '<no output>' } else { Write-Log $rxOut }

    if ($ShouldReceive) {
      Expect-Contains "$Stage $txName to $rxName receive" $rxOut $hex
    } else {
      Expect-NotContains "$Stage $txName to $rxName isolated" $rxOut $hex
    }

    if ($txOut -like '*#SERIAL_*') {
      Add-Result "$Stage $txName serial stayed open after TX" $false 'serial error during/after TX'
    }
  } finally {
    Close-Ra08Port $a
    Close-Ra08Port $b
  }
}

Write-Log "Test: $Label"
Write-Log "Ports: $PortA / $PortB"
Write-Log "Baud:  $Baud"
Write-Log "Log:   $LogPath"
Write-Log ''

Run-OneDirection 'SYNC_BASE' $true  $true  0 0
Run-OneDirection 'SYNC_BASE' $true  $false 0 0
Run-OneDirection 'DESYNC'    $false $true  0 1
Run-OneDirection 'DESYNC'    $false $false 0 1
Run-OneDirection 'RESYNC'    $true  $true  0 0
Run-OneDirection 'RESYNC'    $true  $false 0 0

Write-Log ''
Write-Log '=== RESULTS ==='
foreach ($result in $script:results) {
  Write-Log $result
}

$passCount = ($script:results | Where-Object { $_ -like 'PASS*' }).Count
$failCount = ($script:results | Where-Object { $_ -like 'FAIL*' }).Count
Write-Log '=== SUMMARY ==='
Write-Log "PASS=$passCount FAIL=$failCount"

if ($script:failures.Count -gt 0) {
  Write-Log '=== FAILURES ==='
  foreach ($failure in $script:failures) {
    Write-Log $failure
  }
  exit 1
}

exit 0
