@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Mory Dashboard
echo ========================================
echo.
python start_dashboard.py
pause
