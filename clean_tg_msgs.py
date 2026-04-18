#!/usr/bin/env python3
"""使用Python telegram库获取和清理群组消息"""
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

print("=" * 60)
print("📜 检查并清理Telegram群组消息")
print("=" * 60)

# 使用VPS上的Python telegram库获取消息
script = '''
import os, sys
os.chdir("/root/mory")
sys.path.insert(0, "/root/mory")

from telegram import Bot
import json

# 加载配置
with open("config.json") as f:
    config = json.load(f)

TOKEN = config.get("TOKEN", "")
GROUP_ID = config.get("GROUP_ID", 0)

print(f"Bot Token: {TOKEN[:20]}...")
print(f"Group ID: {GROUP_ID}")

# 创建Bot实例
bot = Bot(token=TOKEN)

# 获取群组信息
try:
    chat = bot.get_chat(GROUP_ID)
    print(f"\\n群组信息:")
    print(f"  名称: {chat.title}")
    print(f"  类型: {chat.type}")
except Exception as e:
    print(f"\\n获取群组信息失败: {e}")

# 获取最近消息
print(f"\\n获取最近消息...")
try:
    # 使用get_chat_history
    messages = bot.get_chat_history(chat_id=GROUP_ID, limit=50)
    msg_list = list(messages)
    print(f"  获取到 {len(msg_list)} 条消息")
    
    # 统计Bot消息
    bot_msgs = [m for m in msg_list if m.from_user and m.from_user.is_bot]
    print(f"  Bot发送的消息: {len(bot_msgs)} 条")
    
    # 显示Bot消息
    for m in bot_msgs[:15]:
        text = m.text or m.caption or ""
        text = text[:60] if text else "(无文字)"
        print(f"    msg_id={m.message_id}: {text}...")
        
except Exception as e:
    print(f"  获取消息失败: {e}")
'''

# 保存脚本到VPS并执行
stdin, stdout, stderr = ssh.exec_command('cat > /tmp/get_msgs.py << "SCRIPT"\n' + script + '\nSCRIPT', timeout=10)
err = stderr.read().decode('utf-8', errors='replace').strip()
if err:
    print(f"保存脚本: {err}")

# 执行脚本
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 /tmp/get_msgs.py', timeout=30)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
print(out)
if err and 'Warning' not in err:
    print(f"ERR: {err}")

ssh.close()
print("\n" + "=" * 60)
