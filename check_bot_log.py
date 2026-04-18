#!/usr/bin/env python3
"""检查Bot最新日志"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 Bot最新日志检查")
print("=" * 60)

# 1. Bot状态
print("\n🤖 Bot状态:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh status", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 2. 最新100行日志
print("\n📜 最新100行日志:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -100 mory.log 2>/dev/null", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "(无日志)")

# 3. 检查是否有任何消息处理
print("\n🔍 消息处理相关日志:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && grep -E '处理消息|收到|清群' mory.log 2>/dev/null | tail -20", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "(无相关日志)")

# 4. 检查reply_tracking表
print("\n📋 reply_tracking表:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  记录数: {out}")

ssh.close()
