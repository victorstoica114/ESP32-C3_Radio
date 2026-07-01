param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [string]$Command = "AT",

    [int]$TimeoutMs = 1500,

    [switch]$NoWarmup
)

$ErrorActionPreference = 'Stop'

$serial = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$serial.Handshake = [System.IO.Ports.Handshake]::None
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.ReadTimeout = 200
$serial.WriteTimeout = 500

function Drain-Input {
    param([System.IO.Ports.SerialPort]$SerialPort, [int]$DurationMs)

    $deadline = [DateTime]::UtcNow.AddMilliseconds($DurationMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        [void]$SerialPort.ReadExisting()
        Start-Sleep -Milliseconds 20
    }
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300

    $serial.DiscardInBuffer()

    if (-not $NoWarmup -and $Command -ne "AT") {
        $serial.Write("AT`r`n")
        Drain-Input -SerialPort $serial -DurationMs 500
    }

    $serial.Write("$Command`r`n")

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    $response = New-Object System.Text.StringBuilder

    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $chunk = $serial.ReadExisting()
            if ($chunk.Length -gt 0) {
                [void]$response.Append($chunk)
                if ($response.ToString().Contains("`n")) {
                    break
                }
            }
        }
        catch [System.TimeoutException] {
        }

        Start-Sleep -Milliseconds 20
    }

    $text = $response.ToString()
    if ($text.Length -eq 0) {
        Write-Host "<no response>"
        exit 2
    }

    $escaped = $text.Replace("`r", "\r").Replace("`n", "\n")
    Write-Host $escaped
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
