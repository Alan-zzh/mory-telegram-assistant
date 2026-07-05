# -*- coding: utf-8 -*-
"""
广告账号统一处置：不踢人，只永久禁言、删消息、双黑名单。
"""

from core.helpers import can_delete_message, format_user_mention
from core.logging_util import get_logger
from core.telebot_compat import delete_all_message_reactions_compat, restrict_chat_member_compat

logger = get_logger("ad_enforcement")


def _safe_delete(bot, db, chat_id: int, msg_id: int) -> bool:
    """删除消息并标记快照，失败不影响主流程。"""
    if not msg_id:
        return False
    deleted = False
    should_mark_deleted = False
    try:
        bot.delete_message(chat_id, msg_id)
        deleted = True
        should_mark_deleted = True
    except Exception as e:
        err = str(e).lower()
        if "not found" in err:
            logger.debug(f"广告消息已不存在: chat={chat_id} msg={msg_id}")
            should_mark_deleted = True
        else:
            logger.debug(f"删除广告消息失败: chat={chat_id} msg={msg_id} err={e}")
    try:
        if should_mark_deleted and db and hasattr(db, "mark_message_deleted"):
            db.mark_message_deleted(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"标记广告消息删除失败: chat={chat_id} msg={msg_id} err={e}")
    return deleted


def _mute_forever(bot, chat_id: int, uid: int) -> bool:
    """永久禁言广告账号，不踢出群。"""
    try:
        restrict_chat_member_compat(
            bot,
            chat_id,
            uid,
            permissions={
                "can_send_messages": False,
                "can_send_audios": False,
                "can_send_documents": False,
                "can_send_photos": False,
                "can_send_videos": False,
                "can_send_video_notes": False,
                "can_send_voice_notes": False,
                "can_send_polls": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False,
                "can_send_paid_media": False,
                "can_react_to_messages": False,
            },
        )
        return True
    except Exception as e:
        logger.warning(f"永久禁言广告账号失败: chat={chat_id} uid={uid} err={e}")
        return False


def _write_blacklists(bot, db, uid: int, reason: str) -> bool:
    """同步写入 global_blacklist 和本地 blacklist。"""
    ok = True
    actor_id = 0
    try:
        actor_id = bot.get_me().id
    except Exception:
        actor_id = 0
    try:
        db.conn.execute(
            "INSERT OR IGNORE INTO global_blacklist "
            "(user_id, reason, added_by, added_at) VALUES (?,?,?,datetime('now'))",
            (uid, reason, actor_id),
        )
        db.conn.commit()
    except Exception as e:
        ok = False
        logger.warning(f"写入global_blacklist失败: uid={uid} err={e}")
        try:
            from modules.auto_tasks import report_fault
            report_fault("广告处置失败", f"写入global_blacklist失败 uid={uid}: {e}", "🚨")
        except Exception as e2:
            # 【v5.31.2 修复】告警链断裂会导致管理员无法感知广告号未被封禁
            logger.error(f"广告处置告警上报失败(global_blacklist): {e2}")
    try:
        if hasattr(db, "blacklist_add"):
            db.blacklist_add(uid, reason)
    except Exception as e:
        ok = False
        logger.warning(f"写入blacklist失败: uid={uid} err={e}")
        try:
            from modules.auto_tasks import report_fault
            report_fault("广告处置失败", f"写入blacklist失败 uid={uid}: {e}", "🚨")
        except Exception as e2:
            # 【v5.31.2 修复】告警链断裂会导致管理员无法感知广告号未被封禁
            logger.error(f"广告处置告警上报失败(blacklist): {e2}")
    return ok


def _remove_blacklists(db, uid: int) -> bool:
    """移除广告处置写入的本地/全局黑名单和禁言记录。"""
    ok = True
    lock = getattr(db, "lock", None)
    try:
        if lock:
            lock.acquire()
        db.conn.execute("DELETE FROM blacklist WHERE uid=?", (uid,))
        db.conn.execute("DELETE FROM global_blacklist WHERE user_id=?", (uid,))
        db.conn.execute("DELETE FROM mute_records WHERE uid=?", (uid,))
        db.conn.commit()
    except Exception as e:
        ok = False
        logger.warning(f"移除广告黑名单失败: uid={uid} err={e}")
    finally:
        if lock:
            try:
                lock.release()
            except Exception:
                pass
    return ok


def _restore_chat_permissions(bot, chat_id: int, uid: int) -> bool:
    """恢复用户在群内的基础发言权限。"""
    if not chat_id:
        return False
    try:
        restrict_chat_member_compat(
            bot,
            chat_id,
            uid,
            permissions={
                "can_send_messages": True,
                "can_send_audios": True,
                "can_send_documents": True,
                "can_send_photos": True,
                "can_send_videos": True,
                "can_send_video_notes": True,
                "can_send_voice_notes": True,
                "can_send_polls": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True,
                "can_send_paid_media": True,
                "can_react_to_messages": True,
            },
        )
        return True
    except Exception as e:
        logger.warning(f"恢复用户发言权限失败: chat={chat_id} uid={uid} err={e}")
        return False


def _clear_ad_tracking(ad_detector, uid: int) -> bool:
    if not ad_detector or not hasattr(ad_detector, "clear_user_tracking"):
        return False
    try:
        ad_detector.clear_user_tracking(uid)
        return True
    except Exception as e:
        logger.warning(f"清理广告追踪记录失败: uid={uid} err={e}")
        return False


def restore_ad_user(bot, db, config: dict, chat_id: int, uid: int, actor_id: int = 0, ad_detector=None) -> dict:
    """撤销广告误封：移除黑名单并尝试恢复群内发言权限。"""
    uid = int(uid)
    chat_id = int(chat_id or 0)
    removed = _remove_blacklists(db, uid)
    restored = _restore_chat_permissions(bot, chat_id, uid)
    tracking_cleared = _clear_ad_tracking(ad_detector, uid)
    logger.warning(
        f"广告误封解封完成: uid={uid} chat={chat_id} "
        f"removed={removed} restored={restored} tracking_cleared={tracking_cleared} actor={actor_id}"
    )
    return {
        "code": 200 if removed else 500,
        "data": {
            "uid": uid,
            "chat_id": chat_id,
            "blacklist_removed": removed,
            "permissions_restored": restored,
            "tracking_cleared": tracking_cleared,
            "actor_id": actor_id,
        },
        "msg": "success" if removed else "remove_blacklist_failed",
    }


def _admin_ids(config: dict) -> set:
    raw_admin_ids = (config or {}).get("ADMIN_IDS", []) or []
    if isinstance(raw_admin_ids, int):
        raw_admin_ids = [raw_admin_ids]
    if not isinstance(raw_admin_ids, (list, tuple, set)):
        raw_admin_ids = []
    admin_ids = set()
    for item in raw_admin_ids:
        try:
            admin_ids.add(int(item))
        except Exception:
            continue
    admin_id = (config or {}).get("ADMIN_ID", 0)
    if admin_id:
        try:
            admin_ids.add(int(admin_id))
        except Exception:
            pass
    return admin_ids


def _extract_unban_token(message) -> str:
    text = (getattr(message, "text", "") or "").strip()
    parts = text.split()
    if len(parts) >= 2:
        return parts[1].strip()
    return ""


def _resolve_username_from_db(db, username: str) -> int:
    username = (username or "").lstrip("@").strip().lower()
    if not username:
        return 0
    queries = [
        ("SELECT uid FROM group_members WHERE lower(username)=? ORDER BY last_checked DESC LIMIT 1", (username,)),
        ("SELECT uid FROM group_members WHERE lower(username)=? LIMIT 1", (username,)),
    ]
    for sql, params in queries:
        try:
            row = db.conn.execute(sql, params).fetchone()
            if row and row[0]:
                return int(row[0])
        except Exception as e:
            logger.debug(f"按username查用户失败: username={username} err={e}")
    return 0


def _display_name_candidates(db, display_name: str) -> list[tuple[int, str, str]]:
    display_name = (display_name or "").lstrip("@").strip()
    if not display_name:
        return []
    queries = [
        (
            "SELECT DISTINCT uid, username, display_name FROM group_members "
            "WHERE display_name=? ORDER BY last_checked DESC LIMIT 8",
            (display_name,),
        ),
        (
            "SELECT DISTINCT uid, username, display_name FROM group_members "
            "WHERE display_name LIKE ? ORDER BY last_checked DESC LIMIT 8",
            (f"%{display_name}%",),
        ),
    ]
    for sql, params in queries:
        try:
            rows = db.conn.execute(sql, params).fetchall()
            candidates = [(int(row[0]), str(row[1] or ""), str(row[2] or "")) for row in rows if row and row[0]]
            if candidates:
                return candidates
        except Exception as e:
            logger.debug(f"按显示名查用户失败: name={display_name} err={e}")
    return []


def _resolve_display_name_from_db(db, display_name: str) -> int:
    candidates = _display_name_candidates(db, display_name)
    if not candidates:
        return 0
    if len(candidates) == 1:
        return candidates[0][0]

    logger.info(f"按显示名解封匹配到多人，拒绝自动选择: name={display_name} count={len(candidates)}")
    return 0


def _format_display_name_candidates(db, display_name: str) -> str:
    candidates = _display_name_candidates(db, display_name)
    if not candidates:
        return ""
    lines = []
    for uid, username, name in candidates[:5]:
        account = f"@{username}" if username else "无username"
        lines.append(f"- {name or display_name}：{uid}（{account}）")
    return "\n".join(lines)


def resolve_unban_target(bot, db, message, token: str = "") -> tuple[int, str]:
    """从回复消息、数字ID或 @username 解析要解封的用户。"""
    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    if reply_user and getattr(reply_user, "id", 0):
        uid = int(reply_user.id)
        label = getattr(reply_user, "username", "") or getattr(reply_user, "first_name", "") or str(uid)
        return uid, str(label)

    token = (token or _extract_unban_token(message)).strip()
    if not token:
        return 0, ""

    cleaned = token.lstrip("@")
    if cleaned.lstrip("-").isdigit():
        return int(cleaned), token

    uid = _resolve_username_from_db(db, cleaned)
    if uid:
        return uid, f"@{cleaned}"

    uid = _resolve_display_name_from_db(db, cleaned)
    if uid:
        return uid, cleaned

    try:
        chat = bot.get_chat(f"@{cleaned}")
        uid = int(getattr(chat, "id", 0) or 0)
        if uid:
            return uid, f"@{cleaned}"
    except Exception as e:
        logger.debug(f"Bot API按username解析失败: username={cleaned} err={e}")
    return 0, token


def handle_unban_command(bot, message, config: dict, db, ad_detector=None) -> bool:
    """管理员解封指令：支持回复、用户ID、@username。"""
    actor_id = getattr(getattr(message, "from_user", None), "id", 0) or 0
    logger.info(
        f"收到解封指令: actor={actor_id} chat={getattr(getattr(message, 'chat', None), 'id', 0)} "
        f"text={(getattr(message, 'text', '') or '').strip()[:80]}"
    )
    if actor_id not in _admin_ids(config or {}):
        try:
            bot.reply_to(message, "只有管理员可以解封。")
        except Exception:
            pass
        return True

    token = _extract_unban_token(message)
    uid, label = resolve_unban_target(bot, db, message, token)
    if not uid:
        candidates_text = _format_display_name_candidates(db, token)
        extra = f"\n\n我找到多个同名候选，请用 ID 精确解封：\n{candidates_text}" if candidates_text else ""
        try:
            bot.reply_to(
                message,
                "没找到要解封的人。请回复被误封用户发送 /unban，或发送 /unban 用户ID / /unban @username / 解封 显示名。重名时请用用户ID。"
                + extra,
            )
        except Exception:
            pass
        return True

    chat_id = getattr(getattr(message, "chat", None), "id", 0) or 0
    if chat_id > 0:
        chat_id = int((config or {}).get("GROUP_ID", 0) or 0)
    result = restore_ad_user(
        bot=bot,
        db=db,
        config=config or {},
        chat_id=chat_id,
        uid=uid,
        actor_id=actor_id,
        ad_detector=ad_detector,
    )
    data = result.get("data", {})
    if result.get("code") == 200:
        text = (
            f"已解封 {label or uid}。\n"
            f"已清理：本地黑名单 / 全局黑名单 / 禁言记录。\n"
            f"已尝试恢复群内发言权限；广告追踪记录：{'已清理' if data.get('tracking_cleared') else '无记录或无需清理'}。"
        )
    else:
        text = f"解封 {label or uid} 失败，黑名单记录没有完全清掉，请看后台日志。"
    try:
        bot.reply_to(message, text)
    except Exception as e:
        logger.debug(f"发送解封指令结果失败: uid={uid} err={e}")
    return True


def _cleanup_user_reactions(bot, config: dict, uid: int, chat_id: int) -> bool:
    """删除广告用户在本群留下的反应，Bot API 不支持时静默降级。"""
    if not (config or {}).get("AD_CLEANUP_REACTIONS", True):
        return False
    try:
        return bool(delete_all_message_reactions_compat(bot, chat_id, user_id=uid))
    except Exception as e:
        logger.debug(f"清理广告用户反应失败: chat={chat_id} uid={uid} err={e}")
        return False


def _cleanup_user_messages(bot, db, config: dict, uid: int, chat_id: int, current_msg_id: int = 0) -> int:
    """删除已追踪的广告用户历史消息。"""
    if not can_delete_message(config):
        return 0
    deleted_count = 0
    seen = set()
    if current_msg_id:
        seen.add((chat_id, current_msg_id))
        deleted_count += 1 if _safe_delete(bot, db, chat_id, current_msg_id) else 0
    try:
        limit = int((config or {}).get("AD_CLEANUP_HISTORY_LIMIT", 2000))
    except Exception:
        limit = 2000
    try:
        if hasattr(db, "get_user_undeleted_messages"):
            messages = db.get_user_undeleted_messages(uid, chat_id, limit=limit)
        elif hasattr(db, "get_user_messages"):
            messages = db.get_user_messages(uid, chat_id, limit=limit)
        else:
            messages = []
    except Exception as e:
        logger.debug(f"查询广告用户历史消息失败: uid={uid} err={e}")
        messages = []
    for item in messages:
        try:
            mid = int(item.get("msg_id") or 0)
            cid = int(item.get("chat_id") or chat_id)
            if not mid or (cid, mid) in seen:
                continue
            seen.add((cid, mid))
            deleted_count += 1 if _safe_delete(bot, db, cid, mid) else 0
        except Exception as e:
            logger.debug(f"清理广告历史消息异常: uid={uid} item={item} err={e}")
    return deleted_count


def _build_unban_markup(uid: int, chat_id: int):
    try:
        from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("解封", callback_data=f"ad_unban:{uid}:{chat_id}"))
        return keyboard
    except Exception as e:
        logger.debug(f"构建广告解封按钮失败: uid={uid} err={e}")
        return None


def _notify_admin(bot, config: dict, chat_id: int, uid: int, uname: str, reason: str, deleted_count: int, muted: bool, reactions_cleaned: bool = False):
    """通知管理员广告处置结果。"""
    admin_id = config.get("ADMIN_ID", 0)
    if not admin_id:
        return
    try:
        bot.send_message(
            admin_id,
            f"🚫 广告账号已处理\n"
            f"👤 用户：{format_user_mention(uid, uname)}\n"
            f"📋 操作：永久禁言 + 加黑名单 + 删除消息\n"
            f"🗑 删除消息：{deleted_count}条\n"
            f"🧹 清理反应：{'已尝试' if reactions_cleaned else '未执行/不支持'}\n"
            f"🔇 永久禁言：{'成功' if muted else '失败'}\n"
            f"🎯 原因：{reason[:200]}",
            parse_mode="HTML",
            reply_markup=_build_unban_markup(uid, chat_id),
        )
    except Exception as e:
        logger.debug(f"广告处置通知管理员失败: uid={uid} err={e}")


def enforce_ad_user(
    bot,
    db,
    config: dict,
    chat_id: int,
    uid: int,
    uname: str = "",
    reason: str = "广告检测",
    message=None,
    current_msg_id: int = 0,
    notify_admin: bool = True,
) -> dict:
    """统一广告处置入口，接口返回固定结构。"""
    reason = str(reason or "广告检测")
    if not current_msg_id and message is not None:
        current_msg_id = getattr(message, "message_id", 0) or 0
    deleted_count = _cleanup_user_messages(bot, db, config or {}, uid, chat_id, current_msg_id)
    muted = _mute_forever(bot, chat_id, uid)
    reactions_cleaned = _cleanup_user_reactions(bot, config or {}, uid, chat_id)
    blacklisted = _write_blacklists(bot, db, uid, reason)
    if notify_admin:
        _notify_admin(bot, config or {}, chat_id, uid, uname or str(uid), reason, deleted_count, muted, reactions_cleaned)
    logger.warning(
        f"广告账号处置完成: uid={uid} chat={chat_id} "
        f"muted={muted} blacklisted={blacklisted} deleted={deleted_count} reactions_cleaned={reactions_cleaned}"
    )
    return {
        "code": 200,
        "data": {
            "uid": uid,
            "chat_id": chat_id,
            "muted": muted,
            "blacklisted": blacklisted,
            "deleted_count": deleted_count,
            "reactions_cleaned": reactions_cleaned,
        },
        "msg": "success",
    }
