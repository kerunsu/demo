param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$BackupDir = ".runtime\backups",
  [string]$RuntimeDatabasePath = $(if ($env:DEMO_SQLITE_DB_PATH) { $env:DEMO_SQLITE_DB_PATH } else { ".runtime\demo.sqlite3" })
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$resolvedBackupDir = Join-Path $resolvedRoot $BackupDir
New-Item -ItemType Directory -Force -Path $resolvedBackupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archivePath = Join-Path $resolvedBackupDir "demo-runtime-$timestamp.zip"
$sources = @(
  (Join-Path $resolvedRoot "deploy"),
  (Join-Path $resolvedRoot "docs\PRODUCT_COMPLETION_PROGRESS.md"),
  (Join-Path $resolvedRoot "docs\AUTOMATION_PROGRESS_M6_M7.md"),
  (Join-Path $resolvedRoot $RuntimeDatabasePath),
  (Join-Path $resolvedRoot "$RuntimeDatabasePath-wal"),
  (Join-Path $resolvedRoot "$RuntimeDatabasePath-shm")
) | Where-Object { Test-Path $_ }

if ($sources.Count -eq 0) {
  throw "No runtime sources found to back up."
}

Compress-Archive -Path $sources -DestinationPath $archivePath -Force
Write-Output "Backup created: $archivePath"
