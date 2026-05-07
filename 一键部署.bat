@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Mory v4.5.8 Deploy To VPS
echo ========================================
echo.
echo [1/2] Checking local VPS config...
python check_vps_local.py
if errorlevel 1 (
    echo.
    echo [ERROR] VPS config check failed.
    pause
    exit /b 1
)

echo.
echo [2/2] Deploying...
python deploy_vps.py
if errorlevel 1 (
    echo.
    echo [ERROR] Deploy failed.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Deploy finished.
echo ========================================
pause
