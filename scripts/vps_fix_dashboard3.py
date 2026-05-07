#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终修复Dashboard - 清理所有残留并正确启动"""

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

    # 1. 停止systemd服务
    print("=== 1. 停止systemd服务 ===")
    client.exec_command("sudo systemctl stop mory-dashboard")
    time.sleep(2)

    # 2. 强制终止所有Dashboard相关进程
    print("=== 2. 强制终止Dashboard进程 ===")
    client.exec_command("sudo pkill -9 -f 'dashboard/app.py' || true")
    client.exec_command("sudo pkill -9 -f 'start_dashboard.py' || true")
    time.sleep(2)

    # 3. 检查端口
    print("=== 3. 检查端口状态 ===")
    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || echo '端口已释放'")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 4. 检查systemd服务文件
    print("=== 4. 检查systemd服务文件 ===")
    stdin, stdout, stderr = client.exec_command("cat /etc/systemd/system/mory-dashboard.service")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 5. 检查start_dashboard.py是否存在
    print("=== 5. 检查启动脚本 ===")
    stdin, stdout, stderr = client.exec_command("ls -la /home/ubuntu/mory_assistant/start_dashboard.py")
    print(stdout.read().decode('utf-8', errors='replace'))

    # 6. 手动前台启动看错误
    print("=== 6. 手动测试启动（看错误） ===")
    stdin, stdout, stderr = client.exec_command(
        "cd /home/ubuntu/mory_assistant && timeout 5 python3 start_dashboard.py 2>&1 || true"
    )
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    print("OUT:", out[:2000])
    print("ERR:", err[:1000])

    # 7. 重新启用并启动
    print("=== 7. 重新启动服务 ===")
    client.exec_command("sudo systemctl daemon-reload")
    time.sleep(1)
    client.exec_command("sudo systemctl start mory-dashboard")
    time.sleep(3)

    # 8. 最终检查
    print("=== 8. 最终状态检查 ===")
    stdin, stdout, stderr = client.exec_command("systemctl status mory-dashboard --no-pager -l")
    print(stdout.read().decode('utf-8', errors='replace')[:1500])

    stdin, stdout, stderr = client.exec_command("ss -tlnp | grep 8080 || echo '未监听'")
    print("端口状态:", stdout.read().decode('utf-8', errors='replace'))

    client.close()
    print("\n=== 修复完成 ===")

if __name__ == "__main__":
    main()
