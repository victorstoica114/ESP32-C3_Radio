$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$firmwareDir = Join-Path $RepoRoot 'firmware\e79_at_modem\gcc'

Push-Location $firmwareDir
try {
    & mingw32-make.exe
    if ($LASTEXITCODE -ne 0) {
        throw "e79_at_modem build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
