#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory Assistant - 私域可视化面板
v6.0 - 全新设计（深色主题/数据可视化/实时监控/专业级UI）
Build: 2026-04-26
"""

import os
import sys
import json
import sqlite3
import io
import hmac
from datetime import datetime, timedelta, timezone
_CST = timezone(timedelta(hours=8))
from functools import wraps
from flask import Flask, request, jsonify, session, Response, g
import time

# ============ 路径配置 ============
_MORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _MORY_ROOT)
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH
from modules.natural_cmd import handle_natural_admin

# 【v4.3.2修复S-10/S-11】添加简单CSRF校验和速率限制
_dashboard_rate_limits = {}
_RATE_LIMIT_MAX_ENTRIES = 10000
_login_failures = {}
_LOGIN_LOCKOUT_SECONDS = 600
_LOGIN_MAX_FAILS = 5

def _check_rate_limit(ip: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    import time as _time
    now = _time.time()
    expired_keys = [k for k, v in _dashboard_rate_limits.items() if now > v["reset_at"]]
    for k in expired_keys:
        del _dashboard_rate_limits[k]
    if len(_dashboard_rate_limits) > _RATE_LIMIT_MAX_ENTRIES:
        oldest = min(_dashboard_rate_limits, key=lambda k: _dashboard_rate_limits[k]["reset_at"])
        del _dashboard_rate_limits[oldest]
    record = _dashboard_rate_limits.get(ip)
    if not record or now > record["reset_at"]:
        _dashboard_rate_limits[ip] = {"count": 1, "reset_at": now + window_seconds}
        return True
    record["count"] += 1
    if record["count"] > max_requests:
        return False
    return True

# ============ Flask应用 ============
app = Flask(__name__)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.secret_key = os.environ.get("DASHBOARD_SECRET")
if not app.secret_key or len(app.secret_key) < 16:
    print("❌ 致命错误：DASHBOARD_SECRET 环境变量未设置或太短（至少16位）！")
    sys.exit(1)

@app.before_request
def _security_check():
    if request.path.startswith(('/static/', '/favicon')):
        return None
    if request.method == 'GET':
        if not _check_rate_limit(request.remote_addr):
            return jsonify({"ok": False, "msg": "请求过于频繁，请稍后再试"}), 429
        return None
    if request.method == 'POST':
        if not _check_rate_limit(request.remote_addr, max_requests=30):
            return jsonify({"ok": False, "msg": "请求过于频繁，请稍后再试"}), 429
        if request.path == '/api/login':
            return None
        if not request.headers.get('X-Requested-With'):
            return jsonify({"ok": False, "msg": "CSRF校验失败"}), 403
    return None

# ============ 数据库工具 ============
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(os.path.join(_MORY_ROOT, "mory.db"))
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def _get_login_fails(ip):
    info = _login_failures.get(ip)
    if not info:
        return {"count": 0, "first_fail_at": 0}
    if time.time() - info["first_fail_at"] > _LOGIN_LOCKOUT_SECONDS:
        del _login_failures[ip]
        return {"count": 0, "first_fail_at": 0}
    return info

def _set_login_fails(ip, info):
    _login_failures[ip] = info

def _clear_login_fails(ip):
    _login_failures.pop(ip, None)

def read_config():
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_config(cfg):
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    tmp_path = cfg_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cfg_path)
        return True
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return False

# ============ VPS工具 ============
def ssh_exec(cmd, timeout=15):
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
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
    now = time.time()
    if _vps_cache["data"] and (now - _vps_cache["updated_at"]) < _VPS_CACHE_TTL:
        return _vps_cache["data"]
    results = {"bot_running": False, "bot_pid": None, "bot_memory": "N/A", "uptime": "N/A", "error": None}
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
        stdin, stdout, stderr = client.exec_command("pgrep -f 'main.py' | head -1", timeout=5)
        pid = stdout.read().decode("utf-8", errors="replace").strip()
        if pid and pid.isdigit():
            results["bot_running"] = True
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

# ============ 认证装饰器 ============
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"ok": False, "msg": "未登录"}), 401
        return f(*args, **kwargs)
    return wrapped

# ============ 认证API ============
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    pw = data.get("password", "")
    admin_pw = os.environ.get("DASHBOARD_PASSWORD")
    if not admin_pw or len(admin_pw) < 6:
        return jsonify({"ok": False, "msg": "系统未正确配置密码，请联系管理员"}), 403
    login_key = request.remote_addr
    fail_info = _get_login_fails(login_key)
    if fail_info["count"] >= 5:
        elapsed = time.time() - fail_info["first_fail_at"]
        if elapsed < 600:
            return jsonify({"ok": False, "msg": "登录尝试过多，请10分钟后再试"}), 429
        fail_info = {"count": 0, "first_fail_at": 0}
    if hmac.compare_digest(pw, admin_pw):
        session["logged_in"] = True
        session["login_time"] = datetime.now().isoformat()
        _clear_login_fails(login_key)
        return jsonify({"ok": True})
    if fail_info["count"] == 0:
        fail_info["first_fail_at"] = time.time()
    fail_info["count"] += 1
    _set_login_fails(login_key, fail_info)
    return jsonify({"ok": False, "msg": "密码错误"}), 401

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/check")
def api_check():
    return jsonify({"ok": bool(session.get("logged_in"))})

# ============ 数据看板API ============
@app.route("/api/stats/overview")
@login_required
def api_stats_overview():
    stats = {
        "total_users": 0, "today_active": 0, "week_active": 0, "month_active": 0,
        "total_group_msgs": 0, "total_private_msgs": 0,
        "online_trend": [], "hourly_dist": {}, "conversion_funnel": {},
        "group_stats": {}, "channel_stats": {}
    }
    try:
        conn = get_db()
        r = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        stats["total_users"] = r[0] if r else 0
        today_start = int((datetime.now() - datetime.now().replace(hour=0, minute=0, second=0)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (today_start,)).fetchone()
        stats["today_active"] = r[0] if r else 0
        week_start = int((datetime.now() - timedelta(days=7)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (week_start,)).fetchone()
        stats["week_active"] = r[0] if r else 0
        month_start = int((datetime.now() - timedelta(days=30)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (month_start,)).fetchone()
        stats["month_active"] = r[0] if r else 0
        r = conn.execute("SELECT COALESCE(SUM(group_messages),0), COALESCE(SUM(private_messages),0) FROM users").fetchone()
        stats["total_group_msgs"] = r[0] if r else 0
        stats["total_private_msgs"] = r[1] if r else 0
        r = conn.execute("SELECT conversion_status, COUNT(*) FROM users GROUP BY conversion_status").fetchall()
        for row in r:
            stats["conversion_funnel"][row[0] or "unknown"] = row[1]
        for i in range(7):
            day = datetime.now() - timedelta(days=6-i)
            day_start = int(day.replace(hour=0, minute=0, second=0).timestamp())
            day_end = int(day.replace(hour=23, minute=59, second=59).timestamp())
            r = conn.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ? AND first_seen <= ?", (day_start, day_end)).fetchone()
            stats["online_trend"].append({"date": day.strftime("%m-%d"), "value": r[0] if r else 0})
        r = conn.execute("""
            SELECT strftime('%H', datetime(last_active, 'unixepoch', 'localtime')) as hour, COUNT(*)
            FROM users WHERE last_active > 0 GROUP BY hour ORDER BY hour
        """).fetchall()
        for row in r:
            stats["hourly_dist"][int(row[0]) if row[0] else 0] = row[1]
        try:
            r = conn.execute("""SELECT COALESCE(SUM(joined_count),0), COALESCE(SUM(left_count),0), COALESCE(SUM(net_count),0)
                               FROM group_stats WHERE date >= date('now', '-7 days')""").fetchone()
            stats["group_stats"] = {"week_joined": r[0] if r else 0, "week_left": r[1] if r else 0, "week_net": r[2] if r else 0}
        except Exception:
            stats["group_stats"] = {"week_joined": 0, "week_left": 0, "week_net": 0}
        try:
            r = conn.execute("SELECT COUNT(*), COALESCE(SUM(current_views),0) FROM channel_tracking").fetchone()
            stats["channel_stats"] = {"total_posts": r[0] if r else 0, "total_views": r[1] if r else 0, "avg_views": r[1] // max(r[0], 1) if r else 0}
        except Exception:
            stats["channel_stats"] = {"total_posts": 0, "total_views": 0, "avg_views": 0}
    except Exception as e:
        stats["error"] = str(e)
    stats["vps"] = get_vps_status()
    return jsonify({"ok": True, "data": stats})

@app.route("/api/stats/users")
@login_required
def api_stats_users():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "").strip()
    sort = request.args.get("sort", "last_active")
    order = request.args.get("order", "desc")
    conn = get_db()
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE name LIKE ? OR CAST(uid AS TEXT) LIKE ?"
        params = [f"%{search}%", f"%{search}%"]
    allowed_sorts = {"uid", "name", "first_seen", "last_active", "group_messages", "private_messages"}
    if sort not in allowed_sorts:
        sort = "last_active"
    allowed_orders = {"asc", "desc"}
    if order.lower() not in allowed_orders:
        order = "desc"
    else:
        order = order.lower()
    order_by_map = {
        ("uid", "asc"): "uid ASC", ("uid", "desc"): "uid DESC",
        ("name", "asc"): "name ASC", ("name", "desc"): "name DESC",
        ("first_seen", "asc"): "first_seen ASC", ("first_seen", "desc"): "first_seen DESC",
        ("last_active", "asc"): "last_active ASC", ("last_active", "desc"): "last_active DESC",
        ("group_messages", "asc"): "group_messages ASC", ("group_messages", "desc"): "group_messages DESC",
        ("private_messages", "asc"): "private_messages ASC", ("private_messages", "desc"): "private_messages DESC",
    }
    order_by = order_by_map.get((sort, order), "last_active DESC")
    # 【v4.5.35修复】where_clause 使用参数化查询，order_by 使用白名单映射，双重防护
    total = conn.execute(f"SELECT COUNT(*) FROM users {where_clause}", params).fetchone()[0]
    offset = (page - 1) * per_page
    rows = conn.execute(f"SELECT * FROM users {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?", params + [per_page, offset]).fetchall()
    users = [dict(r) for r in rows]
    for u in users:
        r = conn.execute("SELECT level, points FROM user_levels WHERE uid = ?", (u["uid"],)).fetchone()
        u["level"] = r[0] if r else 0
        u["points"] = r[1] if r else 0
    pagination = {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page if total > 0 else 0}
    return jsonify({"ok": True, "data": {"users": users, "pagination": pagination}})

@app.route("/api/groups")
@login_required
def api_groups():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT chat_id, title, type,
                   COALESCE(SUM(joined_count), 0) as joined,
                   COALESCE(SUM(left_count), 0) as left_count,
                   COALESCE(SUM(net_count), 0) as net_count,
                   COUNT(*) as msg_count
            FROM group_events
            WHERE date >= date('now', '-30 days')
            GROUP BY chat_id, title, type
        """).fetchall()
        groups = [{"chat_id": r[0], "title": r[1], "type": r[2],
                   "joined": r[3], "left": r[4], "net": r[5], "msg_count": r[6]} for r in rows]
        return jsonify({"ok": True, "data": {"groups": groups}})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/logs")
@login_required
def api_logs():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM reply_tracking").fetchone()[0]
        offset = (page - 1) * per_page
        rows = conn.execute("""
            SELECT bot_msg_id, chat_id, user_msg_id, ts, replied
            FROM reply_tracking ORDER BY ts DESC LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        logs = [{"bot_msg_id": r[0], "chat_id": r[1], "user_msg_id": r[2],
                 "ts": r[3], "replied": r[4]} for r in rows]
        pagination = {"page": page, "per_page": per_page, "total": total,
                      "pages": (total + per_page - 1) // per_page if total > 0 else 0}
        return jsonify({"ok": True, "data": {"logs": logs, "pagination": pagination}})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/logs/search")
@login_required
def api_logs_search():
    keyword = request.args.get("keyword", "").strip()[:50]
    if not keyword:
        return jsonify({"ok": False, "msg": "关键词不能为空"}), 400
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT bot_msg_id, chat_id, user_msg_id, ts, replied
            FROM reply_tracking
            WHERE CAST(bot_msg_id AS TEXT) LIKE ? OR CAST(chat_id AS TEXT) LIKE ?
            ORDER BY ts DESC LIMIT 100
        """, (f"%{keyword}%", f"%{keyword}%")).fetchall()
        logs = [{"bot_msg_id": r[0], "chat_id": r[1], "user_msg_id": r[2],
                 "ts": r[3], "replied": r[4]} for r in rows]
        return jsonify({"ok": True, "data": {"logs": logs, "total": len(logs)}})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/config")
@login_required
def api_config():
    cfg = read_config()
    safe_cfg = {k: v for k, v in cfg.items() if not any(s in k.lower() for s in ['key', 'token', 'password', 'secret'])}
    return jsonify({"ok": True, "data": {"config": safe_cfg}})

@app.route("/api/config/update", methods=["POST"])
@login_required
def api_config_update():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "无效的请求数据"}), 400
    key = data.get("key", "").strip()
    value = data.get("value")
    if not key:
        return jsonify({"ok": False, "msg": "配置项名称不能为空"}), 400
    allowed_types = (str, int, float, bool, list, dict, type(None))
    if not isinstance(value, allowed_types):
        return jsonify({"ok": False, "msg": f"不支持的值类型: {type(value).__name__}"}), 400
    forbidden_exact = {'token', 'password', 'secret', 'api_key', 'admin_id', 'group_id'}
    forbidden_words = {'token', 'password', 'secret'}
    key_parts = set(key.lower().split('_'))
    if key.lower() in forbidden_exact or key_parts & forbidden_words:
        return jsonify({"ok": False, "msg": "禁止修改敏感配置项"}), 403
    cfg = read_config()
    cfg[key] = value
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"配置项 {key} 已更新（⚠️ 需重启Bot或等待自动重载后生效）"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500


class _DashboardFakeMessage:
    def __init__(self, text: str):
        self.text = text


class _DashboardReplyProxy:
    def __init__(self):
        self.messages = []

    def reply_and_track(self, _message, text: str):
        self.messages.append(text)


@app.route("/api/config/natural", methods=["POST"])
@login_required
def api_config_natural():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "msg": "请输入要修改的内容"}), 400

    cfg = read_config()

    def _save():
        return write_config(cfg)

    proxy = _DashboardReplyProxy()
    try:
        handled = handle_natural_admin(
            bot=None,
            m=_DashboardFakeMessage(text),
            config=cfg,
            save_config_fn=_save,
            mory_bot=proxy,
            is_admin=True,
        )
    except AttributeError as e:
        return jsonify({"ok": False, "msg": "该指令暂不支持在网页端使用（缺少Bot上下文），请在Telegram中使用"}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": f"处理失败：{str(e)[:100]}"}), 500
    if not handled:
        return jsonify({"ok": False, "msg": "这句话我还没听明白，换个更明确的说法试试"}), 400
    _sensitive_keys = ['key', 'token', 'password', 'secret']
    safe_cfg = {k: v for k, v in cfg.items() if not any(s in k.lower() for s in _sensitive_keys)}
    return jsonify({
        "ok": True,
        "msg": (proxy.messages[-1] if proxy.messages else "已处理") + "（⚠️ 需重启Bot生效）",
        "data": {"config": safe_cfg},
    })

@app.route("/api/report/download")
@login_required
def api_report_download():
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT uid, name, group_messages, private_messages, last_active, tags
            FROM users ORDER BY last_active DESC LIMIT 1000
        """).fetchall()
        import io, csv
        output = io.StringIO()
        output.write('\ufeff')
        writer = csv.writer(output)
        writer.writerow(["UID", "用户名", "群消息", "私聊消息", "最后活跃", "标签"])
        for u in users:
            writer.writerow([u[0], u[1] or '', u[2], u[3], datetime.fromtimestamp(u[4], _CST).strftime("%Y-%m-%d %H:%M") if u[4] else '', u[5] or ''])
        return Response(output.getvalue(), mimetype='text/csv',
                       headers={"Content-Disposition": "attachment;filename=mory_report.csv"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/channels")
@login_required
def api_channels():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT chat_id, msg_id, posted_at, current_views
            FROM channel_tracking ORDER BY posted_at DESC LIMIT 50
        """).fetchall()
        channels = [{"chat_id": r[0], "msg_id": r[1], "posted_at": r[2], "views": r[3]} for r in rows]
        return jsonify({"ok": True, "data": {"channels": channels}})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

def _get_current_model_name(cfg):
    idx = cfg.get("CURRENT_MODEL_INDEX", 0)
    pools = cfg.get("MODEL_POOLS", {})
    llm_pool = pools.get("llm", pools.get("llm_light", []))
    if isinstance(llm_pool, list) and 0 <= idx < len(llm_pool):
        return llm_pool[idx].get("name", f"模型#{idx}")
    return f"模型#{idx}"

@app.route("/api/bot/status")
@login_required
def api_bot_status():
    cfg = read_config()
    vps = get_vps_status()
    from version import VERSION
    status = {
        "version": VERSION,
        "bot_running": vps.get("bot_running", False),
        "bot_pid": vps.get("bot_pid"),
        "bot_memory": vps.get("bot_memory", "N/A"),
        "uptime": vps.get("uptime", "N/A"),
        "current_model_index": cfg.get("CURRENT_MODEL_INDEX", 0),
        "current_model_name": _get_current_model_name(cfg),
        "reply_chance": cfg.get("REPLY_CHANCE", 10),
        "blacklisted_models": cfg.get("BLACKLISTED_MODELS", []),
        "group_id": cfg.get("GROUP_ID", 0),
        "admin_ids": cfg.get("ADMIN_IDS", []),
    }
    return jsonify({"ok": True, "data": status})

@app.route("/api/models/status")
@login_required
def api_models_status():
    cfg = read_config()
    pools = cfg.get("MODEL_POOLS", {})
    blacklisted = set(cfg.get("BLACKLISTED_MODELS", []))
    result = {}
    now_str = datetime.now(_CST).strftime("%Y-%m-%d")
    for pool_name, models in pools.items():
        pool_info = []
        for m in (models or []):
            expire = m.get("expire", "2099-12-31")
            is_blacked = m.get("name", "") in blacklisted
            days_left = 9999
            try:
                from datetime import date as _date
                exp_d = _date.fromisoformat(expire)
                days_left = (exp_d - _date.today()).days
            except Exception:
                pass
            pool_info.append({
                "name": m.get("name", "?"),
                "desc": m.get("desc", ""),
                "expire": expire,
                "days_left": days_left,
                "blacklisted": is_blacked,
                "status": "黑名单" if is_blacked else ("即将过期" if days_left <= 7 else "正常"),
            })
        result[pool_name] = pool_info
    tier_routing = cfg.get("MODE_ROUTING", {})
    result["_mode_routing"] = tier_routing
    return jsonify({"ok": True, "data": result})

@app.route("/api/tasks/status")
@login_required
def api_tasks_status():
    conn = get_db()
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    task_defs = [
        ("morning_greeting", "早安问候", "08:05"),
        ("morning_news", "早间新闻", "09:05"),
        ("daily_report", "每日报告", "09:10"),
        ("afternoon_greeting", "午安问候", "12:35"),
        ("afternoon_news", "午间新闻", "13:05"),
        ("tarot_chatup", "塔罗搭讪", "15:00"),
        ("trendradar_broadcast", "TrendRadar播报", "18:00"),
        ("evening_news", "晚间新闻", "20:35"),
        ("goodnight_greeting", "晚安问候", "23:05"),
        ("channel_views", "频道浏览量", "每小时"),
        ("burn_cleanup", "阅后即焚清理", "每10分钟"),
    ]
    tasks = []
    for key, name, schedule in task_defs:
        done_today = False
        exec_time = ""
        try:
            row = conn.execute(
                "SELECT exec_date, exec_ts FROM task_log WHERE task_key=? AND exec_date=? ORDER BY exec_ts DESC LIMIT 1",
                (key, today)
            ).fetchone()
            if row:
                done_today = True
                if row[1]:
                    try:
                        exec_time = datetime.fromtimestamp(row[1], _CST).strftime("%H:%M:%S")
                    except Exception:
                        exec_time = str(row[1])
        except Exception:
            pass
        tasks.append({
            "key": key,
            "name": name,
            "schedule": schedule,
            "done_today": done_today,
            "exec_time": exec_time,
        })
    return jsonify({"ok": True, "data": {"tasks": tasks, "date": today}})

@app.route("/api/group/settings")
@login_required
def api_group_settings():
    cfg = read_config()
    settings = {
        "banned_words": cfg.get("BANNED_WORDS", []),
        "hate_keywords": cfg.get("HATE_KEYWORDS", []),
        "spam_limit": cfg.get("SPAM_LIMIT", {"messages_per_minute": 10, "ban_minutes": 5}),
        "welcome_text": cfg.get("WELCOME_TEXT", ""),
        "welcome_msg": cfg.get("WELCOME_MSG", True),
        "auto_mute_names": cfg.get("AUTO_MUTE_NAMES", []),
        "spam_ban_duration": cfg.get("BAN_DURATION_DEFAULT", 5),
        "max_requests_per_user": cfg.get("MAX_REQUESTS_PER_USER", 100),
    }
    return jsonify({"ok": True, "data": settings})

@app.route("/api/group/settings/update", methods=["POST"])
@login_required
def api_group_settings_update():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "无效的请求数据"}), 400
    key = data.get("key", "").strip()
    value = data.get("value")
    if not key:
        return jsonify({"ok": False, "msg": "配置项名称不能为空"}), 400
    allowed_keys = {
        "BANNED_WORDS", "HATE_KEYWORDS", "SPAM_LIMIT", "WELCOME_TEXT",
        "WELCOME_MSG", "AUTO_MUTE_NAMES", "BAN_DURATION_DEFAULT",
        "MAX_REQUESTS_PER_USER"
    }
    if key not in allowed_keys:
        return jsonify({"ok": False, "msg": f"不允许修改 {key}"}), 403
    cfg = read_config()
    cfg[key] = value
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"已更新 {key}（⚠️ 需重启Bot或等待自动重载后生效）"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500

@app.route("/api/feedback/stats")
@login_required
def api_feedback_stats():
    conn = get_db()
    try:
        row = conn.execute("SELECT feedback, COUNT(*) FROM reply_feedback GROUP BY feedback").fetchall()
        counts = {"like": 0, "dislike": 0}
        for r in row:
            if r[0] in counts:
                counts[r[0]] = r[1]
        total = counts["like"] + counts["dislike"]
        rate = round(counts["like"] / total * 100, 1) if total > 0 else 0
    except Exception:
        counts, total, rate = {"like": 0, "dislike": 0}, 0, 0
    try:
        recent = conn.execute("SELECT bot_msg_id, chat_id, user_id, feedback, ts FROM reply_feedback ORDER BY ts DESC LIMIT 20").fetchall()
        recent_list = [{"bot_msg_id": r[0], "chat_id": r[1], "user_id": r[2], "feedback": r[3], "ts": r[4]} for r in recent]
    except Exception:
        recent_list = []
    return jsonify({"ok": True, "data": {"like": counts["like"], "dislike": counts["dislike"], "total": total, "satisfaction_rate": rate, "recent": recent_list}})

@app.route("/api/help/docs")
@login_required
def api_help_docs():
    docs = {
        "user_commands": [
            {"cmd": "直接发消息", "desc": "跟Mory聊天，自动回复", "example": "你好呀"},
            {"cmd": "签到", "desc": "每日签到领积分", "example": "签到"},
            {"cmd": "积分/排行榜", "desc": "查看积分和排名", "example": "排行榜"},
            {"cmd": "我的等级", "desc": "查看当前等级", "example": "我的等级"},
            {"cmd": "碎片寻宝", "desc": "猜暗号赢积分", "example": "碎片寻宝"},
            {"cmd": "塔罗牌", "desc": "抽一张塔罗牌", "example": "塔罗牌"},
            {"cmd": "叫醒服务 HH:MM", "desc": "设置叫醒时间", "example": "叫醒服务 07:30"},
            {"cmd": "👍👎按钮", "desc": "对Bot回复点反馈", "example": "点击Bot消息下方按钮"},
        ],
        "admin_commands": [
            {"section": "配置管理", "items": [
                {"cmd": "查看配置", "desc": "查看所有配置状态"},
                {"cmd": "设置概率 [0-100]", "desc": "修改群聊随机回复概率"},
                {"cmd": "开启/关闭 [功能名]", "desc": "开关功能（早安/晚安/新闻/签到等）"},
            ]},
            {"section": "人设与知识", "items": [
                {"cmd": "设置人设 [文本]", "desc": "修改机器人核心人设"},
                {"cmd": "投喂资料 [文本]", "desc": "追加业务知识库"},
                {"cmd": "学知识 [内容]", "desc": "让机器人学习新知识"},
                {"cmd": "忘记 [关键词]", "desc": "从知识库移除内容"},
            ]},
            {"section": "模型管理", "items": [
                {"cmd": "当前模型", "desc": "查看所有模型和当前使用"},
                {"cmd": "切换模型 [名称]", "desc": "手动切换AI模型"},
                {"cmd": "模型恢复 [模型名]", "desc": "从黑名单恢复模型"},
            ]},
            {"section": "群管理", "items": [
                {"cmd": "增加敏感词 [词]", "desc": "添加违禁词（支持批量，逗号分隔）"},
                {"cmd": "删除敏感词 [词]", "desc": "移除违禁词"},
                {"cmd": "增加反感词 [词]", "desc": "添加反感关键词"},
                {"cmd": "/blacklist @ID", "desc": "拉黑用户"},
                {"cmd": "/mute @ID 分钟", "desc": "禁言用户"},
                {"cmd": "健康检查", "desc": "一键诊断Bot运行状态"},
            ]},
            {"section": "动态进化", "items": [
                {"cmd": "加热词 [词汇...]", "desc": "给热词库追加新词汇"},
                {"cmd": "改风格 [描述]", "desc": "快速调整说话风格"},
                {"cmd": "进化 [指令]", "desc": "高级进化：直接修改任意配置项"},
            ]},
        ],
        "dashboard_guide": [
            {"page": "运行状态", "desc": "Bot运行状态、当前模型、黑名单等"},
            {"page": "模型总览", "desc": "6池模型状态、到期倒计时、三层路由"},
            {"page": "定时任务", "desc": "11项定时任务执行状态"},
            {"page": "群管设置", "desc": "敏感词/刷屏/禁言/欢迎语可视化管理"},
            {"page": "系统配置", "desc": "表单式配置编辑器+自然语言配置"},
            {"page": "用户反馈", "desc": "👍👎满意度统计"},
        ],
    }
    return jsonify({"ok": True, "data": docs})

@app.route("/api/user/analytics")
@login_required
def api_user_analytics():
    conn = get_db()
    now_ts = int(datetime.now(_CST).timestamp())
    try:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except Exception:
        total_users = 0
    try:
        dau = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=?", (now_ts - 86400,)).fetchone()[0]
    except Exception:
        dau = 0
    try:
        wau = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=?", (now_ts - 7 * 86400,)).fetchone()[0]
    except Exception:
        wau = 0
    try:
        mau = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=?", (now_ts - 30 * 86400,)).fetchone()[0]
    except Exception:
        mau = 0
    try:
        churn_risk = conn.execute("SELECT COUNT(*) FROM users WHERE last_active<? AND last_active>0", (now_ts - 14 * 86400,)).fetchone()[0]
    except Exception:
        churn_risk = 0
    try:
        lost = conn.execute("SELECT COUNT(*) FROM users WHERE last_active<? AND last_active>0", (now_ts - 30 * 86400,)).fetchone()[0]
    except Exception:
        lost = 0
    trend = []
    try:
        for i in range(6, -1, -1):
            day_str = (datetime.now(_CST) - timedelta(days=i)).strftime("%Y-%m-%d")
            day_start = int(datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
            day_end = day_start + 86400
            cnt = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=? AND last_active<?", (day_start, day_end)).fetchone()[0]
            trend.append({"date": day_str, "dau": cnt})
    except Exception:
        pass
    top_users = []
    try:
        rows = conn.execute("SELECT uid, name, group_messages, last_active FROM users ORDER BY group_messages DESC LIMIT 10").fetchall()
        for r in rows:
            top_users.append({"uid": r[0], "name": r[1] or "未知", "messages": r[2], "last_active": r[3]})
    except Exception:
        pass
    return jsonify({"ok": True, "data": {
        "total_users": total_users, "dau": dau, "wau": wau, "mau": mau,
        "churn_risk": churn_risk, "lost": lost,
        "dau_trend": trend, "top_users": top_users,
    }})

# ============ 前端页面 ============
HTML_PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mory Assistant - 私域可视化面板</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
* { font-family: 'Inter', system-ui, -apple-system, sans-serif; box-sizing: border-box; }
body { margin: 0; padding: 0; background: #0f0f1a; color: #e2e8f0; min-height: 100vh; }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #1e1e2e; border-radius: 3px; }
::-webkit-scrollbar-thumb { background: #4a4a6a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #6a6a8a; }

.login-container { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%); }
.login-box { background: rgba(30, 30, 46, 0.95); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px; padding: 48px; width: 100%; max-width: 420px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
.login-title { font-size: 28px; font-weight: 700; text-align: center; margin: 0 0 8px 0; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.login-subtitle { text-align: center; color: #94a3b8; margin: 0 0 32px 0; font-size: 14px; }
.input-group { margin-bottom: 20px; }
.input-group label { display: block; color: #94a3b8; font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.input-field { width: 100%; padding: 14px 16px; background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; color: #e2e8f0; font-size: 15px; transition: all 0.3s; }
.input-field:focus { outline: none; border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2); }
.login-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #60a5fa, #3b82f6); border: none; border-radius: 12px; color: white; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.3s; }
.login-btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3); }

.dashboard { display: flex; min-height: 100vh; }
.sidebar { width: 260px; background: #1e1e2e; border-right: 1px solid rgba(255, 255, 255, 0.06); display: flex; flex-direction: column; position: fixed; height: 100vh; z-index: 100; }
.sidebar-header { padding: 24px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.sidebar-logo { display: flex; align-items: center; gap: 12px; }
.sidebar-logo-icon { width: 40px; height: 40px; background: linear-gradient(135deg, #60a5fa, #a78bfa); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 20px; }
.sidebar-logo-text h1 { font-size: 18px; font-weight: 700; color: #fff; margin: 0; }
.sidebar-logo-text span { font-size: 12px; color: #6b7280; }
.sidebar-nav { flex: 1; padding: 16px 12px; overflow-y: auto; }
.nav-section { margin-bottom: 24px; }
.nav-section-title { font-size: 11px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; padding: 0 12px; margin-bottom: 8px; }
.nav-item { display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 10px; color: #94a3b8; text-decoration: none; transition: all 0.2s; font-size: 14px; font-weight: 500; cursor: pointer; }
.nav-item:hover { background: rgba(255, 255, 255, 0.05); color: #e2e8f0; }
.nav-item.active { background: linear-gradient(135deg, rgba(96, 165, 250, 0.2), rgba(167, 139, 250, 0.2)); color: #60a5fa; border-left: 3px solid #60a5fa; }
.nav-item svg { width: 20px; height: 20px; stroke-width: 1.5; }

.main-content { flex: 1; margin-left: 260px; min-height: 100vh; }
.top-bar { background: rgba(30, 30, 46, 0.8); backdrop-filter: blur(10px); border-bottom: 1px solid rgba(255, 255, 255, 0.06); padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 50; }
.top-bar-left { display: flex; align-items: center; gap: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: #fff; }
.top-bar-right { display: flex; align-items: center; gap: 16px; }
.status-pill { display: flex; align-items: center; gap: 8px; padding: 8px 16px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 20px; font-size: 13px; color: #10b981; }
.status-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.icon-btn { width: 40px; height: 40px; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #94a3b8; cursor: pointer; transition: all 0.2s; }
.icon-btn:hover { background: rgba(255, 255, 255, 0.1); color: #e2e8f0; }

.page-content { padding: 32px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; }
.page-header h2 { font-size: 24px; font-weight: 700; color: #fff; margin: 0; }
.page-header p { color: #6b7280; font-size: 14px; margin: 4px 0 0 0; }

.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 24px; margin-bottom: 32px; }
.stat-card { background: linear-gradient(135deg, #1e1e2e, #252540); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 24px; position: relative; overflow: hidden; }
.stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, var(--accent-color), transparent); }
.stat-card.blue { --accent-color: #60a5fa; }
.stat-card.green { --accent-color: #10b981; }
.stat-card.purple { --accent-color: #a78bfa; }
.stat-card.orange { --accent-color: #f59e0b; }
.stat-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; font-size: 24px; background: rgba(255, 255, 255, 0.05); }
.stat-value { font-size: 36px; font-weight: 700; color: #fff; font-family: 'JetBrains Mono', monospace; margin-bottom: 4px; line-height: 1; }
.stat-label { font-size: 14px; color: #6b7280; font-weight: 500; }

.charts-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; margin-bottom: 32px; }
.chart-card { background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 24px; }
.chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.chart-title { font-size: 16px; font-weight: 600; color: #fff; }
.chart-container { height: 280px; position: relative; }

.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 12px 16px; font-size: 12px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.data-table td { padding: 16px; font-size: 14px; color: #e2e8f0; border-bottom: 1px solid rgba(255, 255, 255, 0.03); }
.data-table tr:hover { background: rgba(255, 255, 255, 0.02); }
.data-table .user-cell { display: flex; align-items: center; gap: 12px; }
.user-avatar { width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #60a5fa, #a78bfa); display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; }
.user-info .name { font-weight: 500; color: #fff; }
.user-info .uid { font-size: 12px; color: #6b7280; }

.badge { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 500; }
.badge-success { background: rgba(16, 185, 129, 0.2); color: #10b981; }
.badge-warning { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
.badge-info { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border-radius: 10px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; transition: all 0.2s; }
.btn-primary { background: linear-gradient(135deg, #60a5fa, #3b82f6); color: white; }
.btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 16px rgba(59, 130, 246, 0.3); }
.btn-secondary { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); color: #e2e8f0; }
.btn-secondary:hover { background: rgba(255, 255, 255, 0.1); }

.card { background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 24px; }

.toast { position: fixed; top: 24px; right: 24px; padding: 16px 24px; border-radius: 12px; color: white; font-weight: 500; animation: slideIn 0.3s ease; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3); z-index: 9999; }
.toast-success { background: linear-gradient(135deg, #10b981, #059669); }
.toast-error { background: linear-gradient(135deg, #ef4444, #dc2626); }
.toast-info { background: linear-gradient(135deg, #60a5fa, #3b82f6); }
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

.loading { display: flex; align-items: center; justify-content: center; padding: 60px; color: #6b7280; }
.loading::after { content: ''; width: 24px; height: 24px; border: 3px solid rgba(255, 255, 255, 0.1); border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; margin-left: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }

.empty-state { text-align: center; padding: 60px; color: #6b7280; }
.empty-state h3 { font-size: 18px; color: #94a3b8; margin-bottom: 8px; }

.search-box { display: flex; align-items: center; gap: 12px; background: #252540; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 8px 16px; margin-bottom: 24px; }
.search-box input { background: transparent; border: none; color: #e2e8f0; font-size: 14px; flex: 1; outline: none; }
.search-box input::placeholder { color: #6b7280; }
.search-box svg { color: #6b7280; width: 20px; height: 20px; }

.pagination { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 32px; }
.pagination-btn { min-width: 40px; height: 40px; padding: 0 12px; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; color: #e2e8f0; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; }
.pagination-btn:hover { background: rgba(255, 255, 255, 0.1); }
.pagination-btn.active { background: #60a5fa; border-color: #60a5fa; color: white; }

@media (max-width: 1200px) { .charts-grid { grid-template-columns: 1fr; } }
@media (max-width: 768px) { .sidebar { transform: translateX(-100%); transition: transform 0.3s; } .sidebar.open { transform: translateX(0); } .main-content { margin-left: 0; } .stats-grid { grid-template-columns: 1fr; } .page-content { padding: 16px; } .top-bar { padding: 12px 16px; } }
</style>
</head>
<body>
<div id="app"></div>
<script>
const API_BASE = '';

async function loadVersion() {
  try {
    const d = await api('/api/bot/status');
    const el = document.getElementById('sidebarVersion');
    if (el) el.textContent = d.data.version || '?';
  } catch(e) {}
}

let currentPage = 'overview';
let currentUserPage = 1;
let searchQuery = '';
let sortField = 'last_active';
let sortOrder = 'desc';
let _chartData = null;

function formatTime(ts) {
  if (!ts) return 'N/A';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatNumber(n) {
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n;
}

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function showToast(msg, type = 'info') {
  const c = document.createElement('div');
  c.className = `toast toast-${type}`;
  c.textContent = msg;
  document.body.appendChild(c);
  setTimeout(() => c.remove(), 3000);
}

async function api(path, opts = {}) {
  try {
    const res = await fetch(API_BASE + path, opts);
    const d = await res.json();
    if (!d.ok) throw new Error(d.msg || 'API Error');
    return d;
  } catch (e) {
    showToast(e.message, 'error');
    throw e;
  }
}

async function checkAuth() {
  try {
    const d = await api('/api/check');
    return d.ok;
  } catch {
    return false;
  }
}

async function doLogin() {
  const pw = document.getElementById('password').value;
  if (!pw) return;
  try {
    const d = await fetch('/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ password: pw })
    });
    const r = await d.json();
    if (r.ok) {
      showToast('登录成功', 'success');
      window.location.reload();
    } else {
      showToast(r.msg, 'error');
    }
  } catch (e) {
    showToast('登录失败', 'error');
  }
}

async function doLogout() {
  try {
    await api('/api/logout', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    window.location.reload();
  } catch {
    window.location.reload();
  }
}

async function loadStats() {
  try {
    const d = await api('/api/stats/overview');
    _chartData = d.data;
    renderStats(d.data);
  } catch (e) {
    console.error(e);
  }
}

function renderStats(data) {
  document.getElementById('totalUsers').textContent = formatNumber(data.total_users || 0);
  document.getElementById('todayActive').textContent = formatNumber(data.today_active || 0);
  document.getElementById('weekActive').textContent = formatNumber(data.week_active || 0);
  document.getElementById('totalMsgs').textContent = formatNumber((data.total_group_msgs || 0) + (data.total_private_msgs || 0));
  const vps = data.vps || {};
  const statusEl = document.getElementById('botStatus');
  const statusTextEl = document.getElementById('botStatusText');
  const statusDotEl = document.getElementById('statusDot');
  if (vps.bot_running) {
    statusEl.className = 'status-pill';
    statusTextEl.textContent = '运行中';
    statusDotEl.className = 'status-dot';
  } else {
    statusEl.className = 'status-pill';
    statusTextEl.textContent = '已停止';
    statusDotEl.className = 'status-dot';
  }
  document.getElementById('botUptime').textContent = vps.uptime || 'N/A';
}

async function loadUsers(page = 1) {
  try {
    currentUserPage = page;
    const d = await api(`/api/stats/users?page=${page}&per_page=10&search=${encodeURIComponent(searchQuery)}&sort=${sortField}&order=${sortOrder}`);
    renderUserTable(d.data);
  } catch (e) {
    console.error(e);
  }
}

function renderUserTable(data) {
  const tb = document.getElementById('userTableBody');
  if (!tb) return;
  if (data.users.length === 0) {
    tb.innerHTML = '<tr><td colspan="7" class="empty-state"><h3>暂无用户数据</h3></td></tr>';
    return;
  }
  tb.innerHTML = data.users.map(u => `
    <tr>
      <td>
        <div class="user-cell">
          <div class="user-avatar">${escHtml((u.name || 'U')[0].toUpperCase())}</div>
          <div class="user-info">
            <div class="name">${escHtml(u.name || '未知用户')}</div>
            <div class="uid">UID: ${u.uid || u.user_id}</div>
          </div>
        </div>
      </td>
      <td>${u.level || 1}</td>
      <td>${u.points || 0}</td>
      <td>${u.group_messages || 0}</td>
      <td>${u.private_messages || 0}</td>
      <td><span class="badge ${getStatusClass(u.conversion_status)}">${escHtml(u.conversion_status || '新用户')}</span></td>
      <td>${formatTime(u.last_active)}</td>
    </tr>
  `).join('');
  renderPagination(data.pagination);
}

function getStatusClass(s) {
  if (s === 'paid' || s === 'vip') return 'badge-success';
  if (s === 'interested') return 'badge-info';
  if (s === 'cold') return 'badge-warning';
  return 'badge-info';
}

function renderPagination(p) {
  const pm = document.getElementById('pagination');
  if (!pm || !p) return;
  let html = '';
  for (let i = 1; i <= p.pages; i++) {
    html += `<button class="pagination-btn ${i === p.page ? 'active' : ''}" onclick="loadUsers(${i})">${i}</button>`;
  }
  pm.innerHTML = html;
}

function handleSearch() {
  searchQuery = document.getElementById('searchInput').value;
  loadUsers(1);
}

function handleSort(field) {
  if (sortField === field) {
    sortOrder = sortOrder === 'desc' ? 'asc' : 'desc';
  } else {
    sortField = field;
    sortOrder = 'desc';
  }
  loadUsers(1);
}

const _pageTitles = {
  overview: '数据概览', users: '用户管理', groups: '群组数据',
  status: '运行状态', models: '模型中心', tasks: '定时任务',
  groupmgr: '群管设置', feedback: '用户反馈', userprofile: '用户画像',
  config: '系统配置', reports: '运营报表', logs: '日志查看', helpcenter: '帮助中心'
};
function switchTab(tab) {
  document.querySelectorAll('.nav-item').forEach(t => t.classList.remove('active'));
  const navItem = document.querySelector(`.nav-item[onclick*="${tab}"]`);
  if (navItem) navItem.classList.add('active');
  currentPage = tab;
  const titleEl = document.querySelector('.page-title');
  if (titleEl) titleEl.textContent = _pageTitles[tab] || tab;
  renderPage();
}

function renderPage() {
  const content = document.getElementById('mainContent');
  if (!content) return;
  
  switch (currentPage) {
    case 'status':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>运行状态</h2>
            <p>Bot实时健康监控</p>
          </div>
          <button class="btn btn-secondary" onclick="loadBotStatus()">刷新</button>
        </div>
        <div id="statusContent" class="loading">加载中...</div>
      `;
      loadBotStatus();
      break;

    case 'models':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>模型中心</h2>
            <p>多模型池状态与路由管理</p>
          </div>
          <button class="btn btn-secondary" onclick="loadModels()">刷新</button>
        </div>
        <div id="modelsContent" class="loading">加载中...</div>
      `;
      loadModels();
      break;

    case 'tasks':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>定时任务</h2>
            <p>今日任务执行状态一览</p>
          </div>
          <button class="btn btn-secondary" onclick="loadTasks()">刷新</button>
        </div>
        <div id="tasksContent" class="loading">加载中...</div>
      `;
      loadTasks();
      break;

    case 'groupmgr':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>群管设置</h2>
            <p>敏感词/刷屏/禁言/欢迎语可视化管理</p>
          </div>
          <button class="btn btn-secondary" onclick="loadGroupMgr()">刷新</button>
        </div>
        <div id="groupMgrContent" class="loading">加载中...</div>
      `;
      loadGroupMgr();
      break;

    case 'feedback':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>用户反馈</h2>
            <p>👍👎满意度统计与反馈详情</p>
          </div>
          <button class="btn btn-secondary" onclick="loadFeedback()">刷新</button>
        </div>
        <div id="feedbackContent" class="loading">加载中...</div>
      `;
      loadFeedback();
      break;

    case 'helpcenter':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>帮助中心</h2>
            <p>使用手册与命令参考</p>
          </div>
        </div>
        <div id="helpContent" class="loading">加载中...</div>
      `;
      loadHelpCenter();
      break;

    case 'userprofile':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>用户画像</h2>
            <p>活跃趋势/分布/流失预警</p>
          </div>
          <button class="btn btn-secondary" onclick="loadUserProfile()">刷新</button>
        </div>
        <div id="userProfileContent" class="loading">加载中...</div>
      `;
      loadUserProfile();
      break;

    case 'overview':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>数据概览</h2>
            <p>实时监控核心指标</p>
          </div>
          <div style="display: flex; gap: 12px">
            <button class="btn btn-secondary" onclick="loadStats()">刷新数据</button>
          </div>
        </div>
        <div class="stats-grid">
          <div class="stat-card blue">
            <div class="stat-icon">👥</div>
            <div class="stat-value" id="totalUsers">-</div>
            <div class="stat-label">总用户数</div>
          </div>
          <div class="stat-card green">
            <div class="stat-icon">🟢</div>
            <div class="stat-value" id="todayActive">-</div>
            <div class="stat-label">今日活跃</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">📅</div>
            <div class="stat-value" id="weekActive">-</div>
            <div class="stat-label">7日活跃</div>
          </div>
          <div class="stat-card orange">
            <div class="stat-icon">💬</div>
            <div class="stat-value" id="totalMsgs">-</div>
            <div class="stat-label">消息总量</div>
          </div>
        </div>
        <div class="charts-grid">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">用户趋势（7天）</span>
            </div>
            <div class="chart-container">
              <canvas id="trendChart"></canvas>
            </div>
          </div>
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">时段分布</span>
            </div>
            <div class="chart-container">
              <canvas id="hourlyChart"></canvas>
            </div>
          </div>
        </div>
        <div class="charts-grid" style="margin-top: 0;">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">转化漏斗</span>
            </div>
            <div class="chart-container">
              <canvas id="funnelChart"></canvas>
            </div>
          </div>
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">群组与频道</span>
            </div>
            <div id="groupChannelStats" style="padding: 8px 0;"></div>
          </div>
        </div>
      `;
      loadStats().then(() => { renderCharts(); renderFunnel(); renderGroupChannel(); });
      break;
    
    case 'users':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>用户管理</h2>
            <p>查看和管理用户数据</p>
          </div>
        </div>
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <input type="text" id="searchInput" placeholder="搜索用户名或UID..." onkeyup="if(event.key === 'Enter') handleSearch()">
          <button class="btn btn-primary" onclick="handleSearch()">搜索</button>
        </div>
        <div class="card">
          <table class="data-table">
            <thead>
              <tr>
                <th onclick="handleSort('name')">用户</th>
                <th onclick="handleSort('level')">等级</th>
                <th>积分</th>
                <th onclick="handleSort('group_messages')">群消息</th>
                <th>私聊消息</th>
                <th>状态</th>
                <th>最后活跃</th>
              </tr>
            </thead>
            <tbody id="userTableBody">
              <tr>
                <td colspan="7" class="loading">加载中...</td>
              </tr>
            </tbody>
          </table>
          <div id="pagination" class="pagination"></div>
        </div>
      `;
      loadUsers();
      break;
    
    case 'groups':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>群组数据</h2>
            <p>群组活跃统计</p>
          </div>
          <button class="btn btn-secondary" onclick="loadGroups()">刷新</button>
        </div>
        <div id="groupContent" class="loading">加载中...</div>
      `;
      loadGroups();
      break;
    
    case 'config':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>系统配置</h2>
            <p>管理和配置系统参数</p>
          </div>
          <button class="btn btn-secondary" onclick="loadConfig()">刷新</button>
        </div>
        <div class="card" style="margin-bottom: 24px;">
          <h3 style="color: #fff; margin-bottom: 16px;">🔧 自然语言配置</h3>
          <div style="display: flex; gap: 12px; margin-bottom: 16px;">
            <input type="text" id="nlConfigInput" class="input-field" placeholder="例如：将早安问候时间改为8:30" style="flex: 1;">
            <button class="btn btn-primary" onclick="applyNlConfig()">应用</button>
          </div>
          <p style="color: #6b7280; font-size: 13px;">输入自然语言描述，系统自动解析并修改配置项</p>
        </div>
        <div class="card">
          <h3 style="color: #fff; margin-bottom: 16px;">📋 当前配置</h3>
          <div id="configContent" class="loading">加载中...</div>
        </div>
      `;
      loadConfig();
      break;
    
    case 'reports':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>运营报表</h2>
            <p>查看运营数据报告</p>
          </div>
        </div>
        <div class="card">
          <button class="btn btn-primary" onclick="downloadReport()">下载用户报表</button>
        </div>
      `;
      break;

    case 'logs':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>日志查看</h2>
            <p>查看对话和操作日志</p>
          </div>
        </div>
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <input type="text" id="logSearchInput" placeholder="搜索日志关键词..." onkeyup="if(event.key === 'Enter') searchLogs()">
          <button class="btn btn-primary" onclick="searchLogs()">搜索</button>
        </div>
        <div class="card">
          <div id="logsContent" class="loading">加载中...</div>
        </div>
      `;
      loadLogs();
      break;
    
    default:
      content.innerHTML = '<div class="empty-state"><h3>页面不存在</h3></div>';
  }
}

async function loadBotStatus() {
  try {
    const d = await api('/api/bot/status');
    const s = d.data;
    const el = document.getElementById('statusContent');
    if (!el) return;
    const runColor = s.bot_running ? '#10b981' : '#ef4444';
    const runText = s.bot_running ? '运行中' : '已停止';
    const runBg = s.bot_running ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)';
    const blCount = (s.blacklisted_models || []).length;
    el.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card ${s.bot_running ? 'green' : ''}" style="border-left: 4px solid ${runColor};">
          <div class="stat-icon">${s.bot_running ? '🟢' : '🔴'}</div>
          <div class="stat-value" style="font-size: 28px; color: ${runColor};">${runText}</div>
          <div class="stat-label">Bot状态</div>
        </div>
        <div class="stat-card blue">
          <div class="stat-icon">📦</div>
          <div class="stat-value" style="font-size: 28px;">${escHtml(s.version)}</div>
          <div class="stat-label">版本号</div>
        </div>
        <div class="stat-card purple">
          <div class="stat-icon">🧠</div>
          <div class="stat-value" style="font-size: 18px;">${escHtml(s.current_model_name || '索引' + s.current_model_index)}</div>
          <div class="stat-label">当前模型</div>
        </div>
        <div class="stat-card orange">
          <div class="stat-icon">🚫</div>
          <div class="stat-value" style="font-size: 28px;">${blCount}</div>
          <div class="stat-label">黑名单模型</div>
        </div>
      </div>
      <div class="card" style="margin-top: 24px;">
        <h3 style="color: #fff; margin-bottom: 16px;">📊 详细信息</h3>
        <table class="data-table">
          <tbody>
            <tr><td style="font-weight:500; width:200px;">进程PID</td><td>${s.bot_pid || 'N/A'}</td></tr>
            <tr><td style="font-weight:500;">内存占用</td><td>${s.bot_memory || 'N/A'}</td></tr>
            <tr><td style="font-weight:500;">运行时长</td><td>${s.uptime || 'N/A'}</td></tr>
            <tr><td style="font-weight:500;">回复概率</td><td>${s.reply_chance}%</td></tr>
            <tr><td style="font-weight:500;">主群ID</td><td>${s.group_id || '未配置'}</td></tr>
            <tr><td style="font-weight:500;">管理员</td><td>${(s.admin_ids || []).join(', ') || '未配置'}</td></tr>
            ${blCount > 0 ? `<tr><td style="font-weight:500; color:#ef4444;">黑名单模型</td><td style="color:#ef4444;">${(s.blacklisted_models||[]).join(', ')}</td></tr>` : ''}
          </tbody>
        </table>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function loadModels() {
  try {
    const d = await api('/api/models/status');
    const data = d.data;
    const el = document.getElementById('modelsContent');
    if (!el) return;
    const routing = data._mode_routing || {};
    delete data._mode_routing;
    let html = '';
    const poolLabels = {
      llm: 'LLM文本', vision: '视觉', omni: '全模态',
      voice_tts: 'TTS语音', voice_asr: 'ASR识别', embedding: '向量',
      llm_light: '轻量路由', llm_standard: '标准路由', llm_premium: '旗舰路由'
    };
    for (const [poolName, models] of Object.entries(data)) {
      if (!Array.isArray(models)) continue;
      const label = poolLabels[poolName] || poolName;
      html += `
        <div class="card" style="margin-bottom: 20px;">
          <h3 style="color: #fff; margin-bottom: 16px;">${escHtml(label)} <span style="color:#6b7280; font-size:14px;">(${models.length}个模型)</span></h3>
          ${models.length === 0 ? '<p style="color:#6b7280;">暂无模型</p>' : `
          <table class="data-table">
            <thead><tr><th>模型名</th><th>描述</th><th>到期日</th><th>剩余天数</th><th>状态</th></tr></thead>
            <tbody>
              ${models.map(m => {
                const statusColor = m.blacklisted ? '#ef4444' : (m.days_left <= 7 ? '#f59e0b' : '#10b981');
                const statusBg = m.blacklisted ? 'rgba(239,68,68,0.2)' : (m.days_left <= 7 ? 'rgba(245,158,11,0.2)' : 'rgba(16,185,129,0.2)');
                return `<tr>
                  <td style="font-weight:500; font-family:'JetBrains Mono',monospace;">${escHtml(m.name)}</td>
                  <td>${escHtml(m.desc)}</td>
                  <td>${escHtml(m.expire)}</td>
                  <td style="color:${statusColor}; font-weight:600;">${m.days_left >= 9999 ? '永久' : m.days_left + '天'}</td>
                  <td><span class="badge" style="background:${statusBg}; color:${statusColor};">${m.status}</span></td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>`}
        </div>
      `;
    }
    if (Object.keys(routing).length > 0) {
      html += `
        <div class="card">
          <h3 style="color: #fff; margin-bottom: 16px;">🔀 三层路由映射</h3>
          <table class="data-table">
            <thead><tr><th>模式(mode)</th><th>路由到</th></tr></thead>
            <tbody>
              ${Object.entries(routing).map(([mode, tier]) => `<tr><td style="font-weight:500;">${escHtml(mode)}</td><td><span class="badge badge-info">${escHtml(tier)}</span></td></tr>`).join('')}
            </tbody>
          </table>
        </div>
      `;
    }
    el.innerHTML = html || '<div class="empty-state"><h3>暂无模型配置</h3></div>';
  } catch(e) { console.error(e); }
}

async function loadTasks() {
  try {
    const d = await api('/api/tasks/status');
    const data = d.data;
    const el = document.getElementById('tasksContent');
    if (!el) return;
    const tasks = data.tasks || [];
    const doneCount = tasks.filter(t => t.done_today).length;
    el.innerHTML = `
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); margin-bottom: 24px;">
        <div class="stat-card green">
          <div class="stat-icon">✅</div>
          <div class="stat-value">${doneCount}</div>
          <div class="stat-label">今日已完成</div>
        </div>
        <div class="stat-card orange">
          <div class="stat-icon">⏳</div>
          <div class="stat-value">${tasks.length - doneCount}</div>
          <div class="stat-label">待执行/未到时间</div>
        </div>
        <div class="stat-card blue">
          <div class="stat-icon">📅</div>
          <div class="stat-value" style="font-size: 20px;">${escHtml(data.date)}</div>
          <div class="stat-label">统计日期</div>
        </div>
      </div>
      <div class="card">
        <table class="data-table">
          <thead><tr><th>任务名称</th><th>计划时间</th><th>今日状态</th><th>执行时间</th></tr></thead>
          <tbody>
            ${tasks.map(t => `
              <tr>
                <td style="font-weight:500;">${escHtml(t.name)}</td>
                <td>${escHtml(t.schedule)}</td>
                <td>${t.done_today
                  ? '<span class="badge badge-success">✅ 已完成</span>'
                  : '<span class="badge badge-warning">⏳ 未执行</span>'}</td>
                <td style="color: ${t.done_today ? '#10b981' : '#6b7280'};">${t.done_today ? t.exec_time : '-'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function loadGroupMgr() {
  try {
    const d = await api('/api/group/settings');
    const s = d.data;
    const el = document.getElementById('groupMgrContent');
    if (!el) return;
    const bannedWords = (s.banned_words || []).join(', ');
    const hateKeywords = (s.hate_keywords || []).join(', ');
    const autoMuteNames = (s.auto_mute_names || []).join(', ');
    const spamLimit = s.spam_limit || {};
    const welcomeOn = s.welcome_msg !== false;
    el.innerHTML = `
      <div class="card" style="margin-bottom: 20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🛡️ 敏感词管理</h3>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">违禁词（消息含这些词会被删除，逗号分隔）</label>
          <textarea id="bannedWordsInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(bannedWords)}</textarea>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">反感词（说这些词时Bot冷淡回应，逗号分隔）</label>
          <textarea id="hateKeywordsInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(hateKeywords)}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveGroupList('BANNED_WORDS', 'bannedWordsInput')">保存违禁词</button>
        <button class="btn btn-secondary" onclick="saveGroupList('HATE_KEYWORDS', 'hateKeywordsInput')" style="margin-left:8px;">保存反感词</button>
      </div>

      <div class="card" style="margin-bottom: 20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🚫 刷屏与禁言</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:12px;">
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">每分钟消息上限</label>
            <input id="spamMsgLimit" type="number" value="${spamLimit.messages_per_minute || 10}" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">刷屏封禁时长(分钟)</label>
            <input id="spamBanMin" type="number" value="${spamLimit.ban_minutes || 5}" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">默认封禁时长(分钟)</label>
          <input id="banDuration" type="number" value="${s.spam_ban_duration || 5}" style="width:200px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
        </div>
        <button class="btn btn-primary" onclick="saveSpamSettings()">保存刷屏设置</button>
      </div>

      <div class="card" style="margin-bottom: 20px;">
        <h3 style="color:#fff; margin-bottom:16px;">👋 入群欢迎</h3>
        <div style="margin-bottom:12px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; margin-bottom:8px;">
            <input type="checkbox" id="welcomeOn" ${welcomeOn ? 'checked' : ''} style="width:18px; height:18px;">
            开启入群欢迎
          </label>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">欢迎语内容</label>
          <textarea id="welcomeTextInput" style="width:100%; min-height:80px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(s.welcome_text || '')}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveWelcomeSettings()">保存欢迎设置</button>
      </div>

      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">🔒 自动禁言关键词</h3>
        <p style="color:#6b7280; font-size:13px; margin-bottom:12px;">入群用户名含这些词会被自动永久禁言</p>
        <div style="margin-bottom:12px;">
          <textarea id="autoMuteNamesInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(autoMuteNames)}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveGroupList('AUTO_MUTE_NAMES', 'autoMuteNamesInput')">保存禁言关键词</button>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function saveGroupList(key, inputId) {
  const raw = document.getElementById(inputId).value;
  const items = raw.split(/[,，、]/).map(s => s.trim()).filter(s => s);
  if (items.length === 0) {
    if (!confirm('确定要清空此列表吗？此操作不可撤销！')) return;
  }
  try {
    const r = await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key, value: items})
    });
    showToast(r.ok ? '保存成功' : (r.msg || '保存失败'), r.ok ? 'success' : 'error');
  } catch(e) { showToast('保存失败', 'error'); }
}

async function saveSpamSettings() {
  const msgLimit = parseInt(document.getElementById('spamMsgLimit').value) || 10;
  const banMin = parseInt(document.getElementById('spamBanMin').value) || 5;
  const banDuration = parseInt(document.getElementById('banDuration').value) || 5;
  try {
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'SPAM_LIMIT', value: {messages_per_minute: msgLimit, ban_minutes: banMin}})
    });
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'BAN_DURATION_DEFAULT', value: banDuration})
    });
    showToast('刷屏设置已保存', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

async function saveWelcomeSettings() {
  const welcomeOn = document.getElementById('welcomeOn').checked;
  const welcomeText = document.getElementById('welcomeTextInput').value;
  try {
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'WELCOME_MSG', value: welcomeOn})
    });
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'WELCOME_TEXT', value: welcomeText})
    });
    showToast('欢迎设置已保存', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

async function loadFeedback() {
  try {
    const d = await api('/api/feedback/stats');
    const s = d.data;
    const el = document.getElementById('feedbackContent');
    if (!el) return;
    const rateColor = s.satisfaction_rate >= 80 ? '#10b981' : s.satisfaction_rate >= 50 ? '#f59e0b' : '#ef4444';
    const recent = s.recent || [];
    el.innerHTML = `
      <div class="stats-grid" style="margin-bottom:20px;">
        <div class="stat-card" style="border-left:4px solid #10b981;">
          <div class="stat-value" style="color:#10b981;">${s.like}</div>
          <div class="stat-label">👍 满意</div>
        </div>
        <div class="stat-card" style="border-left:4px solid #ef4444;">
          <div class="stat-value" style="color:#ef4444;">${s.dislike}</div>
          <div class="stat-label">👎 不满意</div>
        </div>
        <div class="stat-card" style="border-left:4px solid ${rateColor};">
          <div class="stat-value" style="color:${rateColor};">${s.satisfaction_rate}%</div>
          <div class="stat-label">满意度</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${s.total}</div>
          <div class="stat-label">总反馈数</div>
        </div>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">最近反馈记录</h3>
        ${recent.length === 0 ? '<p style="color:#6b7280;">暂无反馈数据，Bot回复消息后用户可点击👍👎按钮</p>' : `
        <table class="data-table">
          <thead><tr><th>时间</th><th>用户ID</th><th>反馈</th><th>消息ID</th></tr></thead>
          <tbody>
            ${recent.map(r => {
              const dt = new Date(r.ts * 1000).toLocaleString('zh-CN');
              const fbEmoji = r.feedback === 'like' ? '👍 满意' : '👎 不满意';
              const fbColor = r.feedback === 'like' ? '#10b981' : '#ef4444';
              return `<tr><td>${dt}</td><td>${r.user_id}</td><td style="color:${fbColor};">${fbEmoji}</td><td>${r.bot_msg_id}</td></tr>`;
            }).join('')}
          </tbody>
        </table>`}
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function loadHelpCenter() {
  try {
    const d = await api('/api/help/docs');
    const docs = d.data;
    const el = document.getElementById('helpContent');
    if (!el) return;
    let html = '';
    html += `<div class="card" style="margin-bottom:20px;">
      <h3 style="color:#fff; margin-bottom:16px;">👤 用户命令</h3>
      <table class="data-table"><thead><tr><th>命令</th><th>说明</th><th>示例</th></tr></thead><tbody>
      ${docs.user_commands.map(c => `<tr><td style="color:#60a5fa; font-weight:500;">${escHtml(c.cmd)}</td><td>${escHtml(c.desc)}</td><td style="color:#6b7280;">${escHtml(c.example)}</td></tr>`).join('')}
      </tbody></table></div>`;
    for (const sec of docs.admin_commands) {
      html += `<div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🔐 ${escHtml(sec.section)}</h3>
        <table class="data-table"><thead><tr><th>命令</th><th>说明</th></tr></thead><tbody>
        ${sec.items.map(c => `<tr><td style="color:#60a5fa; font-weight:500;">${escHtml(c.cmd)}</td><td>${escHtml(c.desc)}</td></tr>`).join('')}
        </tbody></table></div>`;
    }
    html += `<div class="card">
      <h3 style="color:#fff; margin-bottom:16px;">📊 Dashboard页面指南</h3>
      <table class="data-table"><thead><tr><th>页面</th><th>说明</th></tr></thead><tbody>
      ${docs.dashboard_guide.map(g => `<tr><td style="color:#60a5fa; font-weight:500;">${escHtml(g.page)}</td><td>${escHtml(g.desc)}</td></tr>`).join('')}
      </tbody></table></div>`;
    el.innerHTML = html;
  } catch(e) { console.error(e); }
}

async function loadUserProfile() {
  try {
    const d = await api('/api/user/analytics');
    const s = d.data;
    const el = document.getElementById('userProfileContent');
    if (!el) return;
    const churnPct = s.total_users > 0 ? (s.churn_risk / s.total_users * 100).toFixed(1) : 0;
    const lostPct = s.total_users > 0 ? (s.lost / s.total_users * 100).toFixed(1) : 0;
    const churnColor = churnPct > 30 ? '#ef4444' : churnPct > 15 ? '#f59e0b' : '#10b981';
    el.innerHTML = `
      <div class="stats-grid" style="margin-bottom:20px;">
        <div class="stat-card">
          <div class="stat-value">${s.total_users}</div>
          <div class="stat-label">总用户数</div>
        </div>
        <div class="stat-card green">
          <div class="stat-value" style="color:#10b981;">${s.dau}</div>
          <div class="stat-label">日活(DAU)</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#60a5fa;">${s.wau}</div>
          <div class="stat-label">周活(WAU)</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#a78bfa;">${s.mau}</div>
          <div class="stat-label">月活(MAU)</div>
        </div>
      </div>
      <div class="stats-grid" style="margin-bottom:20px;">
        <div class="stat-card" style="border-left:4px solid ${churnColor};">
          <div class="stat-value" style="color:${churnColor};">${s.churn_risk} (${churnPct}%)</div>
          <div class="stat-label">⚠️ 流失预警(14天未活跃)</div>
        </div>
        <div class="stat-card" style="border-left:4px solid #ef4444;">
          <div class="stat-value" style="color:#ef4444;">${s.lost} (${lostPct}%)</div>
          <div class="stat-label">🔴 已流失(30天未活跃)</div>
        </div>
      </div>
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">📈 7日DAU趋势</h3>
        <div style="display:flex; align-items:flex-end; gap:8px; height:120px; padding:0 8px;">
          ${(s.dau_trend || []).map(t => {
            const maxDau = Math.max(...(s.dau_trend || []).map(x => x.dau), 1);
            const h = Math.max(t.dau / maxDau * 100, 4);
            const dayLabel = t.date.substring(5);
            return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; gap:4px;">
              <span style="color:#e2e8f0; font-size:11px;">${t.dau}</span>
              <div style="width:100%; height:${h}px; background:linear-gradient(180deg,#60a5fa,#3b82f6); border-radius:4px 4px 0 0;"></div>
              <span style="color:#6b7280; font-size:10px;">${dayLabel}</span>
            </div>`;
          }).join('')}
        </div>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">🏆 活跃排行榜 TOP10</h3>
        <table class="data-table">
          <thead><tr><th>#</th><th>用户</th><th>消息数</th><th>最后活跃</th></tr></thead>
          <tbody>
            ${(s.top_users || []).map((u, i) => {
              const dt = u.last_active ? new Date(u.last_active * 1000).toLocaleString('zh-CN') : '未知';
              const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}`;
              return `<tr><td>${medal}</td><td>${escHtml(u.name)}<span style="color:#6b7280; font-size:11px;"> (${u.uid})</span></td><td>${u.messages}</td><td style="color:#6b7280;">${dt}</td></tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch(e) { console.error(e); }
}

function renderCharts() {
  const ctx1 = document.getElementById('trendChart');
  const ctx2 = document.getElementById('hourlyChart');
  const data = _chartData || {};
  const trend = data.online_trend || [];
  const hourly = data.hourly_dist || {};
  
  if (ctx1 && trend.length > 0) {
    const labels = trend.map(t => t.date);
    const values = trend.map(t => t.value);
    new Chart(ctx1, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '新增用户',
          data: values,
          borderColor: '#60a5fa',
          backgroundColor: 'rgba(96, 165, 250, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  } else if (ctx1) {
    ctx1.parentElement.innerHTML = '<div class="empty-state"><h3>暂无趋势数据</h3></div>';
  }
  
  if (ctx2) {
    const hourLabels = [];
    const hourValues = [];
    for (let h = 0; h < 24; h++) {
      hourLabels.push(String(h).padStart(2, '0') + ':00');
      hourValues.push(hourly[h] || 0);
    }
    new Chart(ctx2, {
      type: 'bar',
      data: {
        labels: hourLabels,
        datasets: [{
          label: '活跃用户',
          data: hourValues,
          backgroundColor: 'rgba(167, 139, 250, 0.8)',
          borderRadius: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#6b7280', maxTicksLimit: 12 }, grid: { display: false } },
          y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  }
}

function renderFunnel() {
  const ctx = document.getElementById('funnelChart');
  if (!ctx || !_chartData) return;
  const funnel = _chartData.conversion_funnel || {};
  const labels = Object.keys(funnel);
  const values = Object.values(funnel);
  if (labels.length === 0) {
    ctx.parentElement.innerHTML = '<div class="empty-state"><h3>暂无转化数据</h3></div>';
    return;
  }
  const colors = ['#60a5fa', '#a78bfa', '#f59e0b', '#10b981', '#ef4444', '#6366f1'];
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: '用户数',
        data: values,
        backgroundColor: labels.map((_, i) => colors[i % colors.length] + 'cc'),
        borderRadius: 8
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#e2e8f0', font: { size: 12 } }, grid: { display: false } }
      }
    }
  });
}

function renderGroupChannel() {
  const el = document.getElementById('groupChannelStats');
  if (!el || !_chartData) return;
  const gs = _chartData.group_stats || {};
  const cs = _chartData.channel_stats || {};
  el.innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
      <div style="background: rgba(96,165,250,0.08); border-radius: 12px; padding: 16px;">
        <div style="font-size: 13px; color: #6b7280; margin-bottom: 8px;">群组（7日）</div>
        <div style="display: flex; gap: 16px; flex-wrap: wrap;">
          <div><span style="font-size: 20px; font-weight: 700; color: #10b981;">+${gs.week_joined || 0}</span><div style="font-size: 11px; color: #6b7280;">入群</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: #ef4444;">-${gs.week_left || 0}</span><div style="font-size: 11px; color: #6b7280;">离群</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: ${(gs.week_net || 0) >= 0 ? '#60a5fa' : '#ef4444'};">${(gs.week_net || 0) >= 0 ? '+' : ''}${gs.week_net || 0}</span><div style="font-size: 11px; color: #6b7280;">净增</div></div>
        </div>
      </div>
      <div style="background: rgba(167,139,250,0.08); border-radius: 12px; padding: 16px;">
        <div style="font-size: 13px; color: #6b7280; margin-bottom: 8px;">频道</div>
        <div style="display: flex; gap: 16px; flex-wrap: wrap;">
          <div><span style="font-size: 20px; font-weight: 700; color: #a78bfa;">${cs.total_posts || 0}</span><div style="font-size: 11px; color: #6b7280;">帖子数</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: #f59e0b;">${cs.total_views || 0}</span><div style="font-size: 11px; color: #6b7280;">总浏览</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: #60a5fa;">${cs.avg_views || 0}</span><div style="font-size: 11px; color: #6b7280;">均浏览</div></div>
        </div>
      </div>
    </div>
  `;
}

async function loadGroups() {
  try {
    const d = await api('/api/groups');
    const g = d.data.groups || [];
    const gc = document.getElementById('groupContent');
    if (!gc) return;
    if (g.length === 0) {
      gc.innerHTML = '<div class="empty-state"><h3>暂无群组数据</h3></div>';
      return;
    }
    gc.innerHTML = `
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));">
        ${g.map(x => `
          <div class="stat-card purple">
            <div class="stat-icon">👥</div>
            <div class="stat-value" style="font-size: 24px;">${x.msg_count}</div>
            <div class="stat-label">${escHtml(x.title || x.chat_id)}</div>
            <div style="margin-top: 12px; display: flex; justify-content: space-between; font-size: 12px; color: #6b7280;">
              <span>入群 +${x.joined}</span>
              <span>离群 -${x.left}</span>
              <span style="color: ${x.net >= 0 ? '#10b981' : '#ef4444'}">净增 ${x.net >= 0 ? '+' : ''}${x.net}</span>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  } catch (e) {
    console.error(e);
  }
}

async function loadConfig() {
  try {
    const d = await api('/api/config');
    const cfg = d.data.config || {};
    const cc = document.getElementById('configContent');
    if (!cc) return;
    const categories = {
      '核心互动': ['REPLY_CHANCE', 'REPLY_DELAY_MIN', 'REPLY_DELAY_MAX', 'MAX_MSG_LENGTH'],
      '功能开关': ['PUZZLE_ENABLED', 'PUZZLE_WORD', 'SIGNUP_ENABLED', 'AUTO_GREETING', 'AUTO_GOODNIGHT', 'AUTO_NEWS', 'WELCOME_MSG', 'ANTI_REVOKE', 'BURN_AFTER', 'RECOVER_ENABLED', 'AUTO_MORNING_NEWS', 'AUTO_AFTERNOON_NEWS', 'AUTO_EVENING_NEWS'],
      '时间调度': ['GREETING_HOUR', 'GOODNIGHT_HOUR', 'NEWS_HOUR_MORNING', 'NEWS_HOUR_AFTERNOON', 'NEWS_HOUR_EVENING', 'SIGNUP_RESET_HOUR'],
      '安全限制': ['SPAM_LIMIT', 'MAX_REQUESTS_PER_USER', 'BAN_DURATION_DEFAULT'],
      'AI模型': ['TEMPERATURE', 'MAX_TOKENS', 'TOP_P', 'FREQUENCY_PENALTY', 'PRESENCE_PENALTY', 'CURRENT_MODEL_INDEX'],
      '内容互动': ['WELCOME_TEXT', 'GREETING_TEMPLATE', 'GOODNIGHT_TEMPLATE', 'HATE_KEYWORDS', 'BANNED_WORDS', 'AUTO_REPLY_TRIGGERS'],
      '业务配置': ['POINTS_PER_SIGNUP', 'POINTS_PER_INVITE', 'REPLY_STICKER_CHANCE', 'MAX_STICKERS_PER_DAY'],
      '数据存储': ['LOG_LEVEL', 'BACKUP_INTERVAL'],
    };
    const friendlyNames = {
      'REPLY_CHANCE': '群聊回复概率(%)', 'REPLY_DELAY_MIN': '回复延迟下限(秒)', 'REPLY_DELAY_MAX': '回复延迟上限(秒)',
      'MAX_MSG_LENGTH': '最大回复长度', 'PUZZLE_ENABLED': '碎片寻宝', 'PUZZLE_WORD': '碎片暗号',
      'SIGNUP_ENABLED': '每日签到', 'AUTO_GREETING': '每日早安', 'AUTO_GOODNIGHT': '每日晚安',
      'AUTO_NEWS': '新闻播报', 'WELCOME_MSG': '入群欢迎', 'ANTI_REVOKE': '撤回检测',
      'BURN_AFTER': '阅后即焚', 'RECOVER_ENABLED': '挽回功能', 'AUTO_MORNING_NEWS': '早间新闻',
      'AUTO_AFTERNOON_NEWS': '午间新闻', 'AUTO_EVENING_NEWS': '晚间新闻',
      'GREETING_HOUR': '早安时间(点)', 'GOODNIGHT_HOUR': '晚安时间(点)',
      'NEWS_HOUR_MORNING': '早间新闻时间(点)', 'NEWS_HOUR_AFTERNOON': '午间新闻时间(点)',
      'NEWS_HOUR_EVENING': '晚间新闻时间(点)', 'SIGNUP_RESET_HOUR': '签到重置时间(点)',
      'SPAM_LIMIT': '刷屏限制', 'MAX_REQUESTS_PER_USER': '用户请求限制(/时)',
      'BAN_DURATION_DEFAULT': '默认封禁时长(分)', 'TEMPERATURE': '创意温度',
      'MAX_TOKENS': '最大Token数', 'TOP_P': 'Top-P采样',
      'FREQUENCY_PENALTY': '频率惩罚', 'PRESENCE_PENALTY': '存在惩罚',
      'CURRENT_MODEL_INDEX': '当前模型索引', 'WELCOME_TEXT': '欢迎语内容',
      'GREETING_TEMPLATE': '早安模板', 'GOODNIGHT_TEMPLATE': '晚安模板',
      'HATE_KEYWORDS': '反感关键词', 'BANNED_WORDS': '违禁词',
      'AUTO_REPLY_TRIGGERS': '自动回复触发词', 'POINTS_PER_SIGNUP': '签到积分',
      'POINTS_PER_INVITE': '邀请积分', 'REPLY_STICKER_CHANCE': '贴纸概率(%)',
      'MAX_STICKERS_PER_DAY': '每日贴纸上限', 'LOG_LEVEL': '日志级别',
      'BACKUP_INTERVAL': '备份间隔(时)',
    };
    let html = '';
    for (const [cat, keys] of Object.entries(categories)) {
      const items = keys.filter(k => k in cfg);
      if (items.length === 0) continue;
      html += `<h4 style="color:#60a5fa; margin:16px 0 8px; font-size:14px;">${escHtml(cat)}</h4>`;
      html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">';
      for (const k of items) {
        const v = cfg[k];
        const label = friendlyNames[k] || k;
        if (typeof v === 'boolean') {
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="flex:1; color:#94a3b8; font-size:13px;">${escHtml(label)}</label>
            <input type="checkbox" ${v ? 'checked' : ''} onchange="quickSaveConfig('${k}', this.checked)" style="width:18px; height:18px;">
          </div>`;
        } else if (typeof v === 'number') {
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="color:#94a3b8; font-size:13px; min-width:100px;">${escHtml(label)}</label>
            <input type="number" value="${v}" onchange="quickSaveConfig('${k}', parseFloat(this.value))" style="width:80px; padding:4px 8px; background:#0f0f1a; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px; text-align:right;">
          </div>`;
        } else if (typeof v === 'string') {
          const short = v.length > 30 ? v.substring(0, 30) + '...' : v;
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="color:#94a3b8; font-size:13px; min-width:100px;">${escHtml(label)}</label>
            <input type="text" value="${escHtml(v)}" onchange="quickSaveConfig('${k}', this.value)" style="flex:1; padding:4px 8px; background:#0f0f1a; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px;">
          </div>`;
        } else if (Array.isArray(v)) {
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="color:#94a3b8; font-size:13px; min-width:100px;">${escHtml(label)}</label>
            <input type="text" value="${escHtml(v.join(', '))}" onchange="quickSaveConfig('${k}', this.value.split(/[,，]/).map(s=>s.trim()).filter(s=>s))" style="flex:1; padding:4px 8px; background:#0f0f1a; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px;">
          </div>`;
        }
      }
      html += '</div>';
    }
    const uncategorized = Object.keys(cfg).filter(k => !Object.values(categories).flat().includes(k));
    if (uncategorized.length > 0) {
      html += `<h4 style="color:#60a5fa; margin:16px 0 8px; font-size:14px;">其他配置</h4>`;
      html += '<table class="data-table"><thead><tr><th>配置项</th><th>当前值</th><th>操作</th></tr></thead><tbody>';
      for (const k of uncategorized) {
        const v = cfg[k];
        html += `<tr><td style="font-weight:500;">${escHtml(k)}</td>
          <td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}</td>
          <td><button class="btn btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="editConfig(${JSON.stringify(k)}, ${JSON.stringify(typeof v === 'object' ? JSON.stringify(v) : String(v))})">编辑</button></td></tr>`;
      }
      html += '</tbody></table>';
    }
    cc.innerHTML = html || '<div class="empty-state"><h3>暂无配置数据</h3></div>';
  } catch (e) { console.error(e); }
}

async function quickSaveConfig(key, value) {
  try {
    const r = await api('/api/config/update', {
      method: 'POST',
      body: JSON.stringify({key, value})
    });
    showToast(r.ok ? `${key} 已更新（⚠️ 需重启Bot生效）` : (r.msg || '更新失败'), r.ok ? 'success' : 'error');
  } catch(e) { showToast('更新失败', 'error'); }
}

function editConfig(key, value) {
  const newValue = prompt(`修改配置项 "${key}":`, value);
  if (newValue === null) return;
  try {
    let parsedValue = newValue;
    try { parsedValue = JSON.parse(newValue); } catch {}
    api('/api/config/update', {
      method: 'POST',
      body: JSON.stringify({ key, value: parsedValue }),
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(() => {
      showToast('配置已更新', 'success');
      loadConfig();
    }).catch(e => showToast('更新失败: ' + e.message, 'error'));
  } catch (e) {
    showToast('更新失败', 'error');
  }
}

function applyNlConfig() {
  const input = document.getElementById('nlConfigInput');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  api('/api/config/natural', {
    method: 'POST',
    body: JSON.stringify({ text }),
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
  }).then((res) => {
    showToast(res.msg || '已处理', 'success');
    input.value = '';
    loadConfig();
  }).catch((e) => {
    showToast(e.message || '无法解析指令，请尝试更明确的描述', 'error');
  });
}

async function loadLogs(page = 1) {
  try {
    const d = await api(`/api/logs?page=${page}&per_page=30`);
    const logs = d.data.logs || [];
    const lc = document.getElementById('logsContent');
    if (!lc) return;
    if (logs.length === 0) {
      lc.innerHTML = '<div class="empty-state"><h3>暂无日志数据</h3></div>';
      return;
    }
    lc.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>时间</th><th>群ID</th><th>Bot消息ID</th><th>用户消息ID</th><th>已回复</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(l => `
            <tr>
              <td style="font-size: 12px; color: #6b7280;">${formatTime(l.ts)}</td>
              <td>${l.chat_id || '-'}</td>
              <td>${l.bot_msg_id || '-'}</td>
              <td>${l.user_msg_id || '-'}</td>
              <td>${l.replied ? '<span class="badge badge-success">✅</span>' : '<span class="badge badge-warning">⏳</span>'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div id="logsPagination" class="pagination"></div>
    `;
    renderPagination(d.data.pagination);
  } catch (e) {
    console.error(e);
  }
}

function searchLogs() {
  const keyword = document.getElementById('logSearchInput')?.value;
  if (!keyword) return;
  api(`/api/logs/search?keyword=${encodeURIComponent(keyword)}`).then(d => {
    const logs = d.data.logs || [];
    const lc = document.getElementById('logsContent');
    if (!lc) return;
    if (logs.length === 0) {
      lc.innerHTML = '<div class="empty-state"><h3>未找到匹配的日志</h3></div>';
      return;
    }
    lc.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>时间</th><th>群ID</th><th>Bot消息ID</th><th>用户消息ID</th><th>已回复</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(l => `
            <tr>
              <td style="font-size: 12px; color: #6b7280;">${formatTime(l.ts)}</td>
              <td>${l.chat_id || '-'}</td>
              <td>${l.bot_msg_id || '-'}</td>
              <td>${l.user_msg_id || '-'}</td>
              <td>${l.replied ? '<span class="badge badge-success">✅</span>' : '<span class="badge badge-warning">⏳</span>'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }).catch(e => showToast('搜索失败', 'error'));
}

function downloadReport() {
  fetch(API_BASE + '/api/report/download', {credentials: 'same-origin'})
    .then(r => {
      if (!r.ok) throw new Error('下载失败');
      return r.blob();
    })
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'mory_report.csv';
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    })
    .catch(e => showToast('下载失败: ' + e.message, 'error'));
}

function renderApp() {
  document.getElementById('app').innerHTML = `
    <div class="dashboard">
      <aside class="sidebar">
        <div class="sidebar-header">
          <div class="sidebar-logo">
            <div class="sidebar-logo-icon">🤖</div>
            <div class="sidebar-logo-text">
              <h1>Mory Assistant</h1>
              <span id="sidebarVersion">加载中</span>
            </div>
          </div>
        </div>
        <nav class="sidebar-nav">
          <div class="nav-section">
            <div class="nav-section-title">数据中心</div>
            <div class="nav-item active" onclick="switchTab('overview')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="3" width="7" height="7" rx="1"/>
                <rect x="14" y="3" width="7" height="7" rx="1"/>
                <rect x="3" y="14" width="7" height="7" rx="1"/>
                <rect x="14" y="14" width="7" height="7" rx="1"/>
              </svg>
              数据概览
            </div>
            <div class="nav-item" onclick="switchTab('users')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
              用户管理
            </div>
            <div class="nav-item" onclick="switchTab('groups')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
              </svg>
              群组数据
            </div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">运行监控</div>
            <div class="nav-item" onclick="switchTab('status')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
              </svg>
              运行状态
            </div>
            <div class="nav-item" onclick="switchTab('models')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2"/>
                <rect x="9" y="9" width="6" height="6"/>
                <line x1="9" y1="2" x2="9" y2="4"/>
                <line x1="15" y1="2" x2="15" y2="4"/>
                <line x1="9" y1="20" x2="9" y2="22"/>
                <line x1="15" y1="20" x2="15" y2="22"/>
              </svg>
              模型中心
            </div>
            <div class="nav-item" onclick="switchTab('tasks')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <polyline points="12 6 12 12 16 14"/>
              </svg>
              定时任务
            </div>
            <div class="nav-item" onclick="switchTab('groupmgr')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              群管设置
            </div>
            <div class="nav-item" onclick="switchTab('feedback')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
              </svg>
              用户反馈
            </div>
            <div class="nav-item" onclick="switchTab('userprofile')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
              用户画像
            </div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">系统</div>
            <div class="nav-item" onclick="switchTab('config')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              系统配置
            </div>
            <div class="nav-item" onclick="switchTab('reports')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
              运营报表
            </div>
            <div class="nav-item" onclick="switchTab('logs')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
              日志查看
            </div>
            <div class="nav-item" onclick="switchTab('helpcenter')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              帮助中心
            </div>
          </div>
        </nav>
      </aside>
      <main class="main-content">
        <header class="top-bar">
          <div class="top-bar-left">
            <button class="icon-btn" onclick="toggleSidebar()">☰</button>
            <h1 class="page-title">数据概览</h1>
          </div>
          <div class="top-bar-right">
            <div class="status-pill" id="botStatus">
              <span class="status-dot" id="statusDot"></span>
              <span id="botStatusText">加载中</span>
            </div>
            <button class="icon-btn" onclick="doLogout()" title="退出登录">🚪</button>
          </div>
        </header>
        <div class="page-content" id="mainContent"></div>
      </main>
    </div>
  `;
  renderPage();
  loadVersion();
}

function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('open');
}

async function init() {
  const isAuthenticated = await checkAuth();
  if (isAuthenticated) {
    renderApp();
  }
}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
'''

@app.route("/")
def index():
    if not session.get("logged_in"):
        return render_login()
    return render_main()

def render_login():
    return '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mory Assistant - 登录</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
* { font-family: 'Inter', system-ui, sans-serif; box-sizing: border-box; }
body { margin: 0; padding: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%); }
.login-box { background: rgba(30, 30, 46, 0.95); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px; padding: 48px; width: 100%; max-width: 420px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
.login-icon { text-align: center; font-size: 48px; margin-bottom: 24px; }
.login-title { font-size: 28px; font-weight: 700; text-align: center; margin: 0 0 8px 0; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.login-subtitle { text-align: center; color: #94a3b8; margin: 0 0 32px 0; font-size: 14px; }
.input-group { margin-bottom: 20px; }
.input-group label { display: block; color: #94a3b8; font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.input-field { width: 100%; padding: 14px 16px; background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; color: #e2e8f0; font-size: 15px; transition: all 0.3s; }
.input-field:focus { outline: none; border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2); }
.login-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #60a5fa, #3b82f6); border: none; border-radius: 12px; color: white; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.3s; }
.login-btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3); }
</style>
</head>
<body>
<div class="login-container">
  <div class="login-box">
    <div class="login-icon">🤖</div>
    <h1 class="login-title">Mory Assistant</h1>
    <p class="login-subtitle">私域可视化面板 v6.0</p>
    <div class="input-group">
      <label>访问密码</label>
      <input type="password" id="password" class="input-field" placeholder="请输入访问密码" onkeyup="if(event.key === 'Enter') doLogin()">
    </div>
    <button class="login-btn" onclick="doLogin()">登录</button>
  </div>
</div>
<script>
async function doLogin() {
  const pw = document.getElementById('password').value;
  if (!pw) return;
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ password: pw })
    });
    const d = await res.json();
    if (d.ok) {
      window.location.reload();
    } else {
      alert(d.msg || '登录失败');
    }
  } catch (e) {
    alert('登录失败');
  }
}
</script>
</body>
</html>
'''

def render_main():
    return HTML_PAGE

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
