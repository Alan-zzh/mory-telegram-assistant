# -*- coding: utf-8 -*-
"""验证 journalctl 业务日志可见性与播报关键词。只读。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from core.vps_config import VPS_PATH, ssh_connect


def main() -> int:
    c = paramiko.SSHClient()
    ssh_connect(c, timeout=15)

    def run(cmd: str) -> str:
        stdin, stdout, stderr = c.exec_command(cmd, timeout=25)
        return stdout.read().decode("utf-8", errors="replace").strip()

    print("== 今日 journalctl 播报相关 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 07:15:00" --no-pager 2>/dev/null | grep -aE "问候|mystic|image_card|播报" | tail -15') or "(无)")
    print("== 今日 journalctl 错误 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 07:15:00" --no-pager 2>/dev/null | grep -aE "ERROR|Traceback" | tail -10') or "(无)")
    print("== journalctl 行数 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 07:15:00" --no-pager 2>/dev/null | wc -l'))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
