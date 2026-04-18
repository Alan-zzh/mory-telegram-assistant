#!/usr/bin/env python3
"""检查Bot运行状态和日志"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 Bot运行状态和日志检查")
print("=" * 60)

# 1. Bot状态
print("\n🤖 Bot状态:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh status", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 2. 查看最近日志
print("\n📜 最近100行日志:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -100 bot.log 2>/dev/null || echo '日志文件不存在'", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
lines = out.split('\n')
# 只显示关键日志
for line in lines[-30:]:
    if line.strip():
        print(f"  {line[:120]}")

# 3. 检查reply_tracking表
print("\n📋 reply_tracking表状态:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  记录数: {out}")

# 4. 检查是否有新的user_msg_id追踪
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT * FROM reply_tracking WHERE user_msg_id > 0"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
if out:
    print(f"  有user追踪的记录: {out}")
else:
    print(f"  无user追踪记录")

# 5. 检查Bot是否在接收消息
print("\n🔍 检查Bot消息接收:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && grep -c '处理消息\\|收到消息\\|message' bot.log 2>/dev/null || echo '0'", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  消息处理日志数: {out}")

ssh.close()
print("\n" + "=" * 60)
