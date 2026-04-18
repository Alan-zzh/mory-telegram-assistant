#!/usr/bin/env python3
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 直接执行命令检查表
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"reply_tracking 记录数: {out}")

# 检查最近的消息
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT * FROM reply_tracking LIMIT 5"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"\n最近记录:\n{out}")

ssh.close()
