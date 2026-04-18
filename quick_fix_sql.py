#!/usr/bin/env python3
"""快速修复SQL语法错误并上传到VPS"""
import paramiko
import os
import sys
import io
from time import sleep

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# VPS配置 - 使用实际的新IP
VPS_HOST = "43.159.168.175"
VPS_PORT = 22
VPS_USER = "root"
VPS_PASS = "066Sh9$YhG#Let"
VPS_PATH = "/root/mory"

LOCAL_DIR = r"c:\Users\Administrator\Desktop\mory小助理"

def main():
    print("=" * 60)
    print("🔧 修复SQL语法错误并上传到VPS")
    print("=" * 60)
    
    # 连接到VPS
    print(f"\n📡 连接到 VPS {VPS_HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)
    sftp = ssh.open_sftp()
    
    # 1. 先检查VPS上当前代码的情况
    print("\n📋 检查VPS当前代码状态...")
    stdin, stdout, stderr = ssh.exec_command(f"grep -n 'ts<?' {VPS_PATH}/core/database.py | grep 'auto_mark_group_active' -A2 -B2", timeout=10)
    out = stdout.read().decode('utf-8', errors='replace')
    print(f"VPS当前代码:\n{out}")
    
    # 2. 上传本地修复后的database.py
    local_file = os.path.join(LOCAL_DIR, "core", "database.py")
    remote_file = f"{VPS_PATH}/core/database.py"
    
    print(f"\n📤 上传修复后的 database.py...")
    sftp.put(local_file, remote_file)
    print(f"✅ 上传成功!")
    
    # 3. 验证上传成功
    stdin, stdout, stderr = ssh.exec_command(f"grep -n 'ts<?' {VPS_PATH}/core/database.py | head -5", timeout=10)
    out = stdout.read().decode('utf-8', errors='replace')
    print(f"\n📋 验证VPS新代码:\n{out}")
    
    # 4. 检查是否还有??
    stdin, stdout, stderr = ssh.exec_command(f"grep -c '??' {VPS_PATH}/core/database.py", timeout=10)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    if out == "0":
        print("✅ 确认: 没有找到双问号(??)")
    else:
        print(f"⚠️ 警告: 仍有 {out} 处双问号!")
    
    # 5. 重启Bot
    print("\n🔄 重启Bot...")
    stdin, stdout, stderr = ssh.exec_command(f"cd {VPS_PATH} && pkill -9 -f 'main.py' 2>/dev/null; sleep 1 && nohup python3 main.py > bot.log 2>&1 &", timeout=15)
    stdout.read()
    stderr.read()
    sleep(3)
    
    # 6. 检查Bot是否启动成功
    stdin, stdout, stderr = ssh.exec_command(f"ps aux | grep 'main.py' | grep -v grep", timeout=10)
    out = stdout.read().decode('utf-8', errors='replace')
    if "main.py" in out:
        print("✅ Bot启动成功!")
    else:
        print("⚠️ Bot可能未启动")
    
    # 7. 查看最新日志
    print("\n📜 最近Bot日志:")
    stdin, stdout, stderr = ssh.exec_command(f"tail -20 {VPS_PATH}/bot.log", timeout=10)
    out = stdout.read().decode('utf-8', errors='replace')
    print(out)
    
    sftp.close()
    ssh.close()
    
    print("\n" + "=" * 60)
    print("✅ 修复完成!")
    print("=" * 60)

if __name__ == "__main__":
    main()
