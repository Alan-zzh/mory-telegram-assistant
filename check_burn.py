"""核对阅后即焚功能"""
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

# 1. 检查进程状态
safe_print('\n=== 1. Bot进程状态 ===')
stdin, stdout, stderr = ssh.exec_command('bash /root/mory/start.sh status', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 2. 查看最新日志中的阅后即焚相关记录
safe_print('\n=== 2. 阅后即焚日志（最近50条）===')
stdin, stdout, stderr = ssh.exec_command('grep -E "阅后即焚|孤儿|探测|track_reply|refresh" /root/mory/mory.log 2>/dev/null | tail -50', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip() or 'No relevant logs')

# 3. 检查reply_tracking表
safe_print('\n=== 3. reply_tracking 表状态 ===')
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 -c "import sqlite3; c=sqlite3.connect(\"mory.db\").cursor(); print(\"总记录数:\", c.execute(\"SELECT COUNT(*) FROM reply_tracking\").fetchone()[0]); print(\"\\n最新10条记录:\"); rows=c.execute(\"SELECT bot_msg_id, chat_id, user_msg_id, ts, replied FROM reply_tracking ORDER BY ts DESC LIMIT 10\").fetchall(); [print(f\"  bot={r[0]} chat={r[1]} user={r[2]} ts={r[3]} replied={r[4]}\") for r in rows]"', timeout=15)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 4. 检查孤儿清理逻辑（查看代码）
safe_print('\n=== 4. 孤儿清理代码检查 ===')
stdin, stdout, stderr = ssh.exec_command('grep -A5 "孤儿清理" /root/mory/modules/auto_tasks.py | head -10', timeout=10)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 5. 检查探测逻辑
safe_print('\n=== 5. 原消息探测代码检查 ===')
stdin, stdout, stderr = ssh.exec_command('grep -A3 "get_unconfirmed_messages" /root/mory/modules/auto_tasks.py | head -10', timeout=10)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 6. 检查database.py中的查询逻辑
safe_print('\n=== 6. database.py get_unconfirmed_messages 检查 ===')
stdin, stdout, stderr = ssh.exec_command('grep -A8 "def get_unconfirmed_messages" /root/mory/core/database.py', timeout=10)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 7. 检查database.py中的孤儿清理
safe_print('\n=== 7. database.py get_orphan_messages 检查 ===')
stdin, stdout, stderr = ssh.exec_command('grep -A10 "def get_orphan_messages" /root/mory/core/database.py', timeout=10)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

# 8. 检查refresh_tracked方法
safe_print('\n=== 8. database.py refresh_tracked 检查 ===')
stdin, stdout, stderr = ssh.exec_command('grep -A8 "def refresh_tracked" /root/mory/core/database.py', timeout=10)
safe_print(stdout.read().decode('utf-8', errors='replace').strip())

ssh.close()
safe_print('\n检查完成!')
