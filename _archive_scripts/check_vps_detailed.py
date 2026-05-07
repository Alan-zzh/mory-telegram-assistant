# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("VPS详细状态检查")
print("=" * 60)

# 1. 检查所有python进程
print("\n1. 所有Python进程:")
stdin, stdout, stderr = ssh.exec_command('ps aux | grep python')
print(stdout.read().decode('utf-8', errors='replace'))

# 2. 检查Bot目录结构
print("\n2. Bot目录内容:")
stdin, stdout, stderr = ssh.exec_command('ls -la /root/mory/')
print(stdout.read().decode('utf-8', errors='replace'))

# 3. 检查最新日志
print("\n3. 最新Bot日志:")
stdin, stdout, stderr = ssh.exec_command('tail -50 /root/mory/mory.log 2>/dev/null || echo "日志不存在"')
print(stdout.read().decode('utf-8', errors='replace'))

# 4. 检查database.py中的SQL语句
print("\n4. database.py中的auto_mark_group_active函数:")
stdin, stdout, stderr = ssh.exec_command('grep -A10 "def auto_mark_group_active" /root/mory/core/database.py')
print(stdout.read().decode('utf-8', errors='replace'))

# 5. 检查是否有SQL错误
print("\n5. 最近的SQL错误:")
stdin, stdout, stderr = ssh.exec_command('grep -i "sqlite.*error\|syntax error" /root/mory/mory.log 2>/dev/null | tail -10 || echo "无错误"')
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
