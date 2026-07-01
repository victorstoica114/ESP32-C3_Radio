$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$SdkRoot = Join-Path $RepoRoot 'sdk\simplelink-lowpower-f2-sdk'
$PropRfRoot = Join-Path $RepoRoot 'sdk\simplelink-prop_rf-examples'
$GccRoot = Join-Path $RepoRoot 'tools\gcc-arm-none-eabi-9-2019-q4-major'
$SysConfigTool = Join-Path $RepoRoot 'tools\sysconfig_1.21.1\sysconfig_cli.bat'
$JLinkExe = Join-Path $RepoRoot 'tools\SEGGER\JLink_V954\JLink.exe'

$RequiredPaths = @(
    $SdkRoot,
    $PropRfRoot,
    (Join-Path $GccRoot 'bin\arm-none-eabi-gcc.exe'),
    $SysConfigTool
)

foreach ($path in $RequiredPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing required path: $path"
    }
}

$env:SIMPLELINK_CC13XX_CC26XX_SDK_INSTALL_DIR = ($SdkRoot -replace '\\', '/')
$env:GCC_ARMCOMPILER = ($GccRoot -replace '\\', '/')
$env:SYSCONFIG_TOOL = ($SysConfigTool -replace '\\', '/')
$env:TICLANG_ARMCOMPILER = ''
$env:IAR_ARMCOMPILER = ''
$env:CMAKE = 'C:/Strawberry/c/bin/cmake.exe'
$env:PYTHON = 'python'
