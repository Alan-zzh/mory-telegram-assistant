#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步代码到 VPS 并重启机器人（v4.5.8 代理脚本）"""

# 【v4.5.8修复】代理脚本只启动 deploy_vps.py 子进程，避免 import 时误触发部署
# 保留此文件是为了兼容旧的调用习惯
import sys
import os
import subprocess
from pathlib import Path

DEPLOY_SCRIPT = Path(__file__).with_name("deploy_vps.py")

if DEPLOY_SCRIPT.exists():
    result = subprocess.run([sys.executable, str(DEPLOY_SCRIPT)])
    sys.exit(result.returncode)

print("⚠️ deploy_vps.py 不存在，使用旧版同步逻辑...")
try:
    # 降级到旧版逻辑（仅重启）
    from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH, ssh_connect
    import paramiko
    
    if not VPS_HOST or not VPS_PASS:
        print("❌ 错误：VPS_HOST 或 VPS_SSH_PASS 未设置！")
        sys.exit(1)
    
    print('Connecting...')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_connect(client, timeout=8)
    
    print('Restarting...')
    _, stdout, stderr = client.exec_command(f'bash {VPS_PATH}/start.sh restart', timeout=15)
    print(stdout.read().decode('utf-8', errors='replace'))
    
    client.close()
    print('OK!')
except Exception as e:
    print(f"❌ 同步失败：{e}")
    sys.exit(1)
