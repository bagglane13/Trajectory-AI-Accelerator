@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
call scripts\find-python.bat
if errorlevel 1 goto error
%TRAJECTORY_PY_CMD% scripts\connect_ai.py
if errorlevel 1 goto error
echo.
pause
exit /b 0
:error
echo.
echo Setup stopped. See FREE_AI_RU.md.
pause
exit /b 1
