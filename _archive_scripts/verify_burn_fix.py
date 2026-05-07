# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("验证阅后即焚功能是否正常")
print("=" * 60)

# 1. Bot进程状态
print("\n1. Bot进程:")
stdin, stdout, stderr = ssh.exec_command('ps aux | grep "python3 main.py" | grep -v grep', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "Bot未运行")

# 2. reply_tracking表状态
print("\n2. reply_tracking表:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"记录数: {count}")

# 3. 查看追踪记录详情
print("\n3. 追踪记录详情:")
stdin, stdout, stderr = ssh.exec_command('''cd /root/mory && sqlite3 mory.db "SELECT bot_msg_id, user_msg_id, replied, datetime(ts, 'unixepoch') FROM reply_tracking ORDER BY ts DESC LIMIT 10"''', timeout=10)
result = stdout.read().decode('utf-8', errors='replace')
print(result if result.strip() else "(无记录)")

# 4. 检查阅后即焚相关日志
print("\n4. 最近30分钟的阅后即焚日志:")
stdin, stdout, stderr = ssh.exec_command('grep -E "阅后即焚|_tracked_reply|孤儿|删除|探测" /root/mory/mory.log 2>/dev/null | tail -20', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无相关日志)")

# 5. 检查auto_tasks是否在运行
print("\n5. auto_tasks后台任务:")
stdin, stdout, stderr = ssh.exec_command('grep -E "后台任务|孤儿清理|探测" /root/mory/mory.log 2>/dev/null | tail -10', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无相关日志)")

# 6. 最新日志
print("\n6. 最新Bot日志:")
stdin, stdout, stderr = ssh.exec_command('tail -20 /root/mory/mory.log', timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

# 7. 检查是否有user=0错误（之前的bug）
print("\n7. 检查是否还有user=0错误:")
stdin, stdout, stderr = ssh.exec_command('grep "user=0" /root/mory/mory.log 2>/dev/null | tail -5', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无错误)")

ssh.close()
print("\n验证完成!")
