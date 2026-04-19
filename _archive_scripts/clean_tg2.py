#!/usr/bin/env python3
"""使用requests直接调用Telegram API获取和清理群组消息"""
import paramiko, sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

BOT_TOKEN = "8009972336:AAE9n2Syu6rwAW4Np077_S4X-NwibFbujdY"
GROUP_ID = "-1003004701688"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 使用requests调用Telegram API")
print("=" * 60)

# 使用requests调用API
script = f'''
import requests
import json

TOKEN = "{BOT_TOKEN}"
GROUP_ID = "{GROUP_ID}"
API_URL = f"https://api.telegram.org/bot{{TOKEN}}"

# 1. 获取Bot信息
print("🤖 Bot信息:")
r = requests.get(f"{{API_URL}}/getMe")
data = r.json()
if data.get("ok"):
    bot = data.get("result", {{}})
    print(f"  名称: {{bot.get('first_name')}}")
    print(f"  用户名: @{{bot.get('username')}}")

# 2. 获取群组信息
print(f"\\n👥 群组信息 (ID: {{GROUP_ID}}):")
r = requests.get(f"{{API_URL}}/getChat?chat_id={{GROUP_ID}}")
data = r.json()
if data.get("ok"):
    chat = data.get("result", {{}})
    print(f"  名称: {{chat.get('title')}}")
    print(f"  类型: {{chat.get('type')}}")
else:
    print(f"  错误: {{data.get('description')}}")

# 3. 获取聊天历史
print(f"\\n📜 获取聊天历史 (limit=100):")
r = requests.get(f"{{API_URL}}/getChatHistory?chat_id={{GROUP_ID}}&limit=100")
data = r.json()
print(f"  响应: {{data.get('ok')}} {{data.get('description', '')}}")

if data.get("ok"):
    msgs = data.get("result", {{}}).get("messages", [])
    total = data.get("result", {{}}).get("total_count", 0)
    print(f"  总消息数: {{total}}")
    print(f"  获取消息数: {{len(msgs)}}")
    
    # 筛选Bot消息
    bot_msgs = [m for m in msgs if m.get("from", {{}}).get("is_bot")]
    print(f"  Bot消息数: {{len(bot_msgs)}}")
    
    if bot_msgs:
        print(f"\\n  Bot发送的消息:")
        for m in bot_msgs[:20]:
            msg_id = m.get("message_id")
            text = m.get("text") or m.get("caption") or "(无文字)"
            text = text[:50]
            date = m.get("date", "")[:19]
            print(f"    [{{date}}] msg_id={{msg_id}}: {{text}}")
'''

# 保存脚本
stdin, stdout, stderr = ssh.exec_command(f'cat > /tmp/tg_api.py << "SCRIPT"\n{script}\nSCRIPT', timeout=10)
err = stderr.read().decode('utf-8', errors='replace').strip()

# 执行
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 /tmp/tg_api.py', timeout=30)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
print(out)
if err and 'Warning' not in err:
    print(f"ERR: {err[:200]}")

ssh.close()
print("\n" + "=" * 60)
