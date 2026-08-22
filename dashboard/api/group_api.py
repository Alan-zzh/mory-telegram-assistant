# -*- coding: utf-8 -*-
"""Dashboard群组设置API"""
from flask import Blueprint, request, jsonify
from dashboard.helpers import login_required, admin_required, read_config, write_config, clamp_int

group_bp = Blueprint('group', __name__, url_prefix='/api')

# 文本长度与列表规模上限（防止超长文本/超大列表写进 config.json）
_TEXT_MAX_LEN = 2000
_LIST_MAX_ITEMS = 500
_LIST_ITEM_MAX_LEN = 100


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

    # 逐键校验/钳制：类型错误或超界一律拒绝，禁止脏值落盘进运行态
    if key in ("BANNED_WORDS", "HATE_KEYWORDS", "AD_KEYWORDS", "AUTO_MUTE_NAMES"):
        if not isinstance(value, list) or len(value) > _LIST_MAX_ITEMS:
            return jsonify({"ok": False, "msg": f"{key} 必须为不超过 {_LIST_MAX_ITEMS} 条的列表"}), 400
        cleaned = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return jsonify({"ok": False, "msg": f"{key} 列表项必须为非空文本"}), 400
            cleaned.append(item.strip()[:_LIST_ITEM_MAX_LEN])
        value = cleaned
    elif key == "SPAM_LIMIT":
        if not isinstance(value, dict):
            return jsonify({"ok": False, "msg": "SPAM_LIMIT 必须为对象（messages_per_minute / ban_minutes）"}), 400
        value = {
            "messages_per_minute": clamp_int(value.get("messages_per_minute", 10), 1, 600),
            "ban_minutes": clamp_int(value.get("ban_minutes", 5), 0, 1000000),
        }
    elif key == "WELCOME_TEXT":
        if not isinstance(value, str):
            return jsonify({"ok": False, "msg": "WELCOME_TEXT 必须为文本"}), 400
        value = value[:_TEXT_MAX_LEN]
    elif key == "WELCOME_MSG":
        value = bool(value)
    elif key == "BAN_DURATION_DEFAULT":
        value = clamp_int(value, 0, 1000000)
    elif key == "MAX_REQUESTS_PER_USER":
        value = clamp_int(value, 1, 100000)

    cfg = read_config()
    cfg[key] = value
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"已更新 {key}（⚠️ 需重启Bot或等待自动重载后生效）"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500
