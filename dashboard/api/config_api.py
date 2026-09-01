# -*- coding: utf-8 -*-
"""Dashboard配置管理API"""
import logging
import math

from flask import Blueprint, request, jsonify
from dashboard.helpers import (
    login_required, admin_required, get_current_role, read_config, write_config,
    _DashboardFakeMessage, _DashboardReplyProxy
)
from core.config_compat import (
    REMOVED_CONFIG_FIELDS,
    is_sensitive_config_key,
    redact_sensitive_config,
)
from modules.natural_cmd import handle_natural_admin, ALL_CONFIGS

logger = logging.getLogger(__name__)

config_bp = Blueprint('config', __name__, url_prefix='/api')

# 配置由 Bot 进程每 30 秒检查 reload_flag；API 不应承诺一个不存在的
# 5-8 秒 SLA。统一复用这条事实说明，避免不同配置页继续传播失真时间。
CONFIG_RELOAD_NOTICE = "将在下一次配置重载周期内生效（默认约30秒）"


def _contains_sensitive_config_field(value) -> bool:
    """拒绝 Dashboard 把任何层级的凭据写回配置文件。"""
    if isinstance(value, dict):
        return any(
            is_sensitive_config_key(key) or _contains_sensitive_config_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_config_field(item) for item in value)
    return False


def _parse_scene_bool(value):
    """将 Dashboard JSON/表单布尔值严格转换，拒绝 ``bool('false')`` 陷阱。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


_SCENE_NUMERIC_LIMITS = {
    "INTENT_RULE_THRESHOLD": (0, None),
    "COLD_GROUP_THRESHOLD_MIN": (1, None),
    "COLD_GROUP_COOLDOWN_MIN": (1, None),
    "COLD_GROUP_MAX_PER_RUN": (1, None),
    "NIGHT_HINT_COOLDOWN_HOURS": (1, None),
    "NIGHT_HINT_MAX_PER_RUN": (1, None),
}

# ── 配置更新白名单：只有在此白名单中的字段才允许通过 /config/update 修改 ──
ALLOWED_CONFIG_FIELDS = {
    # 模型与路由
    "MODEL_COSTS", "MODEL_POOLS", "MODE_ROUTING",
    # AI 请求行为（与 config.json.example 三处同步，允许 Dashboard 端调整）
    "AI_REQUEST_TIMEOUT", "AI_MAX_ATTEMPTS",
    # 人设与提示词（含人设引擎 v5.19.0）
    "SYSTEM_PROMPT", "BASE_PERSONA", "PROMPT_TEMPLATES",
    "PERSONA_ENGINE_ENABLED", "DIALOGUE_TONE_CONTRACTS",
    "EMOTION_BUCKETS", "EMOTION_TRIGGERS", "EMOTION_TEMP_MAP", "ANTI_TEMPLATES",
    # 业务配置
    "SPAM_LIMIT", "IMAGE_POOL", "LOG_LEVEL", "BOT_NAME",
    "REPLY_CHANCE", "BANNED_WORDS", "HATE_KEYWORDS",
    "IGNORE_BOTS", "KNOWLEDGE", "PHOTO_KEYWORDS", "PRICE_LIST",
    "INPUT_HINTS",  # 私聊输入框占位提示（v5.38.28）
    "SPECIAL_AUTO_REPLIES", "PUZZLE_WORD", "SLANG_DICT", "AD_RULES",
    "CHECKIN_CONFIG", "ENABLE_MESSAGE_DELETION", "KEYWORD_AUTO_DELETE_CONFIG",
    "FAQ_TRACKING_ENABLED", "FAQ_AUTO_REPLY_ENABLED", "FAQ_DISTILL_INTERVAL", "FAQ_MIN_FREQUENCY",
    # [Agent G] 回复演化蒸馏总开关（默认关闭，example 已同步）
    "REPLY_EVOLUTION_DISTILL_ENABLED",
    # [阶段4 步骤20] 播报相关 + 高频业务键（三处同步补齐，均有 Dashboard UI 修改需求）
    "MYSTIC_BROADCAST_CONFIG",  # 玄学播报（黄历/塔罗/易经）开关与时段，播报设置页可改
    "LINKED_CHANNEL_SYNC_CONFIG",  # 关联频道联动（置顶取消/点赞/评论转化）
    "GREETING_CONFIG",  # 早安/晚安问候播报配置
    "SCHEDULED_BROADCASTS",  # 定时播报列表，UI 编辑播报条目
    "BROADCAST_AUTO_DELETE",  # 播报消息自动删除（孤儿/问候链清理）
    "PROACTIVE_ENGAGE_CONFIG",  # 主动互动触发配置
    "RELAY_MODE_ENABLED",  # 中继模式开关
    "ORPHAN_CLEANUP_ENABLED",  # 孤儿消息清理开关
    "LANGUAGE",  # 语言设置
    "ANTI_CHANNEL_DEFAULT",  # 防频道转发默认值
    # [Puzan-OS v5.32] 广告检测 AI 升级开关
    "AD_MARKETING_DETECTION_ENABLED", "AD_AI_REVIEW_ENABLED",
    "AD_AI_AUTO_REPLY_ENABLED", "AD_AVATAR_AI_REVIEW_ENABLED", "AD_SELF_UNBAN_ENABLED",
    "STARTUP_MEMBER_SCAN_ENABLED", "STARTUP_MEMBER_SCAN_ENFORCE",
    # Telegram API 2026 适配
    "RICH_MESSAGE_ENABLED", "BROADCAST_FORMAT_VERSION", "BROADCAST_TEMPLATE_VARIATION_ENABLED", "RICH_MESSAGE_STYLE",
    "AUTO_REPLY_CARD_ENABLED",  # 特定词自动回复 Rich/HTML 卡片+随机入口按钮（默认关闭）
    "BUTTON_STYLE_ENABLED", "BUTTON_COLOR_MAP",
    "EPHEMERAL_MESSAGE_ENABLED",
    "CUSTOM_EMOJI_ENABLED", "CUSTOM_EMOJI_POOL",
    "USER_PROFILE_ENABLED",
    # [TRAE SOLO CN] v5.38.16 图片卡播报样式配置（三处同步第三处）
    "BROADCAST_IMAGE_CARD_ENABLED", "BROADCAST_THEME_ENABLED",
    # [TRAE SOLO CN] v5.19.0 场景触发引擎
    "INTENT_ROUTING_ENABLED", "INTENT_LLM_ENABLED", "INTENT_RULE_THRESHOLD",
    "COLD_GROUP_TRIGGER_ENABLED", "COLD_GROUP_THRESHOLD_MIN", "COLD_GROUP_COOLDOWN_MIN", "COLD_GROUP_MAX_PER_RUN",
    "NIGHT_HINT_TRIGGER_ENABLED", "NIGHT_HINT_NEUTRAL_REMINDER_ENABLED",
    "NIGHT_HINT_COOLDOWN_HOURS", "NIGHT_HINT_MAX_PER_RUN",
    "FLOOD_MEDiate_TRIGGER_ENABLED",
    # [v5.35.1] 44 个新模块 CONFIG 键纳入白名单（P1-9 修复）
    # v5.34.0 业务模块（6 个）
    "SALES_CENTER_CONFIG", "SECURITY_CENTER_CONFIG", "MANAGED_GROUPS_CONFIG",
    "CONTENT_AUDIT_CONFIG", "MEMBERSHIP_CONFIG", "NEW_MEMBER_ANALYTICS",
    # v5.35.0 群管机器人模块（36 个）
    "ANTI_RAID_CONFIG",
    "BOTTOM_BUTTON_CONFIG", "CONFIG_TEMPLATE_CONFIG", "CONTENT_ARCHIVE_CONFIG",
    "MESSAGE_LIBRARY_CONFIG", "RANDOM_DROP_CONFIG", "GROUP_PROPS_CONFIG",
    "IMAGE_MANAGER_CONFIG", "CRYPTO_DETECTOR_CONFIG",
    "GROUP_SAFETY_CENTER_CONFIG", "GROUP_MESSAGE_PUSH_CONFIG", "PUNISHMENT_CENTER_CONFIG",
    "ENTERTAINMENT_GAMES_CONFIG",
    "AUTO_RULES_CONFIG", "USER_MARKING_CONFIG", "GROUP_TODO_CONFIG",
    "INVITE_LINK_CONFIG", "CHANNEL_LINK_CONFIG",
    "GROUP_REPORT_CONFIG", "WORD_CLOUD_CONFIG", "LANGUAGE_WHITELIST_CONFIG",
    "FORCE_CHANNEL_CONFIG", "VALID_SPEAK_CONFIG", "CHAT_POINTS_COST_CONFIG",
    "GROUP_MEMBERS_CONFIG", "AD_BLOCKER_CONFIG", "GROUP_MIGRATION_CONFIG",
    "NEW_MEMBER_PROBATION_CONFIG",
    "BOT_LIST_CONFIG", "GROUP_LIST_CONFIG", "SUPER_AFOOL_CONFIG",
    "CHAT_SETTINGS_CONFIG", "JOIN_SETTINGS_CONFIG", "GROUP_COMMANDS_CONFIG",
    "BOT_SETTINGS_CONFIG", "AFOOL_MEMBER_CONFIG",
    # 元信息
    "_CONFIG_VERSION", "_CONFIG_UPDATED", "_SAFETY_NOTE",
}

# 补充 natural_cmd 中 ALL_CONFIGS 的所有键
ALLOWED_CONFIG_FIELDS.update(ALL_CONFIGS.keys())
ALLOWED_CONFIG_FIELDS.difference_update(REMOVED_CONFIG_FIELDS)


@config_bp.route("/config")
@login_required
def api_config():
    """获取配置（过滤敏感项）
    ---
    tags:
      - 配置管理
    summary: 获取系统配置
    description: |
      返回当前系统配置，自动过滤敏感信息（如 API Key、Token、密码等）。
    responses:
      200:
        description: 成功返回配置数据
        schema:
          type: object
          properties:
            ok:
              type: boolean
              example: true
            data:
              type: object
              properties:
                config:
                  type: object
                  description: 配置字典（已过滤敏感项）
    """
    cfg = read_config()
    role = get_current_role()
    safe_cfg = {
        k: redact_sensitive_config(v)
        for k, v in cfg.items()
        if k not in REMOVED_CONFIG_FIELDS and (
            (k == "KEYWORD_AUTO_DELETE_CONFIG" and role == "admin")
            or not is_sensitive_config_key(k)
        )
    }
    if role != "admin":
        safe_cfg.pop("KEYWORD_AUTO_DELETE_CONFIG", None)
    return jsonify({"ok": True, "data": {"config": safe_cfg}})


@config_bp.route("/config/update", methods=["POST"])
@login_required
@admin_required
def api_config_update():
    """更新单个配置项
    ---
    tags:
      - 配置管理
    summary: 更新指定配置项
    description: |
      更新单个配置项并触发配置热重载（默认约 30 秒内生效）。
      仅允许更新白名单中的配置项，需要管理员权限。
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - key
            - value
          properties:
            key:
              type: string
              description: 配置项名称（必须在白名单中）
              example: "BOT_NAME"
            value:
              description: 配置项值（支持字符串、数字、布尔、数组、对象）
              example: "Mory"
    responses:
      200:
        description: 配置更新成功
        schema:
          type: object
          properties:
            ok:
              type: boolean
              example: true
            msg:
              type: string
              example: "配置项 BOT_NAME 已更新，将在下一次配置重载周期内生效（默认约30秒）"
      400:
        description: 请求参数错误
      403:
        description: 配置项不在允许修改的白名单中
      500:
        description: 保存配置失败
    """
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
    if is_sensitive_config_key(key) or _contains_sensitive_config_field(value):
        return jsonify({
            "ok": False,
            "msg": "凭据不得通过 Dashboard 写入配置，请在 .env 中配置后重启服务",
        }), 400
    cfg = read_config()
    if key == "KEYWORD_AUTO_DELETE_CONFIG":
        from modules.keyword_auto_delete import normalize_keyword_auto_delete_payload
        value = normalize_keyword_auto_delete_payload(value if isinstance(value, dict) else {})
    cfg[key] = value
    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"配置项 {key} 已更新，{CONFIG_RELOAD_NOTICE}"})
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
    except AttributeError:
        return jsonify({"ok": False, "msg": "该指令暂不支持在网页端使用（缺少Bot上下文），请在Telegram中使用"}), 400
    except Exception:
        return jsonify({"ok": False, "msg": "处理失败，请检查参数"}), 500
    if not handled:
        return jsonify({"ok": False, "msg": "这句话我还没听明白，换个更明确的说法试试"}), 400
    safe_cfg = {
        key: redact_sensitive_config(value)
        for key, value in cfg.items()
        if key not in REMOVED_CONFIG_FIELDS and not is_sensitive_config_key(key)
    }
    return jsonify({
        "ok": True,
        "msg": (proxy.messages[-1] if proxy.messages else "已处理") + f"，{CONFIG_RELOAD_NOTICE}",
        "data": {"config": safe_cfg},
    })


# ── Telegram API 2026 适配配置 API ─────────────────────────────────────────────

@config_bp.route("/config/broadcast-format", methods=["GET", "POST"])
@login_required
@admin_required
def api_broadcast_format_config():
    """播报格式配置（HTML / Rich / Auto）"""
    cfg = read_config()

    if request.method == "GET":
        return jsonify({
            "ok": True,
            "data": {
                "rich_message_enabled": cfg.get("RICH_MESSAGE_ENABLED", False),
                "broadcast_format_version": cfg.get("BROADCAST_FORMAT_VERSION", "html"),
                "broadcast_image_card_enabled": cfg.get("BROADCAST_IMAGE_CARD_ENABLED", False),
                "broadcast_theme_enabled": cfg.get("BROADCAST_THEME_ENABLED", True),
                "broadcast_template_variation_enabled": cfg.get("BROADCAST_TEMPLATE_VARIATION_ENABLED", False),
                "button_style_enabled": cfg.get("BUTTON_STYLE_ENABLED", False),
                "rich_message_style": cfg.get("RICH_MESSAGE_STYLE", {
                    "title_bold": True,
                    "badge_italic": True,
                    "body_normal": True,
                    "footer_expandable": True,
                    "emoji_custom": False
                })
            }
        })

    # POST
    data = request.get_json() or {}
    if "rich_message_enabled" in data:
        cfg["RICH_MESSAGE_ENABLED"] = bool(data["rich_message_enabled"])
    if "broadcast_format_version" in data:
        version = str(data["broadcast_format_version"]).lower()
        if version in ["html", "rich", "auto"]:
            cfg["BROADCAST_FORMAT_VERSION"] = version
    if "broadcast_image_card_enabled" in data:
        cfg["BROADCAST_IMAGE_CARD_ENABLED"] = bool(data["broadcast_image_card_enabled"])
    if "broadcast_theme_enabled" in data:
        cfg["BROADCAST_THEME_ENABLED"] = bool(data["broadcast_theme_enabled"])
    if "broadcast_template_variation_enabled" in data:
        cfg["BROADCAST_TEMPLATE_VARIATION_ENABLED"] = bool(data["broadcast_template_variation_enabled"])
    if "button_style_enabled" in data:
        cfg["BUTTON_STYLE_ENABLED"] = bool(data["button_style_enabled"])
    if "rich_message_style" in data and isinstance(data["rich_message_style"], dict):
        cfg["RICH_MESSAGE_STYLE"] = data["rich_message_style"]

    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"播报格式配置已更新，{CONFIG_RELOAD_NOTICE}"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500


@config_bp.route("/config/button-style", methods=["GET", "POST"])
@login_required
@admin_required
def api_button_style_config():
    """按钮样式配置（彩色开关/颜色映射）"""
    cfg = read_config()

    if request.method == "GET":
        return jsonify({
            "ok": True,
            "data": {
                "button_style_enabled": cfg.get("BUTTON_STYLE_ENABLED", False),
                "button_color_map": cfg.get("BUTTON_COLOR_MAP", {
                    "buy": "success",
                    "cancel": "danger",
                    "info": "primary",
                    "settings": "default"
                })
            }
        })

    # POST
    data = request.get_json() or {}
    if "button_style_enabled" in data:
        cfg["BUTTON_STYLE_ENABLED"] = bool(data["button_style_enabled"])
    if "button_color_map" in data and isinstance(data["button_color_map"], dict):
        cfg["BUTTON_COLOR_MAP"] = data["button_color_map"]

    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"按钮样式配置已更新，{CONFIG_RELOAD_NOTICE}"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500


@config_bp.route("/config/custom-emoji", methods=["GET", "POST"])
@login_required
@admin_required
def api_custom_emoji_config():
    """Custom Emoji 池配置"""
    cfg = read_config()

    if request.method == "GET":
        return jsonify({
            "ok": True,
            "data": {
                "custom_emoji_enabled": cfg.get("CUSTOM_EMOJI_ENABLED", False),
                "custom_emoji_pool": cfg.get("CUSTOM_EMOJI_POOL", {})
            }
        })

    # POST
    data = request.get_json() or {}
    if "custom_emoji_enabled" in data:
        cfg["CUSTOM_EMOJI_ENABLED"] = bool(data["custom_emoji_enabled"])
    if "custom_emoji_pool" in data and isinstance(data["custom_emoji_pool"], dict):
        cfg["CUSTOM_EMOJI_POOL"] = data["custom_emoji_pool"]

    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"Custom Emoji 配置已更新，{CONFIG_RELOAD_NOTICE}"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500


@config_bp.route("/config/user-profile", methods=["GET", "POST"])
@login_required
@admin_required
def api_user_profile_config():
    """用户画像配置"""
    cfg = read_config()

    if request.method == "GET":
        return jsonify({
            "ok": True,
            "data": {
                "user_profile_enabled": cfg.get("USER_PROFILE_ENABLED", False)
            }
        })

    # POST
    data = request.get_json() or {}
    if "user_profile_enabled" in data:
        cfg["USER_PROFILE_ENABLED"] = bool(data["user_profile_enabled"])

    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"用户画像配置已更新，{CONFIG_RELOAD_NOTICE}"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500


@config_bp.route("/config/scene-triggers", methods=["GET", "POST"])
@login_required
@admin_required
def api_scene_triggers_config():
    """[TRAE SOLO CN] v5.19.0 场景触发引擎配置"""
    cfg = read_config()

    if request.method == "GET":
        return jsonify({
            "ok": True,
            "data": {
                "intent_routing_enabled": cfg.get("INTENT_ROUTING_ENABLED", False),
                "intent_llm_enabled": cfg.get("INTENT_LLM_ENABLED", False),
                "intent_rule_threshold": cfg.get("INTENT_RULE_THRESHOLD", 2.0),
                "cold_group_trigger_enabled": cfg.get("COLD_GROUP_TRIGGER_ENABLED", False),
                "cold_group_threshold_min": cfg.get("COLD_GROUP_THRESHOLD_MIN", 45),
                "cold_group_cooldown_min": cfg.get("COLD_GROUP_COOLDOWN_MIN", 180),
                "cold_group_max_per_run": cfg.get("COLD_GROUP_MAX_PER_RUN", 1),
                "night_hint_trigger_enabled": cfg.get("NIGHT_HINT_TRIGGER_ENABLED", False),
                "night_hint_neutral_reminder_enabled": cfg.get("NIGHT_HINT_NEUTRAL_REMINDER_ENABLED", False),
                "night_hint_cooldown_hours": cfg.get("NIGHT_HINT_COOLDOWN_HOURS", 36),
                "night_hint_max_per_run": cfg.get("NIGHT_HINT_MAX_PER_RUN", 1),
                "flood_mediate_trigger_enabled": cfg.get("FLOOD_MEDiate_TRIGGER_ENABLED", False),
            }
        })

    # POST
    data = request.get_json() or {}
    bool_fields = {
        "intent_routing_enabled": "INTENT_ROUTING_ENABLED",
        "intent_llm_enabled": "INTENT_LLM_ENABLED",
        "cold_group_trigger_enabled": "COLD_GROUP_TRIGGER_ENABLED",
        "night_hint_trigger_enabled": "NIGHT_HINT_TRIGGER_ENABLED",
        "night_hint_neutral_reminder_enabled": "NIGHT_HINT_NEUTRAL_REMINDER_ENABLED",
        "flood_mediate_trigger_enabled": "FLOOD_MEDiate_TRIGGER_ENABLED",
    }
    num_fields = {
        "intent_rule_threshold": ("INTENT_RULE_THRESHOLD", float),
        "cold_group_threshold_min": ("COLD_GROUP_THRESHOLD_MIN", int),
        "cold_group_cooldown_min": ("COLD_GROUP_COOLDOWN_MIN", int),
        "cold_group_max_per_run": ("COLD_GROUP_MAX_PER_RUN", int),
        "night_hint_cooldown_hours": ("NIGHT_HINT_COOLDOWN_HOURS", int),
        "night_hint_max_per_run": ("NIGHT_HINT_MAX_PER_RUN", int),
    }
    for k, cfg_key in bool_fields.items():
        if k in data:
            parsed = _parse_scene_bool(data[k])
            if parsed is None:
                return jsonify({"ok": False, "msg": f"{k} 必须是布尔值"}), 400
            cfg[cfg_key] = parsed
    invalid_numeric = []
    for k, (cfg_key, caster) in num_fields.items():
        if k in data:
            try:
                parsed = caster(data[k])
                minimum, maximum = _SCENE_NUMERIC_LIMITS[cfg_key]
                if isinstance(parsed, float) and not math.isfinite(parsed):
                    raise ValueError("必须是有限数字")
                if (minimum is not None and parsed < minimum) or (
                    maximum is not None and parsed > maximum
                ):
                    raise ValueError(f"范围应为 {minimum} 到 {maximum or '无上限'}")
                cfg[cfg_key] = parsed
            except (ValueError, TypeError) as e:
                invalid_numeric.append(f"{k}: {e}")
                logger.debug(f"场景触发数字字段转换失败: key={cfg_key} err={e}")

    if invalid_numeric:
        return jsonify({"ok": False, "msg": "；".join(invalid_numeric)}), 400

    if write_config(cfg):
        return jsonify({"ok": True, "msg": f"场景触发配置已更新，{CONFIG_RELOAD_NOTICE}"})
    return jsonify({"ok": False, "msg": "保存配置失败"}), 500
