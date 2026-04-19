"""阅后即焚修复补丁 v1.0

问题分析：
1. reply_tracking表为空，因为主动消息(来自auto_tasks)调用track_reply时user_msg_id=0被拒绝
2. 日志级别是INFO，DEBUG日志不输出
3. _tracked_reply中的logger.debug不输出

修复：
1. auto_tasks.py: _send_and_track不调用track_reply(主动消息不需要追踪)
2. main.py: _tracked_reply添加更多INFO日志确认被调用
3. database.py: track_reply增加日志确认被调用
"""
import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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

# 1. 修复 auto_tasks.py - _send_and_track 不再调用 track_reply
print("=== 修复1: auto_tasks.py _send_and_track ===")
fix_auto_tasks = """cat > /tmp/fix_auto_tasks.py << 'PYEOF'
import re

with open('/root/mory/modules/auto_tasks.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到并替换 _send_and_track 函数
old_func = '''def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息并自动追踪阅后即焚（user_msg_id=0 表示主动消息，24h孤儿清理）"""
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        if sent and chat_id < 0:  # 群聊才追踪
            with rm.locked('db'):
                rm.db.track_reply(sent.message_id, chat_id, user_msg_id)
        return sent
    except Exception as e:
        logger.error(f"发送+追踪失败：{e}")
        return None'''

new_func = '''def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息（主动消息不追踪，只有回复才追踪）
    
    注意：主动消息（如早安问候、新闻播报）不需要阅后即焚追踪，
    因为它们没有对应的"原消息"需要探测是否被删除。
    追踪只用于群聊中回复用户消息的场景。
    """
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        # 【修复v21.44】主动消息不追踪，避免reply_tracking表充满无效记录
        # 追踪功能仅用于 bot.reply_to() 的群聊回复场景（由monkey-patch处理）
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open('/root/mory/modules/auto_tasks.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('✅ auto_tasks.py 修复成功')
else:
    print('⚠️ 未找到目标函数，可能已经修复或代码不同')
    # 尝试简单的替换
    if '_send_and_track' in content and 'track_reply' in content:
        print('检测到函数存在但内容不同')
PYEOF
python3 /tmp/fix_auto_tasks.py"""

result = run(fix_auto_tasks)
print(result)

# 2. 修复 main.py - _tracked_reply 添加更多INFO日志
print("\n=== 修复2: main.py _tracked_reply 日志 ===")
fix_main = """cat > /tmp/fix_main.py << 'PYEOF'
with open('/root/mory/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换DEBUG日志为INFO
old_debug = '''logger.debug(f"📌 tracked_reply调用: chat={cid}, sent={sent is not None}, "
                 f"sent.message_id={getattr(sent, 'message_id', 'N/A')}")'''

new_info = '''logger.info(f"📌 【阅后即焚】_tracked_reply被调用: chat={cid}, "
                 f"sent={sent is not None}, bot_msg_id={getattr(sent, 'message_id', 'N/A')}, "
                 f"user_msg_id={user_msg_id}")'''

if old_debug in content:
    content = content.replace(old_debug, new_info)
    with open('/root/mory/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('✅ main.py 日志修复成功')
else:
    print('⚠️ 未找到DEBUG日志，可能已修复')
PYEOF
python3 /tmp/fix_main.py"""

result = run(fix_main)
print(result)

# 3. 验证修复
print("\n=== 验证修复 ===")
print(run("grep -A5 '_send_and_track' /root/mory/modules/auto_tasks.py | head -10"))
print(run("grep 'tracked_reply被调用' /root/mory/main.py | head -3"))

# 4. 重启Bot
print("\n=== 重启Bot ===")
print(run("cd /root/mory && bash start.sh restart 2>&1 | tail -10"))
"""
