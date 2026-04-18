@echo off
chcp 65001 >nul 2>&1
title Mory小助理 - 手动备份VPS数据
echo.
echo  ════════════════════════════════════════
echo   Mory小助理  VPS数据手动备份工具
echo  ════════════════════════════════════════
echo.
echo 功能：从VPS下载重要数据文件到本地备份
echo 包括：数据库、配置文件、运行日志等
echo.

set PYTHON=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe

echo 正在启动备份脚本...
%PYTHON% "%~dp0scripts\vps_backup.py"

echo.
pause