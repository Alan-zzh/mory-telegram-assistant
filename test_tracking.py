"""测试群聊消息追踪"""
import paramiko
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'

def run(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    _, stdout, _ = ssh.exec_command(cmd, timeout=30)
    result = stdout.read().decode('utf-8', errors='replace').strip()
    ssh.close()
    return result

print("=== 1. 检查Bot当前状态 ===")
print(run("ps aux | grep main.py | grep -v grep | head -3"))

print("\n=== 2. 检查日志中所有消息处理 ===")
print(run("grep -E 'master_handler|_dispatch|should_reply' /root/mory/mory.log 2>/dev/null | tail -20"))

print("\n=== 3. 检查消息过滤相关日志 ===")
print(run("grep -E '黑名单|spam|IGNORE|过滤|skip' /root/mory/mory.log 2>/dev/null | tail -20"))

print("\n=== 4. 检查最近的message_id日志 ===")
print(run("grep -E 'message_id' /root/mory/mory.log 2>/dev/null | tail -20"))

print("\n=== 5. 直接模拟测试追踪 ===")
test_script = """python3 -c "
import sys
sys.path.insert(0, '/root/mory')
import sqlite3
from core.database import DB

db = DB('/root/mory/mory.db')
# 测试正常追踪
db.track_reply(99999, -1003004701688, 88888)
# 检查结果
c = db.conn.cursor()
c.execute('SELECT * FROM reply_tracking')
rows = c.fetchall()
print('记录数:', len(rows))
for r in rows:
    print('记录:', r)
# 清理测试数据
db.conn.execute('DELETE FROM reply_tracking WHERE bot_msg_id=99999')
db.conn.commit()
"
"""
print(run(test_script))

print("\n=== 6. 检查main.py中的_tracked_reply调用 ===")
print(run("grep -A20 'def _tracked_reply' /root/mory/main.py | head -25"))

print("\n=== 7. 添加DEBUG日志后重启测试 ===")
debug_script = """python3 -c "
import re

# 读取main.py
with open('/root/mory/main.py', 'r') as f:
    content = f.read()

# 检查logger.debug是否在文件中
if 'logger.debug' in content:
    print('logger.debug found in main.py')
else:
    print('NO logger.debug in main.py')

# 检查日志级别
with open('/root/mory/core/logging_util.py', 'r') as f:
    log_content = f.read()
    print('Logging config:', log_content[:500])
"
"""
print(run(debug_script))
