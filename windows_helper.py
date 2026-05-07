# -*- coding: utf-8 -*-
"""Windows小白启动助手：所有中文提示放在Python里，避免BAT乱码。"""

import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent


def run(cmd):
    """运行命令并返回退出码。"""
    return subprocess.call(cmd, cwd=str(ROOT))


def health() -> int:
    print("=" * 50)
    print("Mory小助理 · Windows健康检查")
    print("=" * 50)

    checks = [
        ("配置文件 config.json", ROOT / "config.json"),
        ("环境变量文件 .env", ROOT / ".env"),
        ("依赖清单 requirements.txt", ROOT / "requirements.txt"),
        ("数据库 mory.db", ROOT / "mory.db"),
    ]
    for name, path in checks:
        print(f"{'正常' if path.exists() else '缺失'}：{name}")

    print("\n正在检查Python语法...")
    code = run([sys.executable, "-m", "compileall", "-q", "main.py", "core", "modules", "dashboard"])
    if code == 0:
        print("语法检查通过。")
    else:
        print("语法检查没通过，请把这个结果发给我，我来修。")
    return code


def install() -> int:
    print("正在安装项目依赖，这一步可能需要几分钟...")
    return run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])


def start() -> int:
    print("正在启动机器人...")
    return run([sys.executable, str(ROOT / "main.py")])


def status() -> int:
    print("正在查看本机Python进程...")
    return run(["tasklist"])


def main() -> int:
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "help"
    if action == "health":
        return health()
    if action == "install":
        return install()
    if action == "start":
        return start()
    if action == "stop":
        print("Windows本地停止方式：关闭正在运行机器人的窗口即可。")
        return 0
    if action == "status":
        return status()

    print("=" * 50)
    print("Mory小助理 · Windows小白助手")
    print("=" * 50)
    print("可用命令：")
    print("  deploy.bat health   健康检查")
    print("  deploy.bat install  安装依赖")
    print("  deploy.bat start    启动机器人")
    print("  deploy.bat stop     停止说明")
    print("  deploy.bat status   查看进程")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
