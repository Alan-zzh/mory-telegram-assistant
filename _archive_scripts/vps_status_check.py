"""检查VPS bot状态"""
import paramiko
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 1. 检查进程
print("=== 进程状态 ===")
stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'main.py' | grep -v grep")
p = stdout.read().decode(errors="replace").strip()
print(p if p else "没有bot进程在运行")

# 2. 最后10行日志
print("\n=== 最新日志 ===")
stdin, stdout, stderr = ssh.exec_command("tail -15 /root/mory/mory.log 2>/dev/null || echo '日志文件不存在'")
lines = stdout.read().decode(errors="replace").strip()
for line in lines.split("\n"):
    print(line)

# 3. 检查本地文件版本
print("\n=== VPS上main.py版本号 ===")
stdin, stdout, stderr = ssh.exec_command("grep -oP 'v21\\.\\d+' /root/mory/main.py | head -3")
print(stdout.read().decode(errors="replace").strip())

# 4. 检查config版本
print("\n=== VPS上config版本 ===")
stdin, stdout, stderr = ssh.exec_command("grep '_CONFIG_VERSION' /root/mory/config.json")
print(stdout.read().decode(errors="replace").strip())

ssh.close()
