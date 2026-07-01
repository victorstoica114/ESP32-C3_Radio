param(
    [string]$PortA = 'COM19',
    [string]$PortB = 'COM22',
    [int]$BridgeBaud = 115200
)

$ErrorActionPreference = 'Stop'

$script:Devices = @()
$script:PassCount = 0
$script:FailCount = 0

function New-TestDevice {
    param([string]$Name, [string]$Port)

    $serial = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $serial.Handshake = [System.IO.Ports.Handshake]::None
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    $serial.ReadTimeout = 100
    $serial.WriteTimeout = 1000

    [PSCustomObject]@{
        Name = $Name
        Port = $Port
        Serial = $serial
        Buffer = ''
        Lines = [System.Collections.Generic.List[string]]::new()
    }
}

function Add-Result {
    param([bool]$Ok, [string]$Message)

    if ($Ok) {
        $script:PassCount++
        Write-Host "[PASS] $Message"
    }
    else {
        $script:FailCount++
        Write-Host "[FAIL] $Message"
    }
}

function Poll-Device {
    param([object]$Device)

    $chunk = $Device.Serial.ReadExisting()
    if ($chunk.Length -le 0) {
        return
    }

    $Device.Buffer += $chunk

    while ($true) {
        $idxR = $Device.Buffer.IndexOf("`r")
        $idxN = $Device.Buffer.IndexOf("`n")

        if ($idxR -lt 0 -and $idxN -lt 0) {
            break
        }

        if ($idxR -lt 0) {
            $idx = $idxN
        }
        elseif ($idxN -lt 0) {
            $idx = $idxR
        }
        else {
            $idx = [Math]::Min($idxR, $idxN)
        }

        $line = $Device.Buffer.Substring(0, $idx)
        $remove = $idx + 1
        while ($remove -lt $Device.Buffer.Length -and
               ($Device.Buffer[$remove] -eq "`r" -or $Device.Buffer[$remove] -eq "`n")) {
            $remove++
        }
        $Device.Buffer = $Device.Buffer.Substring($remove)

        if ($line.Length -gt 0) {
            $Device.Lines.Add($line)
            Write-Host ("[{0}] {1}" -f $Device.Name, $line)
        }
    }
}

function Poll-All {
    foreach ($dev in $script:Devices) {
        if ($dev.Serial.IsOpen) {
            Poll-Device -Device $dev
        }
    }
}

function Drain-All {
    param([int]$DurationMs = 300)

    $deadline = [DateTime]::UtcNow.AddMilliseconds($DurationMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        Poll-All
        Start-Sleep -Milliseconds 20
    }
}

function Clear-Lines {
    param([object]$Device)

    $Device.Lines.Clear()
    $Device.Buffer = ''
}

function Send-Command {
    param(
        [object]$Device,
        [string]$Command,
        [int]$TimeoutMs = 3000
    )

    $start = $Device.Lines.Count
    Write-Host ("[{0}] >>> {1}" -f $Device.Name, $Command)
    $Device.Serial.Write("$Command`r`n")
    try {
        $Device.Serial.BaseStream.Flush()
    }
    catch {
    }

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        Poll-All
        $newLines = @($Device.Lines | Select-Object -Skip $start)
        if ($newLines | Where-Object { $_ -eq 'OK' -or $_.StartsWith('#ERROR:') }) {
            return $newLines
        }
        Start-Sleep -Milliseconds 20
    }

    Poll-All
    return @($Device.Lines | Select-Object -Skip $start)
}

function Expect-Ok {
    param(
        [object]$Device,
        [string]$Command,
        [string]$Message,
        [string]$Contains = '',
        [int]$TimeoutMs = 3000
    )

    $lines = Send-Command -Device $Device -Command $Command -TimeoutMs $TimeoutMs
    $ok = ($lines -contains 'OK')
    if ($Contains.Length -gt 0) {
        $ok = $ok -and (($lines -join "`n") -match $Contains)
    }
    Add-Result -Ok $ok -Message $Message
    return $lines
}

function Expect-Error {
    param(
        [object]$Device,
        [string]$Command,
        [string]$Expected,
        [string]$Message,
        [int]$TimeoutMs = 3000
    )

    $lines = Send-Command -Device $Device -Command $Command -TimeoutMs $TimeoutMs
    $text = $lines -join "`n"
    $ok = $text -match "#ERROR:\s+$Expected"
    Add-Result -Ok $ok -Message $Message
    return $lines
}

function Wait-For-Line {
    param(
        [object]$Device,
        [int]$StartIndex,
        [string]$Pattern,
        [int]$TimeoutMs = 5000
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        Poll-All
        $newLines = @($Device.Lines | Select-Object -Skip $StartIndex)
        foreach ($line in $newLines) {
            if ($line -match $Pattern) {
                return $line
            }
        }
        Start-Sleep -Milliseconds 20
    }

    Poll-All
    return $null
}

function Ensure-At-Link {
    param([object]$Device)

    for ($i = 0; $i -lt 5; $i++) {
        $lines = Send-Command -Device $Device -Command 'AT' -TimeoutMs 1500
        if ($lines -contains 'OK') {
            Add-Result -Ok $true -Message "$($Device.Name) AT link is alive"
            return
        }
        Start-Sleep -Milliseconds 250
    }

    Add-Result -Ok $false -Message "$($Device.Name) AT link is alive"
}

function Configure-Bridge {
    param([object]$Device)

    Write-Host ("[{0}] opening {1}" -f $Device.Name, $Device.Port)
    $Device.Serial.Open()
    Start-Sleep -Milliseconds 500
    [void]$Device.Serial.ReadExisting()
    if ($BridgeBaud -ne 115200) {
        $Device.Serial.Write("~CC1352P_BAUD=$BridgeBaud`n")
        Drain-All -DurationMs 900
    }
    else {
        Drain-All -DurationMs 300
    }
    Clear-Lines -Device $Device
}

function Test-ModuleBasics {
    param([object]$Device)

    Write-Host ""
    Write-Host "==== Basic AT tests on $($Device.Name) / $($Device.Port) ===="

    [void](Expect-Ok $Device 'AT' "$($Device.Name) AT")
    [void](Expect-Ok $Device 'AT?' "$($Device.Name) AT? ID" '\+ID:E79_AT_MODEM')
    [void](Expect-Ok $Device 'AT+VERSION?' "$($Device.Name) version" '\+VERSION:E79_AT_MODEM' -TimeoutMs 8000)
    [void](Expect-Ok $Device 'AT+HELP' "$($Device.Name) help" '\+HELP:AT')

    [void](Expect-Ok $Device 'AT+DEFAULT' "$($Device.Name) default")
    [void](Expect-Ok $Device 'AT+CFG?' "$($Device.Name) default CFG" 'FREQ=433920000,RATE=50000,PWR=13,MOD=2GFSK,SYNC=0x930B51DE.*RX=OFF,SLEEP=NO')

    [void](Expect-Ok $Device 'AT+DEBUG?' "$($Device.Name) debug query" '\+DEBUG:OFF')
    [void](Expect-Ok $Device 'AT+DEBUG=ON' "$($Device.Name) debug on")
    [void](Expect-Ok $Device 'AT+DEBUG?' "$($Device.Name) debug query on" '\+DEBUG:ON')
    [void](Expect-Ok $Device 'AT+DEBUG=OFF' "$($Device.Name) debug off")

    [void](Expect-Ok $Device 'AT+FREQ?' "$($Device.Name) freq query" '\+FREQ:433920000')
    [void](Expect-Ok $Device 'AT+FREQ=431000000' "$($Device.Name) min freq")
    [void](Expect-Ok $Device 'AT+FREQ?' "$($Device.Name) min freq readback" '\+FREQ:431000000')
    [void](Expect-Ok $Device 'AT+FREQ=500000000' "$($Device.Name) max freq")
    [void](Expect-Ok $Device 'AT+FREQ?' "$($Device.Name) max freq readback" '\+FREQ:500000000')
    [void](Expect-Error $Device 'AT+FREQ=430999999' 'BAD_FREQ' "$($Device.Name) reject low freq")
    [void](Expect-Error $Device 'AT+FREQ=500000001' 'BAD_FREQ' "$($Device.Name) reject high freq")
    [void](Expect-Ok $Device 'AT+FREQ=433920000' "$($Device.Name) restore freq")

    [void](Expect-Ok $Device 'AT+PWR?' "$($Device.Name) pwr query" '\+PWR:13')
    [void](Expect-Ok $Device 'AT+PWR=-20' "$($Device.Name) min pwr")
    [void](Expect-Ok $Device 'AT+PWR?' "$($Device.Name) min pwr readback" '\+PWR:-20')
    [void](Expect-Ok $Device 'AT+PWR=13' "$($Device.Name) max safe pwr")
    [void](Expect-Error $Device 'AT+PWR=14' 'BAD_PWR' "$($Device.Name) reject unsupported pwr 14")
    [void](Expect-Error $Device 'AT+PWR=-21' 'BAD_PWR' "$($Device.Name) reject unsupported pwr -21")

    [void](Expect-Ok $Device 'AT+RATE?' "$($Device.Name) rate query" '\+RATE:50000')
    [void](Expect-Ok $Device 'AT+RATE=50000' "$($Device.Name) set supported rate")
    [void](Expect-Error $Device 'AT+RATE=9600' 'BAD_RATE' "$($Device.Name) reject unsupported rate")

    [void](Expect-Ok $Device 'AT+MOD?' "$($Device.Name) mod query" '\+MOD:2GFSK')
    [void](Expect-Ok $Device 'AT+MOD=2GFSK' "$($Device.Name) set 2GFSK")
    [void](Expect-Error $Device 'AT+MOD=LORA' 'BAD_MOD' "$($Device.Name) reject fake LoRa mod")

    [void](Expect-Ok $Device 'AT+SYNC?' "$($Device.Name) sync query" '\+SYNC:0x930B51DE')
    [void](Expect-Ok $Device 'AT+SYNC=0xAABBCCDD' "$($Device.Name) set sync")
    [void](Expect-Ok $Device 'AT+SYNC?' "$($Device.Name) sync readback" '\+SYNC:0xAABBCCDD')
    [void](Expect-Error $Device 'AT+SYNC=0x123456789' 'BAD_SYNC' "$($Device.Name) reject long sync")
    [void](Expect-Ok $Device 'AT+SYNC=0x930B51DE' "$($Device.Name) restore sync")

    [void](Expect-Ok $Device 'AT+ADDR?' "$($Device.Name) addr N/A" '\+ADDR:N/A')
    [void](Expect-Error $Device 'AT+ADDR=1' 'ADDR_NA' "$($Device.Name) reject addr setter")
    [void](Expect-Ok $Device 'AT+CHAN?' "$($Device.Name) chan N/A" '\+CHAN:N/A')
    [void](Expect-Error $Device 'AT+CHAN=1' 'CHAN_NA' "$($Device.Name) reject chan setter")

    [void](Expect-Error $Device 'AT+SEND=' 'BAD_LEN' "$($Device.Name) reject empty send")
    [void](Expect-Error $Device 'AT+SENDHEX=ABC' 'BAD_HEX' "$($Device.Name) reject odd hex")
    [void](Expect-Error $Device 'AT+UNKNOWN' 'UNKNOWN_CMD' "$($Device.Name) reject unknown command")

    [void](Expect-Ok $Device 'AT+RSSI?' "$($Device.Name) RSSI query" '\+RSSI:')
    [void](Expect-Ok $Device 'AT+STATUS?' "$($Device.Name) status query" '\+STATUS:SLEEP=NO')
    [void](Expect-Ok $Device 'AT+LASTPKT?' "$($Device.Name) lastpkt query" '\+LASTPKT:')
    [void](Expect-Ok $Device 'AT+RANDOM?' "$($Device.Name) random query" '\+RANDOM:0x[0-9A-F]+')
    [void](Expect-Ok $Device 'AT+UPTIME?' "$($Device.Name) uptime query" '\+UPTIME:\d+')

    [void](Expect-Error $Device 'AT+SETRADIO=434000000,9600,13,2GFSK,0x930B51DE' 'BAD_RATE' "$($Device.Name) SETRADIO validates before apply")
    [void](Expect-Ok $Device 'AT+CFG?' "$($Device.Name) SETRADIO invalid did not partially apply freq" 'FREQ=433920000,RATE=50000')
    [void](Expect-Ok $Device 'AT+SETRADIO=434000000,50000,13,2GFSK,0x12345678' "$($Device.Name) SETRADIO valid")
    [void](Expect-Ok $Device 'AT+CFG?' "$($Device.Name) SETRADIO readback" 'FREQ=434000000,RATE=50000,PWR=13,MOD=2GFSK,SYNC=0x12345678')
    [void](Expect-Ok $Device 'AT+DEFAULT' "$($Device.Name) default after SETRADIO")
}

function Prepare-RadioPair {
    param([object]$A, [object]$B)

    foreach ($dev in @($A, $B)) {
        [void](Expect-Ok $dev 'AT+DEFAULT' "$($dev.Name) RF prepare default")
        [void](Expect-Ok $dev 'AT+FREQ=433920000' "$($dev.Name) RF prepare freq")
        [void](Expect-Ok $dev 'AT+RATE=50000' "$($dev.Name) RF prepare rate")
        [void](Expect-Ok $dev 'AT+PWR=13' "$($dev.Name) RF prepare pwr")
        [void](Expect-Ok $dev 'AT+SYNC=0x930B51DE' "$($dev.Name) RF prepare sync")
        [void](Expect-Ok $dev 'AT+WAKE' "$($dev.Name) RF prepare wake")
        [void](Expect-Ok $dev 'AT+RX=OFF' "$($dev.Name) RF prepare RX off")
    }
}

function Test-RfPair {
    param([object]$A, [object]$B)

    Write-Host ""
    Write-Host "==== RF tests between $($A.Name) and $($B.Name) ===="
    Prepare-RadioPair -A $A -B $B

    $rxStart = $A.Lines.Count
    [void](Expect-Ok $A 'AT+RX=ON' "$($A.Name) RX ON for text packet")
    [void](Expect-Ok $B 'AT+SEND=HELLOE79' "$($B.Name) SEND text")
    $rxLine = Wait-For-Line -Device $A -StartIndex $rxStart -Pattern '^\+RX:8,-?\d+,HELLOE79$' -TimeoutMs 6000
    Add-Result -Ok ($null -ne $rxLine) -Message "$($A.Name) received text packet from $($B.Name)"
    [void](Expect-Ok $A 'AT+LASTPKT?' "$($A.Name) LASTPKT text payload" '\+LASTPKT:8,-?\d+,48454C4C4F453739')
    [void](Expect-Ok $A 'AT+RSSI?' "$($A.Name) RSSI after RX" '\+RSSI:')

    [void](Expect-Ok $A 'AT+RX=OFF' "$($A.Name) RX OFF before reverse")
    $rxStart = $B.Lines.Count
    [void](Expect-Ok $B 'AT+RX=ON' "$($B.Name) RX ON for hex packet")
    [void](Expect-Ok $A 'AT+SENDHEX=010203A5' "$($A.Name) SENDHEX binary")
    $rxHexLine = Wait-For-Line -Device $B -StartIndex $rxStart -Pattern '^\+RXHEX:4,-?\d+,010203A5$' -TimeoutMs 6000
    Add-Result -Ok ($null -ne $rxHexLine) -Message "$($B.Name) received binary packet from $($A.Name)"
    [void](Expect-Ok $B 'AT+LASTPKT?' "$($B.Name) LASTPKT binary payload" '\+LASTPKT:4,-?\d+,010203A5')

    [void](Expect-Ok $A 'AT+RX=OFF' "$($A.Name) RX off after RF tests")
    [void](Expect-Ok $B 'AT+RX=OFF' "$($B.Name) RX off after RF tests")
}

function Test-SleepAndReset {
    param([object]$Device)

    Write-Host ""
    Write-Host "==== Sleep/reset tests on $($Device.Name) ===="

    [void](Expect-Ok $Device 'AT+RX=OFF' "$($Device.Name) sleep test RX off")
    [void](Expect-Ok $Device 'AT+SLEEP' "$($Device.Name) sleep")
    [void](Expect-Ok $Device 'AT+STATUS?' "$($Device.Name) status sleeping" 'SLEEP=YES')
    [void](Expect-Error $Device 'AT+SEND=Z' 'RADIO_SLEEPING \(send AT\+WAKE\)' "$($Device.Name) reject TX while sleeping")
    [void](Expect-Ok $Device 'AT+WAKE' "$($Device.Name) wake")
    [void](Expect-Ok $Device 'AT+STATUS?' "$($Device.Name) status awake" 'SLEEP=NO')

    $lines = Send-Command -Device $Device -Command 'AT+RESET' -TimeoutMs 3000
    Add-Result -Ok ($lines -contains 'OK') -Message "$($Device.Name) AT+RESET returned OK"
    Start-Sleep -Milliseconds 1200
    Ensure-At-Link -Device $Device
    [void](Expect-Ok $Device 'AT+CFG?' "$($Device.Name) CFG after reset" 'FREQ=433920000,RATE=50000,PWR=13,MOD=2GFSK')
}

try {
    $devA = New-TestDevice -Name 'A' -Port $PortA
    $devB = New-TestDevice -Name 'B' -Port $PortB
    $script:Devices = @($devA, $devB)

    Configure-Bridge -Device $devA
    Configure-Bridge -Device $devB

    Ensure-At-Link -Device $devA
    Ensure-At-Link -Device $devB

    Test-ModuleBasics -Device $devA
    Test-ModuleBasics -Device $devB
    Test-RfPair -A $devA -B $devB
    Test-SleepAndReset -Device $devA
    Test-SleepAndReset -Device $devB
}
finally {
    foreach ($dev in $script:Devices) {
        if ($dev.Serial.IsOpen) {
            $dev.Serial.Close()
        }
        $dev.Serial.Dispose()
    }
}

Write-Host ""
Write-Host "==== SUMMARY ===="
Write-Host "PASS: $script:PassCount"
Write-Host "FAIL: $script:FailCount"

if ($script:FailCount -ne 0) {
    exit 1
}

exit 0
