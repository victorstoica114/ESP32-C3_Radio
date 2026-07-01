param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [int]$Baud = 500000,

    [int]$PreSyncDelaySeconds = 15,

    [switch]$PulseReset
)

$ErrorActionPreference = 'Stop'

Write-Host "Using ESP32 bridge on $Port. CC1352P UART baud: $Baud."
Write-Host "This probe only sends TI ROM SBL sync bytes 0x55 0x55 and waits for 00 CC/00 33."
Write-Host "Hold CC1352P BOOT low now."
Write-Host "During the next $PreSyncDelaySeconds seconds, pulse CC1352P RESET manually, then keep BOOT held."

$serial = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$serial.Handshake = [System.IO.Ports.Handshake]::None
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.ReadTimeout = 100
$serial.WriteTimeout = 500

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300

    $serial.DiscardInBuffer()
    $serial.Write("~CC1352P_BAUD=$Baud`n")
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    Start-Sleep -Seconds $PreSyncDelaySeconds

    if ($PulseReset) {
        Write-Host "Pulsing CC1352P reset through ESP32 bridge..."
        $serial.Write("~CC1352P_RESET`n")
        Start-Sleep -Milliseconds 300
        $serial.DiscardInBuffer()
    }

    Write-Host "Sending sync bytes..."
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
                exit 0
            }
            if ($bytes[$i - 1] -eq 0x00 -and $bytes[$i] -eq 0x33) {
                Write-Host "NACK: 00 33"
                exit 3
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
    exit 2
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
