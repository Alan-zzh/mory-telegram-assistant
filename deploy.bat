@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
python deploy_vps.py
pause
