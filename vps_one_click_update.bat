@echo off
chcp 65001 >nul 2>&1
title Mory小助理 - 一键更新VPS
echo.
echo  ════════════════════════════════════════
echo   Mory小助理  一键更新到VPS (腾讯云硅谷)
echo  ════════════════════════════════════════
echo.
echo 使用参数:
echo   update   - 上传修改文件+热重启+同步数据库到本地
echo   full     - 完全部署(停止所有进程+全量上传)
echo   status   - 检查VPS状态
echo   sync     - 仅同步数据库到本地
echo.
if "%1"=="" (
  echo 使用方法: %~nx0 [update^|full^|status^|sync]
  pause
  exit /b 0
)

set PYTHON=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe

if "%1"=="update" (
  echo [更新模式] 上传修改文件+热重启+同步数据库...
  %PYTHON% "%~dp0vps_deploy.py"
) else if "%1"=="full" (
  echo [完全部署] 停止进程+全量上传+重启...
  %PYTHON% "%~dp0deploy_final.py"
) else if "%1"=="status" (
  echo [状态检查] 查看VPS运行状态...
  %PYTHON% "%~dp0vps_status_check.py"
) else if "%1"=="sync" (
  echo [数据库同步] 从VPS下载最新数据库到本地...
  %PYTHON% -c "import paramiko,os,sys,io; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace'); from core.vps_config import VPS_HOST,VPS_PORT,VPS_USER,VPS_PASS,VPS_PATH; ssh=paramiko.SSHClient(); ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy()); ssh.connect(VPS_HOST,port=VPS_PORT,username=VPS_USER,password=VPS_PASS,timeout=15); sftp=ssh.open_sftp(); sftp.get(VPS_PATH+'/mory.db','mory.db'); print('[OK] Database synced'); sftp.close(); ssh.close()"
) else (
  echo 未知参数: %1
  echo 使用方法: %~nx0 [update^|full^|status^|sync]
)

echo.
pause