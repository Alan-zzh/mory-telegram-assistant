"""Fix auto_tasks.py - remove track_reply from _send_and_track"""
import paramiko

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'

def run(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    _, stdout, _ = ssh.exec_command(cmd, timeout=30)
    result = stdout.read().decode('utf-8', errors='replace').strip()
    ssh.close()
    return result

# Fix auto_tasks.py
fix_cmd = 'python3 /dev/stdin << \'ENDSCRIPT\'\nimport re\nfilepath = \'/root/mory/modules/auto_tasks.py\'\nwith open(filepath, \'r\', encoding=\'utf-8\') as f:\n    content = f.read()\n\nold_block = "        if sent and chat_id < 0:  # 群聊才追踪\\n            with rm.locked(\'db\'):\\n                rm.db.track_reply(sent.message_id, chat_id, user_msg_id)"\nnew_block = "        # FIX v21.44: Active messages dont track, only group chat replies track\\n        pass"\n\nif old_block in content:\n    content = content.replace(old_block, new_block)\n    with open(filepath, \'w\', encoding=\'utf-8\') as f:\n        f.write(content)\n    print(\'OK: auto_tasks.py fixed\')\nelse:\n    print(\'WARN: Target not found, trying alt\')\n    if \'rm.db.track_reply\' in content:\n        lines = content.split(\'\\n\')\n        new_lines = []\n        skip = 0\n        for line in lines:\n            if skip > 0:\n                skip -= 1\n                continue\n            if \'rm.db.track_reply\' in line:\n                skip = 2\n                new_lines.append(\'            # FIX v21.44: removed track_reply\')\n                continue\n            new_lines.append(line)\n        content = \'\\n\'.join(new_lines)\n        with open(filepath, \'w\', encoding=\'utf-8\') as f:\n            f.write(content)\n        print(\'OK: alt fix applied\')\nENDSCRIPT'

print("=== Fixing auto_tasks.py ===")
result = run(fix_cmd)
print(result)

# Fix main.py DEBUG->INFO
fix_main = 'python3 /dev/stdin << \'ENDSCRIPT\'\nfilepath = \'/root/mory/main.py\'\nwith open(filepath, \'r\', encoding=\'utf-8\') as f:\n    content = f.read()\nold = \'logger.debug(f"📌 tracked_reply调用: \'\nnew = \'logger.info(f"📌 [阅后即焚]_tracked_reply被调用: \'\nif old in content:\n    content = content.replace(old, new)\n    with open(filepath, \'w\', encoding=\'utf-8\') as f:\n        f.write(content)\n    print(\'OK: main.py DEBUG->INFO\')\nelse:\n    print(\'WARN: main.py already fixed\')\nENDSCRIPT'

print("\n=== Fixing main.py ===")
result = run(fix_main)
print(result)

# Restart bot
print("\n=== Restarting Bot ===")
result = run('cd /root/mory && bash start.sh restart 2>&1 | tail -10')
print(result)

# Verify
print("\n=== Verification ===")
result = run('grep -c "track_reply" /root/mory/modules/auto_tasks.py')
print("track_reply count in auto_tasks.py:", result)
result = run('grep "_tracked_reply被调用" /root/mory/main.py | head -1')
print("main.py tracking log:", result)
