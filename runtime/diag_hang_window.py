# -*- coding: utf-8 -*-
"""定位 08:17 启动后卡死区间：08:17-09:15 逐段行数 + 边界抽样。只读。"""
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

    for label, start, end in (
        ("08:17-08:30", "2026-08-06 08:17:20", "2026-08-06 08:30:00"),
        ("08:30-08:40", "2026-08-06 08:30:00", "2026-08-06 08:40:00"),
        ("08:40-08:50", "2026-08-06 08:40:00", "2026-08-06 08:50:00"),
        ("08:50-09:00", "2026-08-06 08:50:00", "2026-08-06 09:00:00"),
        ("09:00-09:10", "2026-08-06 09:00:00", "2026-08-06 09:10:00"),
        ("09:10-09:20", "2026-08-06 09:10:00", "2026-08-06 09:20:00"),
    ):
        cnt = run(f'journalctl -u mory-assistant --since "{start}" --until "{end}" --no-pager 2>/dev/null | wc -l')
        print(f"{label} 行数: {cnt}")

    print("== 08:17:20-08:18:00 前 8 行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:17:20" --until "2026-08-06 08:18:00" --no-pager 2>/dev/null | head -8') or "(无)")
    print("== 09:05-09:15 前后 5 行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:05:00" --until "2026-08-06 09:15:00" --no-pager 2>/dev/null | head -5') or "(无)")
    print("== 09:10-09:12 前 5 行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:10:00" --until "2026-08-06 09:12:00" --no-pager 2>/dev/null | head -5') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
