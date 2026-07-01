$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$cmdFile = Join-Path $RepoRoot 'build\jlink-read-ccfg-bl-config.jlink'

if (-not (Test-Path -LiteralPath $JLinkExe)) {
    throw "Missing J-Link executable: $JLinkExe"
}

New-Item -ItemType Directory -Force -Path (Split-Path $cmdFile) | Out-Null
@"
jtagconf -1 -1
connect
h
mem32 0x50004FD8 1
g
q
"@ | Set-Content -LiteralPath $cmdFile -Encoding ASCII

& $JLinkExe -device CC1352P1F3 -if cJTAG -speed 4000 -jtagconf -1,-1 -autoconnect 1 -CommanderScript $cmdFile
if ($LASTEXITCODE -ne 0) {
    throw "J-Link CCFG BL_CONFIG read failed with exit code $LASTEXITCODE"
}
