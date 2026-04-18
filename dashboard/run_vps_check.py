import paramiko
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH

HOST, PORT, USER, PASS = VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS

# 上传脚本
t = paramiko.Transport((HOST, PORT))
t.connect(username=USER, password=PASS)
sftp = paramiko.SFTPClient.from_transport(t)
sftp.put(r"C:\Users\Administrator\Desktop\mory小助理\dashboard\check_vps_db.py", "/tmp/check_db.py")
sftp.close()
t.close()
print("uploaded")

# 执行脚本
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
stdin, stdout, stderr = client.exec_command("cd /root/mory && python3 /tmp/check_db.py", timeout=15)
out = stdout.read().decode("utf-8", errors="replace")
err = stderr.read().decode("utf-8", errors="replace")
client.close()
if out.strip():
    print(out)
else:
    print("ERR:", err)
