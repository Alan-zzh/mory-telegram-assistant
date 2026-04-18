import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 70)
print("检查Bot是否真的回复了消息")
print("=" * 70)

# 1. 查找Bot发送的所有消息
print("\n【1】Bot发送的所有消息")
stdin, stdout, stderr = ssh.exec_command('grep -E "send_message|发送" /root/mory/mory.log 2>/dev/null | tail -30', timeout=15)
msgs = stdout.read().decode('utf-8', errors='replace')
print(msgs if msgs.strip() else "(无发送记录)")

# 2. 查找Bot收到的所有消息
print("\n【2】Bot收到的消息")
stdin, stdout, stderr = ssh.exec_command('grep -E "收到消息|dispatch|msg_id=" /root/mory/mory.log 2>/dev/null | tail -30', timeout=15)
msgs = stdout.read().decode('utf-8', errors='replace')
print(msgs if msgs.strip() else "(无)")

# 3. 查找_tracked_reply调用
print("\n【3】追踪记录")
stdin, stdout, stderr = ssh.exec_command('grep -E "_tracked_reply|阅后即焚追踪成功|tracked_reply" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
tracked = stdout.read().decode('utf-8', errors='replace')
print(tracked if tracked.strip() else "(无追踪记录)")

# 4. 检查Bot回复消息的逻辑
print("\n【4】检查Bot回复逻辑")
stdin, stdout, stderr = ssh.exec_command('grep -n "bot.reply" /root/mory/main.py | head -20', timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

# 5. 检查AI回复
print("\n【5】AI回复日志")
stdin, stdout, stderr = ssh.exec_command('grep -E "AI回复|AI.*reply|ai.ask" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
ai_reply = stdout.read().decode('utf-8', errors='replace')
print(ai_reply if ai_reply.strip() else "(无)")

# 6. 统计收到消息vs回复消息
print("\n【6】消息统计")
stdin, stdout, stderr = ssh.exec_command('grep -c "收到消息" /root/mory/mory.log 2>/dev/null || echo 0', timeout=10)
recv_count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"收到消息次数: {recv_count}")

stdin, stdout, stderr = ssh.exec_command('grep -c "send_message" /root/mory/mory.log 2>/dev/null || echo 0', timeout=10)
send_count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"发送消息次数: {send_count}")

# 7. 检查dispatch函数
print("\n【7】dispatch处理结果")
stdin, stdout, stderr = ssh.exec_command('grep -E "_dispatch|处理消息" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
dispatch = stdout.read().decode('utf-8', errors='replace')
print(dispatch if dispatch.strip() else "(无)")

# 8. 最新的完整日志
print("\n【8】最新50行日志")
stdin, stdout, stderr = ssh.exec_command('tail -50 /root/mory/mory.log', timeout=15)
log = stdout.read().decode('utf-8', errors='replace')
print(log)

ssh.close()
print("\n" + "=" * 70)
