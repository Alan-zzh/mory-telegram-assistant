# -*- coding: utf-8 -*-
import paramiko
import os

_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

VPS_HOST = os.getenv("VPS_HOST")
VPS_PASS = os.getenv("VPS_SSH_PASS")
VPS_PORT = int(os.getenv("VPS_PORT", "22"))
VPS_USER = os.getenv("VPS_USER", "ubuntu")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)

# 查看Bot日志的最后200行
print("=== 查看Bot日志 ===\n")
stdin, stdout, stderr = ssh.exec_command("tail -200 /home/ubuntu/mory_assistant/mory.log", timeout=15)
log = stdout.read().decode("utf-8")
print(log[-3000:] if len(log) > 3000 else log)

# 查看nohup输出
print("\n=== 查看nohup输出 ===\n")
stdin, stdout, stderr = ssh.exec_command("tail -200 /home/ubuntu/mory_assistant/nohup.out 2>/dev/null || echo 'no nohup.out'", timeout=15)
nohup = stdout.read().decode("utf-8")
print(nohup[-2000:] if len(nohup) > 2000 else nohup)

ssh.close()
