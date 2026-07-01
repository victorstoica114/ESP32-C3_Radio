param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [int]$Baud = 500000,

    [int]$PreResetDelaySeconds = 15
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$cmdFile = Join-Path $RepoRoot 'build\jlink-reset-go.jlink'

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

function Probe-Sync {
    param([string]$SerialPort)

    $serial = [System.IO.Ports.SerialPort]::new($SerialPort, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $serial.Handshake = [System.IO.Ports.Handshake]::None
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    $serial.ReadTimeout = 100
    $serial.WriteTimeout = 500

    try {
        $serial.Open()
        Start-Sleep -Milliseconds 200
        $serial.DiscardInBuffer()

        [byte[]]$sync = @(0x55, 0x55)
        $serial.Write($sync, 0, $sync.Length)

        $deadline = [DateTime]::UtcNow.AddMilliseconds(2500)
        $bytes = New-Object System.Collections.Generic.List[byte]

        while ([DateTime]::UtcNow -lt $deadline) {
            while ($serial.BytesToRead -gt 0) {
                $b = $serial.ReadByte()
                if ($b -ge 0) {
                    $bytes.Add([byte]$b)
                }
            }

            for ($i = 1; $i -lt $bytes.Count; $i++) {
                if ($bytes[$i - 1] -eq 0x00 -and $bytes[$i] -eq 0xCC) {
                    Write-Host "ACK: 00 CC"
                    return 0
                }
                if ($bytes[$i - 1] -eq 0x00 -and $bytes[$i] -eq 0x33) {
                    Write-Host "NACK: 00 33"
                    return 3
                }
            }

            Start-Sleep -Milliseconds 20
        }

        if ($bytes.Count -eq 0) {
            Write-Host "<no response>"
        }
        else {
            $hex = ($bytes | ForEach-Object { $_.ToString("X2") }) -join ' '
            Write-Host "Unexpected response: $hex"
        }
        return 2
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

Write-Host "Hold CC1352P BOOT low now. J-Link reset will run in $PreResetDelaySeconds seconds."
Start-Sleep -Seconds $PreResetDelaySeconds

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
Write-Host "Sending TI ROM SBL sync bytes..."
$result = Probe-Sync -SerialPort $Port
exit $result
