import paramiko, os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.vps_config import ssh_connect

s = paramiko.SSHClient(); s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(s)
i,o,e = s.exec_command("pkill -9 -f 'main.py'; sleep 1; ps aux | grep 'main.py' | grep -v grep | wc -l")
print(f"killed, remaining: {o.read().decode().strip()}")
s.close()
