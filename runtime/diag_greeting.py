# -*- coding: utf-8 -*-
"""查 VPS 当前时间与 greeting 任务注册/执行状态。只读。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from core.vps_config import ssh_connect


def main() -> int:
    c = paramiko.SSHClient()
    ssh_connect(c, timeout=15)

    def run(cmd: str) -> str:
        stdin, stdout, stderr = c.exec_command(cmd, timeout=25)
        return stdout.read().decode("utf-8", errors="replace").strip()

    print("VPS时间:", run('date "+%F %T %Z"'))
    print("== greeting 注册/执行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 07:00:00" --no-pager 2>/dev/null | grep -aiE "greeting" | tail -10') or "(无 greeting 相关)")
    print("== 注册任务总数 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 07:00:00" --no-pager 2>/dev/null | grep -c "注册任务"'))
    print("== 最近 8 行日志 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 07:30:00" --no-pager 2>/dev/null | tail -8'))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
