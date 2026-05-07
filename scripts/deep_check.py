# 项目：mory_assistant | 版本：v1.0.6 | 日期：2026-04-27 | 功能：完整诊断关键词触发问题
import paramiko
import os
from dotenv import load_dotenv

load_dotenv(r'c:\Users\Administrator\Desktop\mory_assistant\.env')

VPS_HOST = os.getenv('VPS_HOST')
VPS_SSH_PASS = os.getenv('VPS_SSH_PASS')
VPS_PORT = int(os.getenv('VPS_PORT', '22'))
VPS_USER = os.getenv('VPS_USER', 'root')
VPS_PATH = os.getenv('VPS_PATH', '/root/mory')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_SSH_PASS, timeout=15)

def run_cmd(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    return out, err

# 1. 查看完整的match_keyword_trigger函数
print("=== database.py 中 match_keyword_trigger 函数 ===")
out, _ = run_cmd(f'sed -n "1048,1100p" {VPS_PATH}/core/database.py')
print(out)

# 2. 查看main.py中关键词处理的具体逻辑
print("\n=== main.py 中关键词处理逻辑（第800行附近） ===")
out, _ = run_cmd(f'sed -n "795,830p" {VPS_PATH}/main.py')
print(out)

# 3. 查看整个日志文件中所有包含"更新"关键词的记录（不是调度器的trigger）
print("\n=== 所有包含'更新'关键词的用户消息记录 ===")
out, _ = run_cmd(f'grep "更新" {VPS_PATH}/mory.log | grep -v "apscheduler\|cron\|trigger:" | head -50')
print(out if out else "未找到")

# 4. 查看keyword_trigger模块的_handle_action的完整回复内容
print("\n=== keyword_trigger.py 完整代码（重点关注_handle_action） ===")
out, _ = run_cmd(f'cat {VPS_PATH}/modules/keyword_trigger.py')
print(out)

# 5. 查看最近所有MSG_IN记录
print("\n=== 最近所有用户消息 ===")
out, _ = run_cmd(f'grep "MSG_IN" {VPS_PATH}/mory.log | tail -30')
print(out)

ssh.close()
print("\n完成！")
