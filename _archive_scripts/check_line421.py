# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("检查第421行附近的原始内容")
print("=" * 60)

# 读取原始字节
stdin, stdout, stderr = ssh.exec_command('sed -n "418,426p" /root/mory/core/database.py | cat -A')
content = stdout.read().decode('utf-8', errors='replace')
print("带特殊字符显示:")
print(repr(content))
print("\n实际内容:")
print(content)

# 检查是否有隐藏字符
print("\n" + "=" * 60)
print("检查十六进制")
print("=" * 60)
stdin, stdout, stderr = ssh.exec_command('sed -n "421,423p" /root/mory/core/database.py | xxd | head -20')
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
