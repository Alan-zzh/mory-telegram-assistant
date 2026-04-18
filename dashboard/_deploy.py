#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard VPS一键部署脚本
将Dashboard部署到VPS，通过公网访问
"""
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 导入VPS配置
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH

import paramiko
import time

print("""
╔════════════════════════════════════════════════════╗
║     🚀 Mory Dashboard VPS部署工具               ║
╚════════════════════════════════════════════════════╝
""")

# 连接VPS
print(f"[*] 连接VPS {VPS_HOST}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)
    print(f"[+] 连接成功!")
except Exception as e:
    print(f"[-] 连接失败: {e}")
    sys.exit(1)

sftp = ssh.open_sftp()

# 1. 创建Dashboard目录
print(f"\n[*] 创建Dashboard目录...")
ssh.exec_command(f"mkdir -p {VPS_PATH}/dashboard")
print(f"[+] 目录已创建")

# 2. 上传Dashboard文件
print(f"\n[*] 上传Dashboard文件...")
files_to_upload = [
    ("dashboard/app.py", f"{VPS_PATH}/dashboard/app.py"),
]

for local, remote in files_to_upload:
    local_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), local)
    if os.path.exists(local_path):
        sftp.put(local_path, remote)
        print(f"  [+] {local}")
    else:
        print(f"  [-] {local} 不存在，跳过")

# 创建启动脚本
print(f"\n[*] 创建启动脚本...")
start_script = """#!/bin/bash
cd /root/mory/dashboard
nohup python3 app.py >> /root/mory/dashboard.log 2>&1 &
echo $! > /root/mory/dashboard.pid
echo "Dashboard started, PID: $(cat /root/mory/dashboard.pid)"
"""

stop_script = """#!/bin/bash
if [ -f /root/mory/dashboard.pid ]; then
    kill $(cat /root/mory/dashboard.pid) 2>/dev/null
    rm /root/mory/dashboard.pid
fi
pkill -f "python3.*app.py" 2>/dev/null
echo "Dashboard stopped"
"""

with sftp.open(f"{VPS_PATH}/dashboard/start.sh", 'w') as f:
    f.write(start_script)
print("  [+] dashboard/start.sh")

with sftp.open(f"{VPS_PATH}/dashboard/stop.sh", 'w') as f:
    f.write(stop_script)
print("  [+] dashboard/stop.sh")

# 设置执行权限
print(f"\n[*] 设置执行权限...")
ssh.exec_command(f"chmod +x {VPS_PATH}/dashboard/*.sh")
print(f"[+] 权限已设置")

# 3. 停止旧进程
print(f"\n[*] 停止旧Dashboard进程...")
ssh.exec_command("pkill -f 'python3.*dashboard.*app.py' 2>/dev/null || true")
time.sleep(1)
print(f"[+] 已停止旧进程")

# 4. 启动Dashboard
print(f"\n[*] 启动Dashboard...")
ssh.exec_command(f"cd {VPS_PATH}/dashboard && bash start.sh")
time.sleep(2)

# 5. 检查状态
print(f"\n[*] 检查Dashboard状态...")
stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'dashboard.*app.py' | grep -v grep")
output = stdout.read().decode('utf-8', errors='replace')
if output.strip():
    pid = output.strip().split()[1]
    print(f"[+] Dashboard运行中! PID: {pid}")
else:
    print(f"[-] Dashboard启动失败，请查看日志")

# 查看日志
stdin, stdout, stderr = ssh.exec_command(f"tail -10 {VPS_PATH}/dashboard.log 2>/dev/null || echo '暂无日志'")
log = stdout.read().decode('utf-8', errors='replace')
if log:
    print(f"\n[*] 最近日志:")
    print(log[:500])

# 6. 获取访问地址
print(f"""
╔════════════════════════════════════════════════════╗
║              ✅ 部署完成!                        ║
╠════════════════════════════════════════════════════╣
║  🌐 访问地址: http://{VPS_HOST}:5000            ║
║  🔐 管理密码: mory2026                          ║
╚════════════════════════════════════════════════════╝

📋 常用命令:
  查看日志: tail -f {VPS_PATH}/dashboard.log
  重启服务: cd {VPS_PATH}/dashboard && bash start.sh
  停止服务: cd {VPS_PATH}/dashboard && bash stop.sh
""")

sftp.close()
ssh.close()
