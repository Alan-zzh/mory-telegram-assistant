# -*- coding: utf-8 -*-
"""简化诊断"""
import paramiko

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'
VPS_PATH = '/root/mory'

def run(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    _, stdout, _ = ssh.exec_command(cmd, timeout=30)
    result = stdout.read().decode('utf-8', errors='replace').strip()
    ssh.close()
    return result

# 直接检查数据库
print("=== reply_tracking 完整统计 ===")
sql = """python3 -c "
import sqlite3
c = sqlite3.connect('/root/mory/mory.db').cursor()
print('总记录:', c.execute('SELECT COUNT(*) FROM reply_tracking').fetchone()[0])
for r in c.execute('SELECT chat_id, COUNT(*), MIN(ts), MAX(ts) FROM reply_tracking GROUP BY chat_id').fetchall():
    print('  chat=%s: %s条 时间=%s~%s' % r)
print('最新10条:')
for r in c.execute('SELECT * FROM reply_tracking ORDER BY ts DESC LIMIT 10').fetchall():
    print(r)
"
"""
print(run(sql))

print("\n=== 搜索追踪日志 ===")
print(run("grep 'track_reply' /root/mory/mory.log 2>/dev/null | tail -30"))

print("\n=== 搜索user_msg_id相关 ===")
print(run("grep 'user=0' /root/mory/mory.log 2>/dev/null | tail -10"))

print("\n=== 最近的日志 ===")
print(run("tail -100 /root/mory/mory.log 2>/dev/null"))
