# -*- coding: utf-8 -*-
"""部署debug版main.py到VPS并重启Bot"""
import paramiko
import os
import io

def main():
    env = {}
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()

    host = env.get('VPS_HOST', '43.159.168.175')
    port = int(env.get('VPS_SSH_PORT', 22))
    user = env.get('VPS_SSH_USER', 'root')
    pwd = env.get('VPS_SSH_PASS', '')

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=pwd, timeout=15)
    sftp = ssh.open_sftp()

    # Read main.py
    base_dir = r'c:\Users\Administrator\Desktop\mory小助理'
    main_path = os.path.join(base_dir, 'main.py')
    print("Reading main.py from: %s" % main_path[:50])
    
    with open(main_path, 'rb') as f:
        content_bytes = f.read()
    
    # Convert CRLF -> LF
    clean_str = content_bytes.decode('utf-8').replace('\r\n', '\n')
    clean_bytes = clean_str.encode('utf-8')

    try:
        print("Uploading (%d bytes)..." % len(clean_bytes))
        # Use BytesIO to avoid Windows path length issue
        bio = io.BytesIO(clean_bytes)
        remote_path = '/tmp/main_debug_new.py'
        sftp.putfo(bio, remote_path)
        print("Upload OK")
        
        # Deploy
        print("Deploying...")
        stdin, stdout, stderr = ssh.exec_command(
            'cp /root/mory/main.py /root/mory/main.py.backup_debug && '
            'cp /tmp/main_debug_new.py /root/mory/main.py && '
            'echo "REPLACE_OK"'
        )
        out = stdout.read().decode('utf-8', errors='replace').strip()
        safe_out = out.encode('ascii', errors='replace').decode('ascii')
        print("Replace result: %s" % safe_out)
        
        # Restart
        print("Restarting bot...")
        stdin, stdout, stderr = ssh.exec_command(
            'pkill -9 -f "python3 main.py" 2>/dev/null; sleep 2;'
            'cd /root/mory && nohup python3 main.py > mory.log 2>&1 &'
            'sleep 3; ps aux | grep "python3 main.py" | grep -v grep | head -1'
        )
        out = stdout.read().decode('utf-8', errors='replace')
        safe_out = out.encode('ascii', errors='replace').decode('ascii')
        print("Restart: %s" % safe_out.strip()[:200])
        
    except Exception as e:
        print("ERROR: %s" % e)
        return
    finally:
        sftp.close()

    # Check log
    import time
    time.sleep(3)
    
    stdin, stdout, stderr = ssh.exec_command(
        'tail -20 /root/mory/mory.log 2>/dev/null || echo "NO_LOG"'
    )
    out = stdout.read().decode('utf-8', errors='replace')
    safe = out.encode('ascii', errors='replace').decode('ascii')
    print("\n--- Bot Log ---")
    print(safe[-1200:])
    
    ssh.close()
    print("\n>>> DONE! Send @MoryMateBot test NOW!")

if __name__ == '__main__':
    main()
