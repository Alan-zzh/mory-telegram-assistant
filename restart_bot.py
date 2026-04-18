"""重启VPS上的Bot"""
import sys
import io
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

print("=" * 60)
print("[重启Bot]")
stdin, stdout, stderr = ssh.exec_command("cd /root/mory && pkill -9 -f 'main.py' && sleep 2 && nohup python3 main.py > bot.log 2>&1 & sleep 3 && ps aux | grep main.py | grep -v grep")
out = stdout.read().decode('utf-8', errors='replace')
print(out)

print("\n" + "=" * 60)
print("[确认重启后日志]")
stdin, stdout, stderr = ssh.exec_command("tail -20 /root/mory/mory.log")
out = stdout.read().decode('utf-8', errors='replace')
print(out)

ssh.close()
print("\n✅ Bot已重启！请在群里重新 @MoryMateBot test 发送测试消息")
