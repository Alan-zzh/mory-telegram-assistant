#!/usr/bin/env python3
"""让Bot执行清群无人理指令"""
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
print("🤖 让Bot执行'清群无人理'指令")
print("=" * 60)

# 1. 以管理员身份在群里发送"清群无人理"指令
print(f"\n📨 以管理员身份发送'清群无人理'指令...")
cmd = 'curl -s -X POST "https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage" -H "Content-Type: application/json" -d \'{"chat_id":' + GROUP_ID + ',"text":"清群无人理","from_user_id":' + ADMIN_ID + '}\''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace').strip()
data = json.loads(out)
if data.get('ok'):
    msg_id = data.get('result', {}).get('message_id', 0)
    print(f"  指令已发送，message_id={msg_id}")
    
    # 等待Bot处理
    print(f"\n⏳ 等待Bot处理（约10秒）...")
    import time
    time.sleep(10)
    
    # 2. 删除触发消息
    print(f"\n🗑️ 删除触发消息...")
    cmd = 'curl -s -X POST "https://api.telegram.org/bot' + BOT_TOKEN + '/deleteMessage" -H "Content-Type: application/json" -d \'{"chat_id":' + GROUP_ID + ',"message_id":' + str(msg_id) + '}\''
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    data = json.loads(out)
    if data.get('ok'):
        print(f"  ✅ 触发消息已删除")
    else:
        print(f"  删除结果: {data.get('description', 'OK')}")
else:
    print(f"  发送失败: {data.get('description')}")

# 3. 检查Bot日志
print(f"\n📜 Bot日志中的清理记录:")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && tail -100 mory.log | grep -E '清群|清理|删除|阶段'", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
if out:
    print(out)
else:
    print("  (无相关日志)")

ssh.close()
print("\n" + "=" * 60)
