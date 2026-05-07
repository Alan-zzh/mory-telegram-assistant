# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)

print("=" * 60)
print("检查修复后的日志")
print("=" * 60)

# 查看最新日志
stdin, stdout, stderr = ssh.exec_command('tail -50 /root/mory/mory.log', timeout=15)
log = stdout.read().decode('utf-8', errors='replace')
print(log)

# 检查是否有SQL错误
if 'syntax error' in log:
    print("\n⚠️ 仍有SQL错误!")
else:
    print("\n✅ 没有SQL错误!")

# 检查reply_tracking
stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"', timeout=10)
print(f"\nreply_tracking记录数: {stdout.read().decode('utf-8', errors='replace').strip()}")

ssh.close()
