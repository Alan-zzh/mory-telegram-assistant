# 项目：mory_assistant | 版本：v1.0.2 | 日期：2026-04-27 | 功能：VPS诊断-数据库查询
import paramiko
import os
from dotenv import load_dotenv

load_dotenv(r'c:\Users\Administrator\Desktop\mory_assistant\.env')

VPS_HOST = os.getenv('VPS_HOST')
VPS_SSH_PASS = os.getenv('VPS_SSH_PASS')
VPS_PORT = int(os.getenv('VPS_PORT', '22'))
VPS_USER = os.getenv('VPS_USER', 'root')
VPS_PATH = os.getenv('VPS_PATH', '/root/mory')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_SSH_PASS, timeout=15)

def run_cmd(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    return out, err

# 写入临时脚本到VPS
sftp = ssh.open_sftp()
with sftp.open('/tmp/db_check.py', 'w') as f:
    f.write("""
import sqlite3
conn = sqlite3.connect('mory.db')
c = conn.cursor()

print('=== 表结构 keyword_triggers ===')
c.execute('PRAGMA table_info(keyword_triggers)')
for col in c.fetchall():
    print(col)

print('')
print('=== 所有触发规则 ===')
c.execute('SELECT * FROM keyword_triggers')
rows = c.fetchall()
print(f'共 {len(rows)} 条')
for r in rows:
    print(r)

print('')
print('=== 所有表 ===')
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for t in c.fetchall():
    print(t[0])

print('')
print('=== 最近的chat_messages ===')
try:
    c.execute('SELECT * FROM chat_messages ORDER BY id DESC LIMIT 10')
    rows = c.fetchall()
    for r in rows:
        print(r)
except Exception as e:
    print(f'表不存在: {e}')

conn.close()
""")
sftp.close()

print("="*60)
print("1. 数据库查询结果")
print("="*60)
out, err = run_cmd(f'cd {VPS_PATH} && python3 /tmp/db_check.py')
print(out)
if err:
    print(f"ERR: {err}")

print("="*60)
print("2. 日志中含 服务器/删除/部署/指令/命令 的内容")
print("="*60)
out, _ = run_cmd(f'grep -E "服务器|删除|部署|指令|命令" {VPS_PATH}/mory.log | tail -n 100')
print(out if out else "未找到")

print("="*60)
print("3. 日志中含 auto_reply/keyword/触发/AI 的内容")
print("="*60)
out, _ = run_cmd(f'grep -iE "auto_reply|keyword|trigger|ai_response|llm|回复" {VPS_PATH}/mory.log | tail -n 100')
print(out if out else "未找到")

print("="*60)
print("4. 完整日志最后200行")
print("="*60)
out, _ = run_cmd(f'tail -n 200 {VPS_PATH}/mory.log')
print(out)

ssh.close()
print("\n完成！")
