@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0start_robot_runtime.ps1" (
  echo [EIArt-Robot] start_robot_runtime.ps1 not found.
  echo Re-download the complete package from the Server download page.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_robot_runtime.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo [EIArt-Robot] Startup failed with code %RESULT%.
  echo See logs\startup.log for details.
  pause
)
exit /b %RESULT%
