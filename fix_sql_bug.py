#!/usr/bin/env python3
"""部署SQL语法修复"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

LOCAL = os.path.dirname(os.path.abspath(__file__))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("🔧 部署 SQL 语法修复")
print("=" * 60)

# 1. 上传修复后的database.py
print("\n📤 上传 database.py...")
sftp = ssh.open_sftp()
sftp.put(os.path.join(LOCAL, "core", "database.py"), "/root/mory/core/database.py")
sftp.close()
print("  ✅ database.py 已上传")

# 2. 终止所有Bot进程
print("\n🛑 终止Bot进程...")
ssh.exec_command("pkill -9 -f 'main.py' 2>/dev/null || true")
import time
time.sleep(2)

# 3. 重新启动Bot
print("\n🚀 启动Bot...")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh start", timeout=30)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 4. 验证
print("\n📋 验证...")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh status", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

ssh.close()
print("\n" + "=" * 60)
print("✅ 部署完成！")
print("=" * 60)
