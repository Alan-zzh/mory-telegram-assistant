# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""全面检查VPS上的阅后即焚状态"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📊 VPS 阅后即焚全面检查")
print("=" * 60)

# 1. Bot状态
print("\n🤖 Bot状态:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && bash start.sh status", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 2. reply_tracking表
print("\n📋 reply_tracking表:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  总记录数: {count}")

# 3. 查看所有追踪记录
print("\n📜 所有追踪记录 (最近20条):")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 -header -column mory.db "SELECT * FROM reply_tracking ORDER BY ts DESC LIMIT 20"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
else:
    print("  (无记录)")

# 4. 检查Bot发送的消息表
print("\n📨 Bot消息统计:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM messages WHERE sender_id < 0"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  Bot发送的消息数: {out}")

# 5. 查看Bot消息
print("\n📨 Bot最近消息:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 -header -column mory.db "SELECT message_id, chat_id, content, ts FROM messages WHERE sender_id < 0 ORDER BY ts DESC LIMIT 10"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
else:
    print("  (无记录)")

# 6. 检查配置中的群组
print("\n👥 配置的群组:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && grep -oP "CHAT_ID.*?\\d+" config.json 2>/dev/null || grep "group" config.json', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  {out}")

# 7. 最近日志中的阅后即焚相关
print("\n📜 日志中的阅后即焚记录:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && grep -E '阅后即焚|_tracked_reply|track_reply' bot.log 2>/dev/null | tail -10", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
else:
    print("  (无相关日志)")

ssh.close()
print("\n" + "=" * 60)
