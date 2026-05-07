# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""获取最新消息ID并发送触发消息"""
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
BOT_ID = 8009972336

print("=" * 60)
print("🧹 获取最新消息并扫描Bot历史")
print("=" * 60)

# 1. 获取群组最新消息
print("\n📜 获取群组最新消息...")
stdin, stdout, stderr = ssh.exec_command('curl -s "https://api.telegram.org/bot' + BOT_TOKEN + '/getChat?chat_id=' + GROUP_ID + '"')
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    chat = data.get('result', {})
    last_msg = chat.get('last_message', {})
    latest_msg_id = last_msg.get('message_id', 0) if last_msg else 0
    print(f"群组名: {chat.get('title')}")
    print(f"最新消息ID: {latest_msg_id}")
else:
    print(f"获取失败: {data.get('description')}")
    ssh.close()
    sys.exit(1)

# 2. 发送触发消息
print("\n📨 发送触发消息...")
cmd = 'curl -s -X POST "https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage" -H "Content-Type: application/json" -d '{"chat_id":' + GROUP_ID + ',"text":"🔍 开始扫描Bot历史消息..."}''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    trigger_msg_id = data.get('result', {}).get('message_id', 0)
    print(f"触发消息已发送，ID: {trigger_msg_id}")
else:
    print(f"发送失败: {data.get('description')}")
    trigger_msg_id = latest_msg_id
    print(f"使用最新消息ID作为起始点: {trigger_msg_id}")

# 3. 扫描脚本
print(f"\n🔍 开始扫描（从{trigger_msg_id}往前200条）...")

scan_script = '''
import requests
import time

TOKEN = "8009972336:AAE9n2Syu6rwAW4Np077_S4X-NwibFbujdY"
GROUP_ID = "-1003004701688"
BOT_ID = 8009972336
ADMIN_ID = "8012433255"
START_MSG = ''' + str(trigger_msg_id) + '''
MAX_SCAN = 200

deleted = 0
scan_total = 0
skipped_protected = 0
not_found = 0
bot_found = 0

for offset in range(1, MAX_SCAN + 1):
    mid = START_MSG - offset
    if mid <= 0:
        print(f"到达消息起点")
        break
    
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/forwardMessage",
            json={"chat_id": int(ADMIN_ID), "from_chat_id": int(GROUP_ID), "message_id": mid},
            timeout=10
        )
        result = r.json()
        
        if not result.get("ok"):
            err = result.get("description", "").lower()
            if "protected" in err:
                skipped_protected += 1
                continue
            if "not found" in err or "message_id_invalid" in err:
                not_found += 1
                if not_found >= 15:
                    print(f"连续15条不存在，停止扫描")
                    break
                continue
            continue
        
        msg = result.get("result", {})
        msg_from = msg.get("from", {})
        
        if msg_from.get("id") == BOT_ID:
            bot_found += 1
            text = msg.get("text", msg.get("caption", ""))[:30] if msg.get("text") or msg.get("caption") else "(媒体)"
            
            r2 = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/deleteMessage",
                json={"chat_id": int(GROUP_ID), "message_id": mid},
                timeout=10
            )
            if r2.json().get("ok"):
                deleted += 1
                print(f"  [扫描{offset}] ✅ 删除 msg_id={mid}: {text}...")
            else:
                print(f"  [扫描{offset}] msg_id={mid} 删除失败")
        
        scan_total += 1
        not_found = 0
        
        if scan_total % 20 == 0:
            print(f"进度: 扫描{scan_total}条, Bot消息{bot_found}条, 删除{deleted}条, 跳过受保护{skipped_protected}条")
        
        time.sleep(0.05)
        
    except:
        continue

print(f"")
print(f"=== 扫描完成 ===")
print(f"扫描总数: {scan_total}")
print(f"Bot消息: {bot_found}")
print(f"删除数: {deleted}")
print(f"跳过受保护: {skipped_protected}")
'''

ssh.exec_command('cat > /tmp/scan4.py << "SCRIPT"\n' + scan_script + '\nSCRIPT')
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/scan4.py 2>/dev/null', timeout=180)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 4. 删除触发消息
print("\n🗑️ 删除触发消息...")
cmd = 'curl -s -X POST "https://api.telegram.org/bot' + BOT_TOKEN + '/deleteMessage" -H "Content-Type: application/json" -d '{"chat_id":' + GROUP_ID + ',"message_id":' + str(trigger_msg_id) + '}''
stdin, stdout, stderr = ssh.exec_command(cmd)

ssh.close()
print("\n" + "=" * 60)
print("✅ 完成！")
print("=" * 60)
