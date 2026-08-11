# restart_robot_runtime.ps1 - 一键重启机器人端（RobotRuntime + DollSer）
# 用法：双击 restart.bat，或 powershell -File restart_robot_runtime.ps1
# 行为：停止 19091 端口上的 RobotRuntime（校验进程名）和所有 DollSer 实例，
#       等待全部退出后再走 start_robot_runtime.ps1 完整启动流程。

$ErrorActionPreference = "Stop"

$PackageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PackageDir
$LogDir = Join-Path $PackageDir "logs"
$LogPath = Join-Path $LogDir "restart.log"
$StartScript = Join-Path $PackageDir "start_robot_runtime.ps1"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Write-RestartLog([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $StartScript -PathType Leaf)) {
    Write-RestartLog "ERROR: start_robot_runtime.ps1 not found in package."
    exit 1
}

# ---- 1. 停止 RobotRuntime（只碰 19091 上确认是 RobotRuntime 的进程） ----
$StoppedAnything = $false
$Listener = Get-NetTCPConnection -LocalPort 19091 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($Listener) {
    $Proc = Get-Process -Id $Listener.OwningProcess -ErrorAction SilentlyContinue
    if ($Proc -and $Proc.ProcessName -eq "RobotRuntime") {
        Write-RestartLog ("Stopping RobotRuntime PID={0}" -f $Proc.Id)
        Stop-Process -Id $Proc.Id -Force
        $StoppedAnything = $true
    } else {
        $ProcName = if ($Proc) { $Proc.ProcessName } else { "unknown" }
        Write-RestartLog ("WARNING: port 19091 is held by {0} (PID {1}); leaving it untouched." -f $ProcName, $Listener.OwningProcess)
    }
} else {
    Write-RestartLog "RobotRuntime is not listening on 19091; nothing to stop."
}

# ---- 2. 停止所有 DollSer 实例（多开会互相干扰，全部清掉） ----
$DollSerProcs = Get-Process -Name "DollSer" -ErrorAction SilentlyContinue
foreach ($P in $DollSerProcs) {
    Write-RestartLog ("Stopping DollSer PID={0}" -f $P.Id)
    Stop-Process -Id $P.Id -Force
    $StoppedAnything = $true
}
if (-not $DollSerProcs) {
    Write-RestartLog "No DollSer process found; nothing to stop."
}

# ---- 3. 等待全部退出（端口释放 + DollSer 进程消失，最多 15s） ----
$Deadline = (Get-Date).AddSeconds(15)
do {
    Start-Sleep -Milliseconds 250
    $StillListener = Get-NetTCPConnection -LocalPort 19091 -State Listen -ErrorAction SilentlyContinue
    $StillDollSer = Get-Process -Name "DollSer" -ErrorAction SilentlyContinue
} until ((-not $StillListener -and -not $StillDollSer) -or (Get-Date) -ge $Deadline)

if ($StillListener -or $StillDollSer) {
    Write-RestartLog "ERROR: old components did not exit within 15s; aborting restart. Stop them manually and try again."
    exit 1
}
if ($StoppedAnything) {
    Write-RestartLog "All old components stopped."
} else {
    Write-RestartLog "Nothing was running; starting fresh."
}

# ---- 4. 复用完整启动流程重新拉起 ----
Write-RestartLog "Starting RobotRuntime + DollSer via start_robot_runtime.ps1 ..."
& $StartScript
exit $LASTEXITCODE
