# -*- coding: utf-8 -*-
"""等待今日播报窗口（08:05 早安 / 09:05 黄历），抓取生产运行证据。"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from core.vps_config import VPS_PATH, ssh_connect


def main() -> int:
    deadline = time.time() + 100 * 60  # 最长等 100 分钟（覆盖 08:05 早安 + 09:05 黄历）
    seen = set()
    while time.time() < deadline:
        c = paramiko.SSHClient()
        try:
            ssh_connect(c, timeout=15)
            cmd = (
                'journalctl -u mory-assistant --since "2026-08-06 00:00:00" --no-pager 2>/dev/null | '
                'grep -aE "问候已发送|image_card.*已生成|mystic.*图片卡已发送|greeting.*已发送" | tail -8'
            )
            stdin, stdout, stderr = c.exec_command(cmd, timeout=25)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            if out:
                for line in out.splitlines():
                    if line not in seen:
                        seen.add(line)
                        print(f"[{time.strftime('%H:%M:%S')}] {line}", flush=True)
            # 拿到今天的问候+玄学证据后提前结束
            if any("问候已发送" in s or "greeting" in s.lower() for s in seen) and any(
                "图片卡" in s for s in seen
            ):
                print("BROADCAST_EVIDENCE_COMPLETE", flush=True)
                c.close()
                return 0
        except Exception as exc:
            print(f"[{time.strftime('%H:%M:%S')}] 探针异常: {exc}", flush=True)
        finally:
            try:
                c.close()
            except Exception:
                pass
        time.sleep(60)
    print("BROADCAST_EVIDENCE_TIMEOUT（窗口内未捕获）", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
