# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 70)
print("检查Bot是否真的回复过群消息")
print("=" * 70)

# 1. 查找Bot在群里的所有发送
print("\n【1】Bot在群里发送的所有消息")
stdin, stdout, stderr = ssh.exec_command('grep -E "send_message.*-1003004701688|send.*chat_id.*-1003004701688|✅.*已发送" /root/mory/mory.log 2>/dev/null | head -30', timeout=15)
msgs = stdout.read().decode('utf-8', errors='replace')
print(msgs if msgs.strip() else "(无)")

# 2. 检查Bot所有发送（包括发送给管理员的）
print("\n【2】Bot发送给管理员的所有消息")
stdin, stdout, stderr = ssh.exec_command('grep -E "send_message.*8012433255|forward.*admin|探测" /root/mory/mory.log 2>/dev/null | head -20', timeout=15)
admin_msgs = stdout.read().decode('utf-8', errors='replace')
print(admin_msgs if admin_msgs.strip() else "(无)")

# 3. 检查阅后即焚相关的所有日志
print("\n【3】阅后即焚相关日志（所有）")
stdin, stdout, stderr = ssh.exec_command('grep -E "阅后即焚|探测|孤儿|orphan|refresh" /root/mory/mory.log 2>/dev/null', timeout=15)
burn_logs = stdout.read().decode('utf-8', errors='replace')
print(burn_logs if burn_logs.strip() else "(无)")

# 4. 检查Bot有没有回复群消息的逻辑
print("\n【4】检查_bot_reply_to调用")
stdin, stdout, stderr = ssh.exec_command('grep -E "_bot_reply_to|bot.reply_to|reply_to" /root/mory/mory.log 2>/dev/null | head -20', timeout=15)
reply_logs = stdout.read().decode('utf-8', errors='replace')
print(reply_logs if reply_logs.strip() else "(无)")

# 5. 搜索任何Bot的回复
print("\n【5】任何Bot回复（搜索关键词）")
stdin, stdout, stderr = ssh.exec_command('''grep -E "回复用户|回复.*chat|reply.*group|✅ 阅后" /root/mory/mory.log 2>/dev/null | head -20''', timeout=15)
any_reply = stdout.read().decode('utf-8', errors='replace')
print(any_reply if any_reply.strip() else "(无)")

# 6. 检查孤儿清理任务的实际执行
print("\n【6】孤儿清理任务的详细日志")
stdin, stdout, stderr = ssh.exec_command('grep -E "🗑️|孤儿|get_orphan|清理" /root/mory/mory.log 2>/dev/null', timeout=15)
cleanup = stdout.read().decode('utf-8', errors='replace')
print(cleanup if cleanup.strip() else "(无孤儿清理日志)")

# 7. 检查探测任务的详细日志
print("\n【7】探测任务的详细日志")
stdin, stdout, stderr = ssh.exec_command('grep -E "🔥|探测|probe|forward_message" /root/mory/mory.log 2>/dev/null | head -30', timeout=15)
probe = stdout.read().decode('utf-8', errors='replace')
print(probe if probe.strip() else "(无探测日志)")

ssh.close()
print("\n" + "=" * 70)
