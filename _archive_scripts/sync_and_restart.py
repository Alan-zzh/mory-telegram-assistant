#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步代码到 VPS 并重启机器人"""

import paramiko
import sys
import os
import io
import codecs

# 解决 Windows GBK 控制台编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 读取密码
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
vps_pass = None

if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("VPS_SSH_PASS="):
                vps_pass = line.split("=", 1)[1].strip()
                break

if not vps_pass:
    print("ERROR: VPS_SSH_PASS not found in .env")
    sys.exit(1)

print("Connecting to 43.159.168.175...")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(
    "43.159.168.175",
    port=22,
    username="root",
    password=vps_pass,
    timeout=15
)

try:
    # 1. Git pull
    print("\n1. Pulling latest code from GitHub...")
    stdin, stdout, stderr = client.exec_command("cd /root/mory && git pull", timeout=30)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    if err.strip():
        print("STDERR:", err)

    # 2. Restart bot
    print("\n2. Restarting Mory bot...")
    stdin, stdout, stderr = client.exec_command("bash /root/mory/start.sh restart", timeout=30)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    if err.strip():
        print("STDERR:", err)

    # 3. Check status
    print("\n3. Bot status...")
    stdin, stdout, stderr = client.exec_command("bash /root/mory/start.sh status", timeout=15)
    print(stdout.read().decode("utf-8", errors="replace"))

    # 4. Recent logs
    print("\n4. Recent logs (last 3 lines)...")
    stdin, stdout, stderr = client.exec_command("tail -3 /root/mory/mory.log", timeout=10)
    print(stdout.read().decode("utf-8", errors="replace"))

    print("\n" + "="*50)
    print("✅ VPS sync and restart completed!")
    print("="*50)

finally:
    client.close()
