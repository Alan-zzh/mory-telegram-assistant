#!/usr/bin/env python3
"""修复Bot冲突问题"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("🔧 修复Bot 409 Conflict冲突")
print("=" * 60)

# 1. 查看所有Bot相关进程
print("\n📋 当前Bot相关进程:")
stdin, stdout, stderr = ssh.exec_command("ps aux | grep -E 'main.py|python.*mory' | grep -v grep", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "  无Bot进程")

# 2. 获取PID文件中的进程
stdin, stdout, stderr = ssh.exec_command("cat /root/mory/.mory.pid 2>/dev/null || echo '无PID文件'", timeout=10)
pid_file = stdout.read().decode('utf-8', errors='replace').strip()
print(f"\nPID文件内容: {pid_file}")

# 3. 强制终止所有Bot进程
print("\n🛑 强制终止所有Bot进程...")
ssh.exec_command("pkill -9 -f 'main.py' 2>/dev/null || true")
stdin, stdout, stderr = ssh.exec_command("sleep 2 && ps aux | grep -E 'main.py|python.*mory' | grep -v grep", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  终止后进程: {out if out else '无Bot进程'}")

# 4. 重新启动Bot
print("\n🚀 重新启动Bot...")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh start", timeout=30)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 5. 检查Bot状态
print("\n📋 Bot状态:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh status", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 6. 检查是否有新的409错误
print("\n🔍 检查是否有新的冲突错误:")
stdin, stdout, stderr = ssh.exec_command("grep -c '409' /root/mory/mory.log 2>/dev/null || echo '0'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  409错误数: {out}")

ssh.close()
print("\n" + "=" * 60)
