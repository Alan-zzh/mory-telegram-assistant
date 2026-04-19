#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步代码到 VPS 并重启机器人"""

import paramiko
import sys
import io

# 修复输出编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 读取密码
with open('.env', 'r', encoding='utf-8') as f:
    for line in f:
        if 'VPS_SSH_PASS' in line and '=' in line:
            vps_pass = line.strip().split('=', 1)[1]
            break

print('Connecting...')
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('43.159.168.175', port=22, username='root', password=vps_pass, timeout=8)

print('Restarting...')
_, stdout, stderr = client.exec_command('bash /root/mory/start.sh restart', timeout=15)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
print(out)
if err.strip():
    print(err)

print('Status:')
_, stdout, _ = client.exec_command('bash /root/mory/start.sh status', timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
print('OK!')
