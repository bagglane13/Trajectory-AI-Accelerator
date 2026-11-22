@echo off
setlocal DisableDelayedExpansion
call "%~dp0..\START.bat" %*
exit /b %errorlevel%
