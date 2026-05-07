# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""强制清理群组中的Bot历史消息"""
import paramiko, sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

BOT_TOKEN = "8009972336:AAE9n2Syu6rwAW4Np077_S4X-NwibFbujdY"
GROUP_ID = "-1003004701688"
ADMIN_ID = "8012433255"

print("=" * 60)
print("🧹 强制清理群组Bot历史消息")
print("=" * 60)

# 1. 获取Bot信息
print("\n🤖 获取Bot信息:")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{BOT_TOKEN}/getMe"')
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    bot_info = data.get('result', {})
    bot_id = bot_info.get('id')
    print(f"  Bot名: {bot_info.get('first_name')}")
    print(f"  Bot ID: {bot_id}")
else:
    print(f"  错误: {data.get('description')}")
    ssh.close()
    sys.exit(1)

# 2. 获取群组最新消息ID
print(f"\n📜 获取群组最新消息:")
stdin, stdout, stderr = ssh.exec_command(f'curl -s "https://api.telegram.org/bot{BOT_TOKEN}/getChat?chat_id={GROUP_ID}"')
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    chat = data.get('result', {})
    last_msg = chat.get('last_message', {})
    latest_msg_id = last_msg.get('message_id', 0) if last_msg else 0
    print(f"  群组名: {chat.get('title')}")
    print(f"  最新消息ID: {latest_msg_id}")
else:
    print(f"  错误: {data.get('description')}")
    ssh.close()
    sys.exit(1)

# 3. 发送测试消息获取起始消息ID
print(f"\n📨 发送触发消息以获取起始点...")
test_msg = "🔍 开始扫描Bot历史消息..."
cmd = f'curl -s -X POST "https://api.telegram.org/bot{BOT_TOKEN}/sendMessage" -d "chat_id={GROUP_ID}&text={test_msg}&disable_notification=true"'
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    trigger_msg_id = data.get('result', {}).get('message_id', 0)
    print(f"  已发送触发消息，message_id={trigger_msg_id}")
else:
    print(f"  发送失败: {data.get('description')}")
    print("  将使用最新消息作为起始点...")
    trigger_msg_id = latest_msg_id

# 4. 执行forward探测扫描
print(f"\n🔍 开始forward探测扫描（从msg_id={trigger_msg_id}往前扫100条）...")
scan_script = f'''
import requests
import time
import json

TOKEN = "{BOT_TOKEN}"
GROUP_ID = "{GROUP_ID}"
BOT_ID = {bot_id}
ADMIN_ID = "{ADMIN_ID}"
START_MSG = {trigger_msg_id}
MAX_SCAN = 100

deleted = 0
scan_total = 0
not_found = 0

print(f"开始扫描，从message_id={{START_MSG}}往前扫{{MAX_SCAN}}条...")

for offset in range(1, MAX_SCAN + 1):
    mid = START_MSG - offset
    if mid <= 0:
        print(f"到达消息起点，停止扫描")
        break
    
    try:
        # forward探测
        r = requests.post(
            f"https://api.telegram.org/bot{{TOKEN}}/forwardMessage",
            json={{
                "chat_id": int(ADMIN_ID),
                "from_chat_id": int(GROUP_ID),
                "message_id": mid
            }},
            timeout=10
        )
        data = r.json()
        
        if not data.get("ok"):
            err = data.get("description", "").lower()
            if "not found" in err or "message to forward not found" in err or "message_id_invalid" in err:
                not_found += 1
                if not_found >= 10:
                    print(f"连续10条消息不存在，停止扫描 (offset={{offset}})")
                    break
                continue
            else:
                print(f"错误 offset={{offset}}: {{err}}")
                continue
        
        # forward成功，检查是否是Bot消息
        msg = data.get("result", {{}})
        msg_from = msg.get("from", {{}})
        
        if msg_from.get("id") == BOT_ID:
            # 这是Bot发的消息，删除它
            try:
                r2 = requests.post(
                    f"https://api.telegram.org/bot{{TOKEN}}/deleteMessage",
                    json={{
                        "chat_id": int(GROUP_ID),
                        "message_id": mid
                    }},
                    timeout=10
                )
                result = r2.json()
                if result.get("ok"):
                    deleted += 1
                    text = msg.get("text", "")[:30] if msg.get("text") else "(无文字)"
                    print(f"  [{{offset}}] ✅ 删除msg_id={{mid}}: {{text}}...")
                else:
                    err = result.get("description", "")
                    if "message to delete not found" in err:
                        print(f"  [{{offset}}] msg_id={{mid}} 已被删除")
                    else:
                        print(f"  [{{offset}}] ❌ 删除失败: {{err}}")
            except Exception as e:
                print(f"  [{{offset}}] ❌ 删除异常: {{e}}")
        
        scan_total += 1
        not_found = 0
        
        if scan_total % 20 == 0:
            print(f"已扫描{{scan_total}}条，找到{{deleted}}条Bot消息待删除")
        
        time.sleep(0.1)  # 避免触发限流
        
    except Exception as e:
        print(f"offset={{offset}} 异常: {{e}}")
        continue

print(f"\\n扫描完成：共扫描{{scan_total}}条，删除{{deleted}}条Bot消息")
'''

# 保存并执行脚本
ssh.exec_command(f'cat > /tmp/scan_bot_msgs.py << "SCRIPT"\n{scan_script}\nSCRIPT')
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/scan_bot_msgs.py', timeout=120)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 5. 删除触发消息
print("\n🗑️ 删除触发消息...")
cmd = f'curl -s -X POST "https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage" -d '{{"chat_id":{GROUP_ID},"message_id":{trigger_msg_id}}}''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    print("  ✅ 触发消息已删除")
else:
    print(f"  触发消息删除: {data.get('description')}")

ssh.close()
print("\n" + "=" * 60)
print("✅ 清理完成！")
print("=" * 60)
