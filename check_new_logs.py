#!/usr/bin/env python3
"""检查Bot重启后的日志"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 Bot重启后日志检查")
print("=" * 60)

# 查看日志大小
stdin, stdout, stderr = ssh.exec_command("ls -la /root/mory/mory.log", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"\n日志文件: {out}")

# 查看最新日志
stdin, stdout, stderr = ssh.exec_command("tail -50 /root/mory/mory.log", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"\n最新50行日志:\n{out}")

# 检查是否有新的409错误
print("\n")
stdin, stdout, stderr = ssh.exec_command("tail -500 /root/mory/mory.log | grep -c '409' || echo '0'", timeout=10)
new_409 = stdout.read().decode('utf-8', errors='replace').strip()
print(f"最近500行中409错误数: {new_409}")

ssh.close()
