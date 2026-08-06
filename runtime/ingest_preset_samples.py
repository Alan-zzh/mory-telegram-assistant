# -*- coding: utf-8 -*-
"""在 VPS 执行预设样本录入（读取 preset_payload_b64.txt，base64 解码后在 VPS 运行）。"""
from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from core.vps_config import VPS_PATH, ssh_connect


def main() -> int:
    b64_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preset_payload_b64.txt")
    with open(b64_path, encoding="ascii") as f:
        b64 = f.read().strip()
    payload = base64.b64decode(b64).decode("utf-8")

    c = paramiko.SSHClient()
    ssh_connect(c, timeout=15)

    # 1. 上传解码后的脚本到 VPS /tmp
    sftp = c.open_sftp()
    remote_script = f"{VPS_PATH}/runtime/_preset_ingest.py"
    with sftp.open(remote_script, "w") as f:
        f.write(payload)
    sftp.close()

    # 2. VPS 执行
    stdin, stdout, stderr = c.exec_command(
        f"cd {VPS_PATH} && python3 runtime/_preset_ingest.py", timeout=60
    )
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    print(out)
    if err:
        print("STDERR:", err[:800])

    # 3. 验证：查询 pending 样本
    stdin, stdout, stderr = c.exec_command(
        f"cd {VPS_PATH} && python3 -c \""
        "import sys; sys.path.insert(0,'.'); "
        "from core.database import Database; "
        "db=Database(); rows=db.reply_evolution.list_reply_style_samples(status='pending', limit=50); "
        "print('PENDING_COUNT=', len(rows)); "
        "[print(' -', r.get('scene'), '|', str(r.get('style_text',''))[:40]) for r in rows[-12:]]\"",
        timeout=30,
    )
    print(stdout.read().decode("utf-8", errors="replace").strip())

    # 4. 清理临时脚本
    c.exec_command(f"rm -f {VPS_PATH}/runtime/_preset_ingest.py", timeout=10)
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
