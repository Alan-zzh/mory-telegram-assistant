# -*- coding: utf-8 -*-
"""Dashboard群组设置API"""
from flask import Blueprint, request, jsonify
from dashboard.helpers import login_required, admin_required, read_config, write_config

group_bp = Blueprint('group', __name__, url_prefix='/api')


@group_bp.route("/group/settings")
@login_required
def api_group_settings():
    """获取群组设置"""
    cfg = read_config()
    settings = {
        "banned_words": cfg.get("BANNED_WORDS", []),
        "hate_keywords": cfg.get("HATE_KEYWORDS", []),
        "ad_keywords": cfg.get("AD_KEYWORDS", []),
        "spam_limit": cfg.get("SPAM_LIMIT", {"messages_per_minute": 10, "ban_minutes": 5}),
        "welcome_text": cfg.get("WELCOME_TEXT", ""),
        "welcome_msg": cfg.get("WELCOME_MSG", False),
        "auto_mute_names": cfg.get("AUTO_MUTE_NAMES", []),
        "spam_ban_duration": cfg.get("BAN_DURATION_DEFAULT", 5),
        "max_requests_per_user": cfg.get("MAX_REQUESTS_PER_USER", 100),
    }
    return jsonify({"ok": True, "data": settings})


@group_bp.route("/group/settings/update", methods=["POST"])
@login_required
@admin_required
def api_group_settings_update():
    """更新群组设置"""
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "无效的请求数据"}), 400
    key = data.get("key", "").strip()
    value = data.get("value")
    if not key:
        return jsonify({"ok": False, "msg": "配置项名称不能为空"}), 400
    allowed_keys = {
        "BANNED_WORDS", "HATE_KEYWORDS", "AD_KEYWORDS", "SPAM_LIMIT", "WELCOME_TEXT",
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
