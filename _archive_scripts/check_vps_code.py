# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

# 检查VPS上的SQL语句
print("检查VPS上的 auto_mark_group_active SQL语句:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && grep -A5 "UPDATE reply_tracking SET replied=1" core/database.py', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 检查本地版本
print("\n检查本地版本:")
with open(r"c:\Users\Administrator\Desktop\mory小助理\core\database.py", 'r', encoding='utf-8') as f:
    content = f.read()
    idx = content.find("UPDATE reply_tracking SET replied=1")
    if idx > 0:
        print(content[idx:idx+200])

ssh.close()
