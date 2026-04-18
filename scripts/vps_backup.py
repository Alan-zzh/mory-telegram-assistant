#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory小助理 - VPS数据备份脚本
功能：从VPS下载重要数据文件到本地备份
"""

import paramiko
import os
import sys
import time
import io
from datetime import datetime
import shutil

# 配置信息（统一从 core/vps_config 读取）
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH

VPS_CONFIG = {
    "host": VPS_HOST,
    "port": VPS_PORT,
    "user": VPS_USER,
    "pass": VPS_PASS,
    "timeout": 15,
    "remote_path": VPS_PATH,
}

_LOCAL_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_PROJECT_ROOT = os.path.dirname(_LOCAL_SCRIPT_DIR)
LOCAL_BASE = _LOCAL_PROJECT_ROOT
LOCAL_BACKUP_DIR = os.path.join(LOCAL_BASE, "backups")

# 要备份的文件列表
FILES_TO_BACKUP = [
    ("mory.db", "数据库文件"),
    ("config.json", "配置文件"),
    ("mory.log", "运行日志"),
    ("main.py", "主程序备份"),
    ("requirements.txt", "依赖列表"),
]

# 可选备份的目录
DIRS_TO_BACKUP = [
    ("core", "核心模块"),
    ("modules", "功能模块"),
]

def create_backup_dir():
    """创建备份目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(LOCAL_BACKUP_DIR, timestamp)
    
    # 创建主备份目录
    os.makedirs(backup_path, exist_ok=True)
    
    # 创建latest软链接（Windows上需要特殊处理）
    latest_path = os.path.join(LOCAL_BACKUP_DIR, "latest")
    try:
        if os.path.exists(latest_path) and os.path.islink(latest_path):
            os.unlink(latest_path)
        # Windows不支持软链接，改为复制或创建快捷方式
        with open(os.path.join(LOCAL_BACKUP_DIR, "LATEST.txt"), "w", encoding="utf-8") as f:
            f.write(timestamp)
    except Exception as e:
        print(f"⚠️  创建latest标记失败: {e}")
    
    return backup_path, timestamp

def connect_to_vps():
    """连接到VPS服务器"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=VPS_CONFIG["host"],
            port=VPS_CONFIG["port"],
            username=VPS_CONFIG["user"],
            password=VPS_CONFIG["pass"],
            timeout=VPS_CONFIG["timeout"]
        )
        return ssh
    except Exception as e:
        print(f"❌ 连接VPS失败: {e}")
        return None

def backup_file(ssh, sftp, remote_path, local_path, description):
    """备份单个文件"""
    try:
        # 检查远程文件是否存在
        try:
            sftp.stat(remote_path)
        except FileNotFoundError:
            print(f"  ⚠️  {description}不存在: {remote_path}")
            return False
        
        # 下载文件
        sftp.get(remote_path, local_path)
        file_size = os.path.getsize(local_path)
        print(f"  ✅ {description}: {file_size} 字节")
        return True
        
    except Exception as e:
        print(f"  ❌ 备份{description}失败: {e}")
        return False

def backup_database_info(ssh, backup_path):
    """备份数据库信息（表结构和记录数）"""
    try:
        # 执行SQL查询获取数据库信息
        db_info_cmd = f"""
        cd {VPS_CONFIG['remote_path']} && python3 -c "
import sqlite3
conn = sqlite3.connect('mory.db')
cursor = conn.cursor()

# 获取所有表
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")
tables = cursor.fetchall()

info = []
info.append('=== 数据库信息备份 ===')
info.append(f'备份时间: {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}')

for table in tables:
    table_name = table[0]
    cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
    count = cursor.fetchone()[0]
    info.append(f'{table_name}: {count} 条记录')

conn.close()

with open('db_info.txt', 'w', encoding='utf-8') as f:
    f.write('\\n'.join(info))
print('数据库信息已保存')
"
        """
        
        stdin, stdout, stderr = ssh.exec_command(db_info_cmd, timeout=20)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        
        if out:
            print(f"  ℹ️  {out}")
        
        # 下载数据库信息文件
        sftp = ssh.open_sftp()
        remote_info = os.path.join(VPS_CONFIG['remote_path'], "db_info.txt")
        local_info = os.path.join(backup_path, "database_info.txt")
        
        try:
            sftp.get(remote_info, local_info)
            # 删除远程临时文件
            sftp.remove(remote_info)
            print(f"  ✅ 数据库信息已备份")
        except:
            pass
        finally:
            sftp.close()
            
    except Exception as e:
        print(f"  ⚠️  获取数据库信息失败: {e}")

def cleanup_old_backups(max_days=7):
    """清理旧的备份，保留最近max_days天的备份"""
    try:
        if not os.path.exists(LOCAL_BACKUP_DIR):
            return
        
        backup_dirs = []
        for item in os.listdir(LOCAL_BACKUP_DIR):
            item_path = os.path.join(LOCAL_BACKUP_DIR, item)
            if os.path.isdir(item_path) and len(item) == 15 and item[8] == '_':  # YYYYMMDD_HHMMSS格式
                backup_dirs.append((item, item_path))
        
        if len(backup_dirs) <= max_days:
            return
        
        # 按时间排序，删除最旧的
        backup_dirs.sort(key=lambda x: x[0], reverse=True)
        to_delete = backup_dirs[max_days:]
        
        for name, path in to_delete:
            try:
                shutil.rmtree(path)
                print(f"  🗑️  清理旧备份: {name}")
            except Exception as e:
                print(f"  ⚠️  清理备份失败 {name}: {e}")
                
    except Exception as e:
        print(f"⚠️  备份清理失败: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("🔐 Mory小助理 - VPS数据备份工具")
    print("=" * 60)
    
    # 1. 创建备份目录
    backup_path, timestamp = create_backup_dir()
    print(f"\n📁 创建备份目录: {backup_path}")
    
    # 2. 连接到VPS
    print("\n🔗 正在连接到VPS...")
    ssh = connect_to_vps()
    if not ssh:
        return False
    
    try:
        # 3. 打开SFTP连接
        sftp = ssh.open_sftp()
        
        # 4. 备份文件
        print(f"\n📥 开始备份文件...")
        success_count = 0
        total_count = len(FILES_TO_BACKUP)
        
        for filename, description in FILES_TO_BACKUP:
            remote_file = os.path.join(VPS_CONFIG['remote_path'], filename)
            local_file = os.path.join(backup_path, filename)
            
            if backup_file(ssh, sftp, remote_file, local_file, description):
                success_count += 1
        
        # 5. 备份数据库信息
        print(f"\n📊 备份数据库信息...")
        backup_database_info(ssh, backup_path)
        
        # 6. 关闭连接
        sftp.close()
        
        # 7. 生成备份报告
        report_file = os.path.join(backup_path, "backup_report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"=== Mory小助理备份报告 ===\n")
            f.write(f"备份时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"备份目录: {backup_path}\n")
            f.write(f"VPS地址: {VPS_CONFIG['host']}\n")
            f.write(f"文件备份: {success_count}/{total_count} 成功\n")
            f.write(f"\n已备份文件:\n")
            for filename, description in FILES_TO_BACKUP:
                local_file = os.path.join(backup_path, filename)
                if os.path.exists(local_file):
                    size = os.path.getsize(local_file)
                    f.write(f"  - {filename} ({description}): {size} 字节\n")
        
        print(f"\n📋 生成备份报告: {report_file}")
        
        # 8. 清理旧备份
        print(f"\n🧹 清理旧备份（保留最近7天）...")
        cleanup_old_backups()
        
        # 9. 显示备份大小
        total_size = 0
        for root, dirs, files in os.walk(backup_path):
            for file in files:
                filepath = os.path.join(root, file)
                total_size += os.path.getsize(filepath)
        
        print(f"\n✅ 备份完成!")
        print(f"   备份目录: {backup_path}")
        print(f"   备份大小: {total_size/1024:.2f} KB")
        print(f"   成功文件: {success_count}/{total_count}")
        print(f"   备份时间: {timestamp}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 备份过程中出错: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        ssh.close()

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    success = main()
    if not success:
        print("\n⚠️ 备份失败，请检查网络连接和VPS状态")
        sys.exit(1)
    print("\n💡 提示：备份文件保存在 backups/ 目录下")
    print("   如需恢复，请运行 restore_to_vps.py 脚本")