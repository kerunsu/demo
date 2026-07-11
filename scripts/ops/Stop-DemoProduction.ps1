param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$LogDir = ".runtime\logs"
)

$ErrorActionPreference = "Stop"
$resolvedLogDir = Join-Path (Resolve-Path $ProjectRoot).Path $LogDir
$pidFiles = @("frontend.pid", "backend.pid", "voice-service.pid")
$foundPid = $false

foreach ($pidName in $pidFiles) {
  $pidFile = Join-Path $resolvedLogDir $pidName
  if (!(Test-Path $pidFile)) {
    continue
  }
  $foundPid = $true
  $processName = $pidName -replace "\.pid$", ""
  $processId = [int](Get-Content -Raw $pidFile)
  $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
  if ($process) {
    Stop-Process -Id $processId -ErrorAction Stop
    Write-Output "$processName stopped. pid=$processId"
  } else {
    Write-Output "$processName process was not running. pid=$processId"
  }
  Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
}

if (!$foundPid) {
  Write-Output "No demo pid files found."
  exit 0
}
