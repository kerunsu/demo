$ErrorActionPreference = "Stop"

$PackageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PackageDir
$LogDir = Join-Path $PackageDir "logs"
$LogPath = Join-Path $LogDir "startup.log"
$RuntimeExe = Join-Path $PackageDir "RobotRuntime.exe"
$DollSerExe = Join-Path $PackageDir "DollSer\bin\DollSer.exe"
$ConfigPath = Join-Path $PackageDir "runtime-config.json"
$VersionPath = Join-Path $PackageDir "VERSION"
$RuntimeUrl = "http://127.0.0.1:19091"
$DollSerPort = 12000
$Mutex = $null
$HasMutex = $false

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Write-StartupLog([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Get-RuntimeState([string]$Path = "/health") {
    try {
        return Invoke-RestMethod -Uri ($RuntimeUrl + $Path) -TimeoutSec 2
    } catch {
        return $null
    }
}

function Open-RuntimeInterfaces {
    Start-Process ($RuntimeUrl + "/ui")
    try {
        $WarmState = Get-RuntimeState "/assets/emotions/prewarm/status"
        if (-not $WarmState -or $WarmState.stale -or -not $WarmState.ready) {
            $OpenEmotionResult = Invoke-RestMethod -Method Post `
                -Uri ($RuntimeUrl + "/ui/open-emotion") `
                -ContentType "application/json" `
                -Body "{}" `
                -TimeoutSec 10
            if (-not $OpenEmotionResult.ok) {
                throw ($OpenEmotionResult.error | Out-String)
            }
            Write-StartupLog ("Expression page launch requested. url={0}" -f $OpenEmotionResult.url)
        } else {
            Write-StartupLog "Expression page is already active and prepared."
        }
    } catch {
        Write-StartupLog ("WARNING: Expression page was not opened automatically: " + $_.Exception.Message)
    }
    try {
        $OpenChildResult = Invoke-RestMethod -Method Post `
            -Uri ($RuntimeUrl + "/ui/open-child") `
            -ContentType "application/json" `
            -Body "{}" `
            -TimeoutSec 10
        if (-not $OpenChildResult.ok) {
            throw ($OpenChildResult.error | Out-String)
        }
        Write-StartupLog ("Child page launch requested. mode={0} url={1}" -f $OpenChildResult.mode, $OpenChildResult.url)
    } catch {
        Write-StartupLog ("WARNING: Child page was not opened automatically: " + $_.Exception.Message)
    }
}

function Stop-PreviousPackagedRuntime {
    $Listener = Get-NetTCPConnection -LocalPort 19091 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $Listener) {
        throw "The old Runtime answered /health but its listening process could not be resolved."
    }
    $OldProcess = Get-Process -Id $Listener.OwningProcess -ErrorAction SilentlyContinue
    if (-not $OldProcess -or $OldProcess.ProcessName -ne "RobotRuntime") {
        throw ("Refusing to stop PID {0}: it is not RobotRuntime." -f $Listener.OwningProcess)
    }
    Write-StartupLog ("Stopping superseded RobotRuntime PID={0} version={1}" -f $OldProcess.Id, $Existing.runtimeVersion)
    Stop-Process -Id $OldProcess.Id -Force
    $StopDeadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 200
        $StillListening = Get-NetTCPConnection -LocalPort 19091 -State Listen -ErrorAction SilentlyContinue
    } until ((-not $StillListening) -or (Get-Date) -ge $StopDeadline)
    if ($StillListening) {
        throw "The superseded RobotRuntime did not release port 19091."
    }

    # DollSer loads Settings.xml only during process startup. Restart the exact
    # named process so the current package's COM/OSC configuration takes effect.
    Get-Process -Name "DollSer" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-StartupLog ("Stopping superseded DollSer PID={0}" -f $_.Id)
        Stop-Process -Id $_.Id -Force -PassThru | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
    }
}

try {
    $Mutex = New-Object System.Threading.Mutex($false, "Local\EIArtRobotRuntimeLauncher")
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        Write-StartupLog "Another launcher is already preparing Robot Runtime; exiting."
        exit 0
    }

    $Existing = Get-RuntimeState
    if ($Existing -and $Existing.service -eq "robot_runtime") {
        $ExpectedVersion = if (Test-Path -LiteralPath $VersionPath -PathType Leaf) {
            (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8).Trim()
        } else {
            ""
        }
        if ($Existing.protocolCompatible -eq $true -and $ExpectedVersion -and $Existing.runtimeVersion -eq $ExpectedVersion) {
            Write-StartupLog ("Compatible Runtime process already listens on 19091; opening UI and child page. version={0}" -f $Existing.runtimeVersion)
            Open-RuntimeInterfaces
            exit 0
        }
        Write-StartupLog ("A different Runtime build is active; current package will take over. active={0} package={1}" -f $Existing.runtimeVersion, $ExpectedVersion)
        Stop-PreviousPackagedRuntime
        $Existing = $null
    }
    if ($Existing) {
        throw "Port 19091 is occupied by another HTTP service. Stop it before launching Robot Runtime."
    }
    $Listener = Get-NetTCPConnection -LocalPort 19091 -State Listen -ErrorAction SilentlyContinue
    if ($Listener) {
        throw "Port 19091 is occupied by PID $($Listener[0].OwningProcess), but /health is not a Robot Runtime."
    }
    if (-not (Test-Path -LiteralPath $RuntimeExe -PathType Leaf)) {
        throw "RobotRuntime.exe is missing. Re-download the complete release package."
    }

    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $env:ROBOT_RUNTIME_BACKEND_URL -and $Config.backendUrl) {
            $env:ROBOT_RUNTIME_BACKEND_URL = [string]$Config.backendUrl
        }
        if (-not $env:ROBOT_RUNTIME_KEY -and $Config.runtimeKey) {
            $env:ROBOT_RUNTIME_KEY = [string]$Config.runtimeKey
        }
        if ($Config.dollSerOscPort) {
            $DollSerPort = [int]$Config.dollSerOscPort
            $env:DOLLSER_OSC_PORT = [string]$DollSerPort
        }
    }
    if (-not $env:ROBOT_RUNTIME_BACKEND_URL) {
        throw "Backend URL is not configured. Set ROBOT_RUNTIME_BACKEND_URL or add backendUrl to runtime-config.json."
    }

    if (Test-Path -LiteralPath $DollSerExe -PathType Leaf) {
        $DollSerProcess = Get-Process -Name "DollSer" -ErrorAction SilentlyContinue
        $OscListener = Get-NetUDPEndpoint -LocalPort $DollSerPort -ErrorAction SilentlyContinue
        if (-not $DollSerProcess -or -not $OscListener) {
            if (-not $DollSerProcess) {
                Write-StartupLog "Starting DollSer."
                Start-Process -FilePath $DollSerExe -WorkingDirectory (Split-Path -Parent $DollSerExe)
            } else {
                Write-StartupLog "DollSer process exists but OSC UDP port is not listening yet."
            }
            $OscDeadline = (Get-Date).AddSeconds(10)
            do {
                Start-Sleep -Milliseconds 250
                $DollSerProcess = Get-Process -Name "DollSer" -ErrorAction SilentlyContinue
                $OscListener = Get-NetUDPEndpoint -LocalPort $DollSerPort -ErrorAction SilentlyContinue
            } until (($DollSerProcess -and $OscListener) -or (Get-Date) -ge $OscDeadline)
        }
        if ($DollSerProcess -and $OscListener) {
            Write-StartupLog "DollSer process and OSC UDP listener are ready on port $DollSerPort."
        } else {
            Write-StartupLog "WARNING: DollSer OSC readiness was not confirmed; motion playback may fail."
        }
    } else {
        Write-StartupLog "WARNING: DollSer.exe is missing; motion playback will be unavailable."
    }

    Write-StartupLog ("Starting Robot Runtime; backend={0}" -f $env:ROBOT_RUNTIME_BACKEND_URL)
    $RuntimeLog = Join-Path $LogDir "runtime.stdout.log"
    $RuntimeErrorLog = Join-Path $LogDir "runtime.stderr.log"
    $RuntimeProcess = Start-Process -FilePath $RuntimeExe -WorkingDirectory $PackageDir `
        -RedirectStandardOutput $RuntimeLog -RedirectStandardError $RuntimeErrorLog `
        -WindowStyle Hidden -PassThru

    $ReadyDeadline = (Get-Date).AddSeconds(30)
    $LastReady = $null
    do {
        Start-Sleep -Milliseconds 300
        if ($RuntimeProcess.HasExited) {
            throw "Robot Runtime exited during startup with code $($RuntimeProcess.ExitCode). See $RuntimeErrorLog"
        }
        $LastReady = Get-RuntimeState "/ready"
    } until (($LastReady -and $LastReady.ready) -or (Get-Date) -ge $ReadyDeadline)

    if (-not $LastReady -or -not $LastReady.ready) {
        $failureText = if ($LastReady.failures) { $LastReady.failures -join "," } else { "ready_timeout" }
        throw "Robot Runtime did not become ready: $failureText. See $RuntimeLog and $RuntimeErrorLog"
    }
    Write-StartupLog ("Robot Runtime ready. version={0} protocol={1}" -f $LastReady.runtimeVersion, $LastReady.protocolVersion)
    Open-RuntimeInterfaces
    exit 0
} catch {
    Write-StartupLog ("ERROR: " + $_.Exception.Message)
    exit 1
} finally {
    if ($HasMutex -and $Mutex) {
        $Mutex.ReleaseMutex() | Out-Null
    }
    if ($Mutex) {
        $Mutex.Dispose()
    }
}
