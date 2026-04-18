"""核对阅后即焚功能 - 使用paramiko"""
import paramiko
import sys
import re
import json

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

def safe_print(s):
    if s:
        s = re.sub(r'[\U00010000-\U0010ffff]', '', s)
        print(s)

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'
VPS_PATH = '/root/mory'

def run_ssh(cmd):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        result = stdout.read().decode('utf-8', errors='replace').strip()
        ssh.close()
        return result
    except Exception as e:
        return f"连接失败: {e}"

# 1. 检查reply_tracking表
safe_print('\n=== 1. reply_tracking 表状态 ===')
result = run_ssh(f'cd {VPS_PATH} && python3 -c "import sqlite3; c=sqlite3.connect(\"mory.db\").cursor(); print(\"总记录数:\", c.execute(\"SELECT COUNT(*) FROM reply_tracking\").fetchone()[0]); rows=c.execute(\"SELECT bot_msg_id, chat_id, user_msg_id, ts, replied FROM reply_tracking ORDER BY ts DESC LIMIT 20\").fetchall(); [print(f\'  bot={{r[0]}} chat={{r[1]}} user={{r[2]}} ts={{r[3]}} replied={{r[4]}}\') for r in rows]"')
safe_print(result or '无记录')

# 2. 检查config.json关键配置
safe_print('\n=== 2. config.json 关键配置 ===')
result = run_ssh(f'python3 -c "import json; c=json.load(open(\'{VPS_PATH}/config.json\')); print(\'GROUP_ID:\', c.get(\'GROUP_ID\',\'未设\')); print(\'ADMIN_ID:\', c.get(\'ADMIN_ID\',\'未设\'))"')
safe_print(result)

# 3. 搜索追踪相关日志
safe_print('\n=== 3. 追踪相关日志 ===')
result = run_ssh(f'grep -E "阅后即焚|tracked_reply|track_reply|孤儿清理|竞态|原消息" {VPS_PATH}/mory.log 2>/dev/null | tail -30')
safe_print(result or '无相关日志')

# 4. 检查孤儿清理逻辑
safe_print('\n=== 4. 孤儿清理检查 ===')
result = run_ssh(f'grep -A5 "get_orphan_messages" {VPS_PATH}/modules/auto_tasks.py | head -15')
safe_print(result)

# 5. 检查原消息探测逻辑
safe_print('\n=== 5. 原消息探测检查 ===')
result = run_ssh(f'grep -A10 "get_unconfirmed_messages" {VPS_PATH}/modules/auto_tasks.py | head -15')
safe_print(result)

# 6. 检查追踪调用位置
safe_print('\n=== 6. 追踪调用位置(main.py) ===')
result = run_ssh(f'grep -n "track_reply\|_tracked_reply" {VPS_PATH}/main.py | head -20')
safe_print(result)

# 7. 检查是否monkey-patch生效
safe_print('\n=== 7. monkey-patch检查 ===')
result = run_ssh(f'grep -n "bot.reply_to = _tracked_reply" {VPS_PATH}/main.py')
safe_print(result if result else '未找到monkey-patch!')

# 8. 检查群聊回复handler
safe_print('\n=== 8. 群聊消息处理 ===')
result = run_ssh(f'grep -n "group_message\|chat_member\|on_message" {VPS_PATH}/main.py | head -10')
safe_print(result)

# 9. 检查是否有群聊消息被处理
safe_print('\n=== 9. 最近消息处理日志 ===')
result = run_ssh(f'tail -100 {VPS_PATH}/mory.log 2>/dev/null | grep -E "群|chat|group|message" | tail -20')
safe_print(result or '无')

# 10. 检查进程
safe_print('\n=== 10. Bot进程状态 ===')
result = run_ssh(f'pgrep -f "main.py" && ps aux | grep main.py | grep -v grep || echo "进程未运行"')
safe_print(result)

safe_print('\n诊断完成!')
