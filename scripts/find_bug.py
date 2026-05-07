# 项目：mory_assistant | 版本：v1.0.5 | 日期：2026-04-27 | 功能：查看历史日志中的错误回复
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

# 查看完整日志文件（包括历史日志）
print("=== 查看 mory.log.1 中的关键词触发记录 ===")
out, _ = run_cmd(f'grep -iE "keyword|trigger|关键词|更新|部署|deploy" {VPS_PATH}/mory.log.1 2>/dev/null | tail -50')
print(out if out else "未找到")

print("\n=== 查看 mory.log 中的关键词触发记录 ===")
out, _ = run_cmd(f'grep -iE "keyword|trigger|关键词|更新|部署|deploy" {VPS_PATH}/mory.log 2>/dev/null | tail -50')
print(out if out else "未找到")

print("\n=== 查看 main.py 中的关键词触发逻辑 ===")
out, _ = run_cmd(f'grep -n "keyword_trigger\|关键词\|更新" {VPS_PATH}/main.py | head -30')
print(out if out else "未找到")

print("\n=== 查看 database.py 中的关键词匹配函数 ===")
out, _ = run_cmd(f'grep -n "match_keyword\|keyword_trigger\|关键词" {VPS_PATH}/core/database.py | head -30')
print(out if out else "未找到")

ssh.close()
print("\n完成！")
