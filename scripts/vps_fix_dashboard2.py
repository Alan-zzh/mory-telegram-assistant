#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""强制修复Dashboard端口冲突"""

import paramiko
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)

    # 强制终止所有占用8080的进程
    print("=== 强制终止所有占用8080端口的进程 ===")
    client.exec_command("sudo fuser -k 8080/tcp 2>/dev/null || true")
    time.sleep(2)

    # 再次检查
    print("=== 检查端口状态 ===")
    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || echo '端口已释放'")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 检查所有python3进程
    print("=== 所有python3进程 ===")
    stdin, stdout, stderr = client.exec_command("ps -ef | grep python3 | grep -v grep")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 停止Dashboard服务
    print("=== 停止并禁用Dashboard自动重启 ===")
    client.exec_command("sudo systemctl stop mory-dashboard")
    time.sleep(1)

    # 手动启动Dashboard看错误
    print("=== 手动测试启动Dashboard ===")
    stdin, stdout, stderr = client.exec_command(
        "cd /home/ubuntu/mory_assistant && DASHBOARD_SECRET=test_secret_123456789 DASHBOARD_PASSWORD=test123 python3 start_dashboard.py 2>&1 &"
    )
    time.sleep(3)

    # 检查启动结果
    print("=== 检查Dashboard状态 ===")
    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || echo '未监听'")
    print(stdout.read().decode('utf-8', errors='replace'))

    client.close()
    print("\n=== 修复尝试完成 ===")

if __name__ == "__main__":
    main()
