#!/bin/bash
# 修复1: auto_tasks.py - _send_and_track 不再调用 track_reply

cat > /tmp/fix1.py << 'PYEOF'
import re

with open('/root/mory/modules/auto_tasks.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到并替换 _send_and_track 函数
old_func = '''def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """Send message and auto-track阅后即焚 (user_msg_id=0 = active message, 24h orphan cleanup)"""
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        if sent and chat_id < 0:  # Group chat only
            with rm.locked('db'):
                rm.db.track_reply(sent.message_id, chat_id, user_msg_id)
        return sent
    except Exception as e:
        logger.error(f"Failed: {e}")
        return None'''

new_func = '''def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """Send message (active messages do not need tracking)
    
    Note: Active messages (morning greeting, news, etc.) do not need tracking.
    Only replies to user messages in group chat need tracking.
    """
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        # FIX v21.44: Active messages do not track, only group chat replies track
        return sent
    except Exception as e:
        logger.error(f"Failed: {e}")
        return None'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open('/root/mory/modules/auto_tasks.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: auto_tasks.py fixed')
else:
    print('WARN: Function not found, trying alternative')
    # Try simpler replacement
    if 'rm.db.track_reply' in content and '_send_and_track' in content:
        # Remove the track_reply call
        content = content.replace(
            '''if sent and chat_id < 0:  # group chat only tracking
            with rm.locked('db'):
                rm.db.track_reply(sent.message_id, chat_id, user_msg_id)''',
            '''# FIX v21.44: Active messages do not track'''
        )
        with open('/root/mory/modules/auto_tasks.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: auto_tasks.py fixed (alt method)')
PYEOF
python3 /tmp/fix1.py
