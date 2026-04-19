#!/usr/bin/env python3
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("✅ 验证修复效果")
print("=" * 60)

# 等待Bot处理一些消息
print("\n⏳ 等待Bot处理消息（约30秒）...")
import time
time.sleep(30)

# 检查最新日志
print("\n📜 最新日志 (无SQL错误检查):")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -50 mory.log", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
lines = out.split('\n')
has_error = False
for line in lines:
    if 'OperationalError' in line or 'syntax error' in line.lower():
        has_error = True
        print(f"  ❌ {line[:100]}")
    elif '处理消息' in line or '阅后即焚' in line or 'track_reply' in line:
        print(f"  ✅ {line[:100]}")

if not has_error:
    print("  ✅ 无SQL语法错误！")

# 检查reply_tracking表
print("\n📋 reply_tracking表:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  记录数: {count}")

ssh.close()
