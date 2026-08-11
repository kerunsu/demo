# server.ps1 - 后端服务控制：start / stop / restart / status
# 用法：./server.ps1 status | ./server.ps1 stop | ./server.ps1 restart | ./server.ps1 start
# 也可双击 stop_server.bat / restart_server.bat 使用同一逻辑。

param(
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
# PID 写在独立文件（锁文件本身被 msvcrt 字节锁持有，运行期间其他进程读不到）
$pidFile = Join-Path $projectRoot '.runtime\coordination\server_instance.lock.pid'
$port = 8080
$healthUrl = "http://127.0.0.1:$port/api/server/status"

function Test-ServerHealthy {
    try {
        $status = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        return [bool]$status.success
    } catch {
        return $false
    }
}

function Get-RecordedPid {
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    try {
        $raw = Get-Content -LiteralPath $pidFile -Raw -ErrorAction Stop
    } catch {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $digits = ($raw -replace '[^\d]', '')
    if ([string]::IsNullOrWhiteSpace($digits)) { return $null }
    return [int]$digits
}

function Test-ProcessIsServer([int]$ProcId) {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction Stop).CommandLine
        return [bool]($cmd -like '*app.py*')
    } catch {
        return $false
    }
}

function Get-PortPid {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    } catch { }
    return $null
}

# 定位运行中的后端进程：优先 PID 文件（校验命令行），回退到按 8080 端口查找
function Get-RunningServerPid {
    $recorded = Get-RecordedPid
    if ($recorded -and (Get-Process -Id $recorded -ErrorAction SilentlyContinue) -and (Test-ProcessIsServer $recorded)) {
        return $recorded
    }
    $portPid = Get-PortPid
    if ($portPid -and (Test-ProcessIsServer $portPid)) {
        return $portPid
    }
    return $null
}

function Wait-PortReleased([int]$MaxSeconds = 20) {
    for ($i = 0; $i -lt ($MaxSeconds * 2); $i++) {
        if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

switch ($Command) {
    'status' {
        $healthy = Test-ServerHealthy
        $pidNum = Get-RunningServerPid
        if ($healthy -and $pidNum) {
            Write-Host "[server] 运行中（PID $pidNum）" -ForegroundColor Green
            Write-Host "[server] 控制台：http://127.0.0.1:$port/server/"
            Write-Host "[server] 教师端：http://127.0.0.1:$port/teacher/"
            Write-Host "[server] 停止：./server.ps1 stop（或双击 stop_server.bat）"
        }
        elseif ($healthy) {
            Write-Host "[server] 运行中（端口 $port 健康，进程 PID 未知）" -ForegroundColor Green
            Write-Host "[server] 停止：./server.ps1 stop"
        }
        else {
            Write-Host '[server] 未运行' -ForegroundColor Yellow
            Write-Host '[server] 启动：./server.ps1 start（或双击 start_server.ps1）'
        }
    }
    'stop' {
        $pidNum = Get-RunningServerPid
        if (-not $pidNum) {
            Write-Host '[server] 没有正在运行的后端进程，无需停止。' -ForegroundColor Yellow
            exit 0
        }
        Write-Host "[server] 停止 PID $pidNum ..."
        Stop-Process -Id $pidNum -Force
        if (Wait-PortReleased) {
            Write-Host "[server] 已停止（端口 $port 已释放）。" -ForegroundColor Green
        } else {
            Write-Host "[server] 进程已终止，但端口 $port 仍被占用，请稍后重试或检查其他进程。" -ForegroundColor Red
            exit 1
        }
    }
    'restart' {
        $pidNum = Get-RunningServerPid
        if ($pidNum) {
            Write-Host "[server] 停止旧实例（PID $pidNum）..."
            Stop-Process -Id $pidNum -Force
            if (-not (Wait-PortReleased)) {
                Write-Host "[server] 端口 $port 未能释放，中止重启。" -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host '[server] 当前没有运行中的实例，直接启动。'
        }
        & (Join-Path $projectRoot 'start_server.ps1') -NoPauseOnReuse
        exit $LASTEXITCODE
    }
    'start' {
        & (Join-Path $projectRoot 'start_server.ps1') -NoPauseOnReuse
        exit $LASTEXITCODE
    }
}
