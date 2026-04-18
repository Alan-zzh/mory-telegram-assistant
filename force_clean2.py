#!/usr/bin/env python3
"""强制清理群组Bot历史消息（改进版）"""
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
print("🧹 强制清理群组Bot历史消息（改进版）")
print("=" * 60)

# 发送触发消息获取起始点
print("\n📨 发送触发消息...")
cmd = f'curl -s -X POST "https://api.telegram.org/bot{BOT_TOKEN}/sendMessage" -d \'{{"chat_id":{GROUP_ID},"text":"🔍 开始扫描..."}}\''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
trigger_msg_id = data.get('result', {}).get('message_id', 0) if data.get('ok') else 0
print(f"触发消息ID: {trigger_msg_id}")

# 改进的扫描脚本 - 跳过protected content错误继续扫描
scan_script = f'''
import requests
import time
import json

TOKEN = "{BOT_TOKEN}"
GROUP_ID = "{GROUP_ID}"
BOT_ID = {BOT_ID}
ADMIN_ID = "{ADMIN_ID}"
START_MSG = {trigger_msg_id}
MAX_SCAN = 200

deleted = 0
scan_total = 0
skipped_protected = 0
not_found = 0

print(f"开始扫描，从message_id={{START_MSG}}往前扫{{MAX_SCAN}}条...")

for offset in range(1, MAX_SCAN + 1):
    mid = START_MSG - offset
    if mid <= 0:
        print(f"到达消息起点")
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
        result = r.json()
        
        if not result.get("ok"):
            err = result.get("description", "").lower()
            if "protected" in err:
                skipped_protected += 1
                continue  # 跳过受保护的消息
            if "not found" in err or "message_id_invalid" in err:
                not_found += 1
                if not_found >= 15:
                    print(f"连续15条消息不存在，停止")
                    break
                continue
            continue
        
        # forward成功，检查是否是Bot消息
        msg = result.get("result", {{}})
        msg_from = msg.get("from", {{}})
        
        if msg_from.get("id") == BOT_ID:
            # 这是Bot发的消息
            text = msg.get("text", msg.get("caption", ""))[:40] if msg.get("text") or msg.get("caption") else "(媒体)"
            
            # 尝试删除
            try:
                r2 = requests.post(
                    f"https://api.telegram.org/bot{{TOKEN}}/deleteMessage",
                    json={{
                        "chat_id": int(GROUP_ID),
                        "message_id": mid
                    }},
                    timeout=10
                )
                del_result = r2.json()
                if del_result.get("ok"):
                    deleted += 1
                    print(f"  [{{offset}}] ✅ msg_id={{mid}} 删除成功: {{text}}...")
                else:
                    del_err = del_result.get("description", "")
                    if "message to delete not found" in del_err:
                        print(f"  [{{offset}}] msg_id={{mid}} 已不存在")
                    else:
                        print(f"  [{{offset}}] ❌ msg_id={{mid}} 删除失败: {{del_err}}")
            except Exception as e:
                print(f"  [{{offset}}] msg_id={{mid}} 删除异常: {{e}}")
        
        scan_total += 1
        not_found = 0
        
        if scan_total % 20 == 0:
            print(f"进度: 扫描{{scan_total}}条，删除{{deleted}}条，跳过受保护{{skipped_protected}}条")
        
        time.sleep(0.05)  # 避免限流
        
    except Exception as e:
        continue

print(f"\\n=== 扫描完成 ===")
print(f"扫描总数: {{scan_total}}")
print(f"删除数: {{deleted}}")
print(f"跳过受保护: {{skipped_protected}}")
'''

ssh.exec_command(f'cat > /tmp/scan2.py << "SCRIPT"\n{scan_script}\nSCRIPT')
stdin, stdout, stderr = ssh.exec_command('python3 /tmp/scan2.py', timeout=180)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 删除触发消息
print("\n🗑️ 删除触发消息...")
cmd = f'curl -s -X POST "https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage" -d \'{{"chat_id":{GROUP_ID},"message_id":{trigger_msg_id}}}\''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace').strip()

ssh.close()
print("\n" + "=" * 60)
