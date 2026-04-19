#!/usr/bin/env python3
"""最终验证 v21.44 修复"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 50)
print("v21.44 最终验证")
print("=" * 50)

# 1. 检查代码是否更新
print("\n📝 代码检查:")
checks = [
    ('auto_tasks.py - _send_and_track不追踪', 'grep -A3 "def _send_and_track" /root/mory/modules/auto_tasks.py | head -4'),
    ('main.py - 日志级别为INFO', 'grep "logger.info.*阅后即焚" /root/mory/main.py'),
    ('reply_tracking表状态', 'cd /root/mory && python3 -c "import sqlite3; c=sqlite3.connect(\"mory.db\").cursor(); r=c.execute(\"SELECT COUNT(*) FROM reply_tracking\").fetchone()[0]; print(f\"记录数: {r}\")"'),
]

for desc, cmd in checks:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    print(f"\n  【{desc}】")
    print(f"  {out}")
    if err:
        print(f"  ERR: {err}")

# 2. 检查Bot日志中的关键信息
print("\n\n📜 Bot日志检查 (最近20行):")
stdin, stdout, stderr = ssh.exec_command("tail -20 /root/mory/bot.log 2>/dev/null || echo '日志不存在'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 3. 检查是否有新的追踪调用
print("\n\n🔍 检查修复后是否有 user=0 错误:")
stdin, stdout, stderr = ssh.exec_command("grep -c 'user=0' /root/mory/bot.log 2>/dev/null || echo '0'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  user=0 错误数: {out}")

ssh.close()
print("\n" + "=" * 50)
