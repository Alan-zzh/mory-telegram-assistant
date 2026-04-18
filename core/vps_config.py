"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/vps_config.py  ·  VPS 部署配置统一管理                               ║
║                                                                            ║
║  所有需要连接 VPS 的脚本统一引用此模块，不再硬编码 IP/密码。               ║
║  优先从环境变量读取（.env / 系统环境变量），回退到默认值用于本地调试。      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os

# 自动加载 .env 文件（如果存在）
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _env(key: str, default: str = "") -> str:
    """读取环境变量，支持空默认值"""
    return os.environ.get(key, default)


VPS = {
    "host": _env("VPS_HOST", "43.159.168.175"),
    "port": int(_env("VPS_PORT", "22")),
    "user": _env("VPS_USER", "root"),
    "pass": _env("VPS_SSH_PASS", ""),
    "root": "/root/mory",
}

# 快捷访问
VPS_HOST = VPS["host"]
VPS_PORT = VPS["port"]
VPS_USER = VPS["user"]
VPS_PASS = VPS["pass"]
VPS_PATH = VPS["root"]


def ssh_connect(client, timeout: int = 15):
    """一键建立 SSH 连接（paramiko client）"""
    if not VPS_PASS:
        raise ValueError("VPS_SSH_PASS 未设置！请在 .env 文件中配置 VPS_SSH_PASS=<密码>")
    client.connect(
        VPS_HOST, port=VPS_PORT,
        username=VPS_USER, password=VPS_PASS,
        timeout=timeout,
    )
