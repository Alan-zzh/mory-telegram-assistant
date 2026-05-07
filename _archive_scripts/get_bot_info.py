# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""获取Bot信息和清理Telegram群组中的历史消息"""
import paramiko, sys, io, os, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("🤖 获取Bot Token和群组信息")
print("=" * 60)

# 1. 获取Bot Token (从config.json)
print("\n🔑 Bot Token:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 -c "import json; c=json.load(open("config.json\")); print(c.get("BOT_TOKEN\","NOT_FOUND\"))"', timeout=10)
bot_token = stdout.read().decode('utf-8', errors='replace').strip()
print(f"  Token前缀: {bot_token[:20]}..." if len(bot_token) > 20 else f"  {bot_token}")

# 2. 获取Bot信息
print("\n🤖 Bot信息:")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getMe"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
try:
    data = json.loads(out)
    if data.get('ok'):
        bot_info = data.get('result', {})
        print(f"  Bot名: {bot_info.get('first_name')}")
        print(f"  @用户名: @{bot_info.get('username')}")
        print(f"  Bot ID: {bot_info.get('id')}")
except:
    print(f"  {out[:200]}")

# 3. 获取群组信息
GROUP_ID = -1003004701688
print(f"\n👥 群组信息 (ID: {GROUP_ID}):")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getChat?chat_id={GROUP_ID}"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
try:
    data = json.loads(out)
    if data.get('ok'):
        chat = data.get('result', {})
        print(f"  群组名: {chat.get('title')}")
        print(f"  类型: {chat.get('type')}")
except:
    print(f"  {out[:200]}")

# 4. 获取Bot在该群组中的最近消息
print(f"\n📜 Bot在群组中的最近消息:")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getChatHistory?chat_id={GROUP_ID}&limit=20&from_message_id=0" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); msgs=d.get(/"result\\",{{}}).get(/"messages\\",[]); [print(f/"  msg_id={{m[\\"message_id/"]}} from={{m[\\"from/"] if \\"from/" in m else \\"N/A/"}}\\") for m in msgs[:10]]" 2>/dev/null || echo "  获取失败"', timeout=20)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out if out else "  (无输出)")

ssh.close()
print("\n" + "=" * 60)
