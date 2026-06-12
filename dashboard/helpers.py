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

_CST = timezone(timedelta(hours=8))

# ============ 路径配置 ============
_MORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELOAD_FLAG = Path(_MORY_ROOT) / 'reload_flag'


def _signal_config_reload():
    """通知Bot进程重载配置"""
    try:
        RELOAD_FLAG.touch()
    except Exception:
        pass
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
        print(f"[Dashboard] 已自动创建 {os.path.basename(db_path)} 并初始化表结构")
    except Exception as e:
        # 降级：如果 core.database 依赖有问题，至少保证空文件存在
        print(f"[Dashboard] 自动创建数据库失败（非致命）：{e}")


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
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db


# ============ 配置缓存（5秒TTL） ============
_config_cache = {"data": None, "mtime": 0, "loaded_at": 0}
_CONFIG_CACHE_TTL = 5  # 秒


def read_config():
    """读取config.json配置（带5秒TTL缓存，避免高频请求重复读文件）"""
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
            data = json.load(f)
        _config_cache["data"] = data
        _config_cache["mtime"] = mtime
        _config_cache["loaded_at"] = now
        return data
    except Exception:
        return _config_cache["data"] or {}


def write_config(cfg):
    """安全写入config.json（原子替换），成功后通知Bot进程重载配置"""
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    tmp_path = cfg_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cfg_path)
        _signal_config_reload()
        return True
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
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
    try:
        mode = os.environ.get("DASHBOARD_MODE", "main")
        import paramiko
        from core.vps_config import get_ssh_policy
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(get_ssh_policy())
        client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
        # 根据模式选择查询哪个 Bot
        if mode == "media":
            ps_cmd = "ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep | grep mory_media | head -1"
        else:
            ps_cmd = "ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep | grep -v mory_media | head -1"
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
        client.close()
    except Exception as e:
        results["error"] = str(e)[:100]
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
        if session.get("role", "admin") != "admin":
            return jsonify({"ok": False, "msg": "需要管理员权限"}), 403
        return f(*args, **kwargs)
    return wrapped


def get_current_role():
    """获取当前登录用户的角色"""
    return session.get("role", "admin")
