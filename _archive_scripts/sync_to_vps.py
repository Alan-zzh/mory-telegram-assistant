# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""快速同步修复后的文件到VPS"""
import paramiko
import os

# VPS配置
HOST = "43.159.168.175"
PORT = 22
USER = "root"
PASS = "..."

LOCAL_DIR = r"c:\Users\Administrator\Desktop\mory小助理"
REMOTE_DIR = "/root/mory"

# 要同步的文件
FILES = [
    "modules/auto_tasks.py",
    "main.py"
]

def main():
    print("=" * 50)
    print("同步修复到VPS")
    print("=" * 50)
    
    # 读取本地文件内容
    for f in FILES:
        local_path = os.path.join(LOCAL_DIR, f)
        if os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8') as file:
                content = file.read()
            print(f"✅ 读取: {f}")
            
            # 上传到VPS
            try:
                transport = paramiko.Transport((HOST, PORT))
                transport.connect(username=USER, password=PASS)
                sftp = paramiko.SFTPClient.from_transport(transport)
                
                remote_path = os.path.join(REMOTE_DIR, f)
                sftp.putfo(open(local_path, 'rb'), remote_path)
                print(f"   ✅ 上传成功: {remote_path}")
                
                sftp.close()
                transport.close()
            except Exception as e:
                print(f"   ❌ 上传失败: {e}")
        else:
            print(f"❌ 文件不存在: {local_path}")
    
    print("\n" + "=" * 50)
    print("同步完成！")
    print("=" * 50)

if __name__ == "__main__":
    main()
