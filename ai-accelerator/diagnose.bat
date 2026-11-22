@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo === Python installations ===
py --list-paths 2>nul
where python 2>nul
echo === Project check ===
call scripts\find-python.bat
if errorlevel 1 goto done
%TRAJECTORY_PY_CMD% scripts\bootstrap.py --check
:done
pause
