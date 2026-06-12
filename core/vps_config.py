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
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                os.environ.setdefault(key.strip(), value)


def _env(key: str, default: str = "") -> str:
    """读取环境变量，支持空默认值"""
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    """读取环境变量并转为整数，处理空字符串避免 int("") 崩溃"""
    val = _env(key, str(default))
    try:
        return int(val) if val.strip() else default
    except ValueError:
        return default


VPS = {
    "host": _env("VPS_HOST", ""),  # 【v4.3.2修复F-03】移除硬编码IP默认值
    "port": _env_int("VPS_PORT", 22),
    "user": _env("VPS_USER", "ubuntu"),
    "pass": _env("VPS_SSH_PASS", ""),
    "root": _env("VPS_PATH", "/home/ubuntu/mory_assistant"),  # 【v4.3.2修复】路径也从环境变量读取
}

# 快捷访问
VPS_HOST = VPS["host"]
VPS_PORT = VPS["port"]
VPS_USER = VPS["user"]
VPS_PASS = VPS["pass"]
VPS_PATH = VPS["root"]

# ── SSH 主机密钥缓存（防止 MITM 攻击）──
_KNOWN_HOSTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_ssh_known_hosts")


class _CachedHostKeyPolicy:
    """
    自定义 SSH 主机密钥策略：
    - 首次连接：自动接受并缓存主机密钥到 _ssh_known_hosts 文件
    - 后续连接：验证密钥是否匹配缓存，不匹配则拒绝（防 MITM）
    """

    def __init__(self):
        self._known_keys = {}  # {hostname: key.get_base64()}
        self._load_known_hosts()

    def _load_known_hosts(self):
        """从文件加载已缓存的主机密钥"""
        if not os.path.exists(_KNOWN_HOSTS_FILE):
            return
        try:
            with open(_KNOWN_HOSTS_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        hostname, key_b64 = parts[0], parts[1]
                        self._known_keys[hostname] = key_b64
        except Exception:
            pass

    def _save_known_hosts(self):
        """保存主机密钥到文件"""
        try:
            with open(_KNOWN_HOSTS_FILE, "w") as f:
                for hostname, key_b64 in self._known_keys.items():
                    f.write(f"{hostname} {key_b64}\n")
        except Exception:
            pass

    def missing_host_key(self, client, hostname, key):
        """paramiko 回调：服务器发送了主机密钥"""
        import paramiko
        key_b64 = key.get_base64()
        if hostname in self._known_keys:
            if self._known_keys[hostname] != key_b64:
                raise paramiko.SSHException(
                    f"🚨 主机密钥变更！{hostname} 的密钥与缓存不匹配，"
                    f"可能存在中间人攻击。如确认安全请删除 {_KNOWN_HOSTS_FILE} 后重试"
                )
        else:
            self._known_keys[hostname] = key_b64
            self._save_known_hosts()

    def add(self, hostname, key):
        """添加主机密钥"""
        self._known_keys[hostname] = key.get_base64()
        self._save_known_hosts()


# 全局单例
_ssh_policy = _CachedHostKeyPolicy()


def get_ssh_policy():
    """获取 SSH 主机密钥策略（所有 SSH 连接统一使用）"""
    return _ssh_policy


def ssh_connect(client, timeout: int = 15):
    """一键建立 SSH 连接（paramiko client）"""
    # 【v4.3.2修复F-03】校验必填项
    if not VPS_HOST:
        raise ValueError("VPS_HOST 未设置！请在 .env 文件中配置 VPS_HOST=<IP地址>")
    if not VPS_PASS:
        raise ValueError("VPS_SSH_PASS 未设置！请在 .env 文件中配置 VPS_SSH_PASS=<密码>")
    client.set_missing_host_key_policy(_ssh_policy)
    client.connect(
        VPS_HOST, port=VPS_PORT,
        username=VPS_USER, password=VPS_PASS,
        timeout=timeout,
    )
