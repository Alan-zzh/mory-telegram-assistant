# -*- coding: utf-8 -*-
"""验证 journal 完整性：今天最早/最晚日志、总行数、08:17-09:30 精确查询。只读。"""
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

    print("== 今天最早 3 条 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 00:00:00" --no-pager 2>/dev/null | head -3') or "(无)")
    print("== 今天最后 3 条 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 00:00:00" --no-pager 2>/dev/null | tail -3') or "(无)")
    print("== 今天总行数 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 00:00:00" --no-pager 2>/dev/null | wc -l'))
    print("== 08:17 精确查询(无 until) ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:17:20" --no-pager 2>/dev/null | head -5') or "(无)")
    print("== 09:20 精确查询(无 until) ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 09:20:00" --no-pager 2>/dev/null | head -5') or "(无)")
    print("== journal 磁盘占用 ==")
    print(run('journalctl --disk-usage 2>/dev/null') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
