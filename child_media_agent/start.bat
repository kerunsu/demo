@echo off
REM 兼容旧入口：转发到 robot_runtime
cd /d "%~dp0\.."
echo [DEPRECATED] use robot_runtime\start.bat
call robot_runtime\start.bat
