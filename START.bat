@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0START.ps1" goto missing
if not exist "%~dp0ai-accelerator\app\main.py" goto missing
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START.ps1"
if errorlevel 1 pause
exit /b %errorlevel%
:missing
echo Extract the WHOLE project ZIP before running START.bat.
pause
exit /b 1
