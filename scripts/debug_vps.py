# 项目：mory_assistant | 版本：v1.0.0 | 日期：2026-04-27 | 功能：VPS诊断脚本
import paramiko
import os
from dotenv import load_dotenv

load_dotenv(r'c:\Users\Administrator\Desktop\mory_assistant\.env')

VPS_HOST = os.getenv('VPS_HOST')
VPS_SSH_PASS = os.getenv('VPS_SSH_PASS')
VPS_PORT = int(os.getenv('VPS_PORT', '22'))
VPS_USER = os.getenv('VPS_USER', 'root')
VPS_PATH = os.getenv('VPS_PATH', '/root/mory')

print(f"正在连接 VPS: {VPS_HOST}:{VPS_PORT} ...")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_SSH_PASS, timeout=15)
print("连接成功！\n")

def run_cmd(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    return out, err

# 1. 最近日志
print("="*60)
print("1. 最近500行日志中含关键词的行")
print("="*60)
out, _ = run_cmd(f'tail -n 500 {VPS_PATH}/mory.log')
for line in out.split('\n'):
    if any(kw in line for kw in ['服务器', '删除', '部署', '指令', '命令']):
        print(line)

# 2. 数据库关键词规则
print("\n" + "="*60)
print("2. keyword_triggers 表内容")
print("="*60)
db_script = """
import sqlite3
conn = sqlite3.connect('mory.db')
c = conn.cursor()
c.execute('SELECT * FROM keyword_triggers')
rows = c.fetchall()
print(f'共 {len(rows)} 条规则')
for r in rows:
    print(r)
# 查看表结构
c.execute('PRAGMA table_info(keyword_triggers)')
cols = c.fetchall()
print('列结构:')
for col in cols:
    print(col)
conn.close()
"""
out, err = run_cmd(f'cd {VPS_PATH} && python3 << \'PYEOF\'\n{db_script}\nPYEOF')
print(out if out else f"错误: {err}")

# 3. 最近错误
print("\n" + "="*60)
print("3. 最近错误日志")
print("="*60)
out, _ = run_cmd(f'grep -iE "error|exception|traceback|fail|失败" {VPS_PATH}/mory.log | tail -n 50')
print(out if out else "未找到明显错误")

# 4. AI回复内容
print("\n" + "="*60)
print("4. AI回复相关日志")
print("="*60)
out, _ = run_cmd(f'grep -iE "reply|response|ai|回复|触发|trigger" {VPS_PATH}/mory.log | tail -n 50')
print(out if out else "未找到回复日志")

# 5. 最近100行完整日志
print("\n" + "="*60)
print("5. 最近100行日志")
print("="*60)
out, _ = run_cmd(f'tail -n 100 {VPS_PATH}/mory.log')
print(out)

ssh.close()
print("\n诊断完成！")
