@echo off
chcp 65001 >nul 2>&1
title Mory小助理 - 一键部署到VPS
echo.
echo  ══════════════════════════════════════
echo   Mory小助理  一键部署到VPS
echo  ══════════════════════════════════════
echo.
C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe "%~dp0deploy_final.py"
echo.
pause
