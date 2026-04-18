#!/usr/bin/env python3
"""
直接自动部署到VPS - 避免所有转义问题
"""
import paramiko
import time
import os
import sys
import json

def main():
    print("=== Mory Bot 自动部署 ===")
    
    # VPS 配置（从统一配置模块读取）
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH
    host, port, username, password = VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS
    
    # 本地目录（动态推导，不再硬编码）
    local_base = os.path.dirname(os.path.abspath(__file__))
    
    # 文件列表（与 vps_deploy.py 保持一致）
    files = [
        ("main.py", "/root/mory/main.py"),
        ("config.json", "/root/mory/config.json"),
        ("start.sh", "/root/mory/start.sh"),
        ("CHANGELOG.md", "/root/mory/CHANGELOG.md"),
        ("README.md", "/root/mory/README.md"),
        ("core/optimizer.py", "/root/mory/core/optimizer.py"),
        ("core/vps_config.py", "/root/mory/core/vps_config.py"),
        ("core/ai_engine.py", "/root/mory/core/ai_engine.py"),
        ("core/database.py", "/root/mory/core/database.py"),
        ("modules/optimizer_admin.py", "/root/mory/modules/optimizer_admin.py"),
        ("modules/auto_tasks.py", "/root/mory/modules/auto_tasks.py"),
        ("modules/admin_cmds.py", "/root/mory/modules/admin_cmds.py"),
        ("modules/group_mgr.py", "/root/mory/modules/group_mgr.py"),
        ("modules/content.py", "/root/mory/modules/content.py")
    ]
    
    try:
        # 连接SSH
        print(f"连接 {host}:{port}...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port, username, password, timeout=15)
        print("[OK] SSH连接成功")
        
        # 0. 备份并合并VPS配置（防止配置丢失）
        print("\n0. 备份并合并VPS配置...")
        sftp = ssh.open_sftp()
        remote_config_path = "/root/mory/config.json"
        local_config_path = os.path.join(local_base, "config.json")
        
        try:
            # 拉取远程配置
            with sftp.open(remote_config_path, 'r') as remote_file:
                remote_content = remote_file.read().decode('utf-8')
                vps_config = json.loads(remote_content)
                print(f"  已读取远程配置，版本: {vps_config.get('_CONFIG_VERSION', '未知')}")
        except Exception as e:
            print(f"  警告: 无法读取远程配置，将使用本地配置 ({e})")
            vps_config = {}
        
        # 读取本地配置
        try:
            with open(local_config_path, 'r', encoding='utf-8') as local_file:
                local_config = json.load(local_file)
        except Exception as e:
            print(f"  错误: 无法读取本地配置 ({e})")
            local_config = {}
        
        # 深度合并配置（以VPS配置优先，保留本地新增项）
        def deep_merge(vps, local):
            merged = local.copy()
            for key, value in vps.items():
                if key in merged:
                    if isinstance(value, dict) and isinstance(merged[key], dict):
                        merged[key] = deep_merge(value, merged[key])
                    else:
                        merged[key] = value  # VPS配置优先
                else:
                    merged[key] = value
            return merged
        
        if vps_config:
            merged_config = deep_merge(vps_config, local_config)
            # 特殊处理：保留本地配置版本信息（以本地为准）
            if '_CONFIG_VERSION' in local_config:
                merged_config['_CONFIG_VERSION'] = local_config['_CONFIG_VERSION']
            if '_CONFIG_UPDATED' in local_config:
                merged_config['_CONFIG_UPDATED'] = local_config['_CONFIG_UPDATED']
            if '_SAFETY_NOTE' in local_config:
                merged_config['_SAFETY_NOTE'] = local_config['_SAFETY_NOTE']
            
            # 写回本地配置文件
            with open(local_config_path, 'w', encoding='utf-8') as f:
                json.dump(merged_config, f, ensure_ascii=False, indent=2)
            print("  配置合并完成，已更新本地config.json")
        else:
            print("  未读取到远程配置，跳过合并")
        
        sftp.close()
        
        # 1. 停止现有进程
        print("\n1. 停止现有bot进程...")
        stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'python3.*main.py' | grep -v grep")
        processes = stdout.read().decode('gbk', errors='replace').strip()
        if processes:
            lines = [l for l in processes.split('\n') if l.strip()]
            print(f"发现{len(lines)}个进程:")
            for line in lines:
                print(f"  - {line[:80]}")
            stdin, stdout, stderr = ssh.exec_command("pkill -9 -f 'main.py'")
            time.sleep(2)
            print("[OK] 已停止所有bot进程")
        else:
            print("[OK] 没有运行中的bot进程")
        
        # 2. 上传文件
        print("\n2. 上传文件...")
        sftp = ssh.open_sftp()
        
        for local_rel, remote_path in files:
            local_path = os.path.join(local_base, local_rel.replace("/", os.sep))
            try:
                sftp.put(local_path, remote_path)
                print(f"[OK] {local_rel}")
            except Exception as e:
                print(f"[FAIL] {local_rel}: {e}")
        
        sftp.close()
        
        # 3. 验证版本
        print("\n3. 验证版本...")
        stdin, stdout, stderr = ssh.exec_command("grep -o 'v21\\.\\d\\+' /root/mory/main.py | head -1")
        version = stdout.read().decode('utf-8', errors='replace').strip()
        print(f"主程序版本: {version}")
        
        stdin, stdout, stderr = ssh.exec_command("grep '_CONFIG_VERSION' /root/mory/config.json")
        config_bytes = stdout.read()
        try:
            config_ver = config_bytes.decode('utf-8', errors='replace').strip()
        except:
            config_ver = config_bytes.decode('gbk', errors='replace').strip()
        print(f"配置文件版本: {config_ver[:50]}...")
        
        # 4. 启动bot
        print("\n4. 启动bot...")
        stdin, stdout, stderr = ssh.exec_command("cd /root/mory && nohup python3 main.py >> mory.log 2>&1 &")
        time.sleep(3)
        
        # 5. 检查启动状态
        print("\n5. 检查启动状态...")
        stdin, stdout, stderr = ssh.exec_command("tail -10 /root/mory/mory.log")
        log_bytes = stdout.read()
        try:
            log = log_bytes.decode('utf-8', errors='replace').strip()
        except:
            log = log_bytes.decode('gbk', errors='replace').strip()
        if log:
            print("最近日志:")
            for line in log.split('\n'):
                safe_line = line.encode('gbk', errors='replace').decode('gbk', errors='replace')
                print(f"  {safe_line[:80]}")
        
        stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'python3.*main.py' | grep -v grep | wc -l")
        count = stdout.read().decode().strip()
        print(f"运行进程数: {count}")
        
        # 6. 检查是否有409冲突
        stdin, stdout, stderr = ssh.exec_command("tail -20 /root/mory/mory.log | grep -c '409'")
        conflicts = stdout.read().decode().strip()
        if conflicts != '0':
            print(f"警告: 检测到{conflicts}个409冲突")
        
        ssh.close()
        print("\n[SUCCESS] 自动部署完成!")
        print(f"Bot版本: {version}")
        print("检查日志: ssh root@43.159.168.175 'tail -f /root/mory/mory.log'")
        
    except paramiko.AuthenticationException:
        print("[FAIL] SSH认证失败，检查密码")
    except paramiko.SSHException as e:
        print(f"[FAIL] SSH连接错误: {e}")
    except Exception as e:
        print(f"[FAIL] 部署失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()