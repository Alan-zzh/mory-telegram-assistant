# -*- coding: utf-8 -*-
"""深挖 09:05 黄历未执行根因：注册/claim/abort 全链路。只读。"""
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
        stdin, stdout, stderr = c.exec_command(cmd, timeout=30)
        return stdout.read().decode("utf-8", errors="replace").strip()

    print("== 08:15 后注册任务数 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:00" --no-pager 2>/dev/null | grep -c "注册任务"'))
    print("== 注册任务全部列表(08:15后) ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:00" --no-pager 2>/dev/null | grep "注册任务" | grep -vE "scheduled_broadcast" | head -40'))
    print("== 09:04-09:06 claim/abort 全量 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:04:00" --until "2026-08-06 09:08:00" --no-pager 2>/dev/null | grep -aE "claim|abort|mystic|玄学|ERROR" | head -20') or "(无)")
    print("== 08:16-08:20 重启记录 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:50" --until "2026-08-06 08:18:00" --no-pager 2>/dev/null | grep -aE "Started|Stopped|启动|任务调度器" | head -10') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
