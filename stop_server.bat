@echo off
rem 双击此文件停止后端服务（等价于 server.ps1 stop）
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0server.ps1" stop
echo.
pause
