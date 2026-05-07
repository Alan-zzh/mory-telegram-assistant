# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 70)
print("深入检查孤儿清理为什么没执行")
print("=" * 70)

# 1. 检查reply_tracking表
print("\n【1】reply_tracking表状态")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"记录数: {count}")

# 查看所有记录
print("\n所有追踪记录:")
stdin, stdout, stderr = ssh.exec_command('''cd /root/mory && sqlite3 mory.db "SELECT bot_msg_id, chat_id, user_msg_id, replied, datetime(ts, 'unixepoch', 'localtime') as local_time FROM reply_tracking ORDER BY ts DESC"''', timeout=10)
records = stdout.read().decode('utf-8', errors='replace')
print(records if records.strip() else "(无记录)")

# 2. 检查24小时前的时间戳
print("\n【2】时间计算")
import time
now_ts = int(time.time())
ts_24h_ago = now_ts - 86400
print(f"当前时间戳: {now_ts}")
print(f"24小时前时间戳: {ts_24h_ago}")

stdin, stdout, stderr = ssh.exec_command(f'cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking WHERE ts < {ts_24h_ago}"', timeout=10)
old_count = stdout.read().decode('utf-8', errors='replace').strip()
print(f"超过24小时的记录数: {old_count}")

# 3. 检查孤儿清理函数是否存在
print("\n【3】孤儿清理函数检查")
stdin, stdout, stderr = ssh.exec_command('grep -n "get_orphan_messages" /root/mory/core/database.py | head -5', timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

# 4. 检查孤儿清理的实际逻辑
print("\n【4】孤儿清理SQL逻辑")
stdin, stdout, stderr = ssh.exec_command('grep -A10 "def get_orphan_messages" /root/mory/core/database.py', timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

# 5. 检查auto_tasks中的孤儿清理调用
print("\n【5】auto_tasks孤儿清理调用")
stdin, stdout, stderr = ssh.exec_command('grep -B2 -A5 "get_orphan" /root/mory/modules/auto_tasks.py', timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

# 6. 检查Bot是否真的有回复过消息
print("\n【6】Bot消息发送记录")
stdin, stdout, stderr = ssh.exec_command('grep -E "发送回复|reply_to|bot.*发送" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
bot_replies = stdout.read().decode('utf-8', errors='replace')
print(bot_replies if bot_replies.strip() else "(无发送记录)")

# 7. 检查用户消息和Bot回复的对应关系
print("\n【7】Bot收到的消息")
stdin, stdout, stderr = ssh.exec_command('grep "收到消息|msg_id=" /root/mory/mory.log 2>/dev/null | tail -10', timeout=15)
msgs = stdout.read().decode('utf-8', errors='replace')
print(msgs if msgs.strip() else "(无)")

# 8. 直接测试孤儿清理函数
print("\n【8】直接调用孤儿清理")
stdin, stdout, stderr = ssh.exec_command('''cd /root/mory && python3 -c "
import sqlite3
conn = sqlite3.connect('mory.db')
c = conn.cursor()

# 检查get_orphan_messages的逻辑
cutoff = 1742412180  # 24小时前
c.execute('SELECT bot_msg_id, chat_id, user_msg_id, ts FROM reply_tracking WHERE ts<? AND user_msg_id>0', (cutoff,))
rows = c.fetchall()
print(f'超过24小时的记录: {len(rows)}条')
for r in rows:
    print(f'  bot={r[0]} chat={r[1]} user={r[2]} ts={r[3]}')
conn.close()
"''', timeout=15)
result = stdout.read().decode('utf-8', errors='replace')
print(result)

ssh.close()
print("\n" + "=" * 70)
