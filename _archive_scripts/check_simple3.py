"""简化诊断"""
import paramiko
import sys

# 设置stdout编码
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

# 直接检查数据库
print("=== reply_tracking 完整统计 ===")
sql = """python3 -c "
import sqlite3
c = sqlite3.connect('/root/mory/mory.db').cursor()
print('Total:', c.execute('SELECT COUNT(*) FROM reply_tracking').fetchone()[0])
for r in c.execute('SELECT chat_id, COUNT(*), MIN(ts), MAX(ts) FROM reply_tracking GROUP BY chat_id').fetchall():
    print('  chat=%s: %s recs %s~%s' % r)
print('Latest 10:')
for r in c.execute('SELECT * FROM reply_tracking ORDER BY ts DESC LIMIT 10').fetchall():
    print(r)
"
"""
print(run(sql))

print("\n=== Search track_reply logs ===")
result = run("grep -E 'track_reply|user=0' /root/mory/mory.log 2>/dev/null | tail -20")
print(result[:2000] if result else "None")

print("\n=== Recent logs ===")
result = run("tail -50 /root/mory/mory.log 2>/dev/null")
print(result[:3000] if result else "None")
