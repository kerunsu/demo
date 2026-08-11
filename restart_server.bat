@echo off
rem 双击此文件重启后端服务（等价于 server.ps1 restart）
rem 重启完成后此窗口变为服务窗口，关闭即停止服务
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0server.ps1" restart
echo.
pause
