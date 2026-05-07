@echo off
setlocal
cd /d "%~dp0"
python windows_helper.py %*
pause
