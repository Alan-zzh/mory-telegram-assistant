# -*- coding: utf-8 -*-
"""查部署后 vote_kick 是否不再报错。只读。"""
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
    print("== 部署后 VoteKick 执行 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:00" --no-pager 2>/dev/null | grep -a "VoteKickTask" | tail -5') or "(无)")
    print("== 部署后 vote_kick 错误 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:15:00" --no-pager 2>/dev/null | grep -a "vote_kick.*ERROR\\|cannot commit" | tail -3') or "(无错误)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
