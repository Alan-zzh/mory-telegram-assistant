# -*- coding: utf-8 -*-
"""抓取 v5.38.27 玄学播报生产证据（09:05 黄历 / 13:05 塔罗）。只读。"""
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
    print("== 玄学图片卡生成 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:20:00" --no-pager 2>/dev/null | grep -a "mystic.*图片卡已生成\\|mystic.*图片卡已发送" | tail -6') or "(无)")
    print("== 玄学播报发送与组合 ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:20:00" --no-pager 2>/dev/null | grep -a "cta=\\|✅.*已发送" | tail -8') or "(无)")
    print("== 玄学相关 ERROR ==")
    print(run('journalctl -u mory-assistant --since "2026-08-06 08:20:00" --no-pager 2>/dev/null | grep -a "mystic.*ERROR\\|玄学播报失败" | tail -3') or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
