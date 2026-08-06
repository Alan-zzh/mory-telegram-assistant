# -*- coding: utf-8 -*-
"""查 journald 存储模式与重启时间，解释 08:17-11:33 日志丢失。只读。"""
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

    print("== journald 启动时间 ==")
    print(run("systemctl show systemd-journald -p ActiveEnterTimestamp --value") or "(无)")
    print("== 持久 journal 目录 ==")
    print(run("ls -ld /var/log/journal 2>&1; ls -ld /run/log/journal 2>&1") or "(无)")
    print("== journal 文件最早时间 ==")
    print(run('journalctl --list-boots 2>/dev/null | head -5') or "(无)")
    print("== 服务重启次数 ==")
    print(run("systemctl show mory-assistant -p NRestarts --value") or "(无)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
