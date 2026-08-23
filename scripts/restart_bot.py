#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重启Bot服务"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko
from core.vps_config import ssh_connect

client = paramiko.SSHClient()
ssh_connect(client)
try:
    print("=== 检查Bot进程 ===")
    stdin, stdout, stderr = client.exec_command(
        "ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep | grep -v mory_media"
    )
    result = stdout.read().decode().strip()
    print(result if result else "未找到Bot进程")

    print("\n=== 重启Bot ===")
    stdin, stdout, stderr = client.exec_command(
        "sudo systemctl restart mory-assistant && sleep 2 && sudo systemctl status mory-assistant --no-pager -n 20"
    )
    print(stdout.read().decode())
    print("错误:", stderr.read().decode())

    print("\n=== 最新日志 ===")
    stdin, stdout, stderr = client.exec_command(
        "sleep 3 && journalctl -u mory-assistant -n 30 --no-pager"
    )
    print(stdout.read().decode())
finally:
    try:
        client.close()
    except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
        logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
