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
print("📜 mory.log 最新内容")
print("=" * 60)

# 查看最近日志
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -100 mory.log", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

ssh.close()
