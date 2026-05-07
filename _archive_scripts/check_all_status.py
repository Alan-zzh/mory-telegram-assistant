# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""全面检查VPS状态"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📊 VPS 全面状态检查")
print("=" * 60)

# 1. Bot状态
print("\n🤖 Bot状态:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh status", timeout=10)
print(stdout.read().decode('utf-8', errors='replace').strip())

# 2. reply_tracking表
print("\n📋 reply_tracking表状态:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  记录数: {count}")

# 3. 查看所有追踪记录
print("\n📜 所有追踪记录:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT * FROM reply_tracking LIMIT 20"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "  (无记录)")

# 4. 最新日志中的阅后即焚相关
print("\n📜 最新50行日志中的阅后即焚记录:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -50 mory.log | grep -E '阅后即焚|_tracked_reply|track_reply'", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "  (无相关日志)")

# 5. 检查Bot是否正在接收消息
print("\n🔍 Bot消息处理日志:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -100 mory.log | grep -E '处理消息|收到消息|群消息' | tail -10", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "  (无消息处理日志)")

ssh.close()
