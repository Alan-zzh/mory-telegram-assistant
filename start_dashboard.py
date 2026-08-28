# -*- coding: utf-8 -*-
"""Dashboard安全启动器：从 .env 读取配置，只接受密码哈希。"""

import io
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _configure_utf8_stdio() -> None:
    """仅在直接启动时包装标准流，导入模块不能接管调用方的文件描述符。"""
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def load_env_file() -> None:
    """读取.env文件，已有系统环境变量优先。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env_file()

    if not os.environ.get("DASHBOARD_SECRET"):
        os.environ["DASHBOARD_SECRET"] = secrets.token_hex(32)
        print("已生成本次临时Dashboard密钥。")

    password_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "").strip().lower()
    if len(password_hash) != 64 or any(c not in "0123456789abcdef" for c in password_hash):
        print(
            "Dashboard 未启动：必须在 .env 设置 64 位 SHA-256 "
            "DASHBOARD_PASSWORD_HASH；启动器不会生成或写入明文口令。"
        )
        return 2

    os.environ.setdefault("DASHBOARD_PORT", "6616")
    print(f"Dashboard启动中：http://127.0.0.1:{os.environ['DASHBOARD_PORT']}")

    return subprocess.call([sys.executable, "-m", "dashboard.app"], cwd=str(ROOT))


if __name__ == "__main__":
    _configure_utf8_stdio()
    raise SystemExit(main())
