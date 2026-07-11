param(
  [string]$BackendOrigin = "http://127.0.0.1:3001",
  [int]$DurationMinutes = 30,
  [int]$IntervalSeconds = 30,
  [int]$MaxLogMegabytes = 100,
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$OutputDir = ".runtime\long-run"
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$resolvedOutputDir = Join-Path $resolvedRoot $OutputDir
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($DurationMinutes)
$resultPath = Join-Path $resolvedOutputDir ("long-run-{0}.jsonl" -f $startedAt.ToString("yyyyMMdd-HHmmss"))
$healthUrl = $BackendOrigin.TrimEnd("/") + "/api/health"
$logDir = Join-Path $resolvedRoot ".runtime\logs"

while ((Get-Date) -lt $deadline) {
  $sampleStarted = Get-Date
  $status = "PASS"
  $errorMessage = $null
  try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 10
    if ($health.success -ne $true) {
      throw "Health response success flag was not true."
    }
    if (Test-Path $logDir) {
      $logBytes = (Get-ChildItem -Path $logDir -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
      if ($logBytes -gt ($MaxLogMegabytes * 1MB)) {
        throw "Log directory exceeds ${MaxLogMegabytes}MB."
      }
    }
  } catch {
    $status = "FAIL"
    $errorMessage = $_.Exception.Message
  }

  [pscustomobject]@{
    timestamp = $sampleStarted.ToString("o")
    backendOrigin = $BackendOrigin
    status = $status
    error = $errorMessage
  } | ConvertTo-Json -Compress | Add-Content -Path $resultPath -Encoding utf8

  if ($status -ne "PASS") {
    throw "Long-run smoke failed. See $resultPath"
  }
  Start-Sleep -Seconds $IntervalSeconds
}

Write-Output "Long-run smoke completed: $resultPath"
