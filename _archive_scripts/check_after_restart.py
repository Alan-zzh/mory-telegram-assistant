import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("检查Bot重启后的追踪情况")
print("=" * 60)

# 1. 检查Bot重启后的日志（17:33之后）
print("\n1. Bot重启后的所有日志 (17:33起):")
stdin, stdout, stderr = ssh.exec_command('grep "2026-04-18 17:3" /root/mory/mory.log 2>/dev/null | head -30', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 2. 检查是否有追踪成功
print("\n2. 追踪相关日志 (包括成功和失败):")
stdin, stdout, stderr = ssh.exec_command('grep -E "track_reply|_tracked_reply|追踪|tracked" /root/mory/mory.log 2>/dev/null | grep "17:3" | head -20', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 3. 检查auto_tasks的阅后即焚任务
print("\n3. auto_tasks日志:")
stdin, stdout, stderr = ssh.exec_command('grep -E "auto_tasks|后台任务" /root/mory/mory.log 2>/dev/null | tail -20', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 4. 检查是否有回复消息
print("\n4. 消息回复日志:")
stdin, stdout, stderr = ssh.exec_command('grep -E "回复用户|发送回复|reply_to" /root/mory/mory.log 2>/dev/null | tail -20', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 5. 检查reply_tracking表
print("\n5. reply_tracking表当前状态:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
print(f"记录数: {stdout.read().decode('utf-8', errors='replace').strip()}")

# 6. 查看最近的reply_tracking记录
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT * FROM reply_tracking ORDER BY ts DESC LIMIT 5"', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无记录)")

ssh.close()
print("\n检查完成!")
