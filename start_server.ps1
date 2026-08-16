[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipPip,
    [switch]$SkipNpm,
    [switch]$NoPauseOnReuse
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

# Windows GBK locale + old pip mis-reads UTF-8 requirements.txt; force UTF-8 mode.
$env:PYTHONUTF8 = '1'
# 由本脚本调起的 app.py 若命中单实例锁，不需要等待按键（脚本自会提示）
$env:SERVER_NO_WAIT = '1'

try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/server/status' -TimeoutSec 3
    if ($status.success) {
        Write-Host '[start] Backend is already healthy on port 8080; reusing it.'
        Write-Host '[start] Teacher UI: http://127.0.0.1:8080/teacher/'
        if (-not $NoPauseOnReuse) {
            Write-Host '[start] 服务正在运行中，无需重复启动。'
            Read-Host '[start] 如需重启请双击 restart_server.bat；按回车键关闭此窗口'
        }
        exit 0
    }
} catch {
    # No healthy project server is listening; continue with bootstrap.
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $python = $pythonCommand.Source
}

$bootstrapArgs = @('scripts\bootstrap.py')
if ($CheckOnly) { $bootstrapArgs += '--check-only' }
if ($SkipPip) { $bootstrapArgs += '--skip-pip' }
if ($SkipNpm) { $bootstrapArgs += '--skip-npm' }

Write-Host '[start] Checking server and teacher UI dependencies...'
& $python @bootstrapArgs
if ($LASTEXITCODE -ne 0) {
    throw "Environment bootstrap failed with exit code: $LASTEXITCODE"
}
if ($CheckOnly) {
    Write-Host '[start] Environment check completed; server was not started.'
    exit 0
}

Write-Host '[start] Starting the single backend instance...'
& $python 'app.py'
exit $LASTEXITCODE
