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

# 查找日志文件
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && ls -la *.log 2>/dev/null; cat nohup.out 2>/dev/null | tail -20", timeout=15)
out = stdout.read().decode('utf-8', errors='replace').strip()
print(out)

# 检查start.sh中的日志配置
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && head -30 start.sh", timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
print("\n" + out)

ssh.close()
