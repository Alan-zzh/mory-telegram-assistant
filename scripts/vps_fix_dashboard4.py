#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终极修复Dashboard - 找到并终止真正占用端口的进程"""

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

    # 1. 找到占用8080的进程详细信息
    print("=== 1. 找到占用8080的进程 ===")
    stdin, stdout, stderr = client.exec_command("sudo lsof -i :8080 2>/dev/null || sudo ss -tlnp | grep 8080")
    out = stdout.read().decode('utf-8', errors='replace')
    print(out)

    # 2. 提取PID并强制终止
    print("=== 2. 强制终止占用进程 ===")
    stdin, stdout, stderr = client.exec_command("sudo fuser -k 8080/tcp 2>&1")
    print(stdout.read().decode('utf-8', errors='replace'))
    time.sleep(3)

    # 3. 再次确认端口释放
    print("=== 3. 确认端口释放 ===")
    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || echo '端口已释放'")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 4. 检查是否还有僵尸进程
    print("=== 4. 检查残留进程 ===")
    stdin, stdout, stderr = client.exec_command("ps -ef | grep dashboard | grep -v grep")
    out = stdout.read().decode('utf-8', errors='replace')
    print(out if out else "无残留进程")

    # 5. 启动Dashboard
    print("=== 5. 启动Dashboard ===")
    client.exec_command("sudo systemctl start mory-dashboard")
    time.sleep(4)

    # 6. 最终确认
    print("=== 6. 最终确认 ===")
    stdin, stdout, stderr = client.exec_command("systemctl status mory-dashboard --no-pager -l")
    print(stdout.read().decode('utf-8', errors='replace')[:1500])

    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || echo '未监听'")
    print("端口:", stdout.read().decode('utf-8', errors='replace'))

    client.close()
    print("\n=== 修复完成 ===")

if __name__ == "__main__":
    main()
