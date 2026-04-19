import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("检查Bot追踪和回复逻辑")
print("=" * 60)

# 1. 检查Bot是否在接收消息
print("\n1. 最近的消息接收日志:")
stdin, stdout, stderr = ssh.exec_command('grep -E "收到消息|msg_id|dispatch" /root/mory/mory.log 2>/dev/null | tail -10', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 2. 检查Bot是否有回复记录
print("\n2. Bot回复日志:")
stdin, stdout, stderr = ssh.exec_command('grep -E "发送回复|reply_to|_tracked_reply|📌" /root/mory/mory.log 2>/dev/null | tail -15', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 3. 检查main.py中的追踪逻辑
print("\n3. main.py中_tracked_reply的定义:")
stdin, stdout, stderr = ssh.exec_command('grep -A15 "def _tracked_reply" /root/mory/main.py', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(未找到)")

# 4. 检查bot.reply_to是否设置为_tracked_reply
print("\n4. bot.reply_to的赋值:")
stdin, stdout, stderr = ssh.exec_command('grep "bot.reply_to" /root/mory/main.py', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(未找到)")

# 5. 检查auto_mark_group_active是否被调用
print("\n5. auto_mark_group_active调用日志:")
stdin, stdout, stderr = ssh.exec_command('grep "auto_mark_group_active\|群活跃" /root/mory/mory.log 2>/dev/null | tail -5', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

# 6. 检查孤儿清理任务
print("\n6. 孤儿清理相关日志:")
stdin, stdout, stderr = ssh.exec_command('grep -E "孤儿|orphan|探测" /root/mory/mory.log 2>/dev/null | tail -10', timeout=10)
print(stdout.read().decode('utf-8', errors='replace') or "(无)")

ssh.close()
print("\n检查完成!")
