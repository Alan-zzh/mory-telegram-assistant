# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import paramiko, sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 获取Bot Token
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 -c "import json; c=json.load(open("config.json\")); print(c.get("TOKEN\","\"))"', timeout=10)
bot_token = stdout.read().decode('utf-8', errors='replace').strip()

print("=" * 60)
print("🤖 Bot信息")
print("=" * 60)

# 获取Bot信息
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getMe"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
try:
    data = json.loads(out)
    if data.get('ok'):
        bot_info = data.get('result', {})
        print(f"Bot名: {bot_info.get('first_name')}")
        print(f"@用户名: @{bot_info.get('username')}")
        print(f"Bot ID: {bot_info.get('id')}")
    else:
        print(f"错误: {data.get('description')}")
except Exception as e:
    print(f"解析错误: {e}")
    print(out[:300])

# 获取群组信息
GROUP_ID = -1003004701688
print(f"\n{'='*60}")
print(f"👥 群组信息 (ID: {GROUP_ID})")
print("=" * 60)

stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getChat?chat_id={GROUP_ID}"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
try:
    data = json.loads(out)
    if data.get('ok'):
        chat = data.get('result', {})
        print(f"群组名: {chat.get('title')}")
        print(f"类型: {chat.get('type')}")
        print(f"成员数: {chat.get('member_count', 'N/A')}")
    else:
        print(f"错误: {data.get('description')}")
except Exception as e:
    print(f"解析错误: {e}")
    print(out[:300])

# 获取Bot最近消息
print(f"\n{'='*60}")
print(f"📜 Bot在群组中的最近消息")
print("=" * 60)

# 使用getChatHistory获取消息
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{bot_token}/getChatHistory?chat_id={GROUP_ID}&limit=50&from_message_id=1" 2>/dev/null', timeout=20)
out = stdout.read().decode('utf-8', errors='replace').strip()
try:
    data = json.loads(out)
    if data.get('ok'):
        msgs = data.get('result', {}).get('messages', [])
        print(f"获取到 {len(msgs)} 条消息\n")
        
        bot_messages = []
        for m in msgs:
            if m.get('from', {}).get('is_bot'):
                msg_id = m.get('message_id')
                text = m.get('text', m.get('caption', ''))[:50]
                date = m.get('date', '')[:19]
                bot_messages.append((msg_id, text, date))
        
        if bot_messages:
            print(f"Bot发送的消息 ({len(bot_messages)} 条):")
            for msg_id, text, date in bot_messages[:20]:
                print(f"  [{date}] msg_id={msg_id}: {text}...")
        else:
            print("未找到Bot发送的消息")
    else:
        print(f"错误: {data.get('description')}")
except Exception as e:
    print(f"解析错误: {e}")
    print(out[:500])

ssh.close()
print("\n" + "=" * 60)
