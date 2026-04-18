"""详细检查阅后即焚追踪情况"""
import paramiko
import sys
import re

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

def safe_print(s):
    if s:
        s = re.sub(r'[\U00010000-\U0010ffff]', '', s)
        print(s)

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'
VPS_PATH = '/root/mory'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

# 1. 查看所有包含"追踪"关键字的日志
safe_print('\n=== 所有追踪相关日志 ===')
stdin, stdout, stderr = ssh.exec_command('grep -E "追踪|track_reply|阅后即焚" /root/mory/mory.log 2>/dev/null | tail -100', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No logs')

# 2. 查看消息回复相关日志
safe_print('\n=== AI回复相关日志 ===')
stdin, stdout, stderr = ssh.exec_command('grep -E "回复|AI.*len=|should_reply" /root/mory/mory.log 2>/dev/null | tail -30', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No logs')

# 3. 查看 _tracked_reply 调用日志（需要DEBUG级别）
safe_print('\n=== _tracked_reply 调用日志 ===')
stdin, stdout, stderr = ssh.exec_command('grep -E "tracked_reply" /root/mory/mory.log 2>/dev/null | tail -30', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No logs')

# 4. 查看孤儿清理日志
safe_print('\n=== 孤儿清理日志 ===')
stdin, stdout, stderr = ssh.exec_command('grep -E "孤儿|清理" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No logs')

# 5. 查看探测日志
safe_print('\n=== 探测日志 ===')
stdin, stdout, stderr = ssh.exec_command('grep -E "探测|Probe|forward" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No logs')

# 6. 检查bot最近是否收到消息
safe_print('\n=== Bot最近消息处理 ===')
stdin, stdout, stderr = ssh.exec_command('grep -E "master_handler|_dispatch" /root/mory/mory.log 2>/dev/null | tail -20', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No logs')

# 7. 检查数据库中是否有追踪记录
safe_print('\n=== 数据库追踪记录详情 ===')
stdin, stdout, stderr = ssh.exec_command('''cd /root/mory && python3 -c "
import sqlite3
conn = sqlite3.connect('mory.db')
c = conn.cursor()

# 检查表是否存在
c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='reply_tracking'\")
table_exists = c.fetchone()
print('表是否存在:', table_exists is not None)

if table_exists:
    # 统计
    c.execute('SELECT COUNT(*) FROM reply_tracking')
    count = c.fetchone()[0]
    print('总记录数:', count)
    
    # 查看所有记录
    c.execute('SELECT * FROM reply_tracking LIMIT 20')
    rows = c.fetchall()
    if rows:
        print('记录详情:')
        for r in rows:
            print(f'  {r}')
    else:
        print('无追踪记录')
        
    # 检查 replied 状态分布
    c.execute('SELECT replied, COUNT(*) FROM reply_tracking GROUP BY replied')
    for stat in c.fetchall():
        print(f'replied={stat[0]}: {stat[1]}条')
        
conn.close()
"''', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 8. 检查 _tracked_reply 函数是否存在
safe_print('\n=== 检查monkey-patch ===')
stdin, stdout, stderr = ssh.exec_command('grep -n "_tracked_reply\|tracked_reply" /root/mory/main.py | head -20', timeout=10)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

ssh.close()
safe_print('\n检查完成!')
