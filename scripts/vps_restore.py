#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory小助理 - VPS数据恢复脚本
功能：将本地备份恢复到VPS服务器
"""

import paramiko
import os
import sys
import io
from datetime import datetime

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

def list_backups():
    """列出可用的备份"""
    if not os.path.exists(LOCAL_BACKUP_DIR):
        print("❌ 备份目录不存在，请先创建备份")
        return []
    
    backups = []
    for item in os.listdir(LOCAL_BACKUP_DIR):
        item_path = os.path.join(LOCAL_BACKUP_DIR, item)
        if os.path.isdir(item_path) and len(item) == 15 and item[8] == '_':  # YYYYMMDD_HHMMSS格式
            # 检查是否是有效备份
            db_file = os.path.join(item_path, "mory.db")
            if os.path.exists(db_file):
                size = os.path.getsize(db_file)
                backups.append({
                    "name": item,
                    "path": item_path,
                    "size": size,
                    "date": f"{item[0:4]}-{item[4:6]}-{item[6:8]} {item[9:11]}:{item[11:13]}:{item[13:15]}"
                })
    
    # 按时间倒序排列
    backups.sort(key=lambda x: x["name"], reverse=True)
    return backups

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

def backup_vps_before_restore(ssh, backup_name):
    """恢复前先备份VPS当前状态"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(LOCAL_BACKUP_DIR, f"before_restore_{timestamp}")
        os.makedirs(backup_dir, exist_ok=True)
        
        print(f"📁 创建恢复前备份: {backup_dir}")
        
        sftp = ssh.open_sftp()
        
        # 备份重要文件
        files_to_backup = ["mory.db", "config.json", "main.py"]
        for filename in files_to_backup:
            try:
                remote_file = os.path.join(VPS_CONFIG['remote_path'], filename)
                local_file = os.path.join(backup_dir, filename)
                sftp.get(remote_file, local_file)
                print(f"  ✅ 备份: {filename}")
            except Exception as e:
                print(f"  ⚠️  备份{filename}失败: {e}")
        
        sftp.close()
        
        # 生成备份说明
        with open(os.path.join(backup_dir, "README.txt"), "w", encoding="utf-8") as f:
            f.write(f"=== 恢复前备份 ===\n")
            f.write(f"备份时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"恢复目标: {backup_name}\n")
            f.write(f"创建原因: 在恢复数据前自动备份当前状态\n")
            f.write(f"\n重要提示：如需回滚，可将此目录文件上传到VPS\n")
        
        return backup_dir
        
    except Exception as e:
        print(f"⚠️  创建恢复前备份失败: {e}")
        return None

def restore_file(ssh, sftp, local_file, remote_file, description):
    """恢复单个文件"""
    try:
        # 检查本地文件是否存在
        if not os.path.exists(local_file):
            print(f"  ⚠️  本地{description}不存在: {local_file}")
            return False
        
        # 上传文件
        sftp.put(local_file, remote_file)
        file_size = os.path.getsize(local_file)
        print(f"  ✅ 恢复{description}: {file_size} 字节")
        return True
        
    except Exception as e:
        print(f"  ❌ 恢复{description}失败: {e}")
        return False

def verify_restoration(ssh, backup_path):
    """验证恢复结果"""
    try:
        print(f"\n🔍 验证恢复结果...")
        
        # 检查数据库是否可访问
        verify_cmd = f"""
        cd {VPS_CONFIG['remote_path']} && python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('mory.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')
    tables = cursor.fetchall()
    print(f'数据库表数量: {len(tables)}')
    
    # 检查主要表
    main_tables = ['reply_tracking', 'users', 'user_levels']
    for table in main_tables:
        try:
            cursor.execute(f'SELECT COUNT(*) FROM {table}')
            count = cursor.fetchone()[0]
            print(f'{table}: {count} 条记录')
        except:
            print(f'{table}: 表不存在或查询失败')
    
    conn.close()
    print('✅ 数据库验证通过')
except Exception as e:
    print(f'❌ 数据库验证失败: {{e}}')
"
        """
        
        stdin, stdout, stderr = ssh.exec_command(verify_cmd, timeout=20)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        
        if out:
            print(out)
        if err:
            print(f"STDERR: {err}")
            
    except Exception as e:
        print(f"⚠️  验证失败: {e}")

def restart_bot(ssh):
    """重启bot进程"""
    try:
        print(f"\n🔄 重启bot进程...")
        
        # 先停止现有进程
        stop_cmd = f"cd {VPS_CONFIG['remote_path']} && bash start.sh stop"
        stdin, stdout, stderr = ssh.exec_command(stop_cmd, timeout=10)
        stdout.read()
        
        # 等待进程停止
        import time
        time.sleep(2)
        
        # 启动新进程
        start_cmd = f"cd {VPS_CONFIG['remote_path']} && bash start.sh start"
        stdin, stdout, stderr = ssh.exec_command(start_cmd, timeout=10)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        
        if out:
            print(f"  启动输出: {out}")
        if err:
            print(f"  启动错误: {err}")
            
        # 检查进程状态
        time.sleep(3)
        status_cmd = f"cd {VPS_CONFIG['remote_path']} && bash start.sh status"
        stdin, stdout, stderr = ssh.exec_command(status_cmd, timeout=10)
        status = stdout.read().decode('utf-8', errors='replace').strip()
        
        print(f"  Bot状态: {status}")
        
    except Exception as e:
        print(f"⚠️  重启bot失败: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("🔄 Mory小助理 - VPS数据恢复工具")
    print("=" * 60)
    
    # 1. 列出可用备份
    backups = list_backups()
    if not backups:
        print("\n❌ 没有找到可用的备份")
        print("请先运行 vps_backup.py 创建备份")
        return False
    
    print(f"\n📂 可用备份 ({len(backups)}个):")
    for i, backup in enumerate(backups):
        size_mb = backup["size"] / 1024 / 1024 if backup["size"] > 0 else 0
        print(f"  {i+1}. {backup['date']} ({size_mb:.2f} MB) - {backup['name']}")
    
    # 2. 选择备份
    try:
        choice = input(f"\n请选择要恢复的备份 (1-{len(backups)}) 或输入 'q' 退出: ")
        if choice.lower() == 'q':
            print("操作取消")
            return False
        
        choice_idx = int(choice) - 1
        if choice_idx < 0 or choice_idx >= len(backups):
            print("❌ 无效选择")
            return False
        
        selected_backup = backups[choice_idx]
        backup_path = selected_backup["path"]
        
        print(f"\n📋 选择的备份:")
        print(f"   名称: {selected_backup['name']}")
        print(f"   时间: {selected_backup['date']}")
        print(f"   大小: {selected_backup['size']} 字节")
        print(f"   路径: {backup_path}")
        
        # 3. 确认操作
        confirm = input(f"\n⚠️  警告：这将覆盖VPS上的现有数据！\n   确认恢复吗？(yes/no): ")
        if confirm.lower() != 'yes':
            print("操作取消")
            return False
            
    except ValueError:
        print("❌ 请输入有效的数字")
        return False
    except Exception as e:
        print(f"❌ 选择备份时出错: {e}")
        return False
    
    # 4. 连接到VPS
    print(f"\n🔗 正在连接到VPS...")
    ssh = connect_to_vps()
    if not ssh:
        return False
    
    try:
        # 5. 恢复前备份当前状态
        print(f"\n📋 执行恢复前备份...")
        before_backup_dir = backup_vps_before_restore(ssh, selected_backup['name'])
        if before_backup_dir:
            print(f"   恢复前备份已保存到: {before_backup_dir}")
        
        # 6. 打开SFTP连接
        sftp = ssh.open_sftp()
        
        # 7. 恢复文件
        print(f"\n📤 开始恢复文件...")
        
        files_to_restore = [
            ("mory.db", "数据库文件"),
            ("config.json", "配置文件"),
            # 注意：main.py 和 requirements.txt 通常不恢复，除非特别需要
            # ("main.py", "主程序"),
            # ("requirements.txt", "依赖列表"),
        ]
        
        success_count = 0
        for filename, description in files_to_restore:
            local_file = os.path.join(backup_path, filename)
            remote_file = os.path.join(VPS_CONFIG['remote_path'], filename)
            
            if restore_file(ssh, sftp, local_file, remote_file, description):
                success_count += 1
        
        # 8. 关闭连接
        sftp.close()
        
        # 9. 验证恢复
        verify_restoration(ssh, backup_path)
        
        # 10. 重启bot（可选）
        restart_choice = input(f"\n🔄 是否重启bot以应用恢复的数据？(yes/no): ")
        if restart_choice.lower() == 'yes':
            restart_bot(ssh)
        else:
            print("   跳过重启，请手动重启bot以应用更改")
        
        # 11. 生成恢复报告
        report_file = os.path.join(backup_path, "restore_report.txt")
        with open(report_file, "a", encoding="utf-8") as f:
            f.write(f"\n=== 数据恢复记录 ===\n")
            f.write(f"恢复时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"恢复来源: {selected_backup['name']}\n")
            f.write(f"恢复前备份: {before_backup_dir if before_backup_dir else '无'}\n")
            f.write(f"恢复文件: {success_count}/{len(files_to_restore)} 成功\n")
            f.write(f"重启bot: {'是' if restart_choice.lower() == 'yes' else '否'}\n")
        
        print(f"\n✅ 恢复完成!")
        print(f"   恢复来源: {selected_backup['name']}")
        print(f"   成功文件: {success_count}/{len(files_to_restore)}")
        
        if before_backup_dir:
            print(f"   恢复前备份: {before_backup_dir}")
            print(f"   如需回滚，请使用恢复前备份")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 恢复过程中出错: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        ssh.close()

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    success = main()
    if not success:
        print("\n❌ 恢复失败")
        sys.exit(1)
    print("\n💡 恢复操作已完成")
    print("   请检查bot运行状态，确保数据正确恢复")