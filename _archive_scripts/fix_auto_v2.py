# -*- coding: utf-8 -*-
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

# Fix auto_tasks.py using sed-like replacement
fix_cmd = '''python3 << 'PYEOF'
import re

filepath = '/root/mory/modules/auto_tasks.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the _send_and_track function
# The problematic code is:
#     if sent and chat_id < 0:  # 群聊才追踪
#         with rm.locked('db'):
#             rm.db.track_reply(sent.message_id, chat_id, user_msg_id)

old_block = '''        if sent and chat_id < 0:  # 群聊才追踪
            with rm.locked('db'):
                rm.db.track_reply(sent.message_id, chat_id, user_msg_id)'''

new_block = '''        # 【修复v21.44】主动消息不需要阅后即焚追踪，只有群聊回复才追踪
        # 追踪功能由 main.py 的 monkey-patch 处理
        # 主动消息（如早安问候、新闻播报）没有"原消息"，不需要探测删除'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: auto_tasks.py fixed')
    print('Removed track_reply call from _send_and_track')
else:
    print('WARN: Target block not found')
    # Try alternative
    if 'rm.db.track_reply' in content and 'def _send_and_track' in content:
        print('Trying alternative method...')
        # Simple replacement
        lines = content.split('\n')
        new_lines = []
        skip_next = 0
        for i, line in enumerate(lines):
            if skip_next > 0:
                skip_next -= 1
                continue
            if 'rm.db.track_reply' in line:
                # Skip this and next 2 lines (with statement)
                skip_next = 2
                continue
            if '# 群聊才追踪' in line:
                # Replace with comment
                new_lines.append('        # 【修复v21.44】主动消息不需要阅后即焚追踪')
                continue
            new_lines.append(line)
        content = '\n'.join(new_lines)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: auto_tasks.py fixed (alt method)')
PYEOF'''

print("=== Fixing auto_tasks.py ===")
result = run(fix_cmd)
print(result)

# Fix main.py - change DEBUG to INFO
fix_main_cmd = '''python3 << 'PYEOF'
filepath = '/root/mory/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace logger.debug
old = 'logger.debug(f"📌 tracked_reply调用:'
new = 'logger.info(f"📌 【阅后即焚】_tracked_reply被调用:'

if old in content:
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: main.py DEBUG -> INFO')
else:
    print('WARN: main.py already fixed or pattern not found')
PYEOF'''

print("\n=== Fixing main.py ===")
result = run(fix_main_cmd)
print(result)

# Restart bot
print("\n=== Restarting Bot ===")
restart_cmd = 'cd /root/mory && bash start.sh restart 2>&1 | tail -15'
result = run(restart_cmd)
print(result)

# Verify
print("\n=== Verification ===")
verify_cmd = '''grep -A3 "主动消息" /root/mory/modules/auto_tasks.py | head -5'''
result = run(verify_cmd)
print(result)
