# -*- coding: utf-8 -*-
"""Dashboard配置管理API"""
from flask import Blueprint, request, jsonify
from dashboard.helpers import (
    login_required, admin_required, read_config, write_config,
    _DashboardFakeMessage, _DashboardReplyProxy
)
from modules.natural_cmd import handle_natural_admin, ALL_CONFIGS

config_bp = Blueprint('config', __name__, url_prefix='/api')

# ── 配置更新白名单：只有在此白名单中的字段才允许通过 /config/update 修改 ──
ALLOWED_CONFIG_FIELDS = {
    # 模型与路由
    "MODEL_COSTS", "MODEL_POOLS", "MODE_ROUTING",
    # 人设与提示词
    "SYSTEM_PROMPT", "BASE_PERSONA", "PROMPT_TEMPLATES",
    # 业务配置
    "SPAM_LIMIT", "IMAGE_POOL", "LOG_LEVEL", "BOT_NAME",
    "REPLY_CHANCE", "COST_STRATEGY", "BANNED_WORDS", "HATE_KEYWORDS",
    "IGNORE_BOTS", "KNOWLEDGE", "PHOTO_KEYWORDS", "PRICE_LIST",
    "SPECIAL_AUTO_REPLIES", "PUZZLE_WORD", "SLANG_DICT", "AD_RULES",
    "CHECKIN_CONFIG", "ENABLE_MESSAGE_DELETION",
    # 元信息
    "_CONFIG_VERSION", "_CONFIG_UPDATED", "_SAFETY_NOTE",
}

# 补充 natural_cmd 中 ALL_CONFIGS 的所有键
ALLOWED_CONFIG_FIELDS.update(ALL_CONFIGS.keys())


@config_bp.route("/config")
@login_required
def api_config():
    """获取配置（过滤敏感项）"""
    cfg = read_config()
    safe_cfg = {k: v for k, v in cfg.items() if not any(s in k.lower() for s in ['key', 'token', 'password', 'secret'])}
    return jsonify({"ok": True, "data": {"config": safe_cfg}})


@config_bp.route("/config/update", methods=["POST"])
@login_required
@admin_required
def api_config_update():
    """更新单个配置项"""
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
    if key not in ALLOWED_CONFIG_FIELDS:
        return jsonify({"ok": False, "msg": "该配置项不允许修改"}), 403
    cfg = read_config()
    cfg[key] = value
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"配置项 {key} 已更新（⚠️ 需重启Bot或等待自动重载后生效）"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500


@config_bp.route("/config/natural", methods=["POST"])
@login_required
@admin_required
def api_config_natural():
    """自然语言配置"""
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
        return jsonify({"ok": False, "msg": "处理失败，请检查参数"}), 500
    if not handled:
        return jsonify({"ok": False, "msg": "这句话我还没听明白，换个更明确的说法试试"}), 400
    _sensitive_keys = ['key', 'token', 'password', 'secret']
    safe_cfg = {k: v for k, v in cfg.items() if not any(s in k.lower() for s in _sensitive_keys)}
    return jsonify({
        "ok": True,
        "msg": (proxy.messages[-1] if proxy.messages else "已处理") + "（⚠️ 需重启Bot生效）",
        "data": {"config": safe_cfg},
    })
