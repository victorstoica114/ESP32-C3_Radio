param(
    [string]$Port = 'COM22',

    [int]$Baud = 115200,

    [int]$PostResetDelayMs = 1200
)

$ErrorActionPreference = 'Stop'

function Drain-Input {
    param([System.IO.Ports.SerialPort]$SerialPort, [int]$DurationMs)

    $deadline = [DateTime]::UtcNow.AddMilliseconds($DurationMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        [void]$SerialPort.ReadExisting()
        Start-Sleep -Milliseconds 20
    }
}

function Send-AtCommand {
    param(
        [System.IO.Ports.SerialPort]$SerialPort,
        [string]$Command,
        [int]$TimeoutMs = 2500
    )

    $response = New-Object System.Text.StringBuilder
    $SerialPort.Write("$Command`r`n")

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        $chunk = $SerialPort.ReadExisting()
        if ($chunk.Length -gt 0) {
            [void]$response.Append($chunk)
            $text = $response.ToString()
            if ($text.Contains("OK`r`n") -or $text.Contains("#ERROR:")) {
                return $text
            }
        }

        Start-Sleep -Milliseconds 20
    }

    return $response.ToString()
}

function Read-Uptime {
    param([System.IO.Ports.SerialPort]$SerialPort)

    $text = Send-AtCommand -SerialPort $SerialPort -Command 'AT+UPTIME?' -TimeoutMs 3000
    if ($text -notmatch '\+UPTIME:(\d+)') {
        $escaped = $text.Replace("`r", "\r").Replace("`n", "\n")
        throw "Could not parse AT+UPTIME? response: $escaped"
    }

    return [int]$Matches[1]
}

$serial = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$serial.Handshake = [System.IO.Ports.Handshake]::None
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.ReadTimeout = 100
$serial.WriteTimeout = 500

try {
    Write-Host "Opening ESP32 bridge on $Port..."
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    if ($Baud -ne 115200) {
        Write-Host "Setting CC1352P UART baud to $Baud..."
        $serial.Write("~CC1352P_BAUD=$Baud`n")
        Drain-Input -SerialPort $serial -DurationMs 700
    }

    Write-Host "Checking AT link..."
    $at = Send-AtCommand -SerialPort $serial -Command 'AT' -TimeoutMs 2500
    Write-Host ($at.Replace("`r", "\r").Replace("`n", "\n"))

    $before = Read-Uptime -SerialPort $serial
    Write-Host "Uptime before reset: $before s"

    Start-Sleep -Seconds 2
    $beforeLater = Read-Uptime -SerialPort $serial
    Write-Host "Uptime before reset, 2s later: $beforeLater s"

    Write-Host "Sending ESP32 GPIO10 reset pulse command..."
    $serial.Write("~CC1352P_RESET`n")
    $serial.BaseStream.Flush()
    Start-Sleep -Milliseconds $PostResetDelayMs
    Drain-Input -SerialPort $serial -DurationMs 200

    Write-Host "Checking AT link after reset pulse..."
    $afterAt = Send-AtCommand -SerialPort $serial -Command 'AT' -TimeoutMs 3000
    Write-Host ($afterAt.Replace("`r", "\r").Replace("`n", "\n"))

    $after = Read-Uptime -SerialPort $serial
    Write-Host "Uptime after reset pulse: $after s"

    if ($beforeLater -ge ($before + 1) -and $after -lt $beforeLater) {
        Write-Host "PASS: CC1352P uptime dropped after ESP32 GPIO10 reset pulse."
        exit 0
    }

    Write-Host "FAIL: CC1352P uptime did not drop after ESP32 GPIO10 reset pulse."
    exit 2
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
