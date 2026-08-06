# -*- coding: utf-8 -*-
"""查 09:00-09:10 journal 总行数与时段覆盖。只读。"""
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
        ("08:50-09:10", "2026-08-06 08:50:00", "2026-08-06 09:10:00"),
        ("09:00-09:10", "2026-08-06 09:00:00", "2026-08-06 09:10:00"),
        ("09:10-13:05", "2026-08-06 09:10:00", "2026-08-06 13:05:00"),
        ("13:00-13:06", "2026-08-06 13:00:00", "2026-08-06 13:06:00"),
    ):
        cnt = run(f'journalctl -u mory-assistant --since "{start}" --until "{end}" --no-pager 2>/dev/null | wc -l')
        print(f"{label} journal 行数: {cnt}")

    print("== 08:50-09:10 抽样前 5 行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:50:00" --until "2026-08-06 09:10:00" --no-pager 2>/dev/null | head -5') or "(无)")
    print("== 08:50-09:10 抽样后 5 行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:50:00" --until "2026-08-06 09:10:00" --no-pager 2>/dev/null | tail -5') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
