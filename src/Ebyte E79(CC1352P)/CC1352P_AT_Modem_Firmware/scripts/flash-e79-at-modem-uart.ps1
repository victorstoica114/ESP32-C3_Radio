param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [int]$Baud = 115200,

    [int]$PreSyncDelaySeconds = 8
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$sbl = Join-Path $RepoRoot 'scripts\ti-python-sbl-esp32-bridge.py'
$bin = Join-Path $RepoRoot 'firmware\e79_at_modem\gcc\e79_at_modem.bin'

if (-not (Test-Path -LiteralPath $sbl)) {
    throw "Missing TI serial bootloader script: $sbl"
}
if (-not (Test-Path -LiteralPath $bin)) {
    throw "Build e79_at_modem first. Missing BIN: $bin"
}

Write-Host "Put CC1352P in ROM serial bootloader mode first:"
Write-Host "  1. Hold BOOT low (E79 BOOT = DIO15 active-low)."
Write-Host "  2. During the next $PreSyncDelaySeconds seconds, pulse RESET_N manually."
Write-Host "  3. Release RESET_N, keep BOOT low until this script starts syncing."
Write-Host ""
Write-Host "Using $Port at $Baud baud."
Start-Sleep -Seconds $PreSyncDelaySeconds

& python $sbl -d CC13X2 -p $Port -b $Baud --no-invoke-bootloader -f -e -w -v -a 0x0 $bin
if ($LASTEXITCODE -ne 0) {
    throw "UART serial bootloader flash failed with exit code $LASTEXITCODE"
}
