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

# 检查VPS上的auto_mark_group_active函数
print("📋 VPS上的 auto_mark_group_active 函数:")
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && grep -A15 "def auto_mark_group_active" core/database.py', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 检查本地版本
print("\n📋 本地 auto_mark_group_active 函数:")
with open(r"c:\Users\Administrator\Desktop\mory小助理\core\database.py", 'r', encoding='utf-8') as f:
    content = f.read()
    start = content.find("def auto_mark_group_active")
    if start > 0:
        end = content.find("\n    def ", start + 1)
        print(content[start:end])

ssh.close()
