# 项目：mory_assistant | 版本：v1.0.4 | 日期：2026-04-27 | 功能：查看keyword_trigger模块
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

# 读取 keyword_trigger.py 完整代码
print("=== modules/keyword_trigger.py 完整代码 ===")
out, err = run_cmd(f'cat {VPS_PATH}/modules/keyword_trigger.py')
print(out)
if err:
    print(f"ERR: {err}")

print("\n\n=== modules目录文件列表 ===")
out, _ = run_cmd(f'ls -la {VPS_PATH}/modules/')
print(out)

ssh.close()
print("\n完成！")
