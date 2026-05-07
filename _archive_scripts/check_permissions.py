# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""检查Bot权限并使用getUpdates获取消息"""
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
print("📜 检查Bot权限和获取消息")
print("=" * 60)

script = f'''
import requests

TOKEN = "{BOT_TOKEN}"
GROUP_ID = "{GROUP_ID}"
API_URL = f"https://api.telegram.org/bot{{TOKEN}}"

# 1. 获取Bot在群组中的成员信息
print(f"👥 Bot在群组中的权限:")
r = requests.get(f"{{API_URL}}/getChatMember?chat_id={{GROUP_ID}}&user_id=8009972336")
data = r.json()
if data.get("ok"):
    member = data.get("result", {{}})
    print(f"  状态: {{member.get('status')}}")
    if member.get('custom_title'):
        print(f"  称号: {{member.get('custom_title')}}")
else:
    print(f"  错误: {{data.get('description')}}")

# 2. 检查can_delete_messages权限
print(f"\\n📋 Bot权限检查:")
chat = requests.get(f"{{API_URL}}/getChat?chat_id={{GROUP_ID}}").json().get("result", {{}})
print(f"  群组名: {{chat.get('title')}}")

# 3. 尝试getUpdates获取消息
print(f"\\n📜 尝试getUpdates:")
r = requests.get(f"{{API_URL}}/getUpdates?timeout=1&limit=10")
data = r.json()
print(f"  ok: {{data.get('ok')}}")
updates = data.get("result", [])
print(f"  updates数量: {{len(updates)}}")

# 4. 尝试forwardedMessages获取
print(f"\\n📜 尝试其他API:")
# 尝试获取消息ID范围
r = requests.get(f"{{API_URL}}/getChat?chat_id={{GROUP_ID}}")
print(f"  getChat: {{r.json().get('ok')}}")

ssh.close()
'''

# 保存并执行
stdin, stdout, stderr = ssh.exec_command(f'cat > /tmp/check_perms.py << "SCRIPT"\n{script}\nSCRIPT', timeout=10)

stdin, stdout, stderr = ssh.exec_command('cd /root/mory && python3 /tmp/check_perms.py 2>/dev/null', timeout=30)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
print(out)
if err and 'Warning' not in err and err.strip():
    print(f"ERR: {err[:200]}")

ssh.close()
print("\n" + "=" * 60)
