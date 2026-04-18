"""深度检查消息处理 - 寻找user_msg_id=0的根因"""
import paramiko
import sys
import re

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

def safe_print(s):
    if s:
        s = re.sub(r'[\U00010000-\U0010ffff]', '', s)
        print(s)

VPS_HOST = '43.159.168.175'
VPS_USER = 'root'
VPS_PASS = '066Sh9$YhG#Let'
VPS_PATH = '/root/mory'

def run_ssh(cmd, timeout=30):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        result = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        ssh.close()
        return result + ("\n[ERR] " + err if err else "")
    except Exception as e:
        return f"连接失败: {e}"

# 1. 搜索最近的群聊回复日志
safe_print('\n=== 1. 最近群聊消息处理 ===')
result = run_ssh(f'tail -500 {VPS_PATH}/mory.log 2>/dev/null | grep -E "回复|should_reply|m.reply_to|bot.reply_to|💬" | tail -30')
safe_print(result or '无')

# 2. 搜索所有track_reply调用（包括成功和失败的）
safe_print('\n=== 2. 所有track_reply调用记录 ===')
result = run_ssh(f'grep -E "track_reply|tracked_reply" {VPS_PATH}/mory.log 2>/dev/null | tail -50')
safe_print(result or '无')

# 3. 搜索 _tracked_reply 的调用（注意logger.debug级别）
safe_print('\n=== 3. _tracked_reply 调用 ===')
result = run_ssh(f'grep -E "tracked_reply调用|阅后即焚追踪成功" {VPS_PATH}/mory.log 2>/dev/null | tail -30')
safe_print(result or '无 (可能日志级别问题)')

# 4. 检查日志配置
safe_print('\n=== 4. 日志级别检查 ===')
result = run_ssh(f'grep -E "getLogger|DEBUG|INFO|logging" {VPS_PATH}/main.py | head -20')
safe_print(result)

# 5. 检查当前日志文件大小和最后修改时间
safe_print('\n=== 5. 日志文件状态 ===')
result = run_ssh(f'ls -la {VPS_PATH}/mory.log* 2>/dev/null; wc -l {VPS_PATH}/mory.log 2>/dev/null')
safe_print(result)

# 6. 搜索所有涉及群聊ID -1003004701688的日志
safe_print('\n=== 6. 主群(-1003004701688)相关日志 ===')
result = run_ssh(f'grep -E "1003004701688|-1003004701688" {VPS_PATH}/mory.log 2>/dev/null | tail -30')
safe_print(result or '无')

# 7. 搜索最近的AI回复
safe_print('\n=== 7. 最近AI回复 ===')
result = run_ssh(f'tail -200 {VPS_PATH}/mory.log 2>/dev/null | grep -E "AI|ask|mode=" | tail -20')
safe_print(result or '无')

# 8. 检查VPS上代码版本
safe_print('\n=== 8. 代码版本检查 ===')
result = run_ssh(f'head -10 {VPS_PATH}/main.py')
safe_print(result)

# 9. 检查 auto_tasks.py 的 _send_and_track 函数
safe_print('\n=== 9. auto_tasks.py _send_and_track ===')
result = run_ssh(f'grep -A15 "def _send_and_track" {VPS_PATH}/modules/auto_tasks.py')
safe_print(result)

# 10. 直接测试：检查数据库中是否有任何追踪记录（跨所有chat_id）
safe_print('\n=== 10. 完整的reply_tracking统计 ===')
result = run_ssh(f'cd {VPS_PATH} && python3 -c "import sqlite3; c=sqlite3.connect(\\'mory.db\\').cursor(); '
    f'print(\\'总记录:\\', c.execute(\\'SELECT COUNT(*) FROM reply_tracking\\').fetchone()[0]); '
    f'print(\\'\\n各chat_id记录数:\\'); '
    f'for r in c.execute(\\'SELECT chat_id, COUNT(*) FROM reply_tracking GROUP BY chat_id\\').fetchall(): '
    f'print(f\\'  chat={{r[0]}}: {{r[1]}}条\\'); '
    f'print(\\'\\n最新20条:\\'); '
    f'for r in c.execute(\\'SELECT * FROM reply_tracking ORDER BY ts DESC LIMIT 20\\').fetchall(): '
    f'print(r)"')
safe_print(result)

safe_print('\n诊断完成!')
