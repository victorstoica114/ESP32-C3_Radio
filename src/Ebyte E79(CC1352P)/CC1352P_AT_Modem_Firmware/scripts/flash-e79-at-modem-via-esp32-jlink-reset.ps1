param(
    [string]$Port = 'COM22',

    [int]$Baud = 115200,

    [int]$PreResetDelaySeconds = 0
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$bin = Join-Path $RepoRoot 'firmware\e79_at_modem\gcc\e79_at_modem.bin'
$sbl = Join-Path $RepoRoot 'scripts\ti-python-sbl-esp32-bridge.py'
$cmdFile = Join-Path $RepoRoot 'build\jlink-reset-go.jlink'

if (-not (Test-Path -LiteralPath $bin)) {
    throw "Missing firmware image: $bin"
}

if (-not (Test-Path -LiteralPath $sbl)) {
    throw "Missing ESP32 bridge SBL helper: $sbl"
}

if (-not (Test-Path -LiteralPath $JLinkExe)) {
    throw "Missing J-Link executable: $JLinkExe"
}

function Set-BridgeBaud {
    param([string]$SerialPort, [int]$TargetBaud)

    $serial = [System.IO.Ports.SerialPort]::new($SerialPort, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $serial.Handshake = [System.IO.Ports.Handshake]::None
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    $serial.ReadTimeout = 100
    $serial.WriteTimeout = 500

    try {
        $serial.Open()
        Start-Sleep -Milliseconds 300
        $serial.DiscardInBuffer()
        $serial.Write("~CC1352P_BAUD=$TargetBaud`n")
        Start-Sleep -Milliseconds 300
        $serial.DiscardInBuffer()
    }
    finally {
        if ($serial.IsOpen) {
            $serial.Close()
        }
        $serial.Dispose()
    }
}

Write-Host "Setting ESP32 bridge target UART baud to $Baud..."
Set-BridgeBaud -SerialPort $Port -TargetBaud $Baud

if ($PreResetDelaySeconds -gt 0) {
    Write-Host "Hold CC1352P BOOT low now. J-Link reset will run in $PreResetDelaySeconds seconds."
    Start-Sleep -Seconds $PreResetDelaySeconds
}

New-Item -ItemType Directory -Force -Path (Split-Path $cmdFile) | Out-Null
@"
jtagconf -1 -1
connect
r
g
q
"@ | Set-Content -LiteralPath $cmdFile -Encoding ASCII

Write-Host "Resetting CC1352P through J-Link..."
& $JLinkExe -device CC1352P1F3 -if cJTAG -speed 4000 -jtagconf -1,-1 -autoconnect 1 -CommanderScript $cmdFile
if ($LASTEXITCODE -ne 0) {
    throw "J-Link reset failed with exit code $LASTEXITCODE"
}

Start-Sleep -Milliseconds 300
Write-Host "Writing firmware through TI ROM SBL via ESP32 bridge..."
& python $sbl -d CC13X2 -p $Port -b $Baud --no-invoke-bootloader -f -e -w -v -a 0x0 $bin
exit $LASTEXITCODE
