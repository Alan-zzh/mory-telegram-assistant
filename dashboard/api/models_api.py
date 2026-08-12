# -*- coding: utf-8 -*-
"""Dashboard模型与任务状态API"""
from datetime import datetime, timedelta
from flask import Blueprint, jsonify
from dashboard.helpers import (
    login_required, read_config, get_db, get_vps_status,
    _get_current_model_name, _CST
)
from core.logging_util import get_logger

models_bp = Blueprint('models', __name__, url_prefix='/api')
logger = get_logger("models_api")


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
    """模型池配置状态；未执行实时供应商请求。"""
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
                "status": "黑名单" if is_blacked else ("配置即将过期" if days_left <= 7 else "未探测"),
                "provider_probe": "not_run",
            })
        result[pool_name] = pool_info
    tier_routing = cfg.get("MODE_ROUTING", {})
    result["_mode_routing"] = tier_routing
    result["_truth_note"] = "仅展示配置/过期/黑名单状态，不代表供应商实时可用"
    return jsonify({"ok": True, "data": result})


@models_bp.route("/tasks/status")
@login_required
def api_tasks_status():
    """近 24 小时事务任务执行状态（非 task_log 锁表、非注册清单）。"""
    conn = get_db()
    cutoff = int((datetime.now(_CST) - timedelta(hours=24)).timestamp())
    try:
        rows = conn.execute(
            "SELECT task_key,status,start_ts,end_ts,error_msg,duration_ms "
            "FROM task_execution_history WHERE start_ts >= ? "
            "ORDER BY start_ts DESC, id DESC",
            (cutoff,),
        ).fetchall()
    except Exception as e:
        logger.warning(f"事务任务状态查询失败: {e}")
        return jsonify({"ok": False, "msg": "task_history_unavailable"}), 503
    latest = {}
    for row in rows:
        key = str(row[0])
        if key in latest:
            continue
        latest[key] = {
            "key": key,
            "status": str(row[1]),
            "start_ts": int(row[2] or 0),
            "end_ts": int(row[3] or 0),
            "error": str(row[4] or "")[:160],
            "duration_ms": int(row[5] or 0),
        }
    return jsonify({
        "ok": True,
        "data": {
            "tasks": list(latest.values()),
            "coverage": "transactional_tasks",
            "window_hours": 24,
            "is_scheduler_registry": False,
            "note": "仅含进入 TaskTransactionManager 的任务；当前注册清单需读 Bot 进程",
        },
    })
