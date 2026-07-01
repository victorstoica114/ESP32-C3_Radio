param(
    [string]$Port = 'COM22'
)

$ErrorActionPreference = 'Stop'

$serial = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$serial.Handshake = [System.IO.Ports.Handshake]::None
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.ReadTimeout = 100
$serial.WriteTimeout = 500

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.Write("~CC1352P_RESET`n")
    $serial.BaseStream.Flush()
    Start-Sleep -Milliseconds 500
    Write-Host "Sent ESP32 GPIO10 reset pulse command on $Port."
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
