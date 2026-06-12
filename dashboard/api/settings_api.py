# -*- coding: utf-8 -*-
"""Dashboard设置面板API - 所有/settings/*路由"""
from flask import Blueprint, request, jsonify
from dashboard.helpers import login_required, admin_required, get_current_role, read_config, write_config

settings_bp = Blueprint('settings', __name__, url_prefix='/api')


def _check_admin():
    """检查当前用户是否为管理员，非管理员返回403响应"""
    if get_current_role() != "admin":
        return jsonify({"ok": False, "msg": "需要管理员权限"}), 403
    return None


@settings_bp.route("/settings/warning", methods=["GET", "POST"])
@login_required
def api_settings_warning():
    """警告配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("WARNING_CONFIG", {"limit": 3, "action": "mute", "duration": 3600})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("WARNING_CONFIG", {})
    val["limit"] = int(data.get("limit", val.get("limit", 3)))
    val["action"] = data.get("action", val.get("action", "mute"))
    val["duration"] = int(data.get("duration", val.get("duration", 3600)))
    cfg["WARNING_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/slowmode", methods=["GET", "POST"])
@login_required
def api_settings_slowmode():
    """慢速模式配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("SLOW_MODE_DEFAULT", {"enabled": False, "interval": 0})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("SLOW_MODE_DEFAULT", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["interval"] = int(data.get("interval", val.get("interval", 0)))
    cfg["SLOW_MODE_DEFAULT"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/report", methods=["GET", "POST"])
@login_required
def api_settings_report():
    """举报配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("REPORT_CONFIG", {"enabled": False, "cooldown": 300})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("REPORT_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["cooldown"] = int(data.get("cooldown", val.get("cooldown", 300)))
    cfg["REPORT_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/votekick", methods=["GET", "POST"])
@login_required
def api_settings_votekick():
    """投票踢人配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("VOTEKICK_CONFIG", {"min_yes": 5, "min_ratio": 0.6, "duration": 300})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("VOTEKICK_CONFIG", {})
    val["min_yes"] = int(data.get("min_yes", val.get("min_yes", 5)))
    val["min_ratio"] = float(data.get("min_ratio", val.get("min_ratio", 0.6)))
    val["duration"] = int(data.get("duration", val.get("duration", 300)))
    cfg["VOTEKICK_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/antiflood", methods=["GET", "POST"])
@login_required
def api_settings_antiflood():
    """反刷屏配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("SPAM_LIMIT", {"messages_per_minute": 10, "ban_minutes": 5})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("SPAM_LIMIT", {})
    val["messages_per_minute"] = int(data.get("messages_per_minute", val.get("messages_per_minute", 10)))
    val["ban_minutes"] = int(data.get("ban_minutes", val.get("ban_minutes", 5)))
    cfg["SPAM_LIMIT"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/anti-raid", methods=["GET", "POST"])
@login_required
def api_settings_anti_raid():
    """反突袭配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("ANTI_RAID_CONFIG", {"enabled": False, "threshold": 5, "window": 60, "lock_duration": 300})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("ANTI_RAID_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["threshold"] = int(data.get("threshold", val.get("threshold", 5)))
    val["window"] = int(data.get("window", val.get("window", 60)))
    val["lock_duration"] = int(data.get("lock_duration", val.get("lock_duration", 300)))
    cfg["ANTI_RAID_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/blindbox", methods=["GET", "POST"])
@login_required
def api_settings_blindbox():
    """盲盒配置"""
    if request.method == "GET":
        cfg = read_config()
        # 优先读取 BLIND_BOX_CONFIG，回退到 config.json 中的 BLIND_BOX_COST
        d = cfg.get("BLIND_BOX_CONFIG", {
            "enabled": cfg.get("GAMES_CONFIG", {}).get("enable", False),
            "cost": cfg.get("BLIND_BOX_COST", 30)
        })
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("BLIND_BOX_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["cost"] = int(data.get("cost", val.get("cost", 30)))
    cfg["BLIND_BOX_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/luckywheel", methods=["GET", "POST"])
@login_required
def api_settings_luckywheel():
    """转盘配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("LUCKY_WHEEL_CONFIG", {"enabled": False, "cost": 30, "free_spins": 1})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("LUCKY_WHEEL_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["cost"] = int(data.get("cost", val.get("cost", 30)))
    val["free_spins"] = int(data.get("free_spins", val.get("free_spins", 1)))
    cfg["LUCKY_WHEEL_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/redpacket", methods=["GET", "POST"])
@login_required
def api_settings_redpacket():
    """红包配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("REDPACKET_CONFIG", {"enabled": False, "min_amount": 1, "max_amount": 100})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("REDPACKET_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["min_amount"] = int(data.get("min_amount", val.get("min_amount", 1)))
    val["max_amount"] = int(data.get("max_amount", val.get("max_amount", 100)))
    cfg["REDPACKET_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/lottery", methods=["GET", "POST"])
@login_required
def api_settings_lottery():
    """抽奖配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("LOTTERY_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("LOTTERY_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["LOTTERY_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/checkin", methods=["GET", "POST"])
@login_required
def api_settings_checkin():
    """签到配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("CHECKIN_CONFIG", {"enabled": False, "base_points": 5, "streak_bonus": {"3": 5, "7": 15}})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("CHECKIN_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["base_points"] = int(data.get("base_points", val.get("base_points", 5)))
    cfg["CHECKIN_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/shop", methods=["GET", "POST"])
@login_required
def api_settings_shop():
    """商城配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("SHOP_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("SHOP_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["SHOP_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/coupon", methods=["GET", "POST"])
@login_required
def api_settings_coupon():
    """优惠券配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("COUPON_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("COUPON_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["COUPON_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/tip", methods=["GET", "POST"])
@login_required
def api_settings_tip():
    """打赏配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("TIP_CONFIG", {"enabled": False, "min_amount": 1})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("TIP_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["min_amount"] = int(data.get("min_amount", val.get("min_amount", 1)))
    cfg["TIP_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/dailyquest", methods=["GET", "POST"])
@login_required
def api_settings_dailyquest():
    """每日任务配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("DAILY_QUEST_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("DAILY_QUEST_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["DAILY_QUEST_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/achievement", methods=["GET", "POST"])
@login_required
def api_settings_achievement():
    """成就配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("ACHIEVEMENT_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("ACHIEVEMENT_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["ACHIEVEMENT_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/pointsdecay", methods=["GET", "POST"])
@login_required
def api_settings_pointsdecay():
    """积分衰减配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("POINTS_DECAY", {"enabled": False, "rate": 0.01, "minimum": 10})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("POINTS_DECAY", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["rate"] = float(data.get("rate", val.get("rate", 0.01)))
    val["minimum"] = int(data.get("minimum", val.get("minimum", 10)))
    cfg["POINTS_DECAY"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/afk", methods=["GET", "POST"])
@login_required
def api_settings_afk():
    """AFK配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("AFK_CONFIG", {"enabled": False, "auto_reply": ""})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("AFK_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["auto_reply"] = data.get("auto_reply", val.get("auto_reply", ""))
    cfg["AFK_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/antidelete", methods=["GET", "POST"])
@login_required
def api_settings_antidelete():
    """反撤回配置"""
    if request.method == "GET":
        cfg = read_config()
        raw = cfg.get("ANTI_DELETE_CONFIG", {})
        # 兼容 enable/enabled 两种写法
        en = raw.get("enabled", raw.get("enable", False))
        return jsonify({"ok": True, "data": {"enabled": en}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("ANTI_DELETE_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", val.get("enable", False))))
    cfg["ANTI_DELETE_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/nsfw", methods=["GET", "POST"])
@login_required
def api_settings_nsfw():
    """NSFW检测配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("NSFW_DETECT_CONFIG", {"enabled": False, "threshold": 0.85})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("NSFW_DETECT_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["threshold"] = float(data.get("threshold", val.get("threshold", 0.85)))
    cfg["NSFW_DETECT_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/antichannel", methods=["GET", "POST"])
@login_required
def api_settings_antichannel():
    """反频道转发配置"""
    if request.method == "GET":
        cfg = read_config()
        en = cfg.get("ANTI_CHANNEL_DEFAULT", False)
        return jsonify({"ok": True, "data": {"enabled": en}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["ANTI_CHANNEL_DEFAULT"] = bool(data.get("enabled", cfg.get("ANTI_CHANNEL_DEFAULT", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/cas", methods=["GET", "POST"])
@login_required
def api_settings_cas():
    """CAS检查配置（spam-watch）"""
    if request.method == "GET":
        cfg = read_config()
        sw = cfg.get("SPAM_WATCH_CONFIG", {})
        return jsonify({"ok": True, "data": {"cas_enabled": sw.get("cas_enabled", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    sw = cfg.get("SPAM_WATCH_CONFIG", {})
    sw["cas_enabled"] = bool(data.get("cas_enabled", sw.get("cas_enabled", False)))
    cfg["SPAM_WATCH_CONFIG"] = sw
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/cleanservice", methods=["GET", "POST"])
@login_required
def api_settings_cleanservice():
    """服务消息清理配置"""
    if request.method == "GET":
        cfg = read_config()
        en = cfg.get("CLEAN_SERVICE_DEFAULT", False)
        return jsonify({"ok": True, "data": {"enabled": en}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["CLEAN_SERVICE_DEFAULT"] = bool(data.get("enabled", cfg.get("CLEAN_SERVICE_DEFAULT", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/autoreply", methods=["GET", "POST"])
@login_required
def api_settings_autoreply():
    """自动回复配置"""
    if request.method == "GET":
        cfg = read_config()
        en = cfg.get("AUTO_REPLY_ENABLE", False)
        return jsonify({"ok": True, "data": {"enabled": en}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["AUTO_REPLY_ENABLE"] = bool(data.get("enabled", cfg.get("AUTO_REPLY_ENABLE", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/message-locks", methods=["GET", "POST"])
@login_required
def api_settings_message_locks():
    """消息锁配置"""
    if request.method == "GET":
        cfg = read_config()
        locks = cfg.get("MESSAGE_LOCKS", {"media": False, "sticker": False, "poll": False, "link": False})
        return jsonify({"ok": True, "data": locks})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["MESSAGE_LOCKS"] = {
        "media": bool(data.get("media", False)),
        "sticker": bool(data.get("sticker", False)),
        "poll": bool(data.get("poll", False)),
        "link": bool(data.get("link", False)),
    }
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "锁群配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/ad-spam", methods=["GET", "POST"])
@login_required
def api_settings_ad_spam():
    """广告防刷配置"""
    if request.method == "GET":
        cfg = read_config()
        ad = cfg.get("AD_DETECT_CONFIG", {"enable": False, "sensitivity": 3})
        return jsonify({"ok": True, "data": {"enabled": ad.get("enable", False), "sensitivity": ad.get("sensitivity", 3)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    ad = cfg.get("AD_DETECT_CONFIG", {})
    ad["enable"] = bool(data.get("enabled", ad.get("enable", False)))
    ad["sensitivity"] = int(data.get("sensitivity", ad.get("sensitivity", 3)))
    cfg["AD_DETECT_CONFIG"] = ad
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "反垃圾配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/inactive-clean", methods=["GET", "POST"])
@login_required
def api_settings_inactive_clean():
    """不活跃清理配置"""
    if request.method == "GET":
        cfg = read_config()
        ik = cfg.get("AUTO_KICK_INACTIVE_DAYS", {"enable": False, "days": 30})
        if isinstance(ik, (int, float)):
            ik = {"enable": ik > 0, "days": int(ik) if ik > 0 else 30}
        return jsonify({"ok": True, "data": {"enabled": ik.get("enable", False), "days": ik.get("days", 30)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["AUTO_KICK_INACTIVE_DAYS"] = {
        "enable": bool(data.get("enabled", False)),
        "days": int(data.get("days", 30)),
    }
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "不活跃清理配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/greeting", methods=["GET", "POST"])
@login_required
def api_settings_greeting():
    """早安/晚安播报配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({
            "ok": True,
            "data": {
                "morning_enabled": cfg.get("AUTO_GREETING", False),
                "morning_hour": cfg.get("GREETING_HOUR", 7),
                "night_enabled": cfg.get("AUTO_GOODNIGHT", False),
                "night_hour": cfg.get("GOODNIGHT_HOUR", 22),
            }
        })
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    if "morning_enabled" in data:
        cfg["AUTO_GREETING"] = bool(data["morning_enabled"])
    if "morning_hour" in data:
        cfg["GREETING_HOUR"] = int(data["morning_hour"])
    if "night_enabled" in data:
        cfg["AUTO_GOODNIGHT"] = bool(data["night_enabled"])
    if "night_hour" in data:
        cfg["GOODNIGHT_HOUR"] = int(data["night_hour"])
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "播报配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/news", methods=["GET", "POST"])
@login_required
def api_settings_news():
    """新闻播报配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"enabled": cfg.get("AUTO_NEWS", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["AUTO_NEWS"] = bool(data.get("enabled", cfg.get("AUTO_NEWS", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "新闻播报配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/exchange-rate", methods=["GET", "POST"])
@login_required
def api_settings_exchange_rate():
    """实时U价配置"""
    if request.method == "GET":
        cfg = read_config()
        raw_key = cfg.get("EXCHANGE_API_KEY", "")
        # [TRAE SOLO CN] 脱敏显示：只显示前4位和后4位，中间用****替代
        if raw_key and len(raw_key) > 8:
            masked_key = raw_key[:4] + "****" + raw_key[-4:]
        elif raw_key:
            masked_key = "****"
        else:
            masked_key = ""
        return jsonify({"ok": True, "data": {"enabled": cfg.get("EXCHANGE_RATE_ENABLE", False), "api_key": masked_key}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["EXCHANGE_RATE_ENABLE"] = bool(data.get("enabled", cfg.get("EXCHANGE_RATE_ENABLE", False)))
    if "api_key" in data:
        cfg["EXCHANGE_API_KEY"] = data["api_key"]
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "实时U价配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/visual-dashboard", methods=["GET", "POST"])
@login_required
def api_settings_visual_dashboard():
    """群数据面板配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"enabled": cfg.get("VISUAL_DASHBOARD_ENABLE", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["VISUAL_DASHBOARD_ENABLE"] = bool(data.get("enabled", cfg.get("VISUAL_DASHBOARD_ENABLE", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "群数据面板配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/language", methods=["GET", "POST"])
@login_required
def api_settings_language():
    """语言设置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"language": cfg.get("LANGUAGE", "zh")}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    lang = data.get("language", cfg.get("LANGUAGE", "zh"))
    if lang in ("zh", "en", "ja"):
        cfg["LANGUAGE"] = lang
        if write_config(cfg):
            return jsonify({"ok": True, "msg": "语言已切换"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/spam-action", methods=["GET", "POST"])
@login_required
def api_settings_spam_action():
    """反刷屏动作配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"action": cfg.get("SPAM_ACTION", "mute")}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    action = data.get("action", cfg.get("SPAM_ACTION", "mute"))
    if action in ("mute", "ban", "delete"):
        cfg["SPAM_ACTION"] = action
        if write_config(cfg):
            return jsonify({"ok": True, "msg": "反刷屏动作已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/goodbye", methods=["GET", "POST"])
@login_required
def api_settings_goodbye():
    """退群消息配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({
            "ok": True,
            "data": {
                "enabled": cfg.get("GOODBYE_MSG", False),
                "text": cfg.get("GOODBYE_TEXT", ""),
            }
        })
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["GOODBYE_MSG"] = bool(data.get("enabled", cfg.get("GOODBYE_MSG", False)))
    cfg["GOODBYE_TEXT"] = data.get("text", cfg.get("GOODBYE_TEXT", ""))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "告别消息配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/rules", methods=["GET", "POST"])
@login_required
def api_settings_rules():
    """群规配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({
            "ok": True,
            "data": {
                "enabled": cfg.get("RULES_ENABLE", False),
                "text": cfg.get("RULES_TEXT", ""),
            }
        })
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["RULES_ENABLE"] = bool(data.get("enabled", cfg.get("RULES_ENABLE", False)))
    cfg["RULES_TEXT"] = data.get("text", cfg.get("RULES_TEXT", ""))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "群规配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/games", methods=["GET", "POST"])
@login_required
def api_settings_games():
    """小游戏配置"""
    if request.method == "GET":
        cfg = read_config()
        gc = cfg.get("GAMES_CONFIG", {"enable": False})
        return jsonify({"ok": True, "data": {"enabled": gc.get("enable", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["GAMES_CONFIG"] = {"enable": bool(data.get("enabled", False))}
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "小游戏配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/ai-model", methods=["GET", "POST"])
@login_required
def api_settings_ai_model():
    """AI模型参数配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "temperature": cfg.get("TEMPERATURE", 0.85),
            "top_p": cfg.get("TOP_P", 0.9),
            "max_tokens": cfg.get("MAX_TOKENS", 500),
            "frequency_penalty": cfg.get("FREQUENCY_PENALTY", 0.3),
            "presence_penalty": cfg.get("PRESENCE_PENALTY", 0.2),
            "reply_chance": cfg.get("REPLY_CHANCE", 10),
            "reply_speed": cfg.get("REPLY_SPEED", "human"),
            "reply_sticker_chance": cfg.get("REPLY_STICKER_CHANCE", 5),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["TEMPERATURE"] = float(data.get("temperature", cfg.get("TEMPERATURE", 0.85)))
    cfg["TOP_P"] = float(data.get("top_p", cfg.get("TOP_P", 0.9)))
    cfg["MAX_TOKENS"] = int(data.get("max_tokens", cfg.get("MAX_TOKENS", 500)))
    cfg["FREQUENCY_PENALTY"] = float(data.get("frequency_penalty", cfg.get("FREQUENCY_PENALTY", 0.3)))
    cfg["PRESENCE_PENALTY"] = float(data.get("presence_penalty", cfg.get("PRESENCE_PENALTY", 0.2)))
    cfg["REPLY_CHANCE"] = int(data.get("reply_chance", cfg.get("REPLY_CHANCE", 10)))
    cfg["REPLY_SPEED"] = data.get("reply_speed", cfg.get("REPLY_SPEED", "human"))
    cfg["REPLY_STICKER_CHANCE"] = int(data.get("reply_sticker_chance", cfg.get("REPLY_STICKER_CHANCE", 5)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "AI模型配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/bot-core", methods=["GET", "POST"])
@login_required
def api_settings_bot_core():
    """Bot核心配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "bot_name": cfg.get("BOT_NAME", "Mory小助理"),
            "max_requests_per_user": cfg.get("MAX_REQUESTS_PER_USER", 20),
            "enable_message_deletion": cfg.get("ENABLE_MESSAGE_DELETION", False),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["BOT_NAME"] = data.get("bot_name", cfg.get("BOT_NAME", "Mory小助理"))
    cfg["MAX_REQUESTS_PER_USER"] = int(data.get("max_requests_per_user", cfg.get("MAX_REQUESTS_PER_USER", 20)))
    cfg["ENABLE_MESSAGE_DELETION"] = bool(data.get("enable_message_deletion", cfg.get("ENABLE_MESSAGE_DELETION", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "Bot核心配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/pricing", methods=["GET", "POST"])
@login_required
def api_settings_pricing():
    """定价管理"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"price_list": cfg.get("PRICE_LIST", {})}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    if "price_list" in data:
        cfg["PRICE_LIST"] = data["price_list"]
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "定价配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/persona", methods=["GET", "POST"])
@login_required
def api_settings_persona():
    """人设编辑"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "system_prompt": cfg.get("SYSTEM_PROMPT", ""),
            "knowledge": cfg.get("KNOWLEDGE", ""),
            "base_persona": cfg.get("BASE_PERSONA", ""),
            "style_append": cfg.get("STYLE_APPEND", ""),
            "added_knowledge": cfg.get("ADDED_KNOWLEDGE", ""),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["SYSTEM_PROMPT"] = data.get("system_prompt", cfg.get("SYSTEM_PROMPT", ""))
    cfg["KNOWLEDGE"] = data.get("knowledge", cfg.get("KNOWLEDGE", ""))
    cfg["BASE_PERSONA"] = data.get("base_persona", cfg.get("BASE_PERSONA", ""))
    cfg["STYLE_APPEND"] = data.get("style_append", cfg.get("STYLE_APPEND", ""))
    cfg["ADDED_KNOWLEDGE"] = data.get("added_knowledge", cfg.get("ADDED_KNOWLEDGE", ""))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "人设配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/approvals", methods=["GET", "POST"])
@login_required
def api_settings_approvals():
    """进群审批/验证配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("VERIFICATION_CONFIG", {"enable": False, "mode": "button", "timeout": 120, "max_attempts": 3})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("VERIFICATION_CONFIG", {})
    val["enable"] = bool(data.get("enable", val.get("enable", False)))
    val["mode"] = data.get("mode", val.get("mode", "button"))
    val["timeout"] = int(data.get("timeout", val.get("timeout", 120)))
    val["max_attempts"] = int(data.get("max_attempts", val.get("max_attempts", 3)))
    cfg["VERIFICATION_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "进群审批配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/clean-service", methods=["GET", "POST"])
@login_required
def api_settings_clean_service():
    """服务消息清理配置"""
    if request.method == "GET":
        cfg = read_config()
        en = cfg.get("CLEAN_SERVICE_DEFAULT", False)
        return jsonify({"ok": True, "data": {"enabled": en}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["CLEAN_SERVICE_DEFAULT"] = bool(data.get("enabled", cfg.get("CLEAN_SERVICE_DEFAULT", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "服务消息清理配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/pin", methods=["GET", "POST"])
@login_required
def api_settings_pin():
    """置顶管理配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "pin_notify": cfg.get("PIN_NOTIFY", False),
            "max_pins": cfg.get("MAX_PINS", 5),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["PIN_NOTIFY"] = bool(data.get("pin_notify", cfg.get("PIN_NOTIFY", False)))
    cfg["MAX_PINS"] = int(data.get("max_pins", cfg.get("MAX_PINS", 5)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "置顶管理配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/links", methods=["GET", "POST"])
@login_required
def api_settings_links():
    """链接管理配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "anti_channel": cfg.get("ANTI_CHANNEL_DEFAULT", False),
            "link_delete": cfg.get("LINK_DELETE", False),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["ANTI_CHANNEL_DEFAULT"] = bool(data.get("anti_channel", cfg.get("ANTI_CHANNEL_DEFAULT", False)))
    cfg["LINK_DELETE"] = bool(data.get("link_delete", cfg.get("LINK_DELETE", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "链接管理配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/custom-commands", methods=["GET", "POST"])
@login_required
def api_settings_custom_commands():
    """自定义命令配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("CUSTOM_COMMAND_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("CUSTOM_COMMAND_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["CUSTOM_COMMAND_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "自定义命令配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/group-notes", methods=["GET", "POST"])
@login_required
def api_settings_group_notes():
    """群组笔记配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("NOTES_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("NOTES_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["NOTES_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "群组笔记配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/blind-box", methods=["GET", "POST"])
@login_required
def api_settings_blind_box():
    """盲盒配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("BLIND_BOX_CONFIG", {
            "enabled": cfg.get("GAMES_CONFIG", {}).get("enable", False),
            "cost": cfg.get("BLIND_BOX_COST", 30)
        })
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("BLIND_BOX_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["cost"] = int(data.get("cost", val.get("cost", 30)))
    cfg["BLIND_BOX_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "盲盒配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/lucky-wheel", methods=["GET", "POST"])
@login_required
def api_settings_lucky_wheel():
    """转盘配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("LUCKY_WHEEL_CONFIG", {"enabled": False, "cost": 30, "free_spins": 1})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("LUCKY_WHEEL_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["cost"] = int(data.get("cost", val.get("cost", 30)))
    val["free_spins"] = int(data.get("free_spins", val.get("free_spins", 1)))
    cfg["LUCKY_WHEEL_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "转盘配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/points-rules", methods=["GET", "POST"])
@login_required
def api_settings_points_rules():
    """积分规则配置"""
    if request.method == "GET":
        cfg = read_config()
        pr = cfg.get("POINTS_RULES", {})
        return jsonify({"ok": True, "data": {
            "points_per_message": pr.get("message", 1),
            "points_per_checkin": cfg.get("CHECKIN_CONFIG", {}).get("base_points", 5),
            "points_per_invite": cfg.get("POINTS_PER_INVITE", 5),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    pr = cfg.get("POINTS_RULES", {})
    pr["message"] = int(data.get("points_per_message", pr.get("message", 1)))
    cfg["POINTS_RULES"] = pr
    checkin = cfg.get("CHECKIN_CONFIG", {})
    checkin["base_points"] = int(data.get("points_per_checkin", checkin.get("base_points", 5)))
    cfg["CHECKIN_CONFIG"] = checkin
    cfg["POINTS_PER_INVITE"] = int(data.get("points_per_invite", cfg.get("POINTS_PER_INVITE", 5)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "积分规则配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/level-titles", methods=["GET", "POST"])
@login_required
def api_settings_level_titles():
    """等级称号配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("LEVEL_TITLES", {"1": "萌新", "2": "常客", "3": "达人", "4": "大佬"})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    if "titles" in data:
        cfg["LEVEL_TITLES"] = data["titles"]
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "等级称号配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/shop-items", methods=["GET", "POST"])
@login_required
def api_settings_shop_items():
    """商城商品配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("SHOP_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("SHOP_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["SHOP_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "商城商品配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/coupons", methods=["GET", "POST"])
@login_required
def api_settings_coupons():
    """优惠券配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("COUPON_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("COUPON_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["COUPON_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "优惠券配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/points-decay", methods=["GET", "POST"])
@login_required
def api_settings_points_decay():
    """积分衰减配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("POINTS_DECAY", {"enabled": False, "rate": 0.01, "minimum": 10})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("POINTS_DECAY", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["rate"] = float(data.get("rate", val.get("rate", 0.01)))
    val["minimum"] = int(data.get("minimum", val.get("minimum", 10)))
    cfg["POINTS_DECAY"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "积分衰减配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/daily-quest", methods=["GET", "POST"])
@login_required
def api_settings_daily_quest():
    """每日任务配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("DAILY_QUEST_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("DAILY_QUEST_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["DAILY_QUEST_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "每日任务配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/achievements", methods=["GET", "POST"])
@login_required
def api_settings_achievements():
    """成就系统配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("ACHIEVEMENT_CONFIG", {"enabled": False})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("ACHIEVEMENT_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    cfg["ACHIEVEMENT_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "成就系统配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/morning", methods=["GET", "POST"])
@login_required
def api_settings_morning():
    """早安播报配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "enabled": cfg.get("AUTO_GREETING", False),
            "hour": cfg.get("GREETING_HOUR", 7),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["AUTO_GREETING"] = bool(data.get("enabled", cfg.get("AUTO_GREETING", False)))
    cfg["GREETING_HOUR"] = int(data.get("hour", cfg.get("GREETING_HOUR", 7)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "早安播报配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/night", methods=["GET", "POST"])
@login_required
def api_settings_night():
    """晚安播报配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {
            "enabled": cfg.get("AUTO_GOODNIGHT", False),
            "hour": cfg.get("GOODNIGHT_HOUR", 22),
        }})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["AUTO_GOODNIGHT"] = bool(data.get("enabled", cfg.get("AUTO_GOODNIGHT", False)))
    cfg["GOODNIGHT_HOUR"] = int(data.get("hour", cfg.get("GOODNIGHT_HOUR", 22)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "晚安播报配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/dashboard", methods=["GET", "POST"])
@login_required
def api_settings_dashboard():
    """群数据面板配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"enabled": cfg.get("VISUAL_DASHBOARD_ENABLE", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["VISUAL_DASHBOARD_ENABLE"] = bool(data.get("enabled", cfg.get("VISUAL_DASHBOARD_ENABLE", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "群数据面板配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/speech-stats", methods=["GET", "POST"])
@login_required
def api_settings_speech_stats():
    """发言统计配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("SPEECH_STATS_CONFIG", {"enabled": False, "top_n": 10})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("SPEECH_STATS_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["top_n"] = int(data.get("top_n", val.get("top_n", 10)))
    cfg["SPEECH_STATS_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "发言统计配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/commands", methods=["GET", "POST"])
@login_required
def api_settings_commands():
    """命令管理配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("DISABLED_COMMANDS", [])
        return jsonify({"ok": True, "data": {"disabled_commands": d}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    if "disabled_commands" in data:
        cfg["DISABLED_COMMANDS"] = data["disabled_commands"]
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "命令管理配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/group-backup", methods=["GET", "POST"])
@login_required
def api_settings_group_backup():
    """群设置备份配置"""
    if request.method == "GET":
        cfg = read_config()
        d = cfg.get("BACKUP_CONFIG", {"enabled": False, "interval_hours": 24})
        return jsonify({"ok": True, "data": d})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    val = cfg.get("BACKUP_CONFIG", {})
    val["enabled"] = bool(data.get("enabled", val.get("enabled", False)))
    val["interval_hours"] = int(data.get("interval_hours", val.get("interval_hours", 24)))
    cfg["BACKUP_CONFIG"] = val
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "群设置备份配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/message-deletion", methods=["GET", "POST"])
@login_required
def api_settings_message_deletion():
    """消息删除开关配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"enabled": cfg.get("ENABLE_MESSAGE_DELETION", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["ENABLE_MESSAGE_DELETION"] = bool(data.get("enabled", cfg.get("ENABLE_MESSAGE_DELETION", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "消息删除开关配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/orphan-cleanup", methods=["GET", "POST"])
@login_required
def api_settings_orphan_cleanup():
    """[v5.12.4] 孤儿消息清理独立开关配置

    与 ENABLE_MESSAGE_DELETION 完全独立：
    - 控制 _job_burn_orphan 是否执行删除
    - 默认开启（破例）
    - 关闭窗口：30分钟（v5.12.4 之前是 24小时）
    """
    if request.method == "GET":
        cfg = read_config()
        from core.helpers import can_orphan_cleanup
        return jsonify({
            "ok": True,
            "data": {
                "enabled": can_orphan_cleanup(cfg),
                "raw": cfg.get("ORPHAN_CLEANUP_ENABLED", True),
                "window_seconds": 1800,
            }
        })
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["ORPHAN_CLEANUP_ENABLED"] = bool(data.get("enabled", cfg.get("ORPHAN_CLEANUP_ENABLED", True)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "孤儿清理开关配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@settings_bp.route("/settings/relay-mode", methods=["GET", "POST"])
@login_required
def api_settings_relay_mode():
    """中继模式开关配置"""
    if request.method == "GET":
        cfg = read_config()
        return jsonify({"ok": True, "data": {"enabled": cfg.get("RELAY_MODE_ENABLED", False)}})
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    cfg = read_config()
    cfg["RELAY_MODE_ENABLED"] = bool(data.get("enabled", cfg.get("RELAY_MODE_ENABLED", False)))
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "中继模式开关配置已保存"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500
