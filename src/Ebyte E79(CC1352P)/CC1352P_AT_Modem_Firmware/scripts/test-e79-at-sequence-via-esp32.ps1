param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [string[]]$Commands = @('AT', 'AT+VERSION?', 'AT'),

    [int]$Baud = 115200,

    [int]$DelayMs = 300,

    [int]$TimeoutMs = 3000
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

    $serial.DiscardInBuffer()
    if ($Baud -ne 115200) {
        $serial.Write("~CC1352P_BAUD=$Baud`n")
        Start-Sleep -Milliseconds 600
        $serial.DiscardInBuffer()
    }

    $response = New-Object System.Text.StringBuilder

    foreach ($command in $Commands) {
        Write-Host ">>> $command"
        $serial.Write("$command`r`n")
        Start-Sleep -Milliseconds $DelayMs

        while ($serial.BytesToRead -gt 0) {
            [void]$response.Append($serial.ReadExisting())
            Start-Sleep -Milliseconds 10
        }
    }

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        while ($serial.BytesToRead -gt 0) {
            [void]$response.Append($serial.ReadExisting())
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
