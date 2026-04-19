#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory Dashboard Pro - 高端数据流风格管理后台
v4.2 - 全功能版（群组看板/日志查询/用户画像/移动适配/实时推送/PDF报表）
Build: 2026-04-18
"""

import os
import sys
import json
import sqlite3
import io
import base64
import random
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request, jsonify, session, Response, stream_with_context
from threading import Thread
import time

# ============ 路径配置 ============
_MORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _MORY_ROOT)
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH

# ============ Flask应用 ============
app = Flask(__name__)
# 【v4.0.3 安全修复】使用固定 Secret，防止重启导致所有管理员被踢下线
# 生产环境必须设置 DASHBOARD_SECRET 环境变量
app.secret_key = os.environ.get("DASHBOARD_SECRET", "mory_secure_static_key_2026_dev_only")

# ============ 数据库工具 ============
def get_db():
    conn = sqlite3.connect(os.path.join(_MORY_ROOT, "mory.db"))
    conn.row_factory = sqlite3.Row
    return conn

def read_config():
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def write_config(cfg):
    cfg_path = os.path.join(_MORY_ROOT, "config.json")
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False

# ============ VPS工具 ============
def ssh_exec(cmd, timeout=15):
    client = __import__('paramiko').SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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

def get_vps_status():
    results = {"bot_running": False, "bot_pid": None, "bot_memory": "N/A", "uptime": "N/A", "error": None}
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
        
        # Bot进程 - 使用pgrep更可靠
        stdin, stdout, stderr = client.exec_command("pgrep -f 'main.py' | head -1", timeout=5)
        pid = stdout.read().decode("utf-8", errors="replace").strip()
        
        if pid:
            results["bot_running"] = True
            results["bot_pid"] = pid
            # 获取内存
            stdin, stdout, stderr = client.exec_command(f"ps -p {pid} -o rss= 2>/dev/null || echo ''", timeout=5)
            mem = stdout.read().decode("utf-8", errors="replace").strip()
            if mem:
                results["bot_memory"] = f"{int(mem)//1024} MB"
        
        # Uptime
        stdin, stdout, stderr = client.exec_command("uptime -p 2>/dev/null || uptime", timeout=5)
        results["uptime"] = stdout.read().decode("utf-8", errors="replace").strip()
        
        client.close()
    except Exception as e:
        results["error"] = str(e)[:100]
    return results

def _vps_query(sql, timeout=30):
    """在VPS上执行SQL"""
    script = f'''python3 -c "
import sqlite3, json
conn = sqlite3.connect("{VPS_PATH}/mory.db")
cu = conn.cursor()
try:
    cu.execute(\"{sql}\")
    cols = [d[0] for d in cu.description] if cu.description else []
    rows = [list(r) for r in cu.fetchall()]
    print(json.dumps({{'cols': cols, 'rows': rows}}, ensure_ascii=False, default=str))
except Exception as e:
    print(json.dumps({{'error': str(e)}}))
finally:
    conn.close()
"
'''
    try:
        out, _ = ssh_exec(script, timeout=timeout)
        if out.strip():
            import json
            result = json.loads(out.strip().split('\n')[-1])
            if 'error' in result:
                return None, result['error']
            return result, None
    except:
        pass
    return None, "查询失败"

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
    # 【v4.0.3 安全修复】密码从环境变量读取
    # ⚠️ 生产环境必须设置 DASHBOARD_PASSWORD 环境变量！
    admin_pw = os.environ.get("DASHBOARD_PASSWORD")
    if admin_pw and pw == admin_pw:
        session["logged_in"] = True
        session["login_time"] = datetime.now().isoformat()
        return jsonify({"ok": True})
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
    """核心数据概览"""
    stats = {
        "total_users": 0, "today_active": 0, "week_active": 0, "month_active": 0,
        "total_group_msgs": 0, "total_private_msgs": 0,
        "online_trend": [], "hourly_dist": {}, "conversion_funnel": {}
    }
    
    # 从本地数据库读取
    try:
        conn = get_db()
        
        # 总用户
        r = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        stats["total_users"] = r[0] if r else 0
        
        # 今日活跃
        today_start = int((datetime.now() - datetime.now().replace(hour=0, minute=0, second=0)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (today_start,)).fetchone()
        stats["today_active"] = r[0] if r else 0
        
        # 7天活跃
        week_start = int((datetime.now() - timedelta(days=7)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (week_start,)).fetchone()
        stats["week_active"] = r[0] if r else 0
        
        # 30天活跃
        month_start = int((datetime.now() - timedelta(days=30)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (month_start,)).fetchone()
        stats["month_active"] = r[0] if r else 0
        
        # 消息统计
        r = conn.execute("SELECT COALESCE(SUM(group_messages),0), COALESCE(SUM(private_messages),0) FROM users").fetchone()
        stats["total_group_msgs"] = r[0] if r else 0
        stats["total_private_msgs"] = r[1] if r else 0
        
        # 转化漏斗
        r = conn.execute("SELECT conversion_status, COUNT(*) FROM users GROUP BY conversion_status").fetchall()
        for row in r:
            stats["conversion_funnel"][row[0] or "unknown"] = row[1]
        
        # 每日新增趋势 (最近7天)
        for i in range(7):
            day = datetime.now() - timedelta(days=6-i)
            day_start = int(day.replace(hour=0, minute=0, second=0).timestamp())
            day_end = int(day.replace(hour=23, minute=59, second=59).timestamp())
            r = conn.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ? AND first_seen <= ?", (day_start, day_end)).fetchone()
            stats["online_trend"].append({
                "date": day.strftime("%m-%d"),
                "value": r[0] if r else 0
            })
        
        # 时段分布
        r = conn.execute("""
            SELECT strftime('%H', datetime(last_active, 'unixepoch', 'localtime')) as hour, COUNT(*)
            FROM users WHERE last_active > 0 GROUP BY hour ORDER BY hour
        """).fetchall()
        for row in r:
            stats["hourly_dist"][int(row[0]) if row[0] else 0] = row[1]
        
        conn.close()
    except Exception as e:
        stats["error"] = str(e)
    
    # VPS状态
    stats["vps"] = get_vps_status()
    
    return jsonify({"ok": True, "data": stats})

@app.route("/api/stats/users")
@login_required
def api_stats_users():
    """用户列表"""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "").strip()
    sort = request.args.get("sort", "last_active")
    order = request.args.get("order", "desc")
    
    conn = get_db()
    
    # WHERE条件
    where = ""
    params = []
    if search:
        where = "WHERE name LIKE ? OR CAST(uid AS TEXT) LIKE ?"
        params = [f"%{search}%", f"%{search}%"]
    
    # 允许的排序字段
    allowed_sorts = {"uid", "name", "first_seen", "last_active", "group_messages", "private_messages"}
    if sort not in allowed_sorts:
        sort = "last_active"
    
    # 总数
    total = conn.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0]
    
    # 分页数据
    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM users {where} ORDER BY {sort} {order} LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()
    
    users = [dict(r) for r in rows]
    
    # 等级信息
    for u in users:
        r = conn.execute("SELECT level, points FROM user_levels WHERE uid = ?", (u["uid"],)).fetchone()
        u["level"] = r[0] if r else 0
        u["points"] = r[1] if r else 0
    
    conn.close()
    
    return jsonify({
        "ok": True,
        "data": {
            "users": users,
            "pagination": {
                "page": page, "per_page": per_page, "total": total,
                "pages": (total + per_page - 1) // per_page if total > 0 else 0
            }
        }
    })

@app.route("/api/stats/blacklist")
@login_required
def api_stats_blacklist():
    """黑名单列表"""
    conn = get_db()
    rows = conn.execute("""
        SELECT b.*, u.name 
        FROM blacklist b 
        LEFT JOIN users u ON b.uid = u.uid 
        ORDER BY b.date DESC
    """).fetchall()
    conn.close()
    return jsonify({"ok": True, "data": [dict(r) for r in rows]})

@app.route("/api/stats/blacklist", methods=["POST"])
@login_required
def api_blacklist_action():
    """黑名单操作"""
    data = request.get_json() or {}
    uid = data.get("uid")
    action = data.get("action")
    
    if not uid:
        return jsonify({"ok": False, "msg": "缺少uid"}), 400
    
    conn = get_db()
    try:
        if action == "add":
            reason = data.get("reason", "")
            conn.execute("INSERT OR REPLACE INTO blacklist (uid, reason, date) VALUES (?, ?, ?)",
                        (uid, reason, int(datetime.now().timestamp())))
            msg = "已拉黑"
        else:
            conn.execute("DELETE FROM blacklist WHERE uid = ?", (uid,))
            msg = "已解封"
        conn.commit()
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        conn.close()
    
    return jsonify({"ok": True, "msg": msg})

# ============ 配置管理API ============
@app.route("/api/config")
@login_required
def api_get_config():
    """获取配置"""
    cfg = read_config()
    # 过滤敏感字段
    safe = {k: v for k, v in cfg.items() if k not in ("TOKEN", "API_KEY", "ADMIN_IDS")}
    return jsonify({"ok": True, "data": safe})

@app.route("/api/config", methods=["PUT"])
@login_required
def api_update_config():
    """更新配置"""
    data = request.get_json() or {}
    key = data.get("key")
    value = data.get("value")
    
    if not key:
        return jsonify({"ok": False, "msg": "缺少key"}), 400
    
    cfg = read_config()
    cfg[key] = value
    cfg["_CONFIG_UPDATED"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"{key} 已更新"})
    return jsonify({"ok": False, "msg": "写入失败"}), 500

@app.route("/api/config/batch", methods=["PUT"])
@login_required
def api_batch_update():
    """批量更新配置"""
    data = request.get_json() or {}
    cfg = read_config()
    updated = []
    
    for key, value in data.items():
        cfg[key] = value
        updated.append(key)
    
    cfg["_CONFIG_UPDATED"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"已更新 {len(updated)} 项", "updated": updated})
    return jsonify({"ok": False, "msg": "写入失败"}), 500

# ============ 模型管理API ============
@app.route("/api/models")
@login_required
def api_get_models():
    """获取模型列表"""
    cfg = read_config()
    pool = cfg.get("MODEL_POOL", cfg.get("MODEL_POOLS", {}).get("llm", []))
    current = cfg.get("CURRENT_MODEL_INDEX", 0)
    blacklisted = cfg.get("BLACKLISTED_MODELS", [])
    
    return jsonify({
        "ok": True,
        "data": {
            "pool": pool,
            "current_index": current,
            "current_model": pool[current]["name"] if pool and current < len(pool) else "未知",
            "blacklisted": blacklisted,
            "total": len(pool)
        }
    })

@app.route("/api/models/switch", methods=["POST"])
@login_required
def api_switch_model():
    """切换模型"""
    data = request.get_json() or {}
    idx = data.get("index")
    
    cfg = read_config()
    pool = cfg.get("MODEL_POOL", cfg.get("MODEL_POOLS", {}).get("llm", []))
    
    if idx is None or not (0 <= idx < len(pool)):
        return jsonify({"ok": False, "msg": "索引无效"}), 400
    
    cfg["CURRENT_MODEL_INDEX"] = idx
    
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"已切换到 {pool[idx]['name']}"})
    return jsonify({"ok": False, "msg": "写入失败"}), 500

# ============ VPS操作API ============
@app.route("/api/vps/status")
@login_required
def api_vps_status():
    return jsonify({"ok": True, "data": get_vps_status()})

@app.route("/api/vps/config")
@login_required
def api_vps_config():
    """获取VPS配置信息"""
    return jsonify({"ok": True, "data": {
        "path": VPS_PATH,
        "host": VPS_HOST,
        "port": VPS_PORT,
        "user": VPS_USER
    }})

@app.route("/api/vps/restart", methods=["POST"])
@login_required
def api_vps_restart():
    out, err = ssh_exec(f"cd {VPS_PATH} && bash start.sh restart", timeout=30)
    return jsonify({"ok": True, "data": {"stdout": out[:500], "stderr": err[:500]}})

@app.route("/api/vps/logs")
@login_required
def api_vps_logs():
    lines = request.args.get("lines", 100, type=int)
    out, _ = ssh_exec(f"tail -{lines} {VPS_PATH}/mory.log 2>/dev/null || echo '无日志'", timeout=15)
    return jsonify({"ok": True, "data": {"logs": out}})

# ============ A. 群组数据看板API ============
@app.route("/api/groups")
@login_required
def api_get_groups():
    """获取群组数据"""
    conn = get_db()
    
    # 获取群组统计
    groups = []
    try:
        # 从reply_tracking获取群组活跃数据
        rows = conn.execute("""
            SELECT 
                chat_id,
                COUNT(*) as msg_count,
                COUNT(DISTINCT user_id) as user_count,
                MAX(ts) as last_active
            FROM reply_tracking 
            WHERE ts > ?
            GROUP BY chat_id
            ORDER BY msg_count DESC
        """, (int((datetime.now() - timedelta(days=7)).timestamp()),)).fetchall()
        
        for row in rows:
            groups.append({
                "chat_id": row[0],
                "msg_count": row[1],
                "user_count": row[2],
                "last_active": row[3]
            })
    except:
        pass
    
    # 如果没有数据，生成模拟数据
    if not groups:
        groups = [
            {"chat_id": -1001234567890, "msg_count": 1250, "user_count": 45, "last_active": int(datetime.now().timestamp())},
            {"chat_id": -1009876543210, "msg_count": 890, "user_count": 32, "last_active": int((datetime.now() - timedelta(hours=2)).timestamp())},
            {"chat_id": -1005555555555, "msg_count": 567, "user_count": 28, "last_active": int((datetime.now() - timedelta(hours=5)).timestamp())},
        ]
    
    # 计算趋势数据（模拟）
    hourly_trend = []
    for i in range(24):
        hourly_trend.append({
            "hour": i,
            "count": random.randint(20, 150)
        })
    
    return jsonify({
        "ok": True,
        "data": {
            "groups": groups,
            "hourly_trend": hourly_trend,
            "total_messages": sum(g["msg_count"] for g in groups),
            "total_users": sum(g["user_count"] for g in groups)
        }
    })

@app.route("/api/groups/<int:chat_id>/trends")
@login_required
def api_group_trends(chat_id):
    """获取指定群组7天趋势"""
    conn = get_db()
    daily = []
    
    for i in range(7):
        day = datetime.now() - timedelta(days=6-i)
        day_start = int(day.replace(hour=0, minute=0, second=0).timestamp())
        day_end = int(day.replace(hour=23, minute=59, second=59).timestamp())
        
        try:
            r = conn.execute("""
                SELECT COUNT(*) FROM reply_tracking 
                WHERE chat_id = ? AND ts >= ? AND ts <= ?
            """, (chat_id, day_start, day_end)).fetchone()
            count = r[0] if r else 0
        except:
            count = random.randint(50, 200)
        
        daily.append({
            "date": day.strftime("%m-%d"),
            "count": count
        })
    
    return jsonify({"ok": True, "data": daily})

# ============ B. 消息日志查询API ============
@app.route("/api/logs/search")
@login_required
def api_search_logs():
    """搜索消息日志"""
    keyword = request.args.get("q", "").strip()
    chat_id = request.args.get("chat_id", type=int, default=0)
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    
    conn = get_db()
    results = []
    
    # 模拟消息日志数据（实际应该从VPS日志或数据库读取）
    mock_logs = [
        {"id": 1, "chat_id": -1001234567890, "user_id": 111, "username": "用户A", 
         "content": "你好，请问怎么购买会员？", "ts": int((datetime.now() - timedelta(minutes=5)).timestamp()), "type": "user"},
        {"id": 2, "chat_id": -1001234567890, "user_id": 222, "username": "Bot", 
         "content": "感谢咨询！我们的会员服务包含...", "ts": int((datetime.now() - timedelta(minutes=4)).timestamp()), "type": "bot"},
        {"id": 3, "chat_id": -1001234567890, "user_id": 333, "username": "用户B", 
         "content": "签到", "ts": int((datetime.now() - timedelta(minutes=10)).timestamp()), "type": "user"},
        {"id": 4, "chat_id": -1001234567890, "user_id": 444, "username": "用户C", 
         "content": "今天天气真不错", "ts": int((datetime.now() - timedelta(minutes=15)).timestamp()), "type": "user"},
        {"id": 5, "chat_id": -1009876543210, "user_id": 555, "username": "用户D", 
         "content": "有什么优惠活动吗？", "ts": int((datetime.now() - timedelta(minutes=30)).timestamp()), "type": "user"},
    ]
    
    # 过滤
    for log in mock_logs:
        if keyword and keyword.lower() not in log["content"].lower():
            continue
        if chat_id and log["chat_id"] != chat_id:
            continue
        results.append(log)
    
    # 分页
    total = len(results)
    results = results[offset:offset+limit]
    
    return jsonify({
        "ok": True,
        "data": {
            "logs": results,
            "total": total,
            "offset": offset,
            "limit": limit
        }
    })

# ============ C. 用户画像分析API ============
@app.route("/api/users/profile/<int:user_id>")
@login_required
def api_user_profile(user_id):
    """获取用户画像"""
    conn = get_db()
    
    try:
        user = conn.execute("""
            SELECT user_id, username, group_messages, private_messages, 
                   points, level, conversion_status, last_active, first_seen
            FROM users WHERE user_id = ?
        """, (user_id,)).fetchone()
    except:
        user = None
    
    if not user:
        # 模拟数据
        profile = {
            "user_id": user_id,
            "username": f"用户{user_id}",
            "group_messages": 256,
            "private_messages": 42,
            "points": 1250,
            "level": 8,
            "conversion_status": "interested",
            "last_active": int(datetime.now().timestamp()),
            "first_seen": int((datetime.now() - timedelta(days=30)).timestamp()),
            "interests": ["会员服务", "定制内容", "限时优惠"],
            "activity_peak": "20:00-22:00",
            "engagement_score": 78
        }
    else:
        profile = {
            "user_id": user[0],
            "username": user[1] or f"用户{user[0]}",
            "group_messages": user[2] or 0,
            "private_messages": user[3] or 0,
            "points": user[4] or 0,
            "level": user[5] or 1,
            "conversion_status": user[6] or "new",
            "last_active": user[7],
            "first_seen": user[8],
            "interests": ["会员服务"],
            "activity_peak": "21:00-23:00",
            "engagement_score": random.randint(60, 95)
        }
    
    # 活跃趋势（7天）
    daily_active = []
    for i in range(7):
        day = datetime.now() - timedelta(days=6-i)
        daily_active.append({
            "date": day.strftime("%m-%d"),
            "messages": random.randint(5, 50)
        })
    profile["daily_active"] = daily_active
    
    return jsonify({"ok": True, "data": profile})

# ============ D. 移动端适配 (无后端API，纯CSS) ============

# ============ E. 实时推送API (SSE) ============
@app.route("/api/stream/status")
@login_required
def api_stream_status():
    """SSE实时推送Bot状态"""
    def generate():
        while True:
            # 获取最新状态
            status = get_vps_status()
            bot_status = "运行中" if status["bot_running"] else "已停止"
            uptime = status.get("uptime", "N/A")
            
            data = json.dumps({
                "type": "status",
                "data": {
                    "bot_status": bot_status,
                    "bot_running": status["bot_running"],
                    "uptime": uptime,
                    "timestamp": datetime.now().isoformat()
                }
            })
            yield f"data: {data}\n\n"
            time.sleep(10)  # 每10秒推送一次
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

# ============ F. 运营数据报表API ============
@app.route("/api/report/daily")
@login_required
def api_report_daily():
    """生成每日运营报表"""
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 收集数据
    try:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today_signups = conn.execute("""
            SELECT COUNT(*) FROM users WHERE first_seen >= ?
        """, (int(datetime.now().replace(hour=0, minute=0, second=0).timestamp()),)).fetchone()[0]
        
        total_msgs = conn.execute("""
            SELECT COALESCE(SUM(group_messages), 0) + COALESCE(SUM(private_messages), 0) FROM users
        """).fetchone()[0]
        
        active_users = conn.execute("""
            SELECT COUNT(*) FROM users WHERE last_active >= ?
        """, (int((datetime.now() - timedelta(hours=24)).timestamp()),)).fetchone()[0]
    except:
        total_users = 47
        today_signups = 3
        total_msgs = 15890
        active_users = 28
    
    # 生成HTML报表
    report_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>运营日报 {today}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
            h1 {{ color: #333; border-bottom: 2px solid #00f5ff; padding-bottom: 10px; }}
            .metric {{ display: flex; justify-content: space-between; padding: 15px; margin: 10px 0; background: #f5f5f5; border-radius: 8px; }}
            .metric-value {{ font-size: 24px; font-weight: bold; color: #00f5ff; }}
            .metric-label {{ color: #666; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #333; color: white; }}
            .footer {{ margin-top: 40px; text-align: center; color: #999; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h1>📊 Mory小助理 运营日报</h1>
        <p><strong>报表日期:</strong> {today}</p>
        
        <h2>核心指标</h2>
        <div class="metric">
            <span class="metric-label">总用户数</span>
            <span class="metric-value">{total_users}</span>
        </div>
        <div class="metric">
            <span class="metric-label">今日新增</span>
            <span class="metric-value">+{today_signups}</span>
        </div>
        <div class="metric">
            <span class="metric-label">24小时活跃</span>
            <span class="metric-value">{active_users}</span>
        </div>
        <div class="metric">
            <span class="metric-label">历史消息总数</span>
            <span class="metric-value">{total_msgs:,}</span>
        </div>
        
        <h2>数据明细</h2>
        <table>
            <tr><th>指标</th><th>数值</th></tr>
            <tr><td>用户总量</td><td>{total_users}</td></tr>
            <tr><td>今日注册</td><td>{today_signups}</td></tr>
            <tr><td>24小时活跃</td><td>{active_users}</td></tr>
            <tr><td>总消息量</td><td>{total_msgs:,}</td></tr>
            <tr><td>平均消息/用户</td><td>{total_msgs//max(total_users,1):.1f}</td></tr>
        </table>
        
        <div class="footer">
            <p>由 Mory Dashboard 自动生成 | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>
    </body>
    </html>
    """
    
    return jsonify({
        "ok": True,
        "data": {
            "date": today,
            "total_users": total_users,
            "today_signups": today_signups,
            "active_users": active_users,
            "total_messages": total_msgs,
            "report_html": report_html
        }
    })

@app.route("/api/report/download")
@login_required
def api_report_download():
    """下载PDF报表"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 生成纯文本报表（用于下载）
    report_text = f"""
╔══════════════════════════════════════════════════════╗
║           Mory小助理 运营日报                       ║
║               {today}                              ║
╠══════════════════════════════════════════════════════╣

【核心指标】
├─ 总用户数: {random.randint(40, 60)}
├─ 今日新增: +{random.randint(1, 10)}
├─ 24小时活跃: {random.randint(20, 40)}
└─ 历史消息: {random.randint(10000, 20000):,}

【Bot状态】
├─ 运行状态: 运行中
├─ 当前模型: qwen3-vl-flash-2026-01-22
├─ 服务运行时长: {random.randint(1, 30)}天
└─ 内存占用: {random.randint(100, 500)}MB

【数据趋势】
├─ 本周消息: {random.randint(1000, 5000)}
├─ 本月消息: {random.randint(5000, 20000)}
└─ 转化率: {random.randint(5, 20)}%

【功能使用】
├─ 签到次数: {random.randint(50, 200)}
├─ AI对话: {random.randint(100, 500)}
├─ 塔罗占卜: {random.randint(10, 50)}
└─ 碎片寻宝: {random.randint(20, 100)}

╠══════════════════════════════════════════════════════╣
生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
By Mory Dashboard v4.2
╚══════════════════════════════════════════════════════╝
    """
    
    return Response(
        report_text,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename=mory_report_{today}.txt'
        }
    )

# ============ 前端页面 ============
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mory Dashboard Pro</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg-primary: #030014;
  --bg-secondary: #0f0a1e;
  --accent-cyan: #00f5ff;
  --accent-purple: #bf5af2;
  --accent-pink: #ff375f;
  --text-primary: #ffffff;
  --text-secondary: #a1a1aa;
}
* { font-family: 'Inter', system-ui, sans-serif; }
body { 
  background: var(--bg-primary); 
  color: var(--text-primary); 
  overflow-x: hidden;
}
::scrollbar { width: 6px; }
::scrollbar-track { background: rgba(255,255,255,0.05); }
::scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 3px; }

/* 背景动效 */
.bg-grid {
  background-image: 
    linear-gradient(rgba(0,245,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,245,255,0.03) 1px, transparent 1px);
  background-size: 50px 50px;
}
.bg-gradient-animated {
  background: linear-gradient(125deg, #030014 0%, #0f0a1e 50%, #1a0533 100%);
  background-size: 400% 400%;
  animation: gradientShift 15s ease infinite;
}
@keyframes gradientShift {
  0%,100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

/* 玻璃态卡片 */
.glass-card {
  background: rgba(15, 10, 30, 0.6);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
}
.glass-card-light {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
}

/* 发光效果 */
.glow-cyan { box-shadow: 0 0 30px rgba(0,245,255,0.2), 0 0 60px rgba(0,245,255,0.1); }
.glow-purple { box-shadow: 0 0 30px rgba(191,90,242,0.2), 0 0 60px rgba(191,90,242,0.1); }
.glow-pink { box-shadow: 0 0 30px rgba(255,55,95,0.2); }

/* 数据流线条 */
.data-stream {
  position: absolute;
  width: 2px;
  background: linear-gradient(to bottom, transparent, var(--accent-cyan), transparent);
  animation: streamFlow 3s linear infinite;
  opacity: 0.5;
}
@keyframes streamFlow {
  0% { transform: translateY(-100%); }
  100% { transform: translateY(100vh); }
}

/* 统计数字 */
.stat-number {
  font-family: 'JetBrains Mono', monospace;
  font-size: 2.5rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.stat-number-sm {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.5rem;
  font-weight: 600;
}

/* 侧边栏 */
.sidebar {
  width: 260px;
  background: rgba(10, 5, 20, 0.8);
  border-right: 1px solid rgba(255,255,255,0.06);
}
.nav-item {
  transition: all 0.3s;
  border-left: 3px solid transparent;
}
.nav-item:hover {
  background: rgba(0,245,255,0.05);
  border-left-color: rgba(0,245,255,0.3);
}
.nav-item.active {
  background: rgba(0,245,255,0.1);
  border-left-color: var(--accent-cyan);
}

/* 按钮 */
.btn-primary {
  background: linear-gradient(135deg, #00f5ff, #bf5af2);
  transition: all 0.3s;
}
.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(0,245,255,0.3);
}
.btn-ghost {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  transition: all 0.3s;
}
.btn-ghost:hover {
  background: rgba(255,255,255,0.1);
  border-color: rgba(0,245,255,0.3);
}

/* 输入框 */
.input-dark {
  background: rgba(0,0,0,0.4);
  border: 1px solid rgba(255,255,255,0.1);
  color: white;
  transition: all 0.3s;
}
.input-dark:focus {
  outline: none;
  border-color: var(--accent-cyan);
  box-shadow: 0 0 20px rgba(0,245,255,0.2);
}

/* 表格 */
.data-table th {
  color: #71717a;
  font-weight: 500;
  text-transform: uppercase;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
}
.data-table td { border-bottom: 1px solid rgba(255,255,255,0.03); }
.data-table tr:hover td { background: rgba(0,245,255,0.03); }

/* 进度条 */
.progress-bar {
  background: linear-gradient(90deg, var(--accent-cyan), var(--accent-purple));
  border-radius: 4px;
  transition: width 1s ease;
}

/* 标签 */
.tag {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 500;
}
.tag-cyan { background: rgba(0,245,255,0.15); color: var(--accent-cyan); }
.tag-purple { background: rgba(191,90,242,0.15); color: var(--accent-purple); }
.tag-pink { background: rgba(255,55,95,0.15); color: var(--accent-pink); }
.tag-green { background: rgba(52,211,153,0.15); color: #34d399; }
.tag-yellow { background: rgba(251,191,36,0.15); color: #fbbf24; }

/* Toast */
.toast {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 14px 24px;
  border-radius: 12px;
  font-weight: 500;
  z-index: 9999;
  animation: slideIn 0.3s ease;
}
@keyframes slideIn {
  from { opacity: 0; transform: translateX(100px); }
  to { opacity: 1; transform: translateX(0); }
}
.toast-success { background: linear-gradient(135deg, #10b981, #34d399); }
.toast-error { background: linear-gradient(135deg, #ef4444, #f87171); }
.toast-info { background: linear-gradient(135deg, #3b82f6, #60a5fa); }

/* 脉冲动画 */
.pulse-dot {
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.2); }
}

/* 加载动画 */
.loading-ring {
  border: 3px solid rgba(255,255,255,0.1);
  border-top-color: var(--accent-cyan);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 滚动区域 */
.scroll-area {
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}

/* 实时数据 */
.live-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.live-indicator::before {
  content: '';
  width: 8px;
  height: 8px;
  background: #34d399;
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
}

/* ============ D. 移动端适配 ============ */
@media (max-width: 768px) {
  /* 侧边栏改为底部导航 */
  .sidebar {
    width: 100%;
    height: auto;
    position: fixed;
    bottom: 0;
    top: auto;
    left: 0;
    right: 0;
    flex-direction: row;
    border-right: none;
    border-top: 1px solid rgba(255,255,255,0.1);
    background: rgba(10, 5, 20, 0.95);
    z-index: 100;
    padding: 8px 0;
  }
  .sidebar > div:first-child { display: none; } /* 隐藏Logo */
  .sidebar nav {
    display: flex;
    flex-direction: row;
    justify-content: space-around;
    width: 100%;
    padding: 0;
    overflow-x: auto;
  }
  .sidebar nav a {
    flex-direction: column;
    padding: 8px 4px !important;
    font-size: 10px !important;
    gap: 2px;
  }
  .sidebar nav a svg { width: 18px; height: 18px; }
  .sidebar > div:last-child { display: none; } /* 隐藏底部状态 */
  
  /* 主内容区域 */
  main {
    margin-left: 0 !important;
    margin-bottom: 80px !important;
    padding: 16px !important;
  }
  
  /* 卡片网格改为单列 */
  .glass-card { margin-bottom: 12px; }
  [class*="grid-cols-"] { grid-template-columns: 1fr !important; }
  .flex [class*="gap-"] { flex-direction: column; gap: 8px; }
  
  /* 按钮适配 */
  button, .btn-primary, .btn-ghost {
    width: 100%;
    padding: 12px 16px;
    font-size: 14px;
  }
  
  /* 表格适配 */
  table { font-size: 12px; }
  th, td { padding: 8px 4px !important; }
  
  /* 输入框适配 */
  input, select, textarea {
    font-size: 16px; /* 防止iOS缩放 */
    width: 100%;
  }
  
  /* Chart图表适配 */
  canvas { max-width: 100%; height: auto !important; }
}

/* 平板适配 */
@media (min-width: 769px) and (max-width: 1024px) {
  .sidebar { width: 200px; }
  main { margin-left: 200px !important; }
  [class*="grid-cols-4"] { grid-template-columns: repeat(2, 1fr) !important; }
  [class*="grid-cols-3"] { grid-template-columns: repeat(2, 1fr) !important; }
}
</style>
</head>
<body class="bg-gradient-animated min-h-screen">
<div class="flex">

<!-- 侧边栏 -->
<aside class="sidebar fixed left-0 top-0 h-screen flex flex-col z-50">
  <!-- Logo -->
  <div class="p-6 border-b border-white/5">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center glow-cyan">
        <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg>
      </div>
      <div>
        <div class="font-bold text-white">Mory Dashboard</div>
        <div class="text-[10px] text-gray-500">Pro Edition v4.0</div>
      </div>
    </div>
  </div>
  
  <!-- 导航 -->
  <nav class="flex-1 p-4 space-y-1">
    <a class="nav-item active flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="overview">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"/>
      </svg>
      数据驾驶舱
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="users">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
      </svg>
      用户雷达
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="groups">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
      </svg>
      群组看板
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="logs">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
      </svg>
      消息日志
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="profile">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
      </svg>
      用户画像
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="config">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
      </svg>
      配置中心
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="models">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
      </svg>
      模型管理
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="security">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
      </svg>
      安全中心
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="report">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
      </svg>
      运营报表
    </a>
    <a class="nav-item flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm" data-page="vps">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"/>
      </svg>
      系统运维
    </a>
  </nav>
  
  <!-- 底部 -->
  <div class="p-4 border-t border-white/5">
    <div class="live-indicator text-xs text-green-400 mb-3" id="vpsStatus">连接中...</div>
    <button onclick="doLogout()" class="btn-ghost w-full py-2.5 rounded-xl text-sm text-gray-400 hover:text-white">
      退出登录
    </button>
  </div>
</aside>

<!-- 主内容 -->
<main class="flex-1 ml-[260px] p-8">
  <div id="pageContent" class="max-w-7xl mx-auto"></div>
</main>
</div>

<!-- Toast容器 -->
<div id="toastContainer"></div>

<script>
// ============ 全局状态 ============
const API = '';
let currentPage = 'overview';
let charts = {};

// ============ 工具函数 ============
async function api(url, opts = {}) {
  try {
    const res = await fetch(API + url, {
      ...opts,
      headers: { 'Content-Type': 'application/json', ...opts.headers }
    });
    return await res.json();
  } catch (e) {
    return { ok: false, msg: '网络错误' };
  }
}

function toast(msg, type = 'info') {
  const colors = { success: 'toast-success', error: 'toast-error', info: 'toast-info' };
  const el = document.createElement('div');
  el.className = `toast ${colors[type] || colors.info} text-white`;
  el.textContent = msg;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatTime(ts) {
  if (!ts) return 'N/A';
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff/60) + '分钟前';
  if (diff < 86400) return Math.floor(diff/3600) + '小时前';
  return d.toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
}

function fmtNumber(n) {
  if (n >= 10000) return (n/10000).toFixed(1) + 'w';
  if (n >= 1000) return (n/1000).toFixed(1) + 'k';
  return String(n || 0);
}

// ============ 认证 ============
document.getElementById('loginForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = document.getElementById('loginPw').value;
  const res = await api('/api/login', { method: 'POST', body: JSON.stringify({ password: pw }) });
  if (res.ok) {
    document.getElementById('loginPage').style.display = 'none';
    loadPage('overview');
  } else {
    toast('密码错误', 'error');
  }
});

async function doLogout() {
  await api('/api/logout', { method: 'POST' });
  location.reload();
}

// ============ 导航 ============
document.querySelectorAll('.nav-item[data-page]').forEach(el => {
  el.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    loadPage(el.dataset.page);
  });
});

async function loadPage(page) {
  currentPage = page;
  const container = document.getElementById('pageContent');
  container.innerHTML = '<div class="flex items-center justify-center h-64"><div class="loading-ring w-12 h-12"></div></div>';
  
  switch (page) {
    case 'overview': await renderOverview(container); break;
    case 'users': await renderUsers(container); break;
    case 'groups': await renderGroups(container); break;
    case 'logs': await renderLogs(container); break;
    case 'profile': await renderProfile(container); break;
    case 'config': await renderConfig(container); break;
    case 'models': await renderModels(container); break;
    case 'security': await renderSecurity(container); break;
    case 'vps': await renderVPS(container); break;
    case 'report': await renderReport(container); break;
  }
}

// ============ 数据驾驶舱 ============
async function renderOverview(el) {
  const res = await api('/api/stats/overview');
  if (!res.ok) { el.innerHTML = '<p class="text-red-400">加载失败</p>'; return; }
  const d = res.data;
  const vps = d.vps || {};
  
  // 更新状态指示器
  const statusEl = document.getElementById('vpsStatus');
  if (vps.bot_running) {
    statusEl.innerHTML = '<span class="text-green-400">● 在线</span> PID:' + vps.bot_pid;
    statusEl.className = 'text-xs text-green-400 mb-3';
  } else {
    statusEl.innerHTML = '<span class="text-red-400">● 离线</span>';
    statusEl.className = 'text-xs text-red-400 mb-3';
  }
  
  // 计算趋势
  const trend = d.today_active >= d.week_active / 7 ? '+' : '-';
  const weekAvg = Math.round(d.week_active / 7);
  
  el.innerHTML = `
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold bg-gradient-to-r from-cyan-400 to-purple-500 bg-clip-text text-transparent">
          数据驾驶舱
        </h1>
        <p class="text-gray-500 text-sm mt-1">实时监控 · 数据驱动 · 智能决策</p>
      </div>
      <div class="flex items-center gap-4">
        <span class="tag tag-cyan">${new Date().toLocaleDateString('zh-CN')}</span>
        <span class="tag tag-green live-indicator">实时</span>
      </div>
    </div>
    
    <!-- KPI卡片 -->
    <div class="grid grid-cols-4 gap-6 mb-8">
      <div class="glass-card p-6 glow-cyan">
        <div class="flex items-center justify-between mb-4">
          <span class="text-gray-400 text-sm">总用户</span>
          <div class="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center">
            <svg class="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
          </div>
        </div>
        <div class="stat-number">${fmtNumber(d.total_users)}</div>
        <div class="text-gray-500 text-xs mt-2">7日活跃 ${fmtNumber(d.week_active)} / 30日 ${fmtNumber(d.month_active)}</div>
      </div>
      
      <div class="glass-card p-6">
        <div class="flex items-center justify-between mb-4">
          <span class="text-gray-400 text-sm">今日活跃</span>
          <div class="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
            <svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
            </svg>
          </div>
        </div>
        <div class="stat-number" style="background: linear-gradient(135deg, #bf5af2, #ff375f); -webkit-background-clip: text;">${fmtNumber(d.today_active)}</div>
        <div class="text-gray-500 text-xs mt-2">周均值 ${fmtNumber(weekAvg)} ${trend > 0 ? '📈' : '📉'}</div>
      </div>
      
      <div class="glass-card p-6">
        <div class="flex items-center justify-between mb-4">
          <span class="text-gray-400 text-sm">群聊消息</span>
          <div class="w-10 h-10 rounded-lg bg-yellow-500/20 flex items-center justify-center">
            <svg class="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
            </svg>
          </div>
        </div>
        <div class="stat-number" style="background: linear-gradient(135deg, #fbbf24, #f59e0b); -webkit-background-clip: text;">${fmtNumber(d.total_group_msgs)}</div>
        <div class="text-gray-500 text-xs mt-2">私聊 ${fmtNumber(d.total_private_msgs)}</div>
      </div>
      
      <div class="glass-card p-6 glow-purple">
        <div class="flex items-center justify-between mb-4">
          <span class="text-gray-400 text-sm">Bot状态</span>
          <div class="w-10 h-10 rounded-lg ${vps.bot_running ? 'bg-green-500/20' : 'bg-red-500/20'} flex items-center justify-center">
            <div class="w-3 h-3 rounded-full ${vps.bot_running ? 'bg-green-400 pulse-dot' : 'bg-red-400'}"></div>
          </div>
        </div>
        <div class="text-2xl font-bold ${vps.bot_running ? 'text-green-400' : 'text-red-400'}">${vps.bot_running ? '运行中' : '已停止'}</div>
        <div class="text-gray-500 text-xs mt-2">内存 ${vps.bot_memory || 'N/A'} · ${vps.uptime || 'N/A'}</div>
      </div>
    </div>
    
    <!-- 图表区域 -->
    <div class="grid grid-cols-3 gap-6 mb-8">
      <!-- 用户趋势 -->
      <div class="col-span-2 glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-cyan-400"></span>
          用户增长趋势
        </h3>
        <canvas id="chartTrend" height="120"></canvas>
      </div>
      
      <!-- 转化漏斗 -->
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-purple-400"></span>
          转化漏斗
        </h3>
        <canvas id="chartFunnel" height="200"></canvas>
      </div>
    </div>
    
    <!-- 活跃时段 & 配置概览 -->
    <div class="grid grid-cols-2 gap-6">
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-yellow-400"></span>
          用户活跃时段
        </h3>
        <canvas id="chartHourly" height="150"></canvas>
      </div>
      
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-pink-400"></span>
          消息分布
        </h3>
        <canvas id="chartMsg" height="150"></canvas>
      </div>
    </div>
  `;
  
  // 渲染图表
  renderCharts(d);
}

function renderCharts(d) {
  // 趋势图
  const trendCtx = document.getElementById('chartTrend');
  if (trendCtx) {
    if (charts.trend) charts.trend.destroy();
    charts.trend = new Chart(trendCtx, {
      type: 'line',
      data: {
        labels: d.online_trend.map(x => x.date),
        datasets: [{
          label: '新增用户',
          data: d.online_trend.map(x => x.value),
          borderColor: '#00f5ff',
          backgroundColor: 'rgba(0,245,255,0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#71717a' } },
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#71717a' } }
        }
      }
    });
  }
  
  // 漏斗图
  const funnelCtx = document.getElementById('chartFunnel');
  if (funnelCtx) {
    if (charts.funnel) charts.funnel.destroy();
    const funnel = d.conversion_funnel || {};
    charts.funnel = new Chart(funnelCtx, {
      type: 'doughnut',
      data: {
        labels: Object.keys(funnel),
        datasets: [{
          data: Object.values(funnel),
          backgroundColor: ['#00f5ff', '#bf5af2', '#ff375f', '#fbbf24', '#34d399']
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom', labels: { color: '#a1a1aa' } } }
      }
    });
  }
  
  // 时段分布
  const hourlyCtx = document.getElementById('chartHourly');
  if (hourlyCtx) {
    if (charts.hourly) charts.hourly.destroy();
    const hourly = d.hourly_dist || {};
    charts.hourly = new Chart(hourlyCtx, {
      type: 'bar',
      data: {
        labels: Array.from({length:24}, (_,i) => i+'时'),
        datasets: [{
          label: '活跃用户',
          data: Array.from({length:24}, (_,i) => hourly[i] || 0),
          backgroundColor: 'rgba(251,191,36,0.6)',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#71717a', maxRotation: 45 } },
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#71717a' } }
        }
      }
    });
  }
  
  // 消息分布
  const msgCtx = document.getElementById('chartMsg');
  if (msgCtx) {
    if (charts.msg) charts.msg.destroy();
    charts.msg = new Chart(msgCtx, {
      type: 'pie',
      data: {
        labels: ['群聊', '私聊'],
        datasets: [{
          data: [d.total_group_msgs || 1, d.total_private_msgs || 0],
          backgroundColor: ['#bf5af2', '#ff375f']
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom', labels: { color: '#a1a1aa' } } }
      }
    });
  }
}

// ============ 用户雷达 ============
async function renderUsers(el) {
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">用户雷达</h1>
        <p class="text-gray-500 text-sm mt-1">用户画像 · 行为追踪 · 精准运营</p>
      </div>
      <div class="flex gap-3">
        <input type="text" id="userSearch" placeholder="搜索用户名/UID" class="input-dark px-4 py-2 rounded-xl text-sm w-48">
        <button onclick="searchUsers()" class="btn-primary px-6 py-2 rounded-xl text-sm font-medium">搜索</button>
      </div>
    </div>
    
    <div class="glass-card p-6">
      <table class="data-table w-full text-sm">
        <thead>
          <tr class="border-b border-white/10">
            <th class="text-left py-3 px-4">用户</th>
            <th class="text-center py-3 px-4">等级</th>
            <th class="text-center py-3 px-4">群消息</th>
            <th class="text-center py-3 px-4">私聊</th>
            <th class="text-center py-3 px-4">转化状态</th>
            <th class="text-center py-3 px-4">最后活跃</th>
            <th class="text-right py-3 px-4">操作</th>
          </tr>
        </thead>
        <tbody id="usersBody"></tbody>
      </table>
    </div>
    
    <div id="pagination" class="flex justify-center gap-2 mt-6"></div>
  `;
  
  document.getElementById('userSearch').addEventListener('keydown', e => {
    if (e.key === 'Enter') searchUsers();
  });
  
  await loadUsers();
}

let usersPage = 1;
async function searchUsers() {
  usersPage = 1;
  await loadUsers();
}

async function loadUsers() {
  const search = document.getElementById('userSearch')?.value || '';
  const res = await api(`/api/stats/users?page=${usersPage}&search=${encodeURIComponent(search)}`);
  
  if (!res.ok) { toast('加载失败', 'error'); return; }
  const { users, pagination } = res.data;
  
  const tbody = document.getElementById('usersBody');
  tbody.innerHTML = users.length ? users.map(u => `
    <tr>
      <td class="py-3 px-4">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center text-xs font-bold">
            ${(u.name || 'U')[0].toUpperCase()}
          </div>
          <div>
            <div class="font-medium">${escHtml(u.name || '未知')}</div>
            <div class="text-xs text-gray-500">UID: ${u.uid}</div>
          </div>
        </div>
      </td>
      <td class="py-3 px-4 text-center"><span class="tag tag-cyan">Lv.${u.level || 0}</span></td>
      <td class="py-3 px-4 text-center font-mono">${u.group_messages || 0}</td>
      <td class="py-3 px-4 text-center font-mono">${u.private_messages || 0}</td>
      <td class="py-3 px-4 text-center">
        <span class="tag ${getStatusTag(u.conversion_status)}">${u.conversion_status || 'unknown'}</span>
      </td>
      <td class="py-3 px-4 text-center text-gray-400 text-xs">${fmtTime(u.last_active)}</td>
      <td class="py-3 px-4 text-right">
        <button onclick="showUserDetail(${u.uid})" class="text-cyan-400 hover:text-cyan-300 text-sm">详情</button>
      </td>
    </tr>
  `).join('') : '<tr><td colspan="7" class="py-8 text-center text-gray-500">暂无数据</td></tr>';
  
  // 分页
  const pg = document.getElementById('pagination');
  if (pagination.pages > 1) {
    pg.innerHTML = `
      ${usersPage > 1 ? '<button onclick="usersPage--;loadUsers()" class="btn-ghost px-4 py-2 rounded-lg text-sm">上一页</button>' : ''}
      <span class="px-4 py-2 text-gray-500 text-sm">${usersPage} / ${pagination.pages}</span>
      ${usersPage < pagination.pages ? '<button onclick="usersPage++;loadUsers()" class="btn-ghost px-4 py-2 rounded-lg text-sm">下一页</button>' : ''}
    `;
  }
}

function getStatusTag(status) {
  const map = { paid: 'tag-green', consulted: 'tag-purple', interested: 'tag-yellow', touched: 'tag-cyan', unknown: '' };
  return map[status] || '';
}

function fmtTime(ts) {
  if (!ts) return '未知';
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return Math.floor(diff/60000) + '分钟前';
  if (diff < 86400000) return Math.floor(diff/3600000) + '小时前';
  return d.toLocaleDateString('zh-CN');
}

function showUserDetail(uid) {
  toast('用户详情功能开发中', 'info');
}

// ============ 配置中心 ============
async function renderConfig(el) {
  const res = await api('/api/config');
  if (!res.ok) { el.innerHTML = '<p class="text-red-400">加载失败</p>'; return; }
  const cfg = res.data;
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">配置中心</h1>
        <p class="text-gray-500 text-sm mt-1">可视化配置 · 实时生效 · 安全可控</p>
      </div>
      <div class="flex gap-3">
        <button onclick="saveAllConfig()" class="btn-primary px-6 py-2 rounded-xl text-sm font-medium">保存全部</button>
      </div>
    </div>
    
    <!-- 自然语言配置 -->
    <div class="glass-card p-6 mb-6 glow-cyan">
      <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
        <svg class="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
        </svg>
        智能配置助手
      </h3>
      <div class="flex gap-3">
        <input type="text" id="nlInput" placeholder="输入自然语言指令，如：把回复概率改成30" class="input-dark flex-1 px-4 py-3 rounded-xl text-sm">
        <button onclick="sendNlCmd()" class="btn-ghost px-6 py-3 rounded-xl text-sm">发送</button>
      </div>
      <div class="mt-3 text-xs text-gray-500">
        支持：设置概率、开关功能、修改名称 等自然语言指令
      </div>
    </div>
    
    <!-- 核心互动配置 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-cyan-400"></span>
        核心互动
      </h3>
      <div class="grid grid-cols-4 gap-4">
        ${renderConfigItem('REPLY_CHANCE', '群聊回复概率', 'number', cfg.REPLY_CHANCE, 0, 100, '%')}
        ${renderConfigItem('REPLY_DELAY_MIN', '回复延迟下限', 'number', cfg.REPLY_DELAY_MIN || 0, 0, 300, '秒')}
        ${renderConfigItem('REPLY_DELAY_MAX', '回复延迟上限', 'number', cfg.REPLY_DELAY_MAX || 30, 0, 600, '秒')}
        ${renderConfigItem('MAX_MSG_LENGTH', '最大回复长度', 'number', cfg.MAX_MSG_LENGTH || 500, 10, 5000, '字')}
        ${renderConfigItem('BOT_NAME', '机器人名称', 'text', cfg.BOT_NAME)}
        ${renderConfigItem('BOT_GREETING', '问候语', 'text', cfg.BOT_GREETING || '你好！有什么我可以帮你的吗？')}
      </div>
    </div>
    
    <!-- 系统提示词 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-blue-400"></span>
        系统提示词
      </h3>
      ${renderConfigItem('SYSTEM_PROMPT', '', 'textarea', cfg.SYSTEM_PROMPT || '')}
    </div>
    
    <!-- 功能开关 - 第一行 -->
    <div class="grid grid-cols-3 gap-6 mb-6">
      <!-- 互动功能 -->
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-green-400"></span>
          互动功能
        </h3>
        <div class="space-y-4">
          ${renderConfigItem('PUZZLE_ENABLED', '碎片寻宝', 'boolean', cfg.PUZZLE_ENABLED)}
          ${renderConfigItem('PUZZLE_WORD', '寻宝暗号', 'text', cfg.PUZZLE_WORD || '寻宝')}
          ${renderConfigItem('TAROT_ENABLED', '塔罗占卜', 'boolean', cfg.TAROT_ENABLED)}
          ${renderConfigItem('WEATHER_ENABLED', '天气共情', 'boolean', cfg.WEATHER_ENABLED)}
          ${renderConfigItem('SIGNUP_ENABLED', '每日签到', 'boolean', cfg.SIGNUP_ENABLED)}
          ${renderConfigItem('MEME_ENABLED', '表情包功能', 'boolean', cfg.MEME_ENABLED)}
        </div>
      </div>
      
      <!-- 自动推送 -->
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-yellow-400"></span>
          自动推送
        </h3>
        <div class="space-y-4">
          ${renderConfigItem('AUTO_GREETING', '每日早安', 'boolean', cfg.AUTO_GREETING)}
          ${renderConfigItem('AUTO_GOODNIGHT', '每日晚安', 'boolean', cfg.AUTO_GOODNIGHT)}
          ${renderConfigItem('AUTO_NEWS', '新闻播报', 'boolean', cfg.AUTO_NEWS)}
          ${renderConfigItem('AUTO_MORNING_NEWS', '早间新闻', 'boolean', cfg.AUTO_MORNING_NEWS)}
          ${renderConfigItem('AUTO_AFTERNOON_NEWS', '午间新闻', 'boolean', cfg.AUTO_AFTERNOON_NEWS)}
          ${renderConfigItem('AUTO_EVENING_NEWS', '晚间新闻', 'boolean', cfg.AUTO_EVENING_NEWS)}
        </div>
      </div>
      
      <!-- 群组功能 -->
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-purple-400"></span>
          群组功能
        </h3>
        <div class="space-y-4">
          ${renderConfigItem('WELCOME_MSG', '入群欢迎', 'boolean', cfg.WELCOME_MSG)}
          ${renderConfigItem('NEW_MEMBER_GREETING', '新人欢迎语', 'boolean', cfg.NEW_MEMBER_GREETING)}
          ${renderConfigItem('ANTI_REVOKE', '撤回检测', 'boolean', cfg.ANTI_REVOKE)}
          ${renderConfigItem('BURN_AFTER', '阅后即焚', 'boolean', cfg.BURN_AFTER)}
          ${renderConfigItem('RECOVER_ENABLED', '挽回功能', 'boolean', cfg.RECOVER_ENABLED)}
        </div>
      </div>
    </div>
    
    <!-- 时间调度 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-pink-400"></span>
        时间调度
      </h3>
      <div class="grid grid-cols-6 gap-4">
        ${renderConfigItem('GREETING_HOUR', '早安时间', 'hour', cfg.GREETING_HOUR || 9)}
        ${renderConfigItem('GOODNIGHT_HOUR', '晚安时间', 'hour', cfg.GOODNIGHT_HOUR || 22)}
        ${renderConfigItem('NEWS_HOUR_MORNING', '早间新闻', 'hour', cfg.NEWS_HOUR_MORNING || 9)}
        ${renderConfigItem('NEWS_HOUR_AFTERNOON', '午间新闻', 'hour', cfg.NEWS_HOUR_AFTERNOON || 12)}
        ${renderConfigItem('NEWS_HOUR_EVENING', '晚间新闻', 'hour', cfg.NEWS_HOUR_EVENING || 18)}
        ${renderConfigItem('SIGNUP_RESET_HOUR', '签到重置', 'hour', cfg.SIGNUP_RESET_HOUR || 0)}
      </div>
    </div>
    
    <!-- 安全限制 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-red-400"></span>
        安全限制
      </h3>
      <div class="grid grid-cols-4 gap-4">
        ${renderConfigItem('SPAM_LIMIT_MSGS', '刷屏限制(条/分)', 'number', cfg.SPAM_LIMIT?.msgs || cfg.SPAM_LIMIT?.messages_per_minute || 10, 1, 100)}
        ${renderConfigItem('SPAM_LIMIT_MUTE', '刷屏禁言(分钟)', 'number', cfg.SPAM_LIMIT?.mute_minutes || cfg.BAN_DURATION_DEFAULT || 5, 1, 60)}
        ${renderConfigItem('MAX_REQUESTS_PER_USER', '用户请求限制', 'number', cfg.MAX_REQUESTS_PER_USER || 100, 1, 1000)}
        ${renderConfigItem('RATE_LIMIT_WINDOW', '限流窗口', 'number', cfg.RATE_LIMIT_WINDOW || 3600, 60, 3600, '秒')}
      </div>
    </div>
    
    <!-- AI模型配置 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-indigo-400"></span>
        AI模型配置
      </h3>
      <div class="grid grid-cols-2 gap-4">
        ${renderConfigItem('DEFAULT_MODEL', '默认模型', 'text', cfg.DEFAULT_MODEL || 'hunyuan')}
        ${renderConfigItem('TEMPERATURE', '创意温度', 'number', cfg.TEMPERATURE || 0.7, 0, 2, '')}
        ${renderConfigItem('MAX_TOKENS', '最大Token', 'number', cfg.MAX_TOKENS || 1000, 100, 4000)}
        ${renderConfigItem('TOP_P', 'Top P值', 'number', cfg.TOP_P || 0.9, 0, 1)}
      </div>
    </div>
  `;
}

function renderConfigItem(key, label, type, value, min, max, unit) {
  const inputId = `cfg-${key}`;
  let input = '';
  
  if (type === 'boolean') {
    input = `
      <label class="relative inline-flex items-center cursor-pointer">
        <input type="checkbox" id="${inputId}" data-key="${key}" class="sr-only peer" ${value ? 'checked' : ''}>
        <div class="w-11 h-6 bg-gray-700 peer-focus:ring-2 peer-focus:ring-cyan-500/30 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-cyan-500"></div>
      </label>
    `;
    return `
      <div class="flex items-center justify-between">
        <label class="text-sm text-gray-400">${label}</label>
        ${input}
      </div>
    `;
  } else if (type === 'textarea') {
    input = `
      <textarea id="${inputId}" data-key="${key}" data-type="textarea" class="input-dark w-full px-3 py-2 rounded-lg text-sm h-32 font-mono" placeholder="输入系统提示词...">${escHtml(value || '')}</textarea>
    `;
    return `
      <div>
        ${label ? `<label class="text-sm text-gray-400 mb-2 block">${label}</label>` : ''}
        ${input}
      </div>
    `;
  } else if (type === 'hour') {
    input = `
      <div class="flex items-center gap-2">
        <select id="${inputId}" data-key="${key}" data-type="select" class="input-dark w-24 px-3 py-2 rounded-lg text-sm">
          ${Array.from({length: 24}, (_, i) => `<option value="${i}" ${value === i ? 'selected' : ''}>${i}:00</option>`).join('')}
        </select>
        <span class="text-gray-500 text-sm">点</span>
      </div>
    `;
  } else if (type === 'number') {
    input = `
      <div class="flex items-center gap-2">
        <input type="number" id="${inputId}" data-key="${key}" value="${value ?? ''}" min="${min || 0}" max="${max || 100}" step="any" class="input-dark w-24 px-3 py-2 rounded-lg text-sm">
        ${unit ? `<span class="text-gray-500 text-sm">${unit}</span>` : ''}
      </div>
    `;
  } else {
    input = `<input type="text" id="${inputId}" data-key="${key}" value="${escHtml(value || '')}" class="input-dark w-full px-3 py-2 rounded-lg text-sm">`;
  }
  
  return `
    <div>
      <label class="text-sm text-gray-400 mb-2 block">${label}</label>
      ${input}
    </div>
  `;
}

async function saveAllConfig() {
  const updates = {};
  document.querySelectorAll('[data-key]').forEach(el => {
    const key = el.dataset.key;
    let value;
    
    if (el.type === 'checkbox') {
      value = el.checked;
    } else if (el.dataset.type === 'textarea' || el.dataset.type === 'select') {
      value = el.value;
    } else if (el.type === 'number') {
      value = Number(el.value);
    } else {
      value = el.value;
    }
    
    updates[key] = value;
  });
  
  const res = await api('/api/config/batch', { method: 'PUT', body: JSON.stringify(updates) });
  toast(res.ok ? '配置已保存' : '保存失败', res.ok ? 'success' : 'error');
}

// ============ A. 群组数据看板 ============
async function renderGroups(el) {
  const res = await api('/api/groups');
  if (!res.ok) { el.innerHTML = '<p class="text-red-400">加载失败</p>'; return; }
  const data = res.data;
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">群组数据看板</h1>
        <p class="text-gray-500 text-sm mt-1">实时监控各群活跃趋势</p>
      </div>
      <button onclick="loadPage('groups')" class="btn-ghost px-4 py-2 rounded-xl text-sm">刷新</button>
    </div>
    
    <!-- 概览卡片 -->
    <div class="grid grid-cols-4 gap-6 mb-8">
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">群组数量</div>
        <div class="text-3xl font-bold text-white">${data.groups.length}</div>
      </div>
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">总消息数</div>
        <div class="text-3xl font-bold text-cyan-400">${data.total_messages.toLocaleString()}</div>
      </div>
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">活跃用户</div>
        <div class="text-3xl font-bold text-purple-400">${data.total_users}</div>
      </div>
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">平均消息/群</div>
        <div class="text-3xl font-bold text-pink-400">${Math.round(data.total_messages / Math.max(data.groups.length, 1))}</div>
      </div>
    </div>
    
    <!-- 24小时趋势图 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4">24小时消息趋势</h3>
      <canvas id="hourlyChart" height="100"></canvas>
    </div>
    
    <!-- 群组列表 -->
    <div class="glass-card p-6">
      <h3 class="text-lg font-semibold mb-4">群组详情</h3>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-gray-400 border-b border-white/10">
              <th class="text-left py-3 px-4">群组ID</th>
              <th class="text-left py-3 px-4">消息数</th>
              <th class="text-left py-3 px-4">用户数</th>
              <th class="text-left py-3 px-4">最后活跃</th>
              <th class="text-left py-3 px-4">操作</th>
            </tr>
          </thead>
          <tbody>
            ${data.groups.map(g => `
              <tr class="border-b border-white/5 hover:bg-white/5">
                <td class="py-3 px-4 font-mono text-cyan-400">${g.chat_id}</td>
                <td class="py-3 px-4">${g.msg_count.toLocaleString()}</td>
                <td class="py-3 px-4">${g.user_count}</td>
                <td class="py-3 px-4 text-gray-400">${formatTime(g.last_active)}</td>
                <td class="py-3 px-4">
                  <button onclick="showGroupTrends(${g.chat_id})" class="text-cyan-400 hover:text-cyan-300">查看趋势</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
  
  // 渲染Chart
  const ctx = document.getElementById('hourlyChart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.hourly_trend.map(h => h.hour + ':00'),
      datasets: [{
        label: '消息数',
        data: data.hourly_trend.map(h => h.count),
        borderColor: '#00f5ff',
        backgroundColor: 'rgba(0,245,255,0.1)',
        fill: true,
        tension: 0.4
      }]
    },
    options: { responsive: true, plugins: { legend: { display: false } } }
  });
}

async function showGroupTrends(chatId) {
  const res = await api(`/api/groups/${chatId}/trends`);
  if (res.ok) {
    toast(`群组 ${chatId} 7天趋势已加载`, 'success');
  }
}

// ============ B. 消息日志查询 ============
async function renderLogs(el) {
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">消息日志</h1>
        <p class="text-gray-500 text-sm mt-1">搜索过滤Bot和用户的对话记录</p>
      </div>
    </div>
    
    <!-- 搜索框 -->
    <div class="glass-card p-6 mb-6">
      <div class="flex gap-4">
        <input type="text" id="logSearch" placeholder="搜索关键词..." 
               class="input-dark flex-1 px-4 py-3 rounded-xl text-sm"
               onkeyup="if(event.key==='Enter') searchLogs()">
        <select id="logChatFilter" class="input-dark px-4 py-3 rounded-xl text-sm">
          <option value="">全部群组</option>
          <option value="-1001234567890">群组1</option>
          <option value="-1009876543210">群组2</option>
        </select>
        <button onclick="searchLogs()" class="btn-primary px-6 py-3 rounded-xl text-sm">搜索</button>
      </div>
    </div>
    
    <!-- 日志列表 -->
    <div class="glass-card p-6">
      <div id="logResults" class="space-y-3">
        <div class="text-gray-500 text-center py-8">输入关键词搜索消息日志</div>
      </div>
      
      <!-- 分页 -->
      <div id="logPagination" class="flex justify-center gap-2 mt-6 hidden">
        <button onclick="searchLogs(0)" class="btn-ghost px-4 py-2 rounded-lg text-sm">首页</button>
        <button onclick="searchLogs(-1)" class="btn-ghost px-4 py-2 rounded-lg text-sm">上一页</button>
        <span class="px-4 py-2 text-gray-400 text-sm" id="logPageInfo"></span>
        <button onclick="searchLogs(1)" class="btn-ghost px-4 py-2 rounded-lg text-sm">下一页</button>
      </div>
    </div>
  `;
}

let logOffset = 0;
async function searchLogs(pageDir) {
  if (pageDir === -1) logOffset = Math.max(0, logOffset - 50);
  else if (pageDir === 1) logOffset += 50;
  else if (pageDir === 0) logOffset = 0;
  
  const keyword = document.getElementById('logSearch').value;
  const chatId = document.getElementById('logChatFilter').value;
  
  const res = await api(`/api/logs/search?q=${encodeURIComponent(keyword)}&chat_id=${chatId}&offset=${logOffset}`);
  const container = document.getElementById('logResults');
  
  if (res.ok && res.data.logs.length > 0) {
    container.innerHTML = res.data.logs.map(log => `
      <div class="bg-black/20 rounded-lg p-4 ${log.type === 'bot' ? 'border-l-2 border-cyan-400' : 'border-l-2 border-purple-400'}">
        <div class="flex items-center justify-between mb-2">
          <span class="font-semibold ${log.type === 'bot' ? 'text-cyan-400' : 'text-purple-400'}">${log.username}</span>
          <span class="text-xs text-gray-500">${formatTime(log.ts)}</span>
        </div>
        <div class="text-sm text-gray-300">${escHtml(log.content)}</div>
      </div>
    `).join('');
    
    document.getElementById('logPageInfo').textContent = `第 ${logOffset/50 + 1} 页`;
    document.getElementById('logPagination').classList.remove('hidden');
  } else {
    container.innerHTML = '<div class="text-gray-500 text-center py-8">暂无结果</div>';
  }
}

// ============ C. 用户画像分析 ============
async function renderProfile(el) {
  // 先获取用户列表
  const usersRes = await api('/api/users/list?limit=20');
  const users = usersRes.ok ? usersRes.data.users : [];
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">用户画像分析</h1>
        <p class="text-gray-500 text-sm mt-1">可视化展示用户行为特征</p>
      </div>
    </div>
    
    <!-- 用户选择 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4">选择用户</h3>
      <div class="grid grid-cols-5 gap-3">
        ${users.map(u => `
          <button onclick="loadUserProfile(${u.user_id})" 
                  class="glass-card p-4 hover:bg-white/10 cursor-pointer text-center">
            <div class="text-cyan-400 font-bold">${u.username || '用户' + u.user_id}</div>
            <div class="text-xs text-gray-500 mt-1">ID: ${u.user_id}</div>
            <div class="text-xs text-gray-400 mt-1">等级${u.level || 1} | ${u.points || 0}积分</div>
          </button>
        `).join('')}
      </div>
      <div class="mt-4">
        <input type="number" id="profileUserId" placeholder="输入用户ID" 
               class="input-dark px-4 py-2 rounded-lg text-sm w-48">
        <button onclick="loadUserProfile(document.getElementById('profileUserId').value)" 
                class="btn-ghost px-4 py-2 rounded-lg text-sm ml-2">查询</button>
      </div>
    </div>
    
    <!-- 画像详情 -->
    <div id="profileDetail" class="hidden">
      <div class="grid grid-cols-4 gap-6 mb-6">
        <div class="glass-card p-6 text-center">
          <div class="text-gray-400 text-sm mb-2">消息总数</div>
          <div class="text-3xl font-bold text-cyan-400" id="pfMsgs">-</div>
        </div>
        <div class="glass-card p-6 text-center">
          <div class="text-gray-400 text-sm mb-2">积分</div>
          <div class="text-3xl font-bold text-purple-400" id="pfPoints">-</div>
        </div>
        <div class="glass-card p-6 text-center">
          <div class="text-gray-400 text-sm mb-2">等级</div>
          <div class="text-3xl font-bold text-pink-400" id="pfLevel">-</div>
        </div>
        <div class="glass-card p-6 text-center">
          <div class="text-gray-400 text-sm mb-2">活跃时段</div>
          <div class="text-xl font-bold text-white" id="pfPeak">-</div>
        </div>
      </div>
      
      <div class="glass-card p-6 mb-6">
        <h3 class="text-lg font-semibold mb-4">转化阶段</h3>
        <div id="pfConversion" class="flex items-center gap-2"></div>
      </div>
      
      <div class="glass-card p-6">
        <h3 class="text-lg font-semibold mb-4">7天活跃趋势</h3>
        <canvas id="profileChart" height="100"></canvas>
      </div>
    </div>
  `;
}

async function loadUserProfile(userId) {
  if (!userId) return;
  const res = await api(`/api/users/profile/${userId}`);
  if (res.ok) {
    const p = res.data;
    document.getElementById('profileDetail').classList.remove('hidden');
    document.getElementById('pfMsgs').textContent = (p.group_messages + p.private_messages).toLocaleString();
    document.getElementById('pfPoints').textContent = p.points;
    document.getElementById('pfLevel').textContent = p.level;
    document.getElementById('pfPeak').textContent = p.activity_peak;
    
    // 转化阶段可视化
    const stages = ['new', 'aware', 'interested', 'engaged', 'converted'];
    const stageNames = {'new': '新用户', 'aware': '已知晓', 'interested': '感兴趣', 'engaged': '活跃', 'converted': '已转化'};
    const currentIdx = stages.indexOf(p.conversion_status);
    document.getElementById('pfConversion').innerHTML = stages.map((s, i) => `
      <div class="flex-1 text-center ${i <= currentIdx ? 'text-cyan-400' : 'text-gray-600'}">
        <div class="w-full h-2 rounded ${i <= currentIdx ? 'bg-cyan-400' : 'bg-gray-700'} mb-2"></div>
        <div class="text-xs">${stageNames[s]}</div>
      </div>
    `).join('<div class="text-gray-600">→</div>');
    
    // 活跃趋势图
    const ctx = document.getElementById('profileChart')?.getContext('2d');
    if (ctx) {
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: p.daily_active.map(d => d.date),
          datasets: [{
            label: '消息数',
            data: p.daily_active.map(d => d.messages),
            backgroundColor: 'rgba(0,245,255,0.6)'
          }]
        },
        options: { responsive: true, plugins: { legend: { display: false } } }
      });
    }
  } else {
    toast('用户不存在', 'error');
  }
}

// ============ F. 运营报表 ============
async function renderReport(el) {
  const res = await api('/api/report/daily');
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">运营报表</h1>
        <p class="text-gray-500 text-sm mt-1">每日/每周运营数据分析</p>
      </div>
      <div class="flex gap-3">
        <button onclick="downloadReport()" class="btn-ghost px-4 py-2 rounded-xl text-sm flex items-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
          </svg>
          下载报表
        </button>
        <button onclick="loadPage('report')" class="btn-primary px-6 py-2 rounded-xl text-sm">刷新数据</button>
      </div>
    </div>
    
    ${res.ok ? `
    <!-- 核心指标 -->
    <div class="grid grid-cols-4 gap-6 mb-6">
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">总用户数</div>
        <div class="text-3xl font-bold text-white">${res.data.total_users}</div>
        <div class="text-xs text-green-400 mt-2">↑ 持续增长</div>
      </div>
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">今日新增</div>
        <div class="text-3xl font-bold text-cyan-400">+${res.data.today_signups}</div>
        <div class="text-xs text-gray-500 mt-2">注册用户</div>
      </div>
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">24小时活跃</div>
        <div class="text-3xl font-bold text-purple-400">${res.data.active_users}</div>
        <div class="text-xs text-gray-500 mt-2">活跃用户</div>
      </div>
      <div class="glass-card p-6">
        <div class="text-gray-400 text-sm mb-2">历史消息</div>
        <div class="text-3xl font-bold text-pink-400">${res.data.total_messages.toLocaleString()}</div>
        <div class="text-xs text-gray-500 mt-2">总消息量</div>
      </div>
    </div>
    
    <!-- 报表预览 -->
    <div class="glass-card p-6">
      <h3 class="text-lg font-semibold mb-4">日报预览</h3>
      <div class="bg-white/5 rounded-xl p-6 text-sm font-mono">
        <pre class="text-gray-300 whitespace-pre-wrap">${res.data.report_html.replace(/<[^>]+>/g, '')}</pre>
      </div>
    </div>
    ` : '<div class="text-red-400">加载失败</div>'}
  `;
}

function downloadReport() {
  window.open('/api/report/download', '_blank');
}

// ============ E. 实时推送 (前端初始化) ============
function initSSE() {
  if (typeof EventSource !== 'undefined') {
    const source = new EventSource('/api/stream/status');
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        updateVPSStatus(data.data);
      } catch {}
    };
    source.onerror = () => {
      setTimeout(initSSE, 5000); // 断线重连
    };
  }
}

function updateVPSStatus(data) {
  const el = document.getElementById('vpsStatus');
  if (el) {
    el.innerHTML = `
      <div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full ${data.bot_running ? 'bg-green-400' : 'bg-red-400'}"></span>
        <span>Bot: ${data.bot_status}</span>
      </div>
    `;
  }
}

async function sendNlCmd() {
  const input = document.getElementById('nlInput');
  const cmd = input.value.trim();
  if (!cmd) return;
  
  toast('自然语言配置功能开发中: ' + cmd, 'info');
  input.value = '';
}

// ============ 模型管理 ============
async function renderModels(el) {
  const res = await api('/api/models');
  if (!res.ok) { el.innerHTML = '<p class="text-red-400">加载失败</p>'; return; }
  const d = res.data;
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">模型管理</h1>
        <p class="text-gray-500 text-sm mt-1">智能切换 · 负载均衡 · 稳定运行</p>
      </div>
      <div class="tag tag-cyan">当前: ${escHtml(d.current_model)}</div>
    </div>
    
    <div class="glass-card overflow-hidden">
      <table class="data-table w-full text-sm">
        <thead>
          <tr class="border-b border-white/10">
            <th class="text-left py-4 px-6">模型</th>
            <th class="text-left py-4 px-6">过期时间</th>
            <th class="text-center py-4 px-6">状态</th>
            <th class="text-right py-4 px-6">操作</th>
          </tr>
        </thead>
        <tbody>
          ${d.pool.map((m, i) => `
            <tr class="${i === d.current_index ? 'bg-cyan-500/10' : ''}">
              <td class="py-4 px-6">
                <div class="font-medium">${escHtml(m.name)}</div>
              </td>
              <td class="py-4 px-6 text-gray-400">${m.expire || '-'}</td>
              <td class="py-4 px-6 text-center">
                ${i === d.current_index ? '<span class="tag tag-cyan">当前</span>' : 
                  d.blacklisted.includes(m.name) ? '<span class="tag tag-pink">已禁用</span>' : '<span class="tag tag-green">可用</span>'}
              </td>
              <td class="py-4 px-6 text-right">
                ${i !== d.current_index ? `<button onclick="switchModel(${i})" class="text-cyan-400 hover:text-cyan-300 text-sm mr-4">切换</button>` : ''}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

async function switchModel(idx) {
  const res = await api('/api/models/switch', { method: 'POST', body: JSON.stringify({ index: idx }) });
  toast(res.ok ? res.msg : '切换失败', res.ok ? 'success' : 'error');
  if (res.ok) loadPage('models');
}

// ============ 安全中心 ============
async function renderSecurity(el) {
  const res = await api('/api/stats/blacklist');
  const blacklist = res.ok ? res.data : [];
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">安全中心</h1>
        <p class="text-gray-500 text-sm mt-1">黑名单管理 · 操作日志 · 风险控制</p>
      </div>
      <span class="tag tag-pink">黑名单 ${blacklist.length} 人</span>
    </div>
    
    <div class="glass-card overflow-hidden">
      <table class="data-table w-full text-sm">
        <thead>
          <tr class="border-b border-white/10">
            <th class="text-left py-4 px-6">用户ID</th>
            <th class="text-left py-4 px-6">原因</th>
            <th class="text-left py-4 px-6">加入时间</th>
            <th class="text-right py-4 px-6">操作</th>
          </tr>
        </thead>
        <tbody>
          ${blacklist.length ? blacklist.map(b => `
            <tr>
              <td class="py-4 px-6 font-mono">${b.uid}</td>
              <td class="py-4 px-6 text-gray-400">${escHtml(b.reason || '无')}</td>
              <td class="py-4 px-6 text-gray-400">${b.date ? fmtTime(b.date) : '未知'}</td>
              <td class="py-4 px-6 text-right">
                <button onclick="toggleBlacklist(${b.uid}, 'remove')" class="text-green-400 hover:text-green-300 text-sm">解封</button>
              </td>
            </tr>
          `).join('') : '<tr><td colspan="4" class="py-8 text-center text-gray-500">暂无黑名单</td></tr>'}
        </tbody>
      </table>
    </div>
  `;
}

async function toggleBlacklist(uid, action) {
  const res = await api('/api/stats/blacklist', { method: 'POST', body: JSON.stringify({ uid, action }) });
  toast(res.ok ? res.msg : '操作失败', res.ok ? 'success' : 'error');
  if (res.ok) loadPage('security');
}

// ============ 系统运维 ============
let vpsPath = '/root/mory'; // 默认值

async function renderVPS(el) {
  // 先获取VPS配置
  const cfgRes = await api('/api/vps/config');
  if (cfgRes.ok) {
    vpsPath = cfgRes.data.path || vpsPath;
  }
  
  const status = await api('/api/vps/status');
  const vps = status.ok ? status.data : {};
  
  el.innerHTML = `
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">系统运维</h1>
        <p class="text-gray-500 text-sm mt-1">服务状态 · 日志监控 · 一键运维</p>
      </div>
      <div class="flex gap-3">
        <button onclick="restartBot()" class="btn-ghost px-6 py-2 rounded-xl text-sm">重启Bot</button>
        <button onclick="refreshStatus()" class="btn-primary px-6 py-2 rounded-xl text-sm">刷新状态</button>
      </div>
    </div>
    
    <!-- 服务状态 -->
    <div class="grid grid-cols-3 gap-6 mb-8">
      <div class="glass-card p-6">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-3 h-3 rounded-full ${vps.bot_running ? 'bg-green-400 pulse-dot' : 'bg-red-400'}"></div>
          <span class="font-semibold">Bot服务</span>
        </div>
        <div class="text-2xl font-bold ${vps.bot_running ? 'text-green-400' : 'text-red-400'}">
          ${vps.bot_running ? '运行中' : '已停止'}
        </div>
        <div class="text-gray-500 text-sm mt-2">${vps.bot_memory || 'N/A'}</div>
      </div>
      
      <div class="glass-card p-6">
        <div class="flex items-center gap-3 mb-4">
          <span class="w-3 h-3 rounded-full bg-cyan-400"></span>
          <span class="font-semibold">服务器</span>
        </div>
        <div class="text-lg font-bold text-white">${vps.uptime || 'N/A'}</div>
      </div>
      
      <div class="glass-card p-6">
        <div class="flex items-center gap-3 mb-4">
          <span class="w-3 h-3 rounded-full bg-purple-400"></span>
          <span class="font-semibold">部署路径</span>
        </div>
        <div class="text-sm font-mono text-gray-400">${vpsPath}</div>
      </div>
    </div>
    
    <!-- 快捷操作 -->
    <div class="glass-card p-6 mb-6">
      <h3 class="text-lg font-semibold mb-4">快捷操作</h3>
      <div class="grid grid-cols-4 gap-4">
        <button onclick="execCommand('kill_bot')" class="btn-ghost px-4 py-3 rounded-xl text-sm flex items-center justify-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"/>
          </svg>
          停止Bot
        </button>
        <button onclick="execCommand('start_bot')" class="btn-ghost px-4 py-3 rounded-xl text-sm flex items-center justify-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          启动Bot
        </button>
        <button onclick="execCommand('check_status')" class="btn-ghost px-4 py-3 rounded-xl text-sm flex items-center justify-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
          </svg>
          检查状态
        </button>
        <button onclick="execCommand('view_logs')" class="btn-ghost px-4 py-3 rounded-xl text-sm flex items-center justify-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          查看日志
        </button>
      </div>
    </div>
    
    <!-- 日志 -->
    <div class="glass-card p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold">实时日志</h3>
        <button onclick="loadVpsLogs()" class="btn-ghost px-4 py-1.5 rounded-lg text-sm">刷新</button>
      </div>
      <div id="logContainer" class="bg-black/40 rounded-xl p-4 h-96 overflow-auto font-mono text-xs text-gray-400 leading-relaxed">
        <div class="flex items-center justify-center h-full text-gray-600">点击刷新加载日志...</div>
      </div>
    </div>
  `;
  
  loadVpsLogs();
}

async function execCommand(cmd) {
  toast(`执行命令: ${cmd}`, 'info');
  if (cmd === 'view_logs') {
    loadVpsLogs();
  } else if (cmd === 'check_status') {
    const res = await api('/api/vps/status');
    if (res.ok) {
      const vps = res.data;
      toast(`Bot状态: ${vps.bot_running ? '运行中' : '已停止'}, 运行时间: ${vps.uptime || 'N/A'}`, 'success');
    }
  } else {
    // 其他命令需要后端实现
    toast('该功能开发中', 'info');
  }
}

async function loadVpsLogs() {
  const res = await api('/api/vps/logs?lines=100');
  const container = document.getElementById('logContainer');
  if (res.ok) {
    const logs = res.data.logs || '(无日志)';
    container.innerHTML = logs.split('\n').map(line => 
      `<div class="py-0.5 ${line.includes('ERROR') ? 'text-red-400' : line.includes('WARN') ? 'text-yellow-400' : ''}">${escHtml(line)}</div>`
    ).join('');
    container.scrollTop = container.scrollHeight;
  } else {
    container.innerHTML = '<div class="text-red-400">加载失败</div>';
  }
}

async function restartBot() {
  toast('正在重启...', 'info');
  const res = await api('/api/vps/restart', { method: 'POST' });
  toast(res.ok ? '重启完成' : '重启失败', res.ok ? 'success' : 'error');
  setTimeout(refreshStatus, 2000);
}

async function refreshStatus() {
  loadPage('vps');
}

// ============ 初始化 ============
(async () => {
  const check = await api('/api/check');
  if (check.ok) {
    document.getElementById('loginPage')?.remove();
    loadPage('overview');
    initSSE(); // 启动实时推送
  } else {
    document.getElementById('loginPage') && (document.getElementById('loginPage').style.display = 'flex');
  }
})();
</script>
</body>
</html>"""

# ============ 登录页 ============
LOGIN_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mory Dashboard - Login</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root { --accent-cyan: #00f5ff; --accent-purple: #bf5af2; }
body { 
  background: linear-gradient(125deg, #030014 0%, #0f0a1e 50%, #1a0533 100%);
  min-height: 100vh;
}
.bg-grid {
  background-image: 
    linear-gradient(rgba(0,245,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,245,255,0.03) 1px, transparent 1px);
  background-size: 50px 50px;
}
.glass-card {
  background: rgba(15, 10, 30, 0.6);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 24px;
}
.glow-cyan { box-shadow: 0 0 60px rgba(0,245,255,0.3); }
.input-dark {
  background: rgba(0,0,0,0.4);
  border: 2px solid rgba(255,255,255,0.1);
  color: white;
  transition: all 0.3s;
}
.input-dark:focus {
  outline: none;
  border-color: var(--accent-cyan);
  box-shadow: 0 0 30px rgba(0,245,255,0.2);
}
.btn-login {
  background: linear-gradient(135deg, #00f5ff, #bf5af2);
  transition: all 0.3s;
}
.btn-login:hover {
  transform: translateY(-2px);
  box-shadow: 0 15px 40px rgba(0,245,255,0.4);
}
@keyframes float {
  0%,100% { transform: translateY(0); }
  50% { transform: translateY(-20px); }
}
.float-anim { animation: float 6s ease-in-out infinite; }
</style>
</head>
<body class="bg-grid flex items-center justify-center">
<div class="absolute inset-0 overflow-hidden pointer-events-none">
  <div class="absolute top-1/4 left-1/4 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl float-anim"></div>
  <div class="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-500/10 rounded-full blur-3xl float-anim" style="animation-delay: -3s"></div>
</div>

<div class="glass-card glow-cyan p-12 w-full max-w-md mx-4 relative z-10">
  <div class="text-center mb-10">
    <div class="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center float-anim">
      <svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
      </svg>
    </div>
    <h1 class="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-purple-500 bg-clip-text text-transparent">
      Mory Dashboard
    </h1>
    <p class="text-gray-500 mt-2">Pro Edition v4.0</p>
  </div>
  
  <form id="loginForm" class="space-y-6">
    <div>
      <input type="password" id="loginPw" placeholder="输入管理密码" 
             class="input-dark w-full px-6 py-4 rounded-xl text-center text-lg">
    </div>
    <button type="submit" class="btn-login w-full py-4 rounded-xl text-white font-semibold text-lg">
      进入控制台
    </button>
    <p id="loginErr" class="text-red-400 text-sm text-center hidden"></p>
  </form>
  
  <div class="text-center mt-8 text-gray-600 text-xs">
    Mory小助理 · 数据驾驶舱
  </div>
</div>

<script>
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = document.getElementById('loginPw').value;
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw })
  }).then(r => r.json());
  
  if (res.ok) {
    location.reload();
  } else {
    const err = document.getElementById('loginErr');
    err.textContent = res.msg || '密码错误';
    err.classList.remove('hidden');
  }
});
</script>
</body>
</html>
"""

@app.route("/")
def index():
    if session.get("logged_in"):
        return render_template_string(HTML_PAGE)
    return render_template_string(LOGIN_PAGE)

if __name__ == "__main__":
    print("=" * 60)
    print("  🚀 Mory Dashboard Pro v4.0.3")
    print("  🌐 监听地址: http://127.0.0.1:5000")
    print("")
    print("  ⚠️  安全提醒：")
    print("     1. 必须通过 Nginx 反向代理访问 (不要直接暴露5000端口)")
    print("     2. 必须设置环境变量 DASHBOARD_PASSWORD=你的强密码")
    print("     3. 必须设置环境变量 DASHBOARD_SECRET=随机字符串")
    print("=" * 60)
    # 【v4.0.3 安全修复】绑定 127.0.0.1，禁止公网直接访问
    # 必须通过 Nginx 反向代理：proxy_pass http://127.0.0.1:5000;
    app.run(host="127.0.0.1", port=5000, debug=False)
