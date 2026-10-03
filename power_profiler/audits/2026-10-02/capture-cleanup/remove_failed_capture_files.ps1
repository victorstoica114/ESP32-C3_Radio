$ErrorActionPreference = 'Stop'
$workspacePath = (Resolve-Path -LiteralPath 'D:\Documente\ESP32-C3_Radio').Path.TrimEnd('\')
$auditPath = Join-Path $workspacePath 'power_profiler\audits\2026-10-02\capture-cleanup'
$manifestPath = Join-Path $auditPath 'deletion_manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.workspace_root -ne $workspacePath) { throw 'Wrong workspace in deletion manifest' }
$permittedPrefixes = @('power_profiler', 'module radio', '.tmp') | ForEach-Object { (Join-Path $workspacePath $_) + '\' }
$protectedPaths = @{}
foreach ($entry in $manifest.protected_files) {
    $absolute = [IO.Path]::GetFullPath((Join-Path $workspacePath $entry.path))
    $protectedPaths[$absolute.ToLowerInvariant()] = $true
}
$resolvedTargets = @()
foreach ($entry in $manifest.delete_files) {
    $absolute = (Resolve-Path -LiteralPath $entry.path -ErrorAction Stop).Path
    if (-not ($permittedPrefixes | Where-Object { $absolute.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) { throw "Outside measurement roots: $absolute" }
    if ($absolute -match '\\(\.git|\.venv|node_modules)\\') { throw "Protected program path: $absolute" }
    if ($protectedPaths.ContainsKey($absolute.ToLowerInvariant())) { throw "Protected capture: $absolute" }
    $item = Get-Item -LiteralPath $absolute -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Not a plain capture file: $absolute" }
    $duplicateZipPath = Join-Path $workspacePath '.tmp\e79-ch340-release\e79_ch340_tx_recapture_20260929_full_session.zip'
    $verifiedDuplicateZip = ($absolute -eq $duplicateZipPath -and $entry.status -eq 'verified_redundant_archive' -and $entry.sha256 -eq 'fe09b18b6332ba34362133ab4ca97297633f2f786a21d0af6377544787e6068a')
    if (-not ($absolute.EndsWith('.csv.gz') -or $absolute.EndsWith('.ppk2.bin') -or $verifiedDuplicateZip)) { throw "Unexpected extension: $absolute" }
    if ($item.Length -ne $entry.bytes) { throw "Size changed: $absolute" }
    $resolvedTargets += [PSCustomObject]@{ Path = $absolute; Entry = $entry }
}
$journalPath = Join-Path $auditPath 'deleted_files.jsonl'
if (Test-Path -LiteralPath $journalPath) { throw 'Deletion journal already exists; inspect before resuming' }
$journal = [IO.StreamWriter]::new($journalPath, $false, [Text.UTF8Encoding]::new($false))
$deletedCount = 0
[long]$deletedBytes = 0
$failure = $null
try {
    foreach ($target in $resolvedTargets) {
        $actualHash = (Get-FileHash -LiteralPath $target.Path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $target.Entry.sha256) { throw "Capture changed after inventory: $($target.Path)" }
        Remove-Item -LiteralPath $target.Path -ErrorAction Stop
        if (Test-Path -LiteralPath $target.Path) { throw "File still present: $($target.Path)" }
        $deletedCount++
        $deletedBytes += $target.Entry.bytes
        $journal.WriteLine(([PSCustomObject]@{ path=$target.Entry.relative_path; bytes=$target.Entry.bytes; sha256=$actualHash; deleted_utc=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress))
        $journal.Flush()
        if (($deletedCount % 100) -eq 0) { Write-Output "Deleted $deletedCount / $($resolvedTargets.Count) verified failed capture files" }
    }
} catch {
    $failure = $_.Exception.Message
} finally {
    $journal.Dispose()
}
$execution = [PSCustomObject]@{ completed=($null -eq $failure); deleted_file_count=$deletedCount; deleted_bytes=$deletedBytes; failure=$failure; completed_utc=[DateTime]::UtcNow.ToString('o') }
$execution | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $auditPath 'execution.json') -Encoding UTF8
$execution | ConvertTo-Json -Compress
if ($failure) { throw $failure }
