param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$BackendOrigin = "http://127.0.0.1:3001",
  [string]$FrontendOrigin = "",
  [string]$VoiceServiceOrigin = "http://127.0.0.1:8765",
  [string]$WebSocketUrl = "",
  [string]$SqliteDbPath = $(if ($env:DEMO_SQLITE_DB_PATH) { $env:DEMO_SQLITE_DB_PATH } else { ".runtime\demo.sqlite3" }),
  [string]$VoskModelPath = ".runtime\models\vosk\vosk-model-small-cn-0.22",
  [string]$PiperModelPath = ".runtime\models\piper\zh_CN-huayan-medium.onnx",
  [string]$PiperConfigPath = ".runtime\models\piper\zh_CN-huayan-medium.onnx.json",
  [string]$OutputDir = ".runtime\diagnostics"
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$resolvedOutputDir = Join-Path $resolvedRoot $OutputDir
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path $resolvedOutputDir "diagnostics-$timestamp.txt"

function Resolve-ProjectPath([string]$PathValue) {
  if ([System.IO.Path]::IsPathRooted($PathValue)) { return $PathValue }
  return Join-Path $resolvedRoot $PathValue
}

function Add-Check([System.Collections.Generic.List[string]]$Lines, [string]$Name, [string]$Status, [string]$Detail) {
  $Lines.Add(("check={0} status={1} detail={2}" -f $Name, $Status, ($Detail -replace "`r?`n", " ")))
}

function Test-HttpJson([string]$Url, [int]$TimeoutSec = 5) {
  try {
    $result = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
    return @{ ok = $true; detail = ($result | ConvertTo-Json -Depth 10 -Compress) }
  } catch {
    return @{ ok = $false; detail = $_.Exception.Message }
  }
}

function Test-HttpStatus([string]$Url, [int]$TimeoutSec = 5) {
  try {
    $result = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec
    return @{ ok = ($result.StatusCode -ge 200 -and $result.StatusCode -lt 400); detail = "statusCode=$($result.StatusCode)" }
  } catch {
    return @{ ok = $false; detail = $_.Exception.Message }
  }
}

function Test-WebSocketConnect([string]$Url) {
  if ([string]::IsNullOrWhiteSpace($Url)) {
    $backendUri = [Uri]$BackendOrigin
    $Url = "ws://$($backendUri.Authority)/ws?sessionId=diagnostics&screenRole=operator&clientId=diagnostics"
  }
  $client = [System.Net.WebSockets.ClientWebSocket]::new()
  try {
    $task = $client.ConnectAsync([Uri]$Url, [Threading.CancellationToken]::None)
    if (!$task.Wait(5000)) {
      return @{ ok = $false; detail = "timeout url=$Url" }
    }
    if ($client.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
      $client.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "diagnostics", [Threading.CancellationToken]::None).Wait(1000) | Out-Null
      return @{ ok = $true; detail = "connected url=$Url" }
    }
    return @{ ok = $false; detail = "state=$($client.State) url=$Url" }
  } catch {
    return @{ ok = $false; detail = "$($_.Exception.Message) url=$Url" }
  } finally {
    $client.Dispose()
  }
}

$lines = [System.Collections.Generic.List[string]]::new()
$headerLines = @(
  "timestamp=$(Get-Date -Format o)",
  "projectRoot=$resolvedRoot",
  "backendOrigin=$BackendOrigin",
  "frontendOrigin=$FrontendOrigin",
  "voiceServiceOrigin=$VoiceServiceOrigin",
  "webSocketUrl=$WebSocketUrl",
  "nodeVersion=$(node --version)",
  "npmVersion=$(npm --version)",
  "gitHead=$(git -C $resolvedRoot rev-parse --short HEAD)",
  "gitStatus=$(git -C $resolvedRoot status --short | Out-String)"
)
foreach ($line in $headerLines) {
  $lines.Add([string]$line)
}

$backendHealth = Test-HttpJson ($BackendOrigin.TrimEnd("/") + "/api/health")
Add-Check $lines "backend_health" $(if ($backendHealth.ok) { "PASS" } else { "FAIL" }) $backendHealth.detail

$voiceHealth = Test-HttpJson ($VoiceServiceOrigin.TrimEnd("/") + "/health")
Add-Check $lines "python_voice_service_health" $(if ($voiceHealth.ok) { "PASS" } else { "FAIL" }) $voiceHealth.detail

$sqlitePath = Resolve-ProjectPath $SqliteDbPath
$sqliteExists = Test-Path -LiteralPath $sqlitePath -PathType Leaf
Add-Check $lines "sqlite_database_file" $(if ($sqliteExists) { "PASS" } else { "FAIL" }) $sqlitePath

$voskPath = Resolve-ProjectPath $VoskModelPath
$piperModel = Resolve-ProjectPath $PiperModelPath
$piperConfig = Resolve-ProjectPath $PiperConfigPath
Add-Check $lines "vosk_model_path" $(if (Test-Path -LiteralPath $voskPath) { "PASS" } else { "FAIL" }) $voskPath
Add-Check $lines "piper_model_path" $(if (Test-Path -LiteralPath $piperModel -PathType Leaf) { "PASS" } else { "FAIL" }) $piperModel
Add-Check $lines "piper_config_path" $(if (Test-Path -LiteralPath $piperConfig -PathType Leaf) { "PASS" } else { "FAIL" }) $piperConfig

$ws = Test-WebSocketConnect $WebSocketUrl
Add-Check $lines "websocket_connect" $(if ($ws.ok) { "PASS" } else { "FAIL" }) $ws.detail

if (![string]::IsNullOrWhiteSpace($FrontendOrigin)) {
  $frontend = Test-HttpStatus $FrontendOrigin
  Add-Check $lines "frontend_accessibility" $(if ($frontend.ok) { "PASS" } else { "FAIL" }) $frontend.detail
  $child = Test-HttpStatus ($FrontendOrigin.TrimEnd("/") + "/child")
  Add-Check $lines "frontend_child_route" $(if ($child.ok) { "PASS" } else { "FAIL" }) $child.detail
  $robot = Test-HttpStatus ($FrontendOrigin.TrimEnd("/") + "/robot")
  Add-Check $lines "frontend_robot_route" $(if ($robot.ok) { "PASS" } else { "FAIL" }) $robot.detail
} else {
  Add-Check $lines "frontend_accessibility" "SKIPPED" "FrontendOrigin not provided."
}

Add-Check $lines "microphone_permission_prompt" "MANUAL_ACCEPTANCE_REQUIRED" "Open /child in the target browser, start voice capture, and record permission prompt, selected device, noise, transcript, and degradation outcome."
Add-Check $lines "camera_permission_prompt" "MANUAL_ACCEPTANCE_REQUIRED" "Open /child in the target browser, allow or deny camera, and record permission prompt, lighting, face-count quality, and degradation outcome."

$lines | Set-Content -Path $outputPath -Encoding utf8

Write-Output "Diagnostics written: $outputPath"
