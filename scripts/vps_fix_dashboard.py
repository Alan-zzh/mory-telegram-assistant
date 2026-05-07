#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复Dashboard端口冲突问题"""

import paramiko
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)

    # 检查占用8080端口的进程
    print("=== 检查8080端口占用 ===")
    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || netstat -tlnp | grep 8080 || echo '未找到占用'")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 检查旧Dashboard进程
    print("=== 检查旧Dashboard进程 ===")
    stdin, stdout, stderr = client.exec_command("ps -ef | grep dashboard/app.py | grep -v grep")
    out = stdout.read().decode('utf-8', errors='replace')
    print(out)

    # 修复步骤
    fix_cmds = [
        'echo "=== 停止Dashboard服务 ===" && sudo systemctl stop mory-dashboard',
        'echo "=== 强制终止所有旧Dashboard进程 ===" && sudo pkill -f "dashboard/app.py" || true',
        'echo "=== 等待端口释放 ===" && sleep 2',
        'echo "=== 检查端口是否释放 ===" && ss -tlnp | grep 8080 || echo "端口已释放"',
        'echo "=== 重新启动Dashboard ===" && sudo systemctl start mory-dashboard',
        'echo "=== 等待启动 ===" && sleep 3',
        'echo "=== 检查新状态 ===" && systemctl status mory-dashboard --no-pager -l',
    ]

    for cmd in fix_cmds:
        print(f"\n>>> {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        if out:
            print(out[:2000])
        if err:
            print(f"ERR: {err[:500]}")

    client.close()
    print("\n=== Dashboard修复完成 ===")

if __name__ == "__main__":
    main()
