#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VPS 线上状态诊断脚本"""

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
        ('系统时间', 'date'),
        ('Bot进程状态', 'systemctl status mory-assistant --no-pager -l'),
        ('Dashboard状态', 'systemctl status mory-dashboard --no-pager -l'),
        ('进程数检查', 'ps -ef | grep "mory_assistant/main.py" | grep -v grep | wc -l'),
        ('近期日志50行', 'journalctl -u mory-assistant -n 50 --no-pager'),
        ('409错误统计', 'journalctl -u mory-assistant --since "24 hours ago" --no-pager | grep -c "409" || echo "0"'),
        ('task_log表结构', 'sqlite3 /home/ubuntu/mory_assistant/mory.db ".schema task_log"'),
        ('版本号', 'cat /home/ubuntu/mory_assistant/version.py | grep VERSION'),
        ('磁盘空间', 'df -h'),
        ('内存使用', 'free -h'),
        ('Bot日志最后100行', 'tail -n 100 /home/ubuntu/mory_assistant/mory.log'),
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
    print("\n=== VPS诊断完成 ===")

if __name__ == "__main__":
    main()
