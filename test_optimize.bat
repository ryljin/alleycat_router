@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0test_optimize.ps1"
pause