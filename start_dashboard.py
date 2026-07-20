# -*- coding: utf-8 -*-
"""Dashboard安全启动器：从.env读取配置，缺失时生成本次临时密钥。"""

import io
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent


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

    if not os.environ.get("DASHBOARD_PASSWORD"):
        temp_password = "mory-" + secrets.token_hex(8)
        os.environ["DASHBOARD_PASSWORD"] = temp_password
        # 写入 .env 文件，方便用户从 .env 获取完整密码（避免脱敏后无法登录的功能回归）
        env_file = ROOT / ".env"
        try:
            existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
            if "DASHBOARD_PASSWORD" not in existing:
                with open(env_file, "a", encoding="utf-8") as f:
                    f.write(f"\n# 自动生成的临时Dashboard密码\nDASHBOARD_PASSWORD={temp_password}\n")
                print(f"已生成临时Dashboard密码并写入 .env（前4位: {temp_password[:4]}***，完整密码请查看 .env）")
            else:
                print(f"已生成临时Dashboard密码（前4位: {temp_password[:4]}***，完整密码请查看环境变量）")
        except Exception as e:
            print(f"已生成临时Dashboard密码（前4位: {temp_password[:4]}***，写入 .env 失败: {e}）")
        print("建议以后把 DASHBOARD_PASSWORD 写进 .env，避免每次启动变化。")

    os.environ.setdefault("DASHBOARD_PORT", "6616")
    print(f"Dashboard启动中：http://127.0.0.1:{os.environ['DASHBOARD_PORT']}")

    return subprocess.call([sys.executable, "-m", "dashboard.app"], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
