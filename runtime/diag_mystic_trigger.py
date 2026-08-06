# -*- coding: utf-8 -*-
"""查 09:05 mystic_morning 是否被调度器触发（Running job / MISSED / monitor）。只读。"""
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

    print("== 当前服务启动时间 ==")
    print(run("systemctl show mory-assistant -p ActiveEnterTimestamp --value"))
    print("== 09:04:30-09:06:30 全部 Running job ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:04:30" --until "2026-08-06 09:06:30" --no-pager 2>/dev/null | grep -a "Running job" | head -20') or "(无)")
    print("== 09:00-09:15 MISSED/错过 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:00:00" --until "2026-08-06 09:15:00" --no-pager 2>/dev/null | grep -aiE "MISSED|错过|misfire" | head -10') or "(无)")
    print("== 09:00-09:15 scheduler_monitor ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:00:00" --until "2026-08-06 09:15:00" --no-pager 2>/dev/null | grep -a "scheduler_monitor" | head -10') or "(无)")
    print("== 全天 mystic 执行链 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:00" --no-pager 2>/dev/null | grep -aE "mystic_morning|mystic_afternoon|mystic_evening" | grep -aE "Running|claim|MISSED" | tail -10') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
