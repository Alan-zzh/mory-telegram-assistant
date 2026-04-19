#!/usr/bin/env python3
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 获取Bot Token
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 -c "import json; c=json.load(open(\"config.json\")); print(c.get(\"BOT_TOKEN\",\"\"))"', timeout=10)
bot_token = stdout.read().decode('utf-8', errors='replace').strip()

print(f"Bot Token: {bot_token[:20]}..." if len(bot_token) > 20 else bot_token)

# 获取Bot信息
print("\n获取Bot信息...")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getMe"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out[:500])

# 获取群组消息
GROUP_ID = -1003004701688
print(f"\n获取群组 {GROUP_ID} 的消息...")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getChat?chat_id={GROUP_ID}"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out[:500])

ssh.close()
