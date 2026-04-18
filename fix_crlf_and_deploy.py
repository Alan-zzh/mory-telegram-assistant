#!/usr/bin/env python3
"""修复database.py的CRLF问题并上传到VPS"""
import paramiko
import sys
import io
import os
from time import sleep

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VPS_HOST = "43.159.168.175"
VPS_PORT = 22
VPS_USER = "root"
VPS_PASS = "066Sh9$YhG#Let"
VPS_PATH = "/root/mory"
LOCAL_DIR = r"c:\Users\Administrator\Desktop\mory小助理"

def main():
    print("=" * 60)
    print("修复CRLF问题并部署")
    print("=" * 60)
    
    # 连接VPS
    print(f"\n📡 连接 VPS {VPS_HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)
    print("✅ 连接成功!")
    
    # 1. 读取本地database.py并转换为Unix行尾
    local_file = os.path.join(LOCAL_DIR, "core", "database.py")
    print(f"\n📖 读取本地文件: {local_file}")
    with open(local_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 转换为Unix行尾 (CRLF -> LF)
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    print(f"✅ 转换为Unix行尾 (LF)")
    
    # 2. 停止Bot进程
    print("\n🛑 停止Bot进程...")
    stdin, stdout, stderr = ssh.exec_command('pkill -9 -f "main.py" 2>/dev/null; sleep 1')
    stdout.read()
    stderr.read()
    print("✅ Bot已停止")
    
    # 3. 备份原文件
    print("\n📦 备份原文件...")
    stdin, stdout, stderr = ssh.exec_command(f'cp {VPS_PATH}/core/database.py {VPS_PATH}/core/database.py.bak', timeout=10)
    stdout.read()
    stderr.read()
    print("✅ 备份完成")
    
    # 4. 上传修复后的文件 (使用SFTP)
    print("\n📤 上传修复后的database.py...")
    sftp = ssh.open_sftp()
    
    # 将内容写入临时文件
    with sftp.file(f'{VPS_PATH}/core/database.py', 'w') as f:
        f.write(content)
    sftp.close()
    print("✅ 上传成功!")
    
    # 5. 验证文件已更新
    print("\n🔍 验证文件...")
    stdin, stdout, stderr = ssh.exec_command(f'file {VPS_PATH}/core/database.py', timeout=10)
    result = stdout.read().decode('utf-8', errors='replace')
    print(f"文件类型: {result}")
    
    # 检查行尾
    stdin, stdout, stderr = ssh.exec_command(f'head -1 {VPS_PATH}/core/database.py | xxd | head -1', timeout=10)
    result = stdout.read().decode('utf-8', errors='replace')
    print(f"行尾检查: {result}")
    
    # 6. 启动Bot
    print("\n🚀 启动Bot...")
    stdin, stdout, stderr = ssh.exec_command(f'cd {VPS_PATH} && nohup python3 main.py > bot.log 2>&1 &', timeout=15)
    stdout.read()
    stderr.read()
    print("✅ Bot启动命令已执行")
    
    # 等待启动
    sleep(5)
    
    # 7. 检查Bot是否启动
    print("\n🔍 检查Bot状态...")
    stdin, stdout, stderr = ssh.exec_command('ps aux | grep "main.py" | grep -v grep', timeout=10)
    result = stdout.read().decode('utf-8', errors='replace')
    if "main.py" in result:
        print("✅ Bot启动成功!")
    else:
        print("⚠️ Bot可能未启动，查看日志...")
        stdin, stdout, stderr = ssh.exec_command(f'tail -30 {VPS_PATH}/bot.log', timeout=10)
        print(stdout.read().decode('utf-8', errors='replace'))
    
    # 8. 等待消息处理测试
    print("\n⏳ 等待Bot处理消息...")
    sleep(10)
    
    # 9. 检查是否有SQL错误
    print("\n🔍 检查最新日志...")
    stdin, stdout, stderr = ssh.exec_command(f'tail -50 {VPS_PATH}/mory.log', timeout=10)
    log = stdout.read().decode('utf-8', errors='replace')
    print(log)
    
    # 检查是否有SQL错误
    if 'syntax error' in log or 'OperationalError' in log:
        print("\n⚠️ 仍有SQL错误!")
    else:
        print("\n✅ 看起来没有SQL错误了!")
    
    ssh.close()
    
    print("\n" + "=" * 60)
    print("修复完成!")
    print("=" * 60)

if __name__ == "__main__":
    main()
