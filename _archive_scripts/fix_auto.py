# -*- coding: utf-8 -*-
"""Fix auto_tasks.py - remove track_reply from _send_and_track"""
import paramiko

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'

def run(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    _, stdout, _ = ssh.exec_command(cmd, timeout=30)
    result = stdout.read().decode('utf-8', errors='replace').strip()
    ssh.close()
    return result

# Read the current auto_tasks.py
print("=== Reading current auto_tasks.py ===")
result = run("head -60 /root/mory/modules/auto_tasks.py")
print(result)
