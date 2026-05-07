#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VPS 深度诊断脚本 - 检查隐藏问题"""

import paramiko
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)

    cmds = [
        ('所有Python进程检查', 'ps -ef | grep python | grep -v grep'),
        ('wakeup_check重复执行检查', 'journalctl -u mory-assistant --since "1 hour ago" --no-pager | grep "wakeup_check" | head -20'),
        ('定时任务claim检查', 'journalctl -u mory-assistant --since "6 hours ago" --no-pager | grep -E "(claim_task|已被抢占)" | head -30'),
        ('任务重复执行检查', 'journalctl -u mory-assistant --since "6 hours ago" --no-pager | grep -E "(早安|午安|晚安|新闻|报告)" | head -30'),
        ('Dashboard错误日志', 'journalctl -u mory-dashboard --since "1 hour ago" --no-pager | tail -30'),
        ('数据库task_log记录', 'python3 -c "import sqlite3; c=sqlite3.connect(\"/home/ubuntu/mory_assistant/mory.db\"); print(c.execute(\"SELECT task_key, exec_date, exec_ts FROM task_log ORDER BY exec_ts DESC LIMIT 20\").fetchall())"'),
        ('系统资源使用', 'top -bn1 | head -20'),
        ('定时任务调度器状态', 'journalctl -u mory-assistant --since "1 hour ago" --no-pager | grep -E "APScheduler|BackgroundScheduler" | head -10'),
    ]

    for name, cmd in cmds:
        print(f"\n{'='*60}")
        print(f"【{name}】")
        print('='*60)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        if out:
            print(out[:3000])
        if err and 'Warning' not in err:
            print(f"ERR: {err[:500]}")

    client.close()
    print("\n=== 深度诊断完成 ===")

if __name__ == "__main__":
    main()
