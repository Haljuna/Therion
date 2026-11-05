@echo off
title Therion - teste Jarvis
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -File "%~dp0scripts\omnivoice_minimal\Start-TherionVoiceTest.ps1"
if errorlevel 1 pause
