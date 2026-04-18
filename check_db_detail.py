#!/usr/bin/env python3
"""详细检查数据库和配置"""
import paramiko, sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📊 数据库详细检查")
print("=" * 60)

# 1. 查看所有表
print("\n📋 数据库表列表:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db ".tables"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 2. 查看reply_tracking表结构
print("\n📋 reply_tracking表结构:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db ".schema reply_tracking"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 3. 查看messages表结构
print("\n📋 messages表结构:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db ".schema messages" 2>/dev/null || echo "messages表不存在"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 4. 查看配置中的群组ID
print("\n👥 配置的群组ID:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && cat config.json | grep -E "group|GROUP|chat|CHAT"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 5. 查看所有追踪记录（如果有的话）
print("\n📜 reply_tracking所有记录:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT rowid, * FROM reply_tracking"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
else:
    print("  (空表)")

# 6. 查看auto_tasks中的群组配置
print("\n👥 auto_tasks.py中的群组配置:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && grep -E "CHAT_ID|chat_id.*group|GROUP" modules/auto_tasks.py | head -10', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

ssh.close()
print("\n" + "=" * 60)
