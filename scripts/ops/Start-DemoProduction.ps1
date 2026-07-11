param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$BackendHost = "0.0.0.0",
  [int]$BackendPort = 3001,
  [string]$PublicBackendOrigin = "http://127.0.0.1:3001",
  [string]$CorsOrigin = "*",
  [string]$LogDir = ".runtime\logs",
  [switch]$RealLocalProviders,
  [switch]$StartVoiceService,
  [switch]$StartFrontend,
  [string]$VoiceServiceHost = "127.0.0.1",
  [int]$VoiceServicePort = 8765,
  [string]$VoiceServicePython = "",
  [string]$VoskModelPath = ".runtime\models\vosk\vosk-model-small-cn-0.22",
  [string]$PiperModelPath = ".runtime\models\piper\zh_CN-huayan-medium.onnx",
  [string]$PiperConfigPath = ".runtime\models\piper\zh_CN-huayan-medium.onnx.json",
  [string]$SqliteDbPath = ".runtime\demo.sqlite3",
  [string]$FrontendHost = "0.0.0.0",
  [int]$FrontendPort = 5173,
  [string]$FrontendApiBaseUrl = "",
  [string]$FrontendWsUrl = ""
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$resolvedLogDir = Join-Path $resolvedRoot $LogDir
New-Item -ItemType Directory -Force -Path $resolvedLogDir | Out-Null

$env:BACKEND_HOST = $BackendHost
$env:BACKEND_PORT = [string]$BackendPort
$env:PUBLIC_BACKEND_ORIGIN = $PublicBackendOrigin
$env:CORS_ORIGIN = $CorsOrigin
if ([string]::IsNullOrWhiteSpace($env:AI_CHAT_PROVIDER)) { $env:AI_CHAT_PROVIDER = "rule" }
if ([string]::IsNullOrWhiteSpace($env:AI_TTS_PROVIDER)) { $env:AI_TTS_PROVIDER = "none" }
if ([string]::IsNullOrWhiteSpace($env:VOICE_STT_PROVIDER)) { $env:VOICE_STT_PROVIDER = "mock" }
if ([string]::IsNullOrWhiteSpace($env:VOICE_TTS_PROVIDER)) { $env:VOICE_TTS_PROVIDER = "mock" }
if ([string]::IsNullOrWhiteSpace($env:ATTENTION_PROVIDER)) { $env:ATTENTION_PROVIDER = "mock" }
if ([string]::IsNullOrWhiteSpace($env:DEMO_STORAGE_PROVIDER)) { $env:DEMO_STORAGE_PROVIDER = "sqlite" }
if ([string]::IsNullOrWhiteSpace($env:DEMO_SQLITE_DB_PATH)) { $env:DEMO_SQLITE_DB_PATH = $SqliteDbPath }
if ([string]::IsNullOrWhiteSpace($env:VOICE_PYTHON_SERVICE_URL)) {
  $env:VOICE_PYTHON_SERVICE_URL = "http://${VoiceServiceHost}:${VoiceServicePort}"
}

if ($RealLocalProviders) {
  $env:VOICE_STT_PROVIDER = "local"
  $env:VOICE_TTS_PROVIDER = "local"
  $env:ATTENTION_PROVIDER = "local"
  $env:DEMO_STORAGE_PROVIDER = "sqlite"
  $env:VOICE_PYTHON_SERVICE_URL = "http://${VoiceServiceHost}:${VoiceServicePort}"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Resolve-ProjectPath([string]$PathValue) {
  if ([System.IO.Path]::IsPathRooted($PathValue)) { return $PathValue }
  return Join-Path $resolvedRoot $PathValue
}

function Resolve-CommandPath([string]$CommandName) {
  $command = Get-Command $CommandName -ErrorAction Stop
  return $command.Source
}

function Start-LoggedProcess([string]$Name, [string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory) {
  $stdout = Join-Path $resolvedLogDir "$Name-$timestamp.out.log"
  $stderr = Join-Path $resolvedLogDir "$Name-$timestamp.err.log"
  $pidFile = Join-Path $resolvedLogDir "$Name.pid"
  $process = Start-Process -FilePath $FilePath `
    -ArgumentList $ArgumentList `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru
  Set-Content -Path $pidFile -Value $process.Id -Encoding ascii
  Write-Output "$Name started. pid=$($process.Id) stdout=$stdout stderr=$stderr"
}

if ($StartVoiceService) {
  $resolvedVoskModel = Resolve-ProjectPath $VoskModelPath
  $resolvedPiperModel = Resolve-ProjectPath $PiperModelPath
  $resolvedPiperConfig = Resolve-ProjectPath $PiperConfigPath
  if (!(Test-Path -LiteralPath $resolvedVoskModel)) {
    throw "Vosk model path not found: $resolvedVoskModel"
  }
  if (!(Test-Path -LiteralPath $resolvedPiperModel)) {
    throw "Piper model path not found: $resolvedPiperModel"
  }
  if (!(Test-Path -LiteralPath $resolvedPiperConfig)) {
    throw "Piper config path not found: $resolvedPiperConfig"
  }

  $defaultPython = Join-Path $resolvedRoot "tools\voice-benchmark\.venv\Scripts\python.exe"
  if ([string]::IsNullOrWhiteSpace($VoiceServicePython)) {
    $VoiceServicePython = $(if (Test-Path -LiteralPath $defaultPython) { $defaultPython } else { "python" })
  }
  $env:VOICE_SERVICE_HOST = $VoiceServiceHost
  $env:VOICE_SERVICE_PORT = [string]$VoiceServicePort
  $env:VOICE_SERVICE_STT_PROVIDER = $(if ($RealLocalProviders) { "local-vosk" } else { "mock" })
  $env:VOICE_SERVICE_TTS_PROVIDER = $(if ($RealLocalProviders) { "local-piper" } else { "mock" })
  $env:VOICE_SERVICE_VOSK_MODEL = $resolvedVoskModel
  $env:VOICE_SERVICE_PIPER_MODEL = $resolvedPiperModel
  $env:VOICE_SERVICE_PIPER_CONFIG = $resolvedPiperConfig
  Start-LoggedProcess "voice-service" $VoiceServicePython @("tools\voice-service\voice_service.py") $resolvedRoot
}

Start-LoggedProcess "backend" (Resolve-CommandPath "node") @("dist/index.js") (Join-Path $resolvedRoot "backend")

if ($StartFrontend) {
  $npmCommand = Resolve-CommandPath "npm"
  if ([string]::IsNullOrWhiteSpace($FrontendApiBaseUrl)) {
    $FrontendApiBaseUrl = $PublicBackendOrigin.TrimEnd("/") + "/api"
  }
  if ([string]::IsNullOrWhiteSpace($FrontendWsUrl)) {
    $backendUri = [Uri]$PublicBackendOrigin
    $FrontendWsUrl = "ws://$($backendUri.Authority)/ws"
  }
  $env:VITE_API_BASE_URL = $FrontendApiBaseUrl
  $env:VITE_WS_URL = $FrontendWsUrl
  Start-LoggedProcess "frontend" $npmCommand @("--prefix", "frontend", "run", "preview", "--", "--host", $FrontendHost, "--port", [string]$FrontendPort) $resolvedRoot
}

Write-Output "Provider config: VOICE_STT_PROVIDER=$env:VOICE_STT_PROVIDER VOICE_TTS_PROVIDER=$env:VOICE_TTS_PROVIDER ATTENTION_PROVIDER=$env:ATTENTION_PROVIDER DEMO_STORAGE_PROVIDER=$env:DEMO_STORAGE_PROVIDER DEMO_SQLITE_DB_PATH=$env:DEMO_SQLITE_DB_PATH VOICE_PYTHON_SERVICE_URL=$env:VOICE_PYTHON_SERVICE_URL"
