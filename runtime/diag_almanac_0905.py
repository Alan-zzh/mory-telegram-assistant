# -*- coding: utf-8 -*-
"""查 09:05 黄历（mystic_morning/almanac）执行情况。只读。"""
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

    print("== 09:00-09:15 mystic/almanac/黄历 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:00:00" --until "2026-08-06 09:15:00" --no-pager 2>/dev/null | grep -aE "mystic|almanac|黄历|玄学" | tail -15') or "(无)")
    print("== 09:05 前后任务执行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:04:30" --until "2026-08-06 09:06:30" --no-pager 2>/dev/null | grep -aE "mystic_morning|claim_task|MysticBroadcast" | tail -8') or "(无)")
    print("== 全天 mystic 任务注册 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:00" --no-pager 2>/dev/null | grep -a "注册任务: mystic" | tail -4') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
