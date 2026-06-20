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
        if hasattr(db, "blacklist_add"):
            db.blacklist_add(uid, reason)
    except Exception as e:
        ok = False
        logger.warning(f"写入blacklist失败: uid={uid} err={e}")
    return ok


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


def _notify_admin(bot, config: dict, uid: int, uname: str, reason: str, deleted_count: int, muted: bool, reactions_cleaned: bool = False):
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
        _notify_admin(bot, config or {}, uid, uname or str(uid), reason, deleted_count, muted, reactions_cleaned)
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
