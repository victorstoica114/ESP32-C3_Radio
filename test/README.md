# Test scripts

PowerShell scripts for quick local validation on two ESP32-C3 boards.

Logs are written under `log/` by default. The folder is kept in the repo, but generated logs are ignored by git.

## Upload AT firmware

```powershell
.\test\Upload-AtFirmware.ps1 -Module RADIO_RA02_SX1278 -Port COM4,COM5
```

Useful module values are the same as `RADIO_MODULE` in `src/main.cpp`.

## Run SX127x AT pair test

```powershell
.\test\Test-Sx127xAtPair.ps1 -Label SX1278 -PortA COM4 -PortB COM5
```

The default parameters match the RA-02 SX1278 AT firmware. For another SX127x module, override the default tokens or the batch `AT+SET` command if its expected defaults differ.
