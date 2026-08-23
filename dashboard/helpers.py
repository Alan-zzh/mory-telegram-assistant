# -*- coding: utf-8 -*-
"""Dashboard公共工具函数"""
import os
import sys
import json
import sqlite3
import time
from functools import wraps
from pathlib import Path
from flask import g, jsonify, session
from datetime import datetime, timedelta, timezone
import logging
from core.config_compat import normalize_runtime_config, compact_runtime_config

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# ============ 路径配置 ============
_MORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELOAD_FLAG = Path(_MORY_ROOT) / 'reload_flag'


def _signal_config_reload():
    """通知Bot进程重载配置"""
    try:
        RELOAD_FLAG.touch()
    except Exception as e:
        logger.debug(f"操作异常: {e}")
sys.path.insert(0, _MORY_ROOT)
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH


# ============ 数据库工具 ============
def _ensure_media_db(db_path: str):
    """确保 media 模式下的数据库文件存在且表结构完整

    当 DASHBOARD_MODE=media 时，如果 mory_media.db 不存在或表结构不完整，
    自动用 core.database.DB 初始化（建表 + 索引），
    这样 media Bot 即使还没启动，Dashboard 也能正常工作。
    """
    if os.path.exists(db_path):
        return  # 文件已存在，直接连接即可
    try:
        # 导入 core.database.DB 来初始化表结构
        from core.database import DB
        # DB.__init__ 自动建表 + 初始化 Repo
        _tmp_db = DB(db_path)
        _tmp_db.close()
        logger.info(f"[Dashboard] 已自动创建 {os.path.basename(db_path)} 并初始化表结构")
    except Exception as e:
        # 降级：如果 core.database 依赖有问题，至少保证空文件存在
        logger.warning(f"[Dashboard] 自动创建数据库失败（非致命）：{e}")


def get_db():
    """获取数据库连接（每个请求复用）

    支持多Bot分区：设置 DASHBOARD_MODE=media 时连接 mory_media.db，
    默认连接 mory.db。这样两个 Bot 的 Dashboard 可以独立部署在同一台机器上。

    暗病修复：media 模式下如果 mory_media.db 不存在，自动建表初始化。
    """
    mode = os.environ.get("DASHBOARD_MODE", "main")
    db_name = "mory_media.db" if mode == "media" else "mory.db"
    db_path = os.path.join(_MORY_ROOT, db_name)
    if mode == "media":
        _ensure_media_db(db_path)
    if 'db' not in g:
        # 【TRAE SOLO CN v5.18.3审计修复】Dashboard 连接加 WAL + busy_timeout，防止与 Bot 进程互锁
        g.db = sqlite3.connect(db_path, timeout=30.0)
        g.db.row_factory = sqlite3.Row
        # 【P2-5 修复】PRAGMA 配置补齐,与 core/database.py 保持一致,
        # 避免 Dashboard 读连接因 journal_mode/busy_timeout 不一致导致锁竞争
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA busy_timeout=30000")
        g.db.execute("PRAGMA synchronous=NORMAL")
        g.db.execute("PRAGMA cache_size=-4000")
        g.db.execute("PRAGMA mmap_size=268435456")
    return g.db


# ============ 配置缓存（5秒TTL） ============
_config_cache = {"data": None, "mtime": 0, "loaded_at": 0}
_CONFIG_CACHE_TTL = 5  # 秒


def read_config():
    """读取config.json配置（带5秒TTL缓存，避免高频请求重复读文件）

    【v5.41.0】凭据唯一存 .env：config.json 不再保存明文 TOKEN/API_KEY，
    读取时与 bot_initializer 相同口径用环境变量覆盖注入（TG_TOKEN / DASHSCOPE_KEY）。
    """
    now = time.time()
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    try:
        mtime = os.path.getmtime(cfg_path)
        # 缓存命中：文件未修改 且 未过期
        if _config_cache["data"] is not None and \
           _config_cache["mtime"] == mtime and \
           (now - _config_cache["loaded_at"]) < _CONFIG_CACHE_TTL:
            return _config_cache["data"]
        # 缓存未命中：重新读取
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = normalize_runtime_config(json.load(f))
        # 凭据环境变量优先（与 bot_initializer 同口径；config.json 落盘值恒为空）
        if os.environ.get("TG_TOKEN"):
            data["TOKEN"] = os.environ["TG_TOKEN"]
        if os.environ.get("DASHSCOPE_KEY"):
            data["API_KEY"] = os.environ["DASHSCOPE_KEY"]
        _config_cache["data"] = data
        _config_cache["mtime"] = mtime
        _config_cache["loaded_at"] = now
        return data
    except Exception as e:
        logger.debug(f"config读取失败，回退到缓存或空配置（非致命）：{e}")
        return _config_cache["data"] or {}


def write_config(cfg):
    """安全写入config.json（原子替换），成功后通知Bot进程重载配置"""
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    tmp_path = cfg_path + ".tmp"
    try:
        cfg = compact_runtime_config(cfg)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # config.json 可能包含 Token/API Key；原子替换前先把临时文件收紧，
        # 避免 Dashboard 每次保存后把部署器设置的 0600 放宽成 0644。
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, cfg_path)
        # [P2-NEW-14] 更新缓存，避免同进程立即 read_config 返回旧数据（竞态）
        _config_cache["data"] = cfg
        _config_cache["mtime"] = os.path.getmtime(cfg_path)
        _config_cache["loaded_at"] = time.time()
        _signal_config_reload()
        return True
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        return False


# ============ VPS工具 ============
def ssh_exec(cmd, timeout=15):
    """通过SSH在VPS上执行命令"""
    import paramiko
    from core.vps_config import get_ssh_policy
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(get_ssh_policy())
    try:
        client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=timeout)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err
    except Exception as e:
        return "", str(e)
    finally:
        client.close()


_vps_cache = {"data": None, "updated_at": 0}
_VPS_CACHE_TTL = 300


def get_vps_status():
    """获取VPS运行状态（带5分钟缓存）

    多Bot分区：DASHBOARD_MODE=media 时只查 mory_media 进程，
    默认只查主 Bot 进程。
    """
    now = time.time()
    if _vps_cache["data"] and (now - _vps_cache["updated_at"]) < _VPS_CACHE_TTL:
        return _vps_cache["data"]
    results = {"bot_running": False, "bot_pid": None, "bot_memory": "N/A", "uptime": "N/A", "error": None}
    mode = os.environ.get("DASHBOARD_MODE", "main")
    import paramiko
    from core.vps_config import get_ssh_policy
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(get_ssh_policy())
    try:
        # SSH 认证：优先 SSH Key（推荐），向后兼容密码模式
        # 【v5.31.2 hotfix P1-3a】统一环境变量名为 VPS_SSH_KEY（与 core/vps_config.py 一致），
        # 避免出现 VPS_SSH_KEY_PATH / VPS_SSH_KEY 双命名分裂。
        # 兼容回退：若已部署用户仍用 VPS_SSH_KEY_PATH，向后兼容读取（不推荐新部署使用）。
        ssh_key_path = os.environ.get("VPS_SSH_KEY", "") or os.environ.get("VPS_SSH_KEY_PATH", "")
        if ssh_key_path and os.path.exists(ssh_key_path):
            client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, key_filename=ssh_key_path, timeout=10)
        elif VPS_PASS:
            # 向后兼容：密码模式（不推荐，建议迁移到 SSH Key）
            logger.warning("VPS SSH 使用密码认证，建议配置 VPS_SSH_KEY 环境变量改用 SSH Key")
            client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
        else:
            results["error"] = "无可用 SSH 认证方式（VPS_SSH_KEY 未设置且无密码）"
            _vps_cache["data"] = results
            _vps_cache["updated_at"] = time.time()
            return results
        # 根据模式选择查询哪个 Bot
        if mode == "media":
            ps_cmd = f"ps -ef | grep '{VPS_PATH}/main.py' | grep -v grep | grep mory_media | head -1"
        else:
            ps_cmd = f"ps -ef | grep '{VPS_PATH}/main.py' | grep -v grep | grep -v mory_media | head -1"
        stdin, stdout, stderr = client.exec_command(ps_cmd, timeout=5)
        ps_line = stdout.read().decode("utf-8", errors="replace").strip()
        if ps_line:
            results["bot_running"] = True
            # 从 ps -ef 输出中提取 PID（第2列）
            pid = ps_line.split()[1] if len(ps_line.split()) > 1 else ""
            results["bot_pid"] = pid
            stdin, stdout, stderr = client.exec_command(f"ps -p {pid} -o rss= 2>/dev/null || echo ''", timeout=5)
            mem = stdout.read().decode("utf-8", errors="replace").strip()
            if mem:
                results["bot_memory"] = f"{int(mem)//1024} MB"
        stdin, stdout, stderr = client.exec_command("uptime -p 2>/dev/null || uptime", timeout=5)
        results["uptime"] = stdout.read().decode("utf-8", errors="replace").strip()
    except Exception as e:
        results["error"] = "vps_status_unavailable"
        logger.warning(f"VPS 状态查询失败: {e}")
    finally:
        try:
            client.close()
        except Exception as e:
            logger.debug(f"SSH client.close 失败: {e}")
    _vps_cache["data"] = results
    _vps_cache["updated_at"] = time.time()
    return results


# ============ 模型工具 ============
def _get_current_model_name(cfg):
    """获取当前使用的模型名称"""
    idx = cfg.get("CURRENT_MODEL_INDEX", 0)
    pools = cfg.get("MODEL_POOLS", {})
    llm_pool = pools.get("llm", pools.get("llm_light", []))
    if isinstance(llm_pool, list) and 0 <= idx < len(llm_pool):
        return llm_pool[idx].get("name", f"模型#{idx}")
    return f"模型#{idx}"


def _get_nested(cfg, key, default=None):
    """支持点号分隔的嵌套键，如 'ANTI_DELETE_CONFIG.enable'"""
    parts = key.split(".")
    cur = cfg
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur


# ============ 测试辅助类 ============
class _DashboardFakeMessage:
    """模拟Telegram消息对象（Dashboard自然语言配置用）"""
    def __init__(self, text: str):
        self.text = text


class _DashboardReplyProxy:
    """模拟Bot回复代理（收集回复消息）"""
    def __init__(self):
        self.messages = []

    def reply_and_track(self, _message, text: str):
        self.messages.append(text)


# ============ 认证装饰器 ============
def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"ok": False, "msg": "未登录"}), 401
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    """管理员权限验证装饰器（需先通过login_required）"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"ok": False, "msg": "未登录"}), 401
        # 【TRAE SOLO CN v5.18.3审计修复】默认 viewer，最小权限原则
        if session.get("role", "viewer") != "admin":
            return jsonify({"ok": False, "msg": "需要管理员权限"}), 403
        return f(*args, **kwargs)
    return wrapped


def get_current_role():
    """获取当前登录用户的角色（默认 viewer，最小权限原则）"""
    # 【TRAE SOLO CN v5.18.3审计修复】默认 viewer 而非 admin，防止 session 异常时越权
    return session.get("role", "viewer")


# ── 配置数值钳制（审计加固：Dashboard 数值输入禁止负数/天文数字落盘）────────
_INT_CLAMP_HI = 10_000_000


def clamp_int(value, lo: int = 0, hi: int = _INT_CLAMP_HI):
    """把 Dashboard 传入的整型配置值安全钳制到 [lo, hi]；垃圾输入返回 lo。

    用于 settings_api/group_api 的所有 int(data.get(...)) 写入点，
    防止负数或超大值写进 config.json 影响运行态。
    """
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return lo


def clamp_float(value, lo: float = 0.0, hi: float = float(_INT_CLAMP_HI)):
    """同 clamp_int 的浮点版本；垃圾输入返回 lo。"""
    try:
        return max(lo, min(float(value), hi))
    except (TypeError, ValueError):
        return lo
