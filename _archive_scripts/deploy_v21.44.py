#!/usr/bin/env python3
"""部署 v21.44 阅后即焚修复"""
import paramiko, sys, io, os, time
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS, VPS_PATH, ssh_connect

LOCAL = os.path.dirname(os.path.abspath(__file__))

# 只部署修改的文件
FILES_TO_DEPLOY = [
    ("modules/auto_tasks.py", f"{VPS_PATH}/modules/auto_tasks.py"),
    ("main.py", f"{VPS_PATH}/main.py"),
    ("TECH_BUGFIX_GUIDE.md", f"{VPS_PATH}/TECH_BUGFIX_GUIDE.md"),
]

print("=" * 50)
print("部署 v21.44 阅后即焚修复")
print("=" * 50)

# 1. 连接VPS
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)
sftp = ssh.open_sftp()

# 2. 上传文件
print("\n📤 上传文件...")
for local_rel, remote_path in FILES_TO_DEPLOY:
    local_full = os.path.join(LOCAL, local_rel)
    if os.path.exists(local_full):
        sftp.put(local_full, remote_path)
        print(f"  ✅ {local_rel}")
    else:
        print(f"  ❌ 文件不存在: {local_rel}")

sftp.close()

# 3. 执行热更新
print(f"\n🔄 执行热更新...")
stdin, stdout, stderr = ssh.exec_command(f"cd {VPS_PATH} && bash start.sh update", timeout=30)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
if out: print(out.rstrip())
if err.strip() and "WARNING" not in err: print(f"  {err.rstrip()}")

time.sleep(3)

# 4. 验证
print("\n🔍 验证...")
verify_cmds = [
    ('Bot状态', 'cd /root/mory && bash start.sh status'),
    ('reply_tracking表', 'cd /root/mory && python3 -c "import sqlite3; c=sqlite3.connect(\"mory.db\").cursor(); r=c.execute(\"SELECT COUNT(*) FROM reply_tracking\").fetchone()[0]; print(f\"记录数: {r}\")"'),
    ('修复验证-主动消息不追踪', 'grep -c "_send_and_track" /root/mory/modules/auto_tasks.py | xargs -I{} echo "函数定义数: {}"'),
    ('修复验证-日志级别', 'grep "阅后即焚" /root/mory/main.py | head -1'),
]

for desc, cmd in verify_cmds:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    print(f"  {desc}: {out}")

ssh.close()
print("\n" + "=" * 50)
print("✅ 部署完成！")
print("=" * 50)
