[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PortA,

  [Parameter(Mandatory = $true)]
  [string]$PortB,

  [int]$Baud = 9600,
  [int[]]$Channels = @(80),
  [int[]]$RatesKbps = @(250, 1000, 2000),
  [int[]]$PowersDbm = @(-18, -6, 0),
  [int]$FrameBytes = 32,
  [double]$DurationSeconds = 8.0,
  [int]$GapMs = 15,
  [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ($FrameBytes -lt 8 -or $FrameBytes -gt 32) {
  throw 'FrameBytes must be between 8 and 32 for nRF24L01.'
}
if ($DurationSeconds -lt 1 -or $DurationSeconds -gt 120) {
  throw 'DurationSeconds must be between 1 and 120.'
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
  $OutputDirectory = Join-Path 'log' "NRF24L01_Sustained_${PortA}_${PortB}_$stamp"
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$logPath = Join-Path $OutputDirectory 'session.log'
$csvPath = Join-Path $OutputDirectory 'summary.csv'
$script:rows = [System.Collections.Generic.List[object]]::new()

function Write-Log {
  param([string]$Message = '')
  $line = "[$(Get-Date -Format 'HH:mm:ss')] $Message"
  [Console]::Out.WriteLine($line)
  Add-Content -LiteralPath $script:logPath -Value $line
}

function Open-Port {
  param([string]$Name)
  $port = [System.IO.Ports.SerialPort]::new(
    $Name,
    $script:Baud,
    [System.IO.Ports.Parity]::None,
    8,
    [System.IO.Ports.StopBits]::One
  )
  $port.ReadTimeout = 200
  $port.WriteTimeout = 1000
  $port.NewLine = "`n"
  $port.DtrEnable = $false
  $port.RtsEnable = $false
  $port.Open()
  Start-Sleep -Milliseconds 350
  [void]$port.ReadExisting()
  return $port
}

function Read-For {
  param(
    [System.IO.Ports.SerialPort]$Port,
    [int]$Milliseconds
  )
  $deadline = [DateTime]::UtcNow.AddMilliseconds($Milliseconds)
  $builder = [System.Text.StringBuilder]::new()
  while ([DateTime]::UtcNow -lt $deadline) {
    $chunk = $Port.ReadExisting()
    if ($chunk.Length -gt 0) {
      [void]$builder.Append($chunk)
    }
    Start-Sleep -Milliseconds 10
  }
  return $builder.ToString()
}

function Send-Command {
  param(
    [System.IO.Ports.SerialPort]$Port,
    [string]$Name,
    [string]$Command
  )
  [void](Read-For $Port 30)
  $Port.Write($Command + "`r`n")
  $response = Read-For $Port 260
  if ($response -notmatch '(?m)^OK\r?$') {
    throw "$Name rejected '$Command': $($response.Trim())"
  }
}

function Configure-Base {
  param(
    [System.IO.Ports.SerialPort]$Port,
    [string]$Name
  )
  foreach ($command in @(
    'AT',
    'AT+DEBUG=OFF',
    'AT+RX=OFF',
    'AT+DYN=ON',
    'AT+AUTOACK=OFF',
    'AT+CRC=ON',
    'AT+ADDR=0123456789'
  )) {
    Send-Command $Port $Name $command
  }
}

function Configure-Scenario {
  param(
    [System.IO.Ports.SerialPort]$Port,
    [string]$Name,
    [int]$Channel,
    [int]$RateKbps,
    [int]$PowerDbm,
    [bool]$Receiver
  )
  Send-Command $Port $Name 'AT+RX=OFF'
  Send-Command $Port $Name "AT+CHAN=$Channel"
  Send-Command $Port $Name "AT+RATE=$RateKbps"
  Send-Command $Port $Name "AT+PWR=$PowerDbm"
  if ($Receiver) {
    Send-Command $Port $Name 'AT+RX=ON'
  }
}

function Invoke-LinkRun {
  param(
    [System.IO.Ports.SerialPort]$Tx,
    [System.IO.Ports.SerialPort]$Rx,
    [string]$Direction,
    [int]$Channel,
    [int]$RateKbps,
    [int]$PowerDbm
  )
  [void](Read-For $Tx 50)
  [void](Read-For $Rx 50)
  Start-Sleep -Milliseconds 120

  $sent = [System.Collections.Generic.HashSet[string]]::new()
  $receivedText = [System.Text.StringBuilder]::new()
  $txText = [System.Text.StringBuilder]::new()
  $deadline = [DateTime]::UtcNow.AddSeconds($script:DurationSeconds)
  $index = 0
  while ([DateTime]::UtcNow -lt $deadline) {
    $token = ("N{0:D7}" -f $index).PadRight($script:FrameBytes, 'X')
    [void]$sent.Add($token)
    $Tx.Write($token + "`r`n")
    Start-Sleep -Milliseconds $script:GapMs
    $rxChunk = $Rx.ReadExisting()
    if ($rxChunk.Length -gt 0) {
      [void]$receivedText.Append($rxChunk)
    }
    $txChunk = $Tx.ReadExisting()
    if ($txChunk.Length -gt 0) {
      [void]$txText.Append($txChunk)
    }
    $index++
  }
  Start-Sleep -Milliseconds 400
  [void]$receivedText.Append($Rx.ReadExisting())
  [void]$txText.Append($Tx.ReadExisting())

  $received = [System.Collections.Generic.HashSet[string]]::new()
  foreach ($line in ($receivedText.ToString() -split "`r?`n")) {
    $value = $line.Trim()
    if ($sent.Contains($value)) {
      [void]$received.Add($value)
    }
  }
  $sentCount = $sent.Count
  $receivedCount = $received.Count
  $loss = if ($sentCount) {
    100.0 * ($sentCount - $receivedCount) / $sentCount
  } else {
    100.0
  }
  $serialErrors = ([regex]::Matches($txText.ToString(), '#ERROR')).Count
  $row = [pscustomobject]@{
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    direction = $Direction
    channel = $Channel
    data_rate_kbps = $RateKbps
    tx_power_dbm = $PowerDbm
    frame_bytes = $script:FrameBytes
    duration_s = $script:DurationSeconds
    gap_ms = $script:GapMs
    frames_transmitted = $sentCount
    frames_received = $receivedCount
    frame_loss_percent = $loss
    transmitter_serial_errors = $serialErrors
  }
  [void]$script:rows.Add($row)
  Write-Log ("{0} CH{1} {2} kbps {3} dBm: {4}/{5}, loss={6:N4}%, serial_errors={7}" -f `
    $Direction, $Channel, $RateKbps, $PowerDbm, $receivedCount, $sentCount, $loss, $serialErrors)
}

$portAHandle = $null
$portBHandle = $null
try {
  Write-Log "Starting sustained nRF24L01 link diagnostic on $PortA / $PortB"
  $portAHandle = Open-Port $PortA
  $portBHandle = Open-Port $PortB
  Configure-Base $portAHandle $PortA
  Configure-Base $portBHandle $PortB

  foreach ($channel in $Channels) {
    foreach ($rate in $RatesKbps) {
      foreach ($power in $PowersDbm) {
        Configure-Scenario $portAHandle $PortA $channel $rate $power $false
        Configure-Scenario $portBHandle $PortB $channel $rate $power $true
        Invoke-LinkRun $portAHandle $portBHandle "$PortA->$PortB" $channel $rate $power

        Configure-Scenario $portBHandle $PortB $channel $rate $power $false
        Configure-Scenario $portAHandle $PortA $channel $rate $power $true
        Invoke-LinkRun $portBHandle $portAHandle "$PortB->$PortA" $channel $rate $power
      }
    }
  }
} finally {
  foreach ($item in @(
    @{ Port = $portAHandle; Name = $PortA },
    @{ Port = $portBHandle; Name = $PortB }
  )) {
    if ($null -ne $item.Port -and $item.Port.IsOpen) {
      try {
        Configure-Scenario $item.Port $item.Name 80 1000 -12 $false
      } catch {
        Write-Log "WARNING: could not restore $($item.Name): $($_.Exception.Message)"
      }
      $item.Port.Close()
    }
  }
  $script:rows | Export-Csv -LiteralPath $csvPath -NoTypeInformation
  Write-Log "CSV: $((Resolve-Path $csvPath).Path)"
}

$failed = @($script:rows | Where-Object {
  $_.frame_loss_percent -gt 0 -or $_.transmitter_serial_errors -gt 0
})
Write-Log "Completed $($script:rows.Count) scenarios; non-zero-loss scenarios: $($failed.Count)"
if ($failed.Count) {
  exit 2
}
