@echo off
rem Called by launchers. Exposes TRAJECTORY_PY_CMD to the calling shell.
set "TRAJECTORY_PY_CMD="
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "PYLAUNCHER_ALLOW_INSTALL="
if defined TRAJECTORY_PYTHON call :probe "%TRAJECTORY_PYTHON%"
if defined TRAJECTORY_PY_CMD exit /b 0
call :probe py -3.12
if defined TRAJECTORY_PY_CMD exit /b 0
call :probe py -3.13
if defined TRAJECTORY_PY_CMD exit /b 0
call :probe py -3.14
if defined TRAJECTORY_PY_CMD exit /b 0
if exist ".venv\Scripts\python.exe" call :probe ".venv\Scripts\python.exe"
if defined TRAJECTORY_PY_CMD exit /b 0
call :probe python
if defined TRAJECTORY_PY_CMD exit /b 0
call :probe py
if defined TRAJECTORY_PY_CMD exit /b 0
echo.
echo No supported 64-bit Python runtime was found.
echo Install Python 3.12 with: py install 3.12
echo Or use https://www.python.org/downloads/windows/
echo Installed runtimes: py --list-paths
echo See START_HERE_RU.md for Russian instructions.
exit /b 1
:probe
%* -c "import sys,struct;sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13),(3,14)) and struct.calcsize('P')==8 and sys.version_info.releaselevel=='final' else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "TRAJECTORY_PY_CMD=%*"
exit /b 0
