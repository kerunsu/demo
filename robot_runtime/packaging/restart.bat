@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0restart_robot_runtime.ps1" (
  echo [EIArt-Robot] restart_robot_runtime.ps1 not found.
  echo Re-download the complete package from the Server download page.
  pause
  exit /b 1
)

echo [EIArt-Robot] Restarting Robot Runtime and DollSer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_robot_runtime.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo [EIArt-Robot] Restart failed with code %RESULT%.
  echo See logs\restart.log for details.
  pause
  exit /b %RESULT%
)

echo.
echo [EIArt-Robot] Restart completed. Runtime UI has been opened.
pause
