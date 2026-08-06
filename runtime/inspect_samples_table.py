# -*- coding: utf-8 -*-
"""查 VPS reply_style_samples 表结构与 12 条样本实际存储内容。只读。"""
from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from core.vps_config import VPS_PATH, ssh_connect


def main() -> int:
    c = paramiko.SSHClient()
    ssh_connect(c, timeout=15)

    payload = (
        "import sys, sqlite3; sys.path.insert(0,'.'); "
        "conn=sqlite3.connect('mory.db'); "
        "cols=[r[1] for r in conn.execute('PRAGMA table_info(reply_style_samples)')]; "
        "print('COLUMNS=', cols); "
        "rows=conn.execute('SELECT * FROM reply_style_samples ORDER BY id DESC LIMIT 3').fetchall(); "
        "[print('ROW=', r) for r in rows]"
    )
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    stdin, stdout, stderr = c.exec_command(
        f"cd {VPS_PATH} && echo {b64} | base64 -d > runtime/_inspect.py && "
        f"python3 runtime/_inspect.py && rm -f runtime/_inspect.py",
        timeout=40,
    )
    print(stdout.read().decode("utf-8", errors="replace").strip())
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        print("STDERR:", err[:500])
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
