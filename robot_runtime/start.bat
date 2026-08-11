@echo off
REM Robot Runtime — 一键启动（机器人端）
cd /d "%~dp0\.."

set "DOLLSER=%~dp0..\doll\DollSer\bin\DollSer.exe"
if exist "%DOLLSER%" (
  tasklist /FI "IMAGENAME eq DollSer.exe" 2>NUL | find /I "DollSer.exe" >NUL
  if errorlevel 1 (
    echo [RobotRuntime] starting DollSer...
    start "" "%DOLLSER%"
    timeout /t 2 /nobreak >NUL
  ) else (
    echo [RobotRuntime] DollSer already running
  )
) else (
  echo [RobotRuntime] DollSer.exe not found at %DOLLSER% — skip
)

if "%ROBOT_RUNTIME_BACKEND_URL%"=="" (
  echo [RobotRuntime] 后端地址可在打开的 /ui 页面填写并「应用并注册」
  echo [RobotRuntime] 也可事先: set ROBOT_RUNTIME_BACKEND_URL=http://^<backend-ip^>:8080
)

echo [RobotRuntime] starting on port 19091 ...
start "" cmd /c "timeout /t 2 /nobreak >NUL && start http://127.0.0.1:19091/ui && if not "%ROBOT_RUNTIME_BACKEND_URL%"=="" start %ROBOT_RUNTIME_BACKEND_URL%/robot/emotion"
python -m robot_runtime.agent
pause
