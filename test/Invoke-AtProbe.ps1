[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Port,

  [int]$Baud = 115200,

  [string[]]$Command = @(
    'AT',
    'AT+CFG?',
    'AT+AUX?',
    'AT+MODE?',
    'AT+CHAN?',
    'AT+BAUD?',
    'AT+POWER?',
    'AT+INFO?'
  ),

  [int]$OpenWaitMs = 500,
  [int]$CommandWaitMs = 1300
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$sp = [System.IO.Ports.SerialPort]::new($Port, $Baud, 'None', 8, 'One')
$sp.NewLine = "`r`n"
$sp.ReadTimeout = 700
$sp.WriteTimeout = 700

try {
  Write-Host "--- $Port @ $Baud ---"
  $sp.Open()
  Start-Sleep -Milliseconds $OpenWaitMs

  $boot = $sp.ReadExisting()
  if (-not [string]::IsNullOrWhiteSpace($boot)) {
    Write-Host '[BOOT/BUFFER]'
    Write-Host $boot
  }

  foreach ($cmd in $Command) {
    Write-Host ">> $cmd"
    $sp.Write($cmd + "`r`n")
    Start-Sleep -Milliseconds $CommandWaitMs

    $out = $sp.ReadExisting()
    if ([string]::IsNullOrWhiteSpace($out)) {
      Write-Host '<no output>'
    } else {
      Write-Host $out
    }
  }
} finally {
  if ($sp.IsOpen) {
    $sp.Close()
  }
}
