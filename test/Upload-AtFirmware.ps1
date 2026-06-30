[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string[]]$Port,

  [string]$Module = 'RADIO_RA02_SX1278',
  [string]$Program = 'AT_COMMANDS',
  [string]$Environment = 'esp32-c3-devkitc-02',
  [switch]$Clean
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$env:PYTHONIOENCODING = 'utf-8'
$env:PLATFORMIO_BUILD_FLAGS = "-DRADIO_MODULE=$Module -DRADIO_PROGRAM=$Program"

Write-Host "Module:  $Module"
Write-Host "Program: $Program"
Write-Host "Env:     $Environment"
Write-Host "Ports:   $($Port -join ', ')"
Write-Host ""

if ($Clean) {
  pio run -e $Environment -t clean
}

foreach ($uploadPort in $Port) {
  Write-Host "Uploading to $uploadPort..."
  pio run -e $Environment -t upload --upload-port $uploadPort
}
