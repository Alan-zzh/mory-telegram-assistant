# -*- coding: utf-8 -*-
"""Dashboard功能配置API - 验证码/欢迎/夜间模式/播报/联邦/关键词/emoji面具"""
import time
from flask import Blueprint, request, jsonify
from dashboard.helpers import login_required, admin_required, get_current_role, get_db, read_config, write_config

features_bp = Blueprint('features', __name__, url_prefix='/api')


def _check_admin():
    """检查当前用户是否为管理员，非管理员返回403响应"""
    if get_current_role() != "admin":
        return jsonify({"ok": False, "msg": "需要管理员权限"}), 403
    return None


@features_bp.route("/settings/verification", methods=["GET", "POST"])
@login_required
def api_settings_verification():
    """验证码配置"""
    if request.method == "GET":
        cfg = read_config()
        vc = cfg.get("VERIFICATION_CONFIG", {"enable": False, "mode": "button", "timeout": 120, "max_attempts": 3})
        return jsonify({"ok": True, "data": vc})
    data = request.get_json() or {}
    _adm = _check_admin()
    if _adm:
        return _adm
    enable = bool(data.get("enable", False))
    mode = data.get("mode", "button")
    if mode not in ("button", "math", "text"):
        return jsonify({"ok": False, "msg": "mode必须是button/math/text之一"}), 400
    timeout = int(data.get("timeout", 120))
    timeout = max(10, min(300, timeout))
    max_attempts = int(data.get("max_attempts", 3))
    max_attempts = max(1, min(10, max_attempts))
    cfg = read_config()
    cfg["VERIFICATION_CONFIG"] = {"enable": enable, "mode": mode, "timeout": timeout, "max_attempts": max_attempts}
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "验证码配置已保存（需重启Bot生效）"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@features_bp.route("/settings/welcome", methods=["GET", "POST"])
@login_required
def api_settings_welcome():
    """欢迎定制配置"""
    conn = get_db()
    if request.method == "GET":
        cfg = read_config()
        # 读取数据库welcome_configs（取chat_id=0的默认配置）
        try:
            row = conn.execute("SELECT welcome_text, goodbye_text, rules_text, enable_welcome, enable_goodbye, enable_rules, clean_welcome FROM welcome_configs WHERE chat_id=0").fetchone()
        except Exception:
            row = None
        data = {
            "welcome_text": row[0] if row else cfg.get("WELCOME_TEXT", ""),
            "goodbye_text": row[1] if row else "",
            "rules_text": row[2] if row else "",
            "enable_welcome": bool(row[3]) if row else bool(cfg.get("WELCOME_MSG", False)),
            "enable_goodbye": bool(row[4]) if row else False,
            "enable_rules": bool(row[5]) if row else False,
            "clean_welcome": bool(row[6]) if row else False,
        }
        return jsonify({"ok": True, "data": data})
    data = request.get_json() or {}
    _adm = _check_admin()
    if _adm:
        return _adm
    cfg = read_config()
    # 写config.json
    cfg["WELCOME_TEXT"] = data.get("welcome_text", "")
    cfg["WELCOME_MSG"] = bool(data.get("enable_welcome", False))
    if not write_config(cfg):
        return jsonify({"ok": False, "msg": "保存config失败"}), 500
    # 写数据库
    try:
        conn.execute("""INSERT OR REPLACE INTO welcome_configs
            (chat_id, welcome_text, goodbye_text, rules_text, enable_welcome, enable_goodbye, enable_rules, clean_welcome)
            VALUES (0, ?, ?, ?, ?, ?, ?, ?)""",
            (data.get("welcome_text", ""), data.get("goodbye_text", ""), data.get("rules_text", ""),
             int(bool(data.get("enable_welcome", False))), int(bool(data.get("enable_goodbye", False))),
             int(bool(data.get("enable_rules", False))), int(bool(data.get("clean_welcome", False)))))
        conn.commit()
    except Exception as e:
        return jsonify({"ok": False, "msg": "数据库写入失败，请检查参数"}), 500
    return jsonify({"ok": True, "msg": "欢迎配置已保存（需重启Bot生效）"})


@features_bp.route("/settings/nightmode", methods=["GET", "POST"])
@login_required
def api_settings_nightmode():
    """夜间模式配置"""
    if request.method == "GET":
        cfg = read_config()
        nc = cfg.get("NIGHT_MODE_CONFIG", {"enable": False, "start_hour": 23, "end_hour": 7})
        return jsonify({"ok": True, "data": nc})
    data = request.get_json() or {}
    _adm = _check_admin()
    if _adm:
        return _adm
    enable = bool(data.get("enable", False))
    start_hour = int(data.get("start_hour", 23))
    end_hour = int(data.get("end_hour", 7))
    start_hour = max(0, min(23, start_hour))
    end_hour = max(0, min(23, end_hour))
    cfg = read_config()
    cfg["NIGHT_MODE_CONFIG"] = {"enable": enable, "start_hour": start_hour, "end_hour": end_hour}
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "夜间模式配置已保存（需重启Bot生效）"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@features_bp.route("/settings/broadcasts", methods=["GET", "POST", "DELETE"])
@login_required
def api_settings_broadcasts():
    """定点播报配置"""
    if request.method == "GET":
        cfg = read_config()
        broadcasts = cfg.get("SCHEDULED_BROADCASTS", [])
        return jsonify({"ok": True, "data": {"broadcasts": broadcasts}})
    elif request.method == "POST":
        _adm = _check_admin()
        if _adm:
            return _adm
        data = request.get_json() or {}
        bid = data.get("id", "").strip()
        if not bid:
            return jsonify({"ok": False, "msg": "播报ID不能为空"}), 400
        hour = int(data.get("hour", 0))
        minute = int(data.get("minute", 0))
        content = data.get("content", "").strip()
        if not content:
            return jsonify({"ok": False, "msg": "播报内容不能为空"}), 400
        btype = data.get("type", "text")
        enabled = bool(data.get("enabled", False))
        day_of_week = data.get("day_of_week")
        day_of_month = data.get("day_of_month")
        cfg = read_config()
        broadcasts = cfg.get("SCHEDULED_BROADCASTS", [])
        # 检查ID重复
        if any(b.get("id") == bid for b in broadcasts):
            return jsonify({"ok": False, "msg": f"播报ID '{bid}' 已存在"}), 400
        new_item = {"id": bid, "hour": hour, "minute": minute, "content": content, "type": btype, "enabled": enabled}
        if day_of_week is not None:
            new_item["day_of_week"] = day_of_week
        if day_of_month is not None:
            new_item["day_of_month"] = day_of_month
        broadcasts.append(new_item)
        cfg["SCHEDULED_BROADCASTS"] = broadcasts
        if write_config(cfg):
            return jsonify({"ok": True, "msg": "播报项已添加（需重启Bot生效）"})
        return jsonify({"ok": False, "msg": "保存失败"}), 500
    else:  # DELETE
        _adm = _check_admin()
        if _adm:
            return _adm
        data = request.get_json() or {}
        bid = data.get("id", "").strip()
        if not bid:
            return jsonify({"ok": False, "msg": "播报ID不能为空"}), 400
        cfg = read_config()
        broadcasts = cfg.get("SCHEDULED_BROADCASTS", [])
        new_broadcasts = [b for b in broadcasts if b.get("id") != bid]
        if len(new_broadcasts) == len(broadcasts):
            return jsonify({"ok": False, "msg": f"未找到播报项 '{bid}'"}), 404
        cfg["SCHEDULED_BROADCASTS"] = new_broadcasts
        if write_config(cfg):
            return jsonify({"ok": True, "msg": "播报项已删除（需重启Bot生效）"})
        return jsonify({"ok": False, "msg": "保存失败"}), 500


@features_bp.route("/settings/broadcasts/<string:bid>", methods=["PUT"])
@login_required
@admin_required
def api_broadcast_update(bid):
    """更新指定ID的定点播报项"""
    data = request.get_json() or {}
    cfg = read_config()
    broadcasts = cfg.get("SCHEDULED_BROADCASTS", [])
    updated = False
    for b in broadcasts:
        if b.get("id") == bid:
            if "hour" in data:
                b["hour"] = int(data["hour"])
            if "minute" in data:
                b["minute"] = int(data["minute"])
            if "content" in data:
                b["content"] = data["content"].strip()
            if "type" in data:
                b["type"] = data["type"]
            if "enabled" in data:
                b["enabled"] = bool(data["enabled"])
            if "day_of_week" in data:
                b["day_of_week"] = data["day_of_week"]
            if "day_of_month" in data:
                b["day_of_month"] = data["day_of_month"]
            updated = True
            break
    if not updated:
        return jsonify({"ok": False, "msg": f"未找到播报项 '{bid}'"}), 404
    cfg["SCHEDULED_BROADCASTS"] = broadcasts
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "播报项已更新（需重启Bot生效）"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500


@features_bp.route("/settings/federation", methods=["GET", "POST", "DELETE"])
@login_required
def api_settings_federation():
    """联邦封禁管理"""
    conn = get_db()
    if request.method == "GET":
        try:
            rows = conn.execute("SELECT user_id, banned_by, reason, chat_id, ts FROM federation_bans ORDER BY ts DESC").fetchall()
            bans = [{"user_id": r[0], "banned_by": r[1], "reason": r[2] or "", "chat_id": r[3], "ts": r[4]} for r in rows]
        except Exception:
            bans = []
        return jsonify({"ok": True, "data": {"bans": bans}})
    elif request.method == "POST":
        _adm = _check_admin()
        if _adm:
            return _adm
        data = request.get_json() or {}
        user_id = data.get("user_id")
        reason = data.get("reason", "").strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "用户ID不能为空"}), 400
        if not reason:
            reason = "Dashboard手动封禁"
        try:
            conn.execute("INSERT OR REPLACE INTO federation_bans (user_id, banned_by, reason, chat_id, ts) VALUES (?, 0, ?, 0, ?)",
                         (int(user_id), reason, int(time.time())))
            conn.commit()
            return jsonify({"ok": True, "msg": f"用户 {user_id} 已加入联邦封禁"})
        except Exception as e:
            return jsonify({"ok": False, "msg": "数据库写入失败，请检查参数"}), 500
    else:  # DELETE
        _adm = _check_admin()
        if _adm:
            return _adm
        data = request.get_json() or {}
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "msg": "用户ID不能为空"}), 400
        try:
            cur = conn.execute("DELETE FROM federation_bans WHERE user_id=?", (int(user_id),))
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"ok": False, "msg": f"用户 {user_id} 不在封禁列表中"}), 404
            return jsonify({"ok": True, "msg": f"用户 {user_id} 已解除联邦封禁"})
        except Exception as e:
            return jsonify({"ok": False, "msg": "数据库操作失败，请检查参数"}), 500


@features_bp.route("/keywords", methods=["GET", "POST"])
@login_required
def api_keywords():
    """关键词触发规则列表/创建"""
    conn = get_db()
    if request.method == "GET":
        try:
            rows = conn.execute(
                "SELECT id, keyword, reply_text, reply_type, action_type, enabled, created_at, updated_at "
                "FROM keyword_triggers ORDER BY id DESC"
            ).fetchall()
            triggers = [
                {
                    "id": r[0], "keyword": r[1], "reply_text": r[2],
                    "reply_type": r[3], "action_type": r[4] or "",
                    "enabled": r[5], "created_at": r[6], "updated_at": r[7]
                }
                for r in rows
            ]
        except Exception:
            triggers = []
        return jsonify({"ok": True, "data": {"triggers": triggers}})
    # POST - 创建新规则
    _adm = _check_admin()
    if _adm:
        return _adm
    data = request.get_json() or {}
    keyword = data.get("keyword", "").strip()
    reply_text = data.get("reply_text", "").strip()
    reply_type = data.get("reply_type", "static")
    action_type = data.get("action_type", "")
    if not keyword or not reply_text:
        return jsonify({"ok": False, "msg": "关键词和回复内容不能为空"}), 400
    ts = int(time.time())
    try:
        conn.execute(
            "INSERT INTO keyword_triggers (keyword, reply_text, reply_type, action_type, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (keyword, reply_text, reply_type, action_type, ts, ts)
        )
        conn.commit()
        return jsonify({"ok": True, "msg": "关键词触发规则已添加"})
    except Exception as e:
        return jsonify({"ok": False, "msg": "保存失败，请检查参数"}), 500


@features_bp.route("/keywords/<int:tid>", methods=["PUT", "DELETE"])
@login_required
@admin_required
def api_keyword_item(tid):
    """关键词触发规则更新/删除"""
    conn = get_db()
    exists = conn.execute("SELECT id FROM keyword_triggers WHERE id=?", (tid,)).fetchone()
    if not exists:
        return jsonify({"ok": False, "msg": f"未找到规则 #{tid}"}), 404

    if request.method == "DELETE":
        conn.execute("DELETE FROM keyword_triggers WHERE id=?", (tid,))
        conn.commit()
        return jsonify({"ok": True, "msg": "关键词触发规则已删除"})

    # PUT - 更新规则
    data = request.get_json() or {}
    allowed = ["keyword", "reply_text", "reply_type", "action_type", "enabled"]
    updates = []
    params = []
    for f in allowed:
        if f in data:
            val = data[f]
            if f == "enabled":
                val = 1 if val else 0
            if isinstance(val, str):
                val = val.strip()
            updates.append(f"{f}=?")
            params.append(val)
    if not updates:
        return jsonify({"ok": False, "msg": "无有效更新字段"}), 400
    updates.append("updated_at=?")
    params.append(int(time.time()))
    params.append(tid)
    sql = f"UPDATE keyword_triggers SET {', '.join(updates)} WHERE id=?"
    try:
        conn.execute(sql, params)
        conn.commit()
        return jsonify({"ok": True, "msg": "关键词触发规则已更新"})
    except Exception as e:
        return jsonify({"ok": False, "msg": "更新失败，请检查参数"}), 500


@features_bp.route("/settings/emoji-mask", methods=["GET", "POST"])
@login_required
def api_settings_emoji_mask():
    """emoji面具检测配置"""
    if request.method == "GET":
        cfg = read_config()
        keywords = cfg.get("AUTO_MUTE_NAMES", [])
        enable = cfg.get("AUTO_MUTE_NAMES_ENABLED", False)
        return jsonify({"ok": True, "data": {"keywords": keywords, "enable": enable}})
    data = request.get_json() or {}
    _adm = _check_admin()
    if _adm:
        return _adm
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list):
        return jsonify({"ok": False, "msg": "keywords必须是数组"}), 400
    enable = bool(data.get("enable", False))
    cfg = read_config()
    cfg["AUTO_MUTE_NAMES"] = keywords
    cfg["AUTO_MUTE_NAMES_ENABLED"] = enable
    if write_config(cfg):
        return jsonify({"ok": True, "msg": "emoji面具检测配置已保存（需重启Bot生效）"})
    return jsonify({"ok": False, "msg": "保存失败"}), 500
