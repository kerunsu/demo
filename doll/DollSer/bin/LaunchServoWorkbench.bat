@echo off
setlocal

set "ROOT=%~dp0"
set "DOLL_DIR=%ROOT%..\doll"
set "URL=http://localhost:3000"
set "NODE_EXE=node"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

where node >nul 2>nul
if errorlevel 1 (
    if exist "%ProgramFiles%\nodejs\node.exe" (
        set "NODE_EXE=%ProgramFiles%\nodejs\node.exe"
    ) else (
        echo Node.js is not installed or not in PATH.
        echo Please install Node.js first, then run this launcher again.
        pause
        exit /b 1
    )
)

if not exist "%ROOT%data\Settings.xml" (
    echo ERROR: Required neutral configuration is missing:
    echo "%ROOT%data\Settings.xml"
    echo DollSer.exe will not be started without a verified neutral configuration.
    pause
    exit /b 1
)

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; [xml]$x=Get-Content -LiteralPath '%ROOT%data\Settings.xml'; $values=@($x.EIGui.Pitch,$x.EIGui.Yaw,$x.EIGui.ArmL,$x.EIGui.ArmR); foreach($v in $values){$n=0; if(-not [int]::TryParse([string]$v,[ref]$n) -or $n -lt 0 -or $n -gt 359){exit 1}}; exit 0" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Settings.xml contains an invalid neutral angle.
    echo DollSer.exe was not started. Check Pitch, Yaw, ArmL and ArmR first.
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq DollSer.exe" | find /I "DollSer.exe" >nul
if errorlevel 1 (
    if exist "%ROOT%DollSer.exe" (
        echo Starting DollSer.exe ...
        start "DollSer" /D "%ROOT%" "%ROOT%DollSer.exe"
        timeout /t 2 >nul
    ) else (
        echo Warning: "%ROOT%DollSer.exe" not found.
    )
)

echo Starting Servo Motion Workbench ...
start "Servo Workbench Server" /D "%DOLL_DIR%" cmd /k ""%NODE_EXE%" "server.js""

echo Waiting for web UI ...
for /L %%I in (1,1,20) do (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri '%URL%' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }" >nul 2>nul
    if not errorlevel 1 goto web_ready
    timeout /t 1 >nul
)

echo Warning: Web UI did not respond yet. Keep the server window open and refresh the browser.

:web_ready
start "" "%URL%"

echo Servo Motion Workbench launched at %URL%
exit /b 0
