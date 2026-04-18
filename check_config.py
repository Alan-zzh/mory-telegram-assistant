#!/usr/bin/env python3
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 查看config.json的keys
print("config.json 中的所有key:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 -c "import json; c=json.load(open(\"config.json\")); print(list(c.keys()))"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 查看token相关字段
print("\nToken相关字段:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && grep -i "token" config.json', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

ssh.close()
