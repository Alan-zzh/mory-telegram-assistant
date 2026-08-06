# -*- coding: utf-8 -*-
"""生产日志诊断：VPS 时间 / logs 目录 / 最新日志文件 / 今日播报关键词。只读。"""
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
        stdin, stdout, stderr = c.exec_command(cmd, timeout=20)
        return stdout.read().decode("utf-8", errors="replace").strip()

    print("VPS时间:", run('date "+%F %T %Z"'))
    print("logs目录:", run(f"ls -la {VPS_PATH}/logs/ | tail -20"))
    latest = run(f"ls -t {VPS_PATH}/logs/*.log 2>/dev/null | head -5")
    print("最新日志:", latest)
    for f in latest.splitlines()[:3]:
        if not f:
            continue
        print(f"--- {f} 尾部 ---")
        print(run(f"tail -8 {f}"))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
