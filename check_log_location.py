#!/usr/bin/env python3
"""检查日志位置和Bot进程"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 查找日志位置和Bot活动")
print("=" * 60)

# 1. 查找日志文件
print("\n📁 查找日志文件:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && ls -la *.log 2>/dev/null; ls -la logs/ 2>/dev/null || echo '无logs目录'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 2. 查找最近的日志文件
print("\n📁 最近修改的日志文件:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && find . -name '*.log' -mmin -60 2>/dev/null | head -10", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "  无最近日志")

# 3. 查看Bot进程的输出
print("\n📜 Bot进程输出 (stderr/stdout):")
stdin, stdout, stderr = ssh.exec_command("ps aux | grep python | grep -v grep", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 4. 查看Bot进程的文件描述符
stdin, stdout, stderr = ssh.exec_command("ls -la /proc/$(pgrep -f 'main.py' | head -1)/fd 2>/dev/null | grep log || echo '无法查看fd'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 5. 检查start.sh如何处理日志
print("\n📜 start.sh日志配置:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && grep -A5 'log' start.sh | head -20", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 6. 直接查看Bot进程的输出
print("\n📜 尝试读取Bot日志:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && cat nohup.out 2>/dev/null | tail -50 || echo 'nohup.out不存在'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

ssh.close()
print("\n" + "=" * 60)
