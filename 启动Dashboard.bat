@echo off
chcp 65001 >nul 2>&1
title Mory Dashboard Pro v4.0
echo.
echo  ══════════════════════════════════════
echo   Mory Dashboard Pro - 启动中
echo  ══════════════════════════════════════
echo.
echo  🌐 访问地址: http://localhost:5000
echo  🔐 管理密码: mory2026
echo.
python "%~dp0dashboard\app.py"
pause
