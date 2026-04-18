#!/usr/bin/env python3
"""获取Telegram群组中的Bot消息并清理"""
import paramiko, sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

BOT_TOKEN = "8009972336:AAE9n2Syu6rwAW4Np077_S4X-NwibFbujdY"
GROUP_ID = "-1003004701688"  # 字符串形式

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 获取Telegram群组消息")
print("=" * 60)

# 1. 获取Bot信息
print("\n🤖 Bot信息:")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{BOT_TOKEN}/getMe"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    bot_info = data.get('result', {})
    print(f"  Bot名: {bot_info.get('first_name')}")
    print(f"  @用户名: @{bot_info.get('username')}")

# 2. 获取群组信息
print(f"\n👥 群组信息 (ID: {GROUP_ID}):")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{BOT_TOKEN}/getChat?chat_id={GROUP_ID}"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    chat = data.get('result', {})
    print(f"  群组名: {chat.get('title')}")
    print(f"  类型: {chat.get('type')}")
    print(f"  成员数: {chat.get('member_count', 'N/A')}")
else:
    print(f"  错误: {data.get('description')}")

# 3. 获取Bot发送的消息
print(f"\n📜 Bot在群组中的消息:")
# 尝试获取聊天历史
cmd = f'curl -s "https://api.telegram.org/bot{BOT_TOKEN}/getChatHistory?chat_id={GROUP_ID}&limit=100"'
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=20)
out = stdout.read().decode('utf-8', errors='replace').strip()

try:
    data = json.loads(out)
    if data.get('ok'):
        result = data.get('result', {})
        msgs = result.get('messages', [])
        total = result.get('total_count', 0)
        print(f"  总消息数: {total}")
        
        # 筛选Bot发送的消息
        bot_msgs = [m for m in msgs if m.get('from', {}).get('is_bot')]
        print(f"  Bot消息数: {len(bot_msgs)}")
        
        if bot_msgs:
            print(f"\n  Bot发送的消息详情:")
            for m in bot_msgs[:10]:
                msg_id = m.get('message_id')
                text = m.get('text', m.get('caption', ''))
                if text:
                    text = text[:80]
                date = m.get('date', '')[:19]
                print(f"    [{date}] msg_id={msg_id}: {text}")
        else:
            print("  未找到Bot发送的消息")
    else:
        print(f"  错误: {data.get('description')}")
        print(f"  响应: {out[:200]}")
except Exception as e:
    print(f"  解析错误: {e}")
    print(f"  原始响应: {out[:300]}")

# 4. 尝试获取Bot的群组列表
print(f"\n🤖 Bot所在群组:")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{BOT_TOKEN}/getMyChats" 2>/dev/null || echo "{{\\"ok\\":false}}"', timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
try:
    data = json.loads(out)
    if data.get('ok'):
        chats = data.get('result', [])
        print(f"  Bot加入了 {len(chats)} 个群组")
        for c in chats[:5]:
            print(f"    - {c.get('title', 'N/A')} (ID: {c.get('id')})")
    else:
        print(f"  (getMyChats不可用，这是正常的)")
except:
    pass

ssh.close()
print("\n" + "=" * 60)
