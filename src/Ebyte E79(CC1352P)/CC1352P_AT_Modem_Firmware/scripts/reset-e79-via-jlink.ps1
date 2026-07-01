param(
    [int]$Speed = 4000
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$cmdFile = Join-Path $RepoRoot 'build\jlink-reset-go.jlink'

if (-not (Test-Path -LiteralPath $JLinkExe)) {
    throw "Missing J-Link executable: $JLinkExe"
}

New-Item -ItemType Directory -Force -Path (Split-Path $cmdFile) | Out-Null
@"
jtagconf -1 -1
connect
r
g
q
"@ | Set-Content -LiteralPath $cmdFile -Encoding ASCII

& $JLinkExe -device CC1352P1F3 -if cJTAG -speed $Speed -jtagconf -1,-1 -autoconnect 1 -CommanderScript $cmdFile
exit $LASTEXITCODE
