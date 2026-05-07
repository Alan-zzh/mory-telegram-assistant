# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""修复database.py的CRLF问题并上传到VPS"""
import paramiko
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VPS_HOST = "43.159.168.175"
VPS_PORT = 22
VPS_USER = "root"
VPS_PASS = "066Sh9$YhG#Let"
VPS_PATH = "/root/mory"
LOCAL_DIR = r"c:\Users\Administrator\Desktop\mory小助理"

def run_ssh(ssh, cmd, timeout=30):
    """执行SSH命令"""
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        return stdout.read().decode('utf-8', errors='replace'), stderr.read().decode('utf-8', errors='replace')
    except Exception as e:
        return "", str(e)

def main():
    print("=" * 60)
    print("修复CRLF问题并部署")
    print("=" * 60)
    
    # 连接VPS
    print(f"\n连接 VPS {VPS_HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)
    print("连接成功!")
    
    # 1. 读取本地database.py并转换为Unix行尾
    local_file = os.path.join(LOCAL_DIR, "core", "database.py")
    print(f"\n读取本地文件...")
    with open(local_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 转换为Unix行尾
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    print("转换为Unix行尾 (LF)")
    
    # 2. 停止Bot
    print("\n停止Bot...")
    run_ssh(ssh, 'pkill -9 -f "main.py" 2>/dev/null; sleep 1')
    print("Bot已停止")
    
    # 3. 上传文件
    print("\n上传database.py...")
    sftp = ssh.open_sftp()
    with sftp.file(f'{VPS_PATH}/core/database.py', 'w') as f:
        f.write(content)
    sftp.close()
    print("上传成功!")
    
    # 4. 验证
    out, err = run_ssh(ssh, f'head -1 {VPS_PATH}/core/database.py | xxd | head -1')
    print(f"行尾检查: {out.strip()}")
    
    # 5. 启动Bot
    print("\n启动Bot...")
    run_ssh(ssh, f'cd {VPS_PATH} && nohup python3 main.py > bot.log 2>&1 & sleep 2')
    print("Bot启动命令已执行")
    
    # 6. 等待
    import time
    time.sleep(15)
    
    # 7. 检查状态
    print("\n检查Bot状态...")
    out, err = run_ssh(ssh, 'ps aux | grep "main.py" | grep -v grep')
    if "main.py" in out:
        print("Bot运行中!")
    else:
        print("Bot未运行")
    
    # 8. 查看日志
    print("\n最新日志:")
    out, err = run_ssh(ssh, f'tail -30 {VPS_PATH}/mory.log')
    print(out)
    
    ssh.close()
    print("\n修复完成!")

if __name__ == "__main__":
    main()
