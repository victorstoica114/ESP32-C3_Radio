$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$hex = Join-Path $RepoRoot 'firmware\e79_at_modem\gcc\e79_at_modem.hex'
$cmdFile = Join-Path $RepoRoot 'build\jlink-e79-at-modem.jlink'

if (-not (Test-Path -LiteralPath $JLinkExe)) {
    throw "Missing J-Link executable: $JLinkExe"
}
if (-not (Test-Path -LiteralPath $hex)) {
    throw "Build e79_at_modem first. Missing HEX: $hex"
}

New-Item -ItemType Directory -Force -Path (Split-Path $cmdFile) | Out-Null
@"
jtagconf -1 -1
connect
r
h
loadfile $hex
r
g
q
"@ | Set-Content -LiteralPath $cmdFile -Encoding ASCII

& $JLinkExe -NoGui 1 -ExitOnError 1 -device CC1352P1F3 -if cJTAG -speed 4000 -jtagconf -1,-1 -autoconnect 1 -CommanderScript $cmdFile
if ($LASTEXITCODE -ne 0) {
    throw "J-Link flash failed with exit code $LASTEXITCODE"
}
