[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PortA,

  [Parameter(Mandatory = $true)]
  [string]$PortB,

  [int]$Baud = 115200,
  [string]$Label = 'ATPair',

  [string]$SetCommandTemplate = 'AT+CHAN={value}',
  [Parameter(Mandatory = $true)]
  [string]$SameValue,
  [Parameter(Mandatory = $true)]
  [string]$DifferentValueA,
  [Parameter(Mandatory = $true)]
  [string]$DifferentValueB,

  [string]$QueryCommand = 'AT+CHAN?',
  [AllowEmptyString()]
  [string]$RxOnCommand = 'AT+RX=ON',
  [switch]$SkipRxOn,
  [string[]]$SetupCommands = @('AT', 'AT+WAKE', 'AT+DEBUG=OFF'),

  [ValidateSet('Text', 'Hex')]
  [string]$PayloadKind = 'Text',

  [string]$SendTemplate = '{payload}',
  [string]$SendTemplateAtoB = '',
  [string]$SendTemplateBtoA = '',

  [int]$TxWaitMs = 500,
  [int]$RxWaitMs = 2200,
  [int]$CommandWaitMs = 1200,
  [string]$LogPath = '',

  [switch]$ResetOnOpen,
  [switch]$SkipFinalRestore
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
  $LogPath = Join-Path 'log' "Test-AtPairChannelIsolation_${safeLabel}_${safeA}_${safeB}_$stamp.txt"
}

$logDir = Split-Path -Parent $LogPath
if (-not [string]::IsNullOrWhiteSpace($logDir)) {
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

$script:results = [System.Collections.Generic.List[string]]::new()
$script:failures = [System.Collections.Generic.List[string]]::new()
$script:restoreDone = $false
$script:exitCode = 0

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
    [bool]$Ok,
    [string]$Detail = ''
  )

  $status = if ($Ok) { 'PASS' } else { 'FAIL' }
  $line = if ($Detail) { "$status`t$Name`t$Detail" } else { "$status`t$Name" }
  [void]$script:results.Add($line)

  if (-not $Ok) {
    [void]$script:failures.Add($line)
  }
}

function Clean-Text {
  param($Text)
  $value = As-Text $Text
  return (($value -replace "`0", '<NUL>') -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', '').Trim()
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
      # USB CDC ports can briefly throw around reset/open; keep polling.
    }
    Start-Sleep -Milliseconds 25
  }

  return (Clean-Text $sb.ToString())
}

function Open-Port {
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
  $serialPort.DtrEnable = $false
  $serialPort.RtsEnable = $false
  $serialPort.Open()

  if ($script:ResetOnOpen) {
    $serialPort.DtrEnable = $false
    $serialPort.RtsEnable = $true
    Start-Sleep -Milliseconds 150
    $serialPort.RtsEnable = $false
    Start-Sleep -Milliseconds 2500
  } else {
    Start-Sleep -Milliseconds 250
  }

  return $serialPort
}

function Send-Cmd {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Name,
    [string]$Command,
    [int]$Milliseconds = $script:CommandWaitMs,
    [switch]$Quiet
  )

  if ([string]::IsNullOrWhiteSpace($Command)) {
    return ''
  }

  [void](Read-For $SerialPort 80)
  $SerialPort.Write($Command + "`r`n")
  $out = Read-For $SerialPort $Milliseconds

  if (-not $Quiet) {
    Write-Log "--- $Name >> $Command ---"
    if ([string]::IsNullOrWhiteSpace($out)) {
      Write-Log '<no output>'
    } else {
      Write-Log $out
    }
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

function Expand-SetCommand {
  param([string]$Value)
  return $script:SetCommandTemplate.Replace('{value}', $Value)
}

function To-Hex {
  param([string]$Text)

  $bytes = [System.Text.Encoding]::ASCII.GetBytes($Text)
  return (($bytes | ForEach-Object { $_.ToString('X2') }) -join '')
}

function Expand-SendCommand {
  param(
    [string]$Template,
    [string]$PayloadText,
    [string]$FromName,
    [string]$ToName
  )

  $hex = To-Hex $PayloadText
  $command = $Template
  $command = $command.Replace('{payload}', $PayloadText)
  $command = $command.Replace('{hex}', $hex)
  $command = $command.Replace('{from}', $FromName)
  $command = $command.Replace('{to}', $ToName)
  $command = $command.Replace('{label}', $script:Label)
  return $command
}

function Get-ExpectedToken {
  param([string]$PayloadText)

  if ($script:PayloadKind -eq 'Hex') {
    return (To-Hex $PayloadText)
  }

  return $PayloadText
}

function Set-RadioValue {
  param(
    [System.IO.Ports.SerialPort]$SerialPort,
    [string]$Name,
    [string]$Value
  )

  $cmd = Expand-SetCommand $Value
  $out = Send-Cmd $SerialPort $Name $cmd ($script:CommandWaitMs + 500)
  Expect-Contains "$Name set $Value" $out 'OK'

  if (-not $script:SkipRxOn -and -not [string]::IsNullOrWhiteSpace($script:RxOnCommand)) {
    $rxOut = Send-Cmd $SerialPort $Name $script:RxOnCommand $script:CommandWaitMs
    Expect-Contains "$Name RX on after set $Value" $rxOut 'OK'
  }

  if (-not [string]::IsNullOrWhiteSpace($script:QueryCommand)) {
    [void](Send-Cmd $SerialPort $Name $script:QueryCommand $script:CommandWaitMs)
  }
}

function Send-PairPayload {
  param(
    [System.IO.Ports.SerialPort]$TxPort,
    [System.IO.Ports.SerialPort]$RxPort,
    [string]$TxName,
    [string]$RxName,
    [string]$Template,
    [string]$PayloadText
  )

  $command = Expand-SendCommand $Template $PayloadText $TxName $RxName
  $expected = Get-ExpectedToken $PayloadText

  [void](Read-For $TxPort 100)
  [void](Read-For $RxPort 100)
  $TxPort.Write($command + "`r`n")

  $txOut = Read-For $TxPort $script:TxWaitMs
  $rxOut = Read-For $RxPort $script:RxWaitMs

  Write-Log "--- $TxName payload -> $RxName ---"
  Write-Log "command: $command"
  Write-Log "expected token: $expected"
  Write-Log "$TxName tx output:"
  if ([string]::IsNullOrWhiteSpace($txOut)) { Write-Log '<no output>' } else { Write-Log $txOut }
  Write-Log "$RxName rx output:"
  if ([string]::IsNullOrWhiteSpace($rxOut)) { Write-Log '<no output>' } else { Write-Log $rxOut }

  return [pscustomobject]@{
    Command = $command
    Payload = $PayloadText
    Expected = $expected
    TxOutput = $txOut
    RxOutput = $rxOut
  }
}

function Run-LinkCheck {
  param(
    [string]$Stage,
    [bool]$ShouldReceive,
    [System.IO.Ports.SerialPort]$A,
    [System.IO.Ports.SerialPort]$B
  )

  $templateAB = if ([string]::IsNullOrWhiteSpace($script:SendTemplateAtoB)) { $script:SendTemplate } else { $script:SendTemplateAtoB }
  $templateBA = if ([string]::IsNullOrWhiteSpace($script:SendTemplateBtoA)) { $script:SendTemplate } else { $script:SendTemplateBtoA }

  $payloadAB = "$($script:Label)_$($Stage)_A_TO_B"
  $resultAB = Send-PairPayload $A $B $script:PortA $script:PortB $templateAB $payloadAB
  if ($ShouldReceive) {
    Expect-Contains "$Stage $script:PortA to $script:PortB receive" $resultAB.RxOutput $resultAB.Expected
  } else {
    Expect-NotContains "$Stage $script:PortA to $script:PortB isolated" $resultAB.RxOutput $resultAB.Expected
  }

  $payloadBA = "$($script:Label)_$($Stage)_B_TO_A"
  $resultBA = Send-PairPayload $B $A $script:PortB $script:PortA $templateBA $payloadBA
  if ($ShouldReceive) {
    Expect-Contains "$Stage $script:PortB to $script:PortA receive" $resultBA.RxOutput $resultBA.Expected
  } else {
    Expect-NotContains "$Stage $script:PortB to $script:PortA isolated" $resultBA.RxOutput $resultBA.Expected
  }
}

function Restore-SameValue {
  param(
    [System.IO.Ports.SerialPort]$A,
    [System.IO.Ports.SerialPort]$B
  )

  foreach ($pair in @(@($A, $script:PortA), @($B, $script:PortB))) {
    $handle = $pair[0]
    $name = $pair[1]
    if ($null -eq $handle -or -not $handle.IsOpen) {
      continue
    }

    try {
      [void](Send-Cmd $handle $name 'AT+WAKE' $script:CommandWaitMs -Quiet)
      [void](Send-Cmd $handle $name (Expand-SetCommand $script:SameValue) ($script:CommandWaitMs + 500) -Quiet)
      if (-not $script:SkipRxOn -and -not [string]::IsNullOrWhiteSpace($script:RxOnCommand)) {
        [void](Send-Cmd $handle $name $script:RxOnCommand $script:CommandWaitMs -Quiet)
      }
    } catch {
      Write-Log "#ERROR: RESTORE_$name $($_.Exception.Message)"
    }
  }

  $script:restoreDone = $true
}

function Test-AtPairChannelIsolation {
  $a = $null
  $b = $null

  try {
    Write-Log "Test: $script:Label"
    Write-Log "Ports: $script:PortA / $script:PortB"
    Write-Log "Baud: $script:Baud"
    Write-Log "Set command: $script:SetCommandTemplate"
    Write-Log "Same value: $script:SameValue"
    Write-Log "Different values: $script:DifferentValueA / $script:DifferentValueB"
    Write-Log "Send template A->B: $(if ([string]::IsNullOrWhiteSpace($script:SendTemplateAtoB)) { $script:SendTemplate } else { $script:SendTemplateAtoB })"
    Write-Log "Send template B->A: $(if ([string]::IsNullOrWhiteSpace($script:SendTemplateBtoA)) { $script:SendTemplate } else { $script:SendTemplateBtoA })"
    Write-Log "Payload kind: $script:PayloadKind"
    Write-Log "Log: $script:LogPath"
    Write-Log ''

    $a = Open-Port $script:PortA
    $b = Open-Port $script:PortB

    $bootA = Read-For $a 600
    $bootB = Read-For $b 600
    Write-Log "--- $script:PortA boot/open ---"
    if ([string]::IsNullOrWhiteSpace($bootA)) { Write-Log '<no output>' } else { Write-Log $bootA }
    Write-Log "--- $script:PortB boot/open ---"
    if ([string]::IsNullOrWhiteSpace($bootB)) { Write-Log '<no output>' } else { Write-Log $bootB }

    foreach ($pair in @(@($a, $script:PortA), @($b, $script:PortB))) {
      foreach ($cmd in $script:SetupCommands) {
        if ([string]::IsNullOrWhiteSpace($cmd)) {
          continue
        }
        [void](Send-Cmd $pair[0] $pair[1] $cmd $script:CommandWaitMs)
      }
    }

    Write-Log ''
    Write-Log '=== STAGE 1: synchronized value, link must work ==='
    Set-RadioValue $a $script:PortA $script:SameValue
    Set-RadioValue $b $script:PortB $script:SameValue
    Run-LinkCheck 'SYNC_BASE' $true $a $b

    Write-Log ''
    Write-Log '=== STAGE 2: different values, link must stop ==='
    Set-RadioValue $a $script:PortA $script:DifferentValueA
    Set-RadioValue $b $script:PortB $script:DifferentValueB
    Run-LinkCheck 'DESYNC' $false $a $b

    Write-Log ''
    Write-Log '=== STAGE 3: synchronized again, link must recover ==='
    Set-RadioValue $a $script:PortA $script:SameValue
    Set-RadioValue $b $script:PortB $script:SameValue
    Run-LinkCheck 'RESYNC' $true $a $b

    $script:restoreDone = $true
  } finally {
    if (-not $script:SkipFinalRestore -and -not $script:restoreDone) {
      Restore-SameValue $a $b
    }

    if ($null -ne $a -and $a.IsOpen) { $a.Close() }
    if ($null -ne $b -and $b.IsOpen) { $b.Close() }
  }

  Write-Log ''
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
}

try {
  Test-AtPairChannelIsolation
} catch {
  Write-Log "#ERROR: $($_.Exception.Message)"
  $script:exitCode = 1
} finally {
  exit $script:exitCode
}
