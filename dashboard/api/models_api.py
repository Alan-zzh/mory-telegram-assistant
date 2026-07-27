# -*- coding: utf-8 -*-
"""Dashboard模型与任务状态API"""
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from dashboard.helpers import (
    login_required, read_config, get_db, get_vps_status,
    _get_current_model_name, _CST
)

models_bp = Blueprint('models', __name__, url_prefix='/api')


def _get_hhmm(cfg: dict, section: str, key: str, fallback: str) -> str:
    section_data = cfg.get(section, {}) if isinstance(cfg, dict) else {}
    value = section_data.get(key, fallback)
    return value if isinstance(value, str) and ":" in value else fallback


@models_bp.route("/bot/status")
@login_required
def api_bot_status():
    """Bot运行状态"""
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


@models_bp.route("/models/status")
@login_required
def api_models_status():
    """模型池状态"""
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
            except Exception as e:
                logger.debug(f"操作异常: {e}")
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


@models_bp.route("/tasks/status")
@login_required
def api_tasks_status():
    """定时任务状态"""
    conn = get_db()
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    cfg = read_config()
    task_defs = [
        ("greeting_morning", "早安问候", _get_hhmm(cfg, "GREETING_CONFIG", "morning_time", "08:05")),
        ("mystic_morning", "早间今日黄历", _get_hhmm(cfg, "MYSTIC_BROADCAST_CONFIG", "morning_time", "09:05")),
        ("daily_report", "每日报告", "09:10"),
        ("greeting_afternoon", "午安问候", _get_hhmm(cfg, "GREETING_CONFIG", "afternoon_time", "12:35")),
        ("mystic_afternoon", "午间三张塔罗", _get_hhmm(cfg, "MYSTIC_BROADCAST_CONFIG", "afternoon_time", "13:05")),
        ("mystic_evening", "晚间易经一卦", _get_hhmm(cfg, "MYSTIC_BROADCAST_CONFIG", "evening_time", "20:35")),
        ("greeting_evening", "晚安问候", _get_hhmm(cfg, "GREETING_CONFIG", "evening_time", "23:05")),
        ("channel_views", "频道浏览量", "每小时"),
        ("burn_orphan", "孤儿清理", "每6小时"),
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
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        tasks.append({
            "key": key,
            "name": name,
            "schedule": schedule,
            "done_today": done_today,
            "exec_time": exec_time,
        })
    return jsonify({"ok": True, "data": {"tasks": tasks, "date": today}})
