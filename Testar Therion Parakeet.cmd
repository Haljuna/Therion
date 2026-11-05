@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\voice_gateway\Start-TherionParakeet.ps1"
if errorlevel 1 pause
