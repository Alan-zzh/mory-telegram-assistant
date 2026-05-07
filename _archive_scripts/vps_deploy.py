# -*- coding: utf-8 -*-
import paramiko, sys, io, os, time
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 【修复】统一从 core/vps_config 读取VPS配置，不再硬编码
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS, VPS_PATH

LOCAL = os.path.dirname(os.path.abspath(__file__))
LOCAL_BACKUP_DIR = os.path.join(LOCAL, "backups")

# 需要部署的修改文件
FILES_TO_DEPLOY = [
    ("main.py", f"{VPS_PATH}/main.py"),
    (os.path.join("modules", "auto_tasks.py"), f"{VPS_PATH}/modules/auto_tasks.py"),
    (os.path.join("modules", "admin_cmds.py"), f"{VPS_PATH}/modules/admin_cmds.py"),
    (os.path.join("modules", "content.py"), f"{VPS_PATH}/modules/content.py"),
    (os.path.join("modules", "group_mgr.py"), f"{VPS_PATH}/modules/group_mgr.py"),
    (os.path.join("core", "ai_engine.py"), f"{VPS_PATH}/core/ai_engine.py"),
    (os.path.join("core", "database.py"), f"{VPS_PATH}/core/database.py"),
    (os.path.join("core", "optimizer.py"), f"{VPS_PATH}/core/optimizer.py"),
    (os.path.join("modules", "optimizer_admin.py"), f"{VPS_PATH}/modules/optimizer_admin.py"),
    # v21.38 新增：自然语言指令模块
    (os.path.join("modules", "natural_cmd.py"), f"{VPS_PATH}/modules/natural_cmd.py"),
    # v21.37 新增：线程安全重构
    (os.path.join("core", "logging_util.py"), f"{VPS_PATH}/core/logging_util.py"),
    (os.path.join("core", "resource_manager.py"), f"{VPS_PATH}/core/resource_manager.py"),
    ("AI_DEBUG_HISTORY.md", f"{VPS_PATH}/AI_DEBUG_HISTORY.md"),
    ("config.json", f"{VPS_PATH}/config.json"),
    ("CHANGELOG.md", f"{VPS_PATH}/CHANGELOG.md"),
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
from core.vps_config import ssh_connect
ssh_connect(ssh)

print("🚀 开始部署 v21.23 (含自动备份)...\n")

# 1. 上传文件
sftp = ssh.open_sftp()
for local_rel, remote_path in FILES_TO_DEPLOY:
    local_full = os.path.join(LOCAL, local_rel)
    sftp.put(local_full, remote_path)
    print(f"✅ 已上传: {local_rel}")
sftp.close()

# 2. 执行热更新
print(f"\n📦 执行热更新...")
stdin, stdout, stderr = ssh.exec_command(f"cd {VPS_PATH} && bash start.sh update", timeout=30)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
if out: print(out.rstrip())
if err.strip(): print(f"STDERR: {err.rstrip()}")

# 等待启动
time.sleep(3)

# 3. 自动备份VPS数据
print("\n📥 自动备份VPS数据到本地...")
try:
    # 创建备份目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(LOCAL_BACKUP_DIR, f"auto_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)
    
    # 备份重要文件
    sftp = ssh.open_sftp()
    files_to_backup = [
        ("mory.db", "数据库"),
        ("config.json", "配置"),
    ]
    
    for filename, desc in files_to_backup:
        try:
            remote_file = os.path.join(VPS_PATH, filename)
            local_file = os.path.join(backup_path, filename)
            sftp.get(remote_file, local_file)
            size = os.path.getsize(local_file)
            print(f"  ✅ 备份{desc}: {size} 字节")
        except Exception as e:
            print(f"  ⚠️  备份{desc}失败: {e}")
    
    sftp.close()
    
    # 记录备份信息
    with open(os.path.join(backup_path, "backup_info.txt"), "w", encoding="utf-8") as f:
        f.write(f"自动备份时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"备份模式: update (快速更新)\n")
        f.write(f"备份目录: {backup_path}\n")
    
    print(f"  备份保存到: {backup_path}")
    
except Exception as e:
    print(f"  ⚠️  自动备份失败（不影响部署）: {e}")

# 4. 验证
print("\n🔍 验证部署结果...")
verify_cmds = [
    'cd /root/mory && bash start.sh status',
    '''cd /root/mory && python3 -c "
import sqlite3; conn=sqlite3.connect('mory.db')
rows=conn.execute('SELECT * FROM reply_tracking').fetchall()
print(f'reply_tracking: {len(rows)}条记录')
conn.close()"''',
    # 检查新代码是否包含竞态兜底关键字（验证代码已更新）
    'grep -c "竞态" /root/mory/main.py',
    'grep -c "重试机制\\|第.*次尝试" /root/mory/modules/auto_tasks.py',
]

for cmd in verify_cmds:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    print(f"  {out}")

# 清理工作区临时文件
for f in ["vps_check2.py", "vps_check3.py", "vps_cleanup.py", 
          "deep_check.py", "upload_and_run.py", "vps_deep_check.py",
          "vps_deploy.py", "vps_sync_docs.py"]:
    try:
        fp = os.path.join(r"c:\Users\Administrator\WorkBuddy\20260414232245", f)
        if os.path.exists(fp):
            os.remove(fp)
    except:
        pass

ssh.close()
print("\n✅ 部署完成！")
