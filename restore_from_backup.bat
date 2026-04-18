@echo off
chcp 65001 >nul 2>&1
title Mory小助理 - 从备份恢复VPS数据
echo.
echo  ════════════════════════════════════════
echo   Mory小助理  VPS数据恢复工具
echo  ════════════════════════════════════════
echo.
echo 警告：此操作将覆盖VPS上的现有数据！
echo 建议先使用 backup_vps_data.bat 创建当前备份
echo.

set PYTHON=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe

echo 正在启动恢复脚本...
%PYTHON% "%~dp0scripts\vps_restore.py"

echo.
pause