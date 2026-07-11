[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string[]]$RelativePaths = @(".runtime\logs", ".runtime\backups", ".runtime\demo.sqlite3", ".runtime\demo.sqlite3-wal", ".runtime\demo.sqlite3-shm"),
  [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$cutoff = (Get-Date).AddDays(-1 * $RetentionDays).ToUniversalTime().ToString("o")
$sqliteScript = Join-Path $resolvedRoot "tools\sqlite-store\sqlite_store.py"
$dbPath = if ($env:DEMO_SQLITE_DB_PATH) { $env:DEMO_SQLITE_DB_PATH } else { ".runtime\demo.sqlite3" }
$resolvedDbPath = Join-Path $resolvedRoot $dbPath

if ((Test-Path $sqliteScript) -and (Test-Path $resolvedDbPath)) {
  if ($PSCmdlet.ShouldProcess($resolvedDbPath, "Delete sessions older than $RetentionDays days")) {
    python $sqliteScript --db $resolvedDbPath delete-before --before $cutoff | Write-Output
  }
}

foreach ($relative in $RelativePaths) {
  $target = Join-Path $resolvedRoot $relative
  if (!(Test-Path $target)) {
    continue
  }
  $resolvedTarget = (Resolve-Path $target).Path
  if (!$resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clear outside project root: $resolvedTarget"
  }
  if ($PSCmdlet.ShouldProcess($resolvedTarget, "Remove runtime data")) {
    Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    Write-Output "Cleared: $resolvedTarget"
  }
}
