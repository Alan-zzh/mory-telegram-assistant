#!/usr/bin/env python3
"""使用正确的API获取聊天历史"""
import paramiko, sys, io, os, json
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
print("📜 尝试不同的API获取聊天历史")
print("=" * 60)

# 尝试不同的API
script = f'''
import requests
import time

TOKEN = "{BOT_TOKEN}"
GROUP_ID = "{GROUP_ID}"
API_URL = f"https://api.telegram.org/bot{{TOKEN}}"

# 1. 尝试不同的getChatHistory参数
print("尝试1: getChatHistory with limit=50")
r = requests.get(f"{{API_URL}}/getChatHistory", params={{
    "chat_id": GROUP_ID,
    "limit": 50
}})
data = r.json()
print(f"  ok: {{data.get('ok')}}")
if not data.get('ok'):
    print(f"  错误: {{data.get('description')}}")
else:
    msgs = data.get("result", {{}}).get("messages", [])
    print(f"  消息数: {{len(msgs)}}")

time.sleep(1)

# 2. 尝试offset_message_id
print("\\n尝试2: getChatHistory with offset_message_id")
r = requests.get(f"{{API_URL}}/getChatHistory", params={{
    "chat_id": GROUP_ID,
    "limit": 100,
    "offset_message_id": 0
}})
data = r.json()
print(f"  ok: {{data.get('ok')}}")
if not data.get('ok'):
    print(f"  错误: {{data.get('description')}}")
else:
    msgs = data.get("result", {{}}).get("messages", [])
    print(f"  消息数: {{len(msgs)}}")

time.sleep(1)

# 3. 尝试从最新消息开始
print("\\n尝试3: getChatHistory from_message_id=latest")
r = requests.get(f"{{API_URL}}/getChatHistory", params={{
    "chat_id": GROUP_ID,
    "limit": 100,
    "from_message_id": 1
}})
data = r.json()
print(f"  ok: {{data.get('ok')}}")
if not data.get('ok'):
    print(f"  错误: {{data.get('description')}}")
else:
    msgs = data.get("result", {{}}).get("messages", [])
    print(f"  消息数: {{len(msgs)}}")

# 4. 获取群组的最新消息ID
print("\\n尝试4: 获取群组信息中的last_message")
r = requests.get(f"{{API_URL}}/getChat?chat_id={{GROUP_ID}}")
data = r.json()
if data.get('ok'):
    chat = data.get('result', {{}})
    last_msg = chat.get('last_message')
    if last_msg:
        print(f"  最新消息ID: {{last_msg.get('message_id')}}")
        print(f"  最新消息内容: {{last_msg.get('text', 'N/A')[:50]}}")

# 5. 尝试使用message_id范围获取
print("\\n尝试5: 使用message_id范围获取")
if last_msg:
    latest_id = last_msg.get('message_id', 0)
    for start_id in range(max(1, latest_id - 100), latest_id, 20):
        r = requests.get(f"{{API_URL}}/getChatHistory", params={{
            "chat_id": GROUP_ID,
            "limit": 20,
            "from_message_id": start_id
        }})
        data = r.json()
        if data.get('ok'):
            msgs = data.get("result", {{}}).get("messages", [])
            bot_msgs = [m for m in msgs if m.get("from", {{}}).get("is_bot")]
            if bot_msgs:
                print(f"  找到Bot消息! from_message_id={{start_id}}")
                for m in bot_msgs[:5]:
                    print(f"    msg_id={{m.get('message_id')}}: {{m.get('text','')[:50]}}")
                break
'''

stdin, stdout, stderr = ssh.exec_command(f'cat > /tmp/get_msgs2.py << "SCRIPT"\n{script}\nSCRIPT', timeout=10)
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 /tmp/get_msgs2.py 2>/dev/null', timeout=60)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

ssh.close()
print("\n" + "=" * 60)
