@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
if errorlevel 1 pause
exit /b %errorlevel%
:missing
echo Run ..\START.bat once to prepare the environment and local model, then stop the web server.
pause
exit /b 1
