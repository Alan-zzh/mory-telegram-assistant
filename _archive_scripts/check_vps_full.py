# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("深度检查SQL错误来源")
print("=" * 60)

# 1. 查看完整日志
print("\n1. 最新日志(最后100行):")
stdin, stdout, stderr = ssh.exec_command('tail -100 /root/mory/mory.log')
print(stdout.read().decode('utf-8', errors='replace'))

# 2. 检查所有SQL语句中的?
print("\n2. database.py中所有包含?的行:")
stdin, stdout, stderr = ssh.exec_command('grep -n "?" /root/mory/core/database.py | grep -E "execute|""')
print(stdout.read().decode('utf-8', errors='replace'))

# 3. 检查main.py中的SQL
print("\n3. main.py中调用auto_mark_group_active的地方:")
stdin, stdout, stderr = ssh.exec_command('grep -n "auto_mark_group_active" /root/mory/main.py')
print(stdout.read().decode('utf-8', errors='replace'))

# 4. 检查auto_mark_group_active的完整实现
print("\n4. auto_mark_group_active完整实现:")
stdin, stdout, stderr = ssh.exec_command('sed -n "405,435p" /root/mory/core/database.py')
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
