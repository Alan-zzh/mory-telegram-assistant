# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 检查Token
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && cat config.json | python3 -c "import sys,json; d=json.load(sys.stdin); print("TOKEN:\", d.get("TOKEN\","NOT_FOUND\")[:30])"', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
print(out)
if err:
    print(f"ERR: {err}")

# 直接执行curl测试
TOKEN = "8009972336:AAE9n2Syu6rwAW4Np077_S4X-NwibFbujdY"
print(f"\n直接测试API (Token: {TOKEN[:20]}...):")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{TOKEN}/getMe"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out[:500])

ssh.close()
