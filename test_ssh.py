import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 测试连接
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect('43.159.168.175', port=22, username='root', password='066Sh9$YhG#Let', timeout=15)
    print("[OK] SSH连接成功!")
    
    # 测试命令
    stdin, stdout, stderr = ssh.exec_command('echo OK && hostname && pwd')
    print(stdout.read().decode('utf-8', errors='replace'))
    
    # 检查Bot进程
    stdin, stdout, stderr = ssh.exec_command('ps aux | grep main.py | grep -v grep')
    print("Bot进程:", stdout.read().decode('utf-8', errors='replace'))
    
    # 检查reply_tracking
    stdin, stdout, stderr = ssh.exec_command('cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"')
    print("reply_tracking记录数:", stdout.read().decode('utf-8', errors='replace'))
    
    # 检查SQL语法
    stdin, stdout, stderr = ssh.exec_command('grep -n "ts<?\"\"?" /root/mory/core/database.py')
    print("双问号检查:", stdout.read().decode('utf-8', errors='replace') or "无")
    
except Exception as e:
    print(f"[ERROR] {e}")
finally:
    ssh.close()
