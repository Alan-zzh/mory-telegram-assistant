# -*- coding: utf-8 -*-
"""
广告账号统一处置：不踢人，只永久禁言、删消息、双黑名单。
"""

import logging
import json
import time

from core.helpers import format_user_mention
from core.logging_util import get_logger
from core.telegram_send_utils import delete_all_message_reactions_compat, restrict_chat_member_compat

logger = get_logger("ad_enforcement")


def _delete_message_with_status(bot, db, chat_id: int, msg_id: int) -> str:
    """删除消息并返回 deleted/already_absent/failed 三态。"""
    if not msg_id:
        return "failed"
    status = "failed"
    should_mark_deleted = False
    try:
        result = bot.delete_message(chat_id, msg_id)
        if result is not False:
            status = "deleted"
            should_mark_deleted = True
    except Exception as e:
        err = str(e).lower()
        if "not found" in err:
            logger.debug(f"治理消息已不存在: chat={chat_id} msg={msg_id}")
            status = "already_absent"
            should_mark_deleted = True
        else:
            logger.debug(f"删除治理消息失败: chat={chat_id} msg={msg_id} err={e}")
    try:
        if should_mark_deleted and db and hasattr(db, "mark_message_deleted"):
            db.mark_message_deleted(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"标记广告消息删除失败: chat={chat_id} msg={msg_id} err={e}")
    return status


def _safe_delete(bot, db, chat_id: int, msg_id: int) -> bool:
    """兼容布尔调用：只有本次真实删除成功才计入 deleted_count。"""
    return _delete_message_with_status(bot, db, chat_id, msg_id) == "deleted"


def _mark_current_message_ad(db, chat_id: int, msg_id: int) -> bool:
    """先固化逐条广告判定，再执行外部删除，避免删除失败时丢失审计真值。"""
    if not db or not chat_id or not msg_id or not hasattr(db, "mark_message_ad"):
        return False
    try:
        return bool(db.mark_message_ad(chat_id, msg_id))
    except Exception as e:
        logger.warning(f"标记广告消息失败: chat={chat_id} msg={msg_id} err={e}")
        return False


def delete_confirmed_ad_message(bot, db, chat_id: int, msg_id: int) -> dict:
    """只处理已逐条确证的广告消息；独立于普通删除总闸。"""
    evidence_persisted = _mark_current_message_ad(db, chat_id, msg_id)
    status = _delete_message_with_status(bot, db, chat_id, msg_id)
    return {
        "evidence_persisted": evidence_persisted,
        "deleted": status == "deleted",
        "status": status,
    }


def delete_repeated_spam_messages(bot, db, messages: list[dict]) -> dict:
    """只删除已达到重复阈值的消息组；不标广告、不禁言、不写黑名单。"""
    statuses = []
    seen = set()
    for message in messages or []:
        try:
            chat_id = int(message.get("chat_id", 0) or 0)
            msg_id = int(message.get("msg_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        key = (chat_id, msg_id)
        if not chat_id or not msg_id or key in seen:
            continue
        seen.add(key)
        statuses.append({
            "chat_id": chat_id,
            "msg_id": msg_id,
            "status": _delete_message_with_status(bot, db, chat_id, msg_id),
        })
    return {
        "handled": bool(statuses),
        "deleted_count": sum(item["status"] == "deleted" for item in statuses),
        "already_absent_count": sum(item["status"] == "already_absent" for item in statuses),
        "failed_count": sum(item["status"] == "failed" for item in statuses),
        "statuses": statuses,
    }


def _mute_forever(bot, db, chat_id: int, uid: int, reason: str = "广告检测") -> bool:
    """永久禁言广告账号，不踢出群；持久态由统一事务写入。"""
    try:
        current_member = bot.get_chat_member(chat_id, uid)
        if str(getattr(current_member, "status", "") or "").lower() == "kicked":
            # 账号已被外部管理员封禁时保持更严格的现状，不用 restrict 将其改回群成员。
            # 返回成功让统一链继续固化双黑名单和 mute_records，阻止后续重入漏审。
            logger.info(f"广告账号已处于群封禁状态，保留现状并固化治理记录: chat={chat_id} uid={uid}")
            return True
    except Exception as e:
        # 处置入口已经完成管理员三态门禁；这里的状态读回只用于避免改写既有 kicked 状态。
        logger.debug(f"读取广告账号既有限制状态失败，继续执行永久禁言: chat={chat_id} uid={uid} err={e}")
    try:
        restriction_result = restrict_chat_member_compat(
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
        if restriction_result is False:
            logger.warning(f"永久禁言广告账号返回失败: chat={chat_id} uid={uid}")
            return False
        return True
    except Exception as e:
        logger.warning(f"永久禁言广告账号失败: chat={chat_id} uid={uid} err={e}")
        return False


def _persist_ad_state(bot, db, chat_id: int, uid: int, reason: str, muted: bool) -> bool:
    """在一个事务内写入广告持久态；重复拦截不得覆盖首次根因和时间。"""
    if db is None or not getattr(db, "conn", None):
        logger.error(f"广告处置缺少数据库，无法固化状态: uid={uid}")
        return False
    actor_id = 0
    try:
        actor_id = bot.get_me().id
    except Exception:
        actor_id = 0
    lock = getattr(db, "lock", None)
    try:
        if lock:
            lock.acquire()
        if muted:
            db.conn.execute(
                "INSERT OR IGNORE INTO mute_records "
                "(uid, chat_id, mute_until, reason) VALUES (?,?,?,?)",
                (uid, chat_id, 0, reason),
            )
        db.conn.execute(
            "INSERT OR IGNORE INTO global_blacklist "
            "(user_id, reason, added_by, added_at) VALUES (?,?,?,datetime('now'))",
            (uid, reason, actor_id),
        )
        # 旧部署曾只有 uid/reason 两列，后续 schema 才加入 date；事务路径需兼容两者。
        try:
            blacklist_columns = [
                str(row[1]) for row in db.conn.execute("PRAGMA table_info(blacklist)").fetchall()
            ]
        except Exception:
            blacklist_columns = ["uid", "reason", "date"]
        if "date" in blacklist_columns:
            db.conn.execute(
                "INSERT OR IGNORE INTO blacklist (uid, reason, date) VALUES (?,?,?)",
                (uid, reason, int(time.time())),
            )
        elif "timestamp" in blacklist_columns:
            db.conn.execute(
                "INSERT OR IGNORE INTO blacklist (uid, reason, timestamp) VALUES (?,?,?)",
                (uid, reason, int(time.time())),
            )
        elif len(blacklist_columns) >= 3:
            db.conn.execute("INSERT OR IGNORE INTO blacklist VALUES (?,?,?)", (uid, reason, int(time.time())))
        else:
            db.conn.execute(
                "INSERT OR IGNORE INTO blacklist (uid, reason) VALUES (?,?)",
                (uid, reason),
            )
        db.conn.commit()
        return True
    except Exception as e:
        try:
            db.conn.rollback()
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
        logger.warning(f"广告处置持久态事务失败并已回滚: uid={uid} err={e}")
        try:
            from tasks.support.fault_reporter import report_fault
            report_fault("广告处置失败", f"持久态事务失败 uid={uid}: {e}", "🚨")
        except Exception as e2:
            logger.error(f"广告处置告警上报失败(persist_state): {e2}")
        return False
    finally:
        if lock:
            try:
                lock.release()
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger(__name__).debug(f'非致命忽略: {_e}')


def _remove_blacklists(db, uid: int) -> bool:
    """移除广告处置写入的本地/全局黑名单、禁言记录和可疑用户追踪。"""
    ok = True
    lock = getattr(db, "lock", None)
    try:
        if lock:
            lock.acquire()
        db.conn.execute("DELETE FROM blacklist WHERE uid=?", (uid,))
        db.conn.execute("DELETE FROM global_blacklist WHERE user_id=?", (uid,))
        db.conn.execute("DELETE FROM mute_records WHERE uid=?", (uid,))
        # 【v5.31.6 修复】解封时清理 ad_suspicious_users，避免残留可疑评分导致再次触发禁封
        db.conn.execute("DELETE FROM ad_suspicious_users WHERE user_id=?", (uid,))
        db.conn.commit()
    except Exception as e:
        try:
            db.conn.rollback()
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
        ok = False
        logger.warning(f"移除广告黑名单失败: uid={uid} err={e}")
    finally:
        if lock:
            try:
                lock.release()
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
    return ok


def _restore_chat_permissions(bot, chat_id: int, uid: int) -> bool:
    """恢复用户在群内的基础发言权限。"""
    if not chat_id:
        return False
    try:
        result = restrict_chat_member_compat(
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
        if result is False:
            logger.warning(f"恢复用户发言权限返回失败: chat={chat_id} uid={uid}")
            return False
        return True
    except Exception as e:
        logger.warning(f"恢复用户发言权限失败: chat={chat_id} uid={uid} err={e}")
        return False


def _verify_persistent_state_cleared(db, uid: int) -> tuple[bool, dict]:
    """读回四项广告持久态；任何查询失败都按未确认处理。"""
    checks = {
        "blacklist": ("SELECT COUNT(*) FROM blacklist WHERE uid=?", uid),
        "global_blacklist": ("SELECT COUNT(*) FROM global_blacklist WHERE user_id=?", uid),
        "mute_records": ("SELECT COUNT(*) FROM mute_records WHERE uid=?", uid),
        "ad_suspicious_users": ("SELECT COUNT(*) FROM ad_suspicious_users WHERE user_id=?", uid),
    }
    counts = {}
    lock = getattr(db, "lock", None)
    try:
        if lock:
            lock.acquire()
        for name, (sql, value) in checks.items():
            row = db.conn.execute(sql, (value,)).fetchone()
            counts[name] = int(row[0]) if row else -1
    except Exception as e:
        logger.warning(f"解封持久态读回失败: uid={uid} err={e}")
        return False, counts
    finally:
        if lock:
            try:
                lock.release()
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
    return all(count == 0 for count in counts.values()), counts


def _verify_chat_permissions_restored(bot, chat_id: int, uid: int) -> bool:
    """通过 Bot API 读回成员状态，禁止用 restrict 调用未报错冒充成功。"""
    try:
        member = bot.get_chat_member(chat_id, uid)
        status = str(getattr(member, "status", "") or "").lower()
        if status in {"creator", "administrator", "member"}:
            return True
        return status == "restricted" and getattr(member, "can_send_messages", None) is True
    except Exception as e:
        logger.warning(f"解封权限读回失败: chat={chat_id} uid={uid} err={e}")
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
    """撤销广告误封：远端恢复读回确认后，才清除四项本地治理事实。"""
    uid = int(uid)
    chat_id = int(chat_id or 0)
    restored = _restore_chat_permissions(bot, chat_id, uid)
    permission_verified = restored and _verify_chat_permissions_restored(bot, chat_id, uid)
    removed = False
    persistence_verified = False
    tracking_cleared = False
    persistence_counts = {}

    # Telegram 的成功返回不等于真实生效，必须先读回。远端恢复失败或未知时，
    # 黑名单、禁言记录和可疑追踪都保留，避免出现“人仍被禁言但治理事实已消失”。
    if permission_verified:
        removed = _remove_blacklists(db, uid)
        persistence_verified, persistence_counts = _verify_persistent_state_cleared(
            db, uid
        )
        if removed and persistence_verified:
            tracking_cleared = _clear_ad_tracking(ad_detector, uid)
    else:
        # 即使不清理，也返回当前读回，供管理员确认保留的四项事实。
        _ignored, persistence_counts = _verify_persistent_state_cleared(
            db, uid
        )

    confirmed = removed and persistence_verified and permission_verified
    resolved_events = 0
    if confirmed and hasattr(db, "list_unresolved_ad_events") and hasattr(db, "resolve_ad_event"):
        try:
            roots = {
                str(item.get("root_event_id") or item.get("event_id") or "")
                for item in (db.list_unresolved_ad_events(uid) or [])
            }
            for root_id in roots:
                if root_id:
                    resolved_events += int(db.resolve_ad_event(
                        root_id, "restored",
                        {"actor_id": int(actor_id or 0), "permission_verified": True,
                         "persistence_verified": True},
                    ) or 0)
        except Exception as e:
            logger.warning(f"解封后关闭处置事件失败: uid={uid} err={e}")
    logger.warning(
        f"广告误封解封核验: uid={uid} chat={chat_id} confirmed={confirmed} "
        f"removed={removed} persistence_verified={persistence_verified} "
        f"permission_verified={permission_verified} tracking_cleared={tracking_cleared} actor={actor_id}"
    )
    # 【v5.31.7】解封后通知管理员（卡片化），与禁封通知对称
    try:
        admin_id = (config or {}).get("ADMIN_ID", 0)
        if admin_id:
            from core.broadcast_formatter import build_alert_card_html
            body = (
                f"👤 用户：{format_user_mention(uid, str(uid))}\n"
                f"📋 操作：移除黑名单 + 恢复权限 + 清理追踪\n"
                f"🗄 四项持久态读回：{'已清空' if persistence_verified else '未确认'}\n"
                f"🔓 权限读回：{'已恢复' if permission_verified else '未确认'}\n"
                f"🧹 追踪清理：{'成功' if tracking_cleared else '失败'}\n"
                f"👨‍⚖️ 操作者：{actor_id}"
            )
            card = build_alert_card_html(
                title="广告误封已解封" if confirmed else "广告解封未完全确认",
                body=body,
                level="success" if confirmed else "warning",
                footer=f"chat_id={chat_id} uid={uid}",
            )
            bot.send_message(admin_id, card, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"解封通知管理员失败: uid={uid} err={e}")
    # 【v5.31.7】Ephemeral Messages 接入：给被解封用户发群内私密通知（Bot API 10.2）
    # 默认关闭，开启 EPHEMERAL_MESSAGE_ENABLED 后生效。被禁言用户可见性官方未明示，
    # 仅在已解封（restored=True）后发送，确保用户已恢复发言权限。
    if (config or {}).get("EPHEMERAL_MESSAGE_ENABLED", False) and confirmed and chat_id:
        try:
            from core.telegram_send_utils import send_ephemeral_message_compat
            from core.broadcast_formatter import build_alert_card_html
            user_card = build_alert_card_html(
                title="你的群内发言权限已恢复",
                body="如果是误封，已为你解除。欢迎继续正常交流～",
                level="success",
            )
            send_ephemeral_message_compat(
                bot, chat_id, uid, user_card, parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"解封 Ephemeral 通知用户失败: uid={uid} err={e}")
    return {
        "code": 200 if confirmed else 500,
        "data": {
            "uid": uid,
            "chat_id": chat_id,
            "blacklist_removed": removed,
            "permissions_restored": restored,
            "persistence_verified": persistence_verified,
            "persistence_counts": persistence_counts,
            "permission_verified": permission_verified,
            "tracking_cleared": tracking_cleared,
            "actor_id": actor_id,
            "resolved_events": resolved_events,
        },
        "msg": "success" if confirmed else "restore_not_verified",
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
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
    return admin_ids


def _is_chat_admin_member(bot, chat_id: int, uid: int) -> str:
    """查询用户在群内是否为管理员/群主，三态返回。

    - "admin"：查询成功且 status ∈ (administrator, creator)
    - "not_admin"：查询成功但非管理（或入参缺失）
    - "unknown"：get_chat_member 抛异常，无法判定

    职责边界：与 core/handlers/member_handlers._is_member_ad_exempt
    （检测前 whitelist+admin 免检）是两层防线——检测前置 vs 处置链兜底。
    """
    if not chat_id or not uid:
        return "not_admin"
    try:
        member = bot.get_chat_member(chat_id, uid)
        if bool(member and getattr(member, "status", "") in ("administrator", "creator")):
            return "admin"
        return "not_admin"
    except AttributeError:
        # 调用对象缺少 get_chat_member（仅测试桩等不完整对象，生产 telebot 必有）：
        # 视为非管理继续处置，保持旧行为，不触发降级
        logger.debug(f"调用对象缺少 get_chat_member，按非管理继续处置: chat={chat_id} uid={uid}")
        return "not_admin"
    except Exception as e:
        logger.debug(f"查询群管身份失败，按未知处理等待人工复核: chat={chat_id} uid={uid} err={e}")
        return "unknown"


def _admin_skip_result(uid: int, chat_id: int, skipped_reason: str) -> dict:
    """豁免/降级跳过的同构返回结构：不做任何处置，仅记录跳过原因。"""
    return {
        "code": 200,
        "data": {
            "uid": uid,
            "chat_id": chat_id,
            "muted": False,
            "blacklisted": False,
            "deleted_count": 0,
            "evidence_persisted": False,
            "reactions_cleaned": False,
            "skipped_reason": skipped_reason,
        },
        "msg": "skipped_admin",
    }



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
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
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
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
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
            f"已读回确认清理：本地黑名单 / 全局黑名单 / 禁言记录 / 可疑追踪。\n"
            f"已通过 Bot API 确认群内发言权限恢复；内存追踪：{'已清理' if data.get('tracking_cleared') else '无记录或无需清理'}。"
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
    """删除当前拦截消息，以及数据库中逐条确认为广告的历史消息。

    广告治理必须独立于普通自动删消息总闸。`ENABLE_MESSAGE_DELETION` 只控制
    夜间模式、慢速模式等普通自动清理，不能让已确认广告留在群内。
    """
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
        if hasattr(db, "get_user_ad_messages"):
            messages = db.get_user_ad_messages(uid, chat_id, limit=limit)
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
        keyboard.add(InlineKeyboardButton("一键解封", callback_data=f"ad_unban:{uid}:{chat_id}"))
        return keyboard
    except Exception as e:
        logger.debug(f"构建广告解封按钮失败: uid={uid} err={e}")
        return None


def _event_categories(evidence) -> list[str]:
    labels = {
        "money_promise": "收益承诺", "recruit": "招募引流",
        "adult_content": "成人招揽", "gray_industry": "灰产",
        "crypto_money": "资金/洗钱", "strong_contact": "明确联系方式",
        "contact_info": "联系方式", "marketing_contact": "私聊/客服引导",
        "profile_ad": "资料/Bio", "username_profile": "昵称/用户名",
        "external_blacklist": "外部反垃圾库", "personal_chat": "关联频道",
    }
    values = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", ""))
        label = labels.get(category, "")
        if label and label not in values:
            values.append(label)
    return values


def self_review_ad_event(bot, db, config: dict, event_id: str, actor_id: int,
                         ad_detector=None) -> dict:
    """本人整改后复检；任何高风险或未知状态都保持原处置。"""
    if not (config or {}).get("AD_SELF_UNBAN_ENABLED", False):
        return {"code": 403, "status": "disabled", "message": "自助复检暂未开放"}
    try:
        clicked = db.get_ad_enforcement_event(str(event_id))
    except Exception:
        clicked = None
    if not clicked:
        return {"code": 404, "status": "not_found", "message": "复检记录不存在或已清理"}
    root_id = str(clicked.get("root_event_id") or clicked.get("event_id") or "")
    claim = db.claim_ad_recheck(root_id, int(actor_id), cooldown_seconds=60, max_attempts=5)
    status = str(claim.get("status") or "")
    if status != "claimed":
        messages = {
            "not_owner": "只有被限制的账号本人可以操作",
            "expired": "按钮已超过24小时，请联系管理员",
            "resolved": "本次处置已经完成恢复",
            "attempts_exhausted": "本次复检次数已用完，请联系管理员",
            "not_found": "复检记录不存在或已清理",
        }
        if status == "rate_limited":
            wait = int(claim.get("retry_after") or 60)
            message = f"请等待{wait}秒后再复检"
        else:
            message = messages.get(status, "当前无法复检，请联系管理员")
        return {"code": 409 if status != "not_owner" else 403, "status": status, "message": message}

    event = claim.get("event") or clicked
    uid = int(event.get("user_id") or 0)
    # 卡片可能由 P1 在另一个群重申；恢复应以用户实际点击的卡片所在群为准。
    chat_id = int(clicked.get("chat_id") or event.get("chat_id") or 0)
    level = str(event.get("evidence_level") or "high")
    try:
        evidence = json.loads(event.get("evidence_json") or "[]")
    except Exception:
        evidence = []
    categories = {str(item.get("category", "")) for item in evidence if isinstance(item, dict)}
    if level not in {"low", "ambiguous"} or categories & {
        "adult_content", "gray_industry", "money_promise", "recruit", "crypto_money",
        "strong_contact", "external_blacklist", "profile_ad", "personal_chat",
    }:
        return {
            "code": 403, "status": "manual_review_required",
            "message": "该记录属于高风险或确证广告，需联系管理员复核",
        }

    # 同一账号存在其他未解决高风险根事件时，低风险卡不能绕过它。
    try:
        unresolved = db.list_unresolved_ad_events(uid) or []
        if any(
            str(item.get("event_id") or "") != root_id
            and str(item.get("evidence_level") or "high") == "high"
            for item in unresolved
        ):
            return {"code": 403, "status": "other_high_risk", "message": "仍有高风险记录未解决，请联系管理员"}
    except Exception:
        return {"code": 503, "status": "state_unknown", "message": "风险状态读取失败，请稍后再试"}

    try:
        chat_info = bot.get_chat(uid)
        from modules.ad_profile_signals import detect_profile_ad_signal
        profile = detect_profile_ad_signal(
            bot, chat_info, getattr(chat_info, "bio", "") or "", config or {}, chat_info=chat_info
        )
    except Exception as e:
        logger.warning(f"自助解封资料复检失败: uid={uid} err={e}")
        return {"code": 503, "status": "profile_unknown", "message": "当前资料读取失败，请稍后再试"}
    if profile.get("is_ad") or int(profile.get("score", 0) or 0) > 0:
        return {
            "code": 403, "status": "profile_not_clean",
            "message": "昵称、用户名、Bio、状态或关联频道仍有风险内容，请整改后再试",
        }

    if not ad_detector or not hasattr(ad_detector, "_check_cas"):
        return {"code": 503, "status": "external_unknown", "message": "外部反垃圾状态暂时无法确认，请稍后再试"}
    try:
        cas_banned, _cas_reason = ad_detector._check_cas(uid)
    except Exception as e:
        logger.warning(f"自助解封CAS复检失败: uid={uid} err={e}")
        return {"code": 503, "status": "external_unknown", "message": "外部反垃圾状态暂时无法确认，请稍后再试"}
    if cas_banned:
        return {"code": 403, "status": "external_blacklist", "message": "外部反垃圾库仍有记录，请联系管理员"}
    try:
        row = db.conn.execute("SELECT 1 FROM federation_bans WHERE user_id=? LIMIT 1", (uid,)).fetchone()
    except Exception:
        return {"code": 503, "status": "federation_unknown", "message": "联邦黑名单状态读取失败，请稍后再试"}
    if row:
        return {"code": 403, "status": "federation_ban", "message": "联邦黑名单仍有记录，请联系管理员"}

    restored = restore_ad_user(
        bot=bot, db=db, config=config or {}, chat_id=chat_id, uid=uid,
        actor_id=actor_id, ad_detector=ad_detector,
    )
    if restored.get("code") != 200:
        return {"code": 500, "status": "restore_not_verified", "message": "恢复未完全确认，请联系管理员"}
    return {
        "code": 200, "status": "restored",
        "message": "已恢复发言权限；历史被删除的消息无法恢复",
        "data": restored.get("data", {}),
    }


def self_review_ad_group_notice(bot, db, config: dict, notice_event_id: str,
                                actor_id: int, ad_detector=None) -> dict:
    """共享群卡入口：按点击者本人和卡片所在群定位其根事件。"""
    try:
        notice_event = db.get_ad_enforcement_event(str(notice_event_id))
    except Exception:
        notice_event = None
    if not notice_event or int(notice_event.get("expires_at") or 0) <= int(time.time()):
        return {"code": 404, "status": "expired", "message": "按钮已超过24小时，请联系管理员"}
    chat_id = int(notice_event.get("chat_id") or 0)
    try:
        actor_event = db.get_open_ad_root_event(int(actor_id), chat_id)
    except Exception:
        actor_event = None
    if not actor_event:
        return {
            "code": 404, "status": "not_found",
            "message": "你的账号在本群没有待复检的限制记录",
        }
    return self_review_ad_event(
        bot=bot, db=db, config=config, event_id=str(actor_event.get("event_id") or ""),
        actor_id=actor_id, ad_detector=ad_detector,
    )


def _derive_event_meta(reason: str, evidence=None, source_type: str = "detection",
                       reason_code: str = "", evidence_level: str = "") -> tuple[str, str]:
    categories = {str(item.get("category", "")) for item in (evidence or []) if isinstance(item, dict)}
    code = str(reason_code or "")
    level = str(evidence_level or "")
    if not code:
        code = "blacklist_reassert" if source_type == "blacklist_reassert" else "ad_detected"
    if not level:
        high = not (evidence or []) or bool(categories & {
            "money_promise", "recruit", "adult_content", "gray_industry", "crypto_money",
            "strong_contact", "external_blacklist", "profile_ad", "personal_chat",
        })
        level = "high" if high else "ambiguous"
    return code[:64], level[:16]


def _safe_event_reason(reason: str, evidence=None) -> str:
    categories = _event_categories(evidence)
    if categories:
        return "触发类别：" + "、".join(categories)
    value = str(reason or "")
    keyword_labels = (
        (("cas", "spb", "外部", "spamwatch"), "外部反垃圾库"),
        (("bio", "资料", "简介", "昵称", "用户名"), "账号资料"),
        (("emoji", "贴纸", "头像"), "头像或状态"),
        (("色情", "成人", "裸聊", "约炮"), "成人招揽"),
        (("灰产", "洗米", "跑分", "代收"), "灰产或资金风险"),
        (("收益", "日入", "日赚", "赚钱"), "收益承诺"),
        (("招募", "兼职", "招聘"), "招募引流"),
        (("私信", "私聊", "客服", "联系", "引流"), "联系方式或引流"),
    )
    lower = value.lower()
    for needles, label in keyword_labels:
        if any(item in lower for item in needles):
            return f"触发类别：{label}"
    return "广告检测规则命中"


def _create_enforcement_event(db, uid: int, chat_id: int, msg_id: int, reason: str,
                              evidence=None, source_type: str = "detection",
                              reason_code: str = "", evidence_level: str = ""):
    if not db or not hasattr(db, "create_ad_enforcement_event"):
        return None
    try:
        root = db.get_open_ad_root_event(uid) if source_type == "blacklist_reassert" else None
        parent_id = ""
        root_id = ""
        event_evidence = evidence or []
        event_reason = _safe_event_reason(reason, event_evidence)
        code, level = _derive_event_meta(
            event_reason, event_evidence, source_type, reason_code, evidence_level
        )
        if root:
            root_id = str(root.get("root_event_id") or root.get("event_id") or "")
            parent_id = str(root.get("event_id") or "")
            # 重复 P1 只关联首次事件，播报和账本都保留原始根因。
            if source_type == "blacklist_reassert":
                event_reason = str(root.get("reason_summary") or event_reason)
                code = str(root.get("reason_code") or code)
                level = str(root.get("evidence_level") or level)
                try:
                    event_evidence = json.loads(root.get("evidence_json") or "[]")
                except Exception:
                    event_evidence = []
        return db.create_ad_enforcement_event(
            user_id=uid, chat_id=chat_id, source_message_id=msg_id,
            source_type=source_type, reason_code=code, reason_summary=event_reason,
            evidence_level=level, evidence=event_evidence, root_event_id=root_id,
            parent_event_id=parent_id, expires_at=int(time.time()) + 86400,
        )
    except Exception as e:
        logger.warning(f"创建广告处置事件失败: uid={uid} chat={chat_id} err={e}")
        return None


def _build_self_review_markup(event_id: str, shared_group: bool = False):
    try:
        from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup()
        callback_prefix = "ad_group_review" if shared_group else "ad_self_review"
        keyboard.row(
            InlineKeyboardButton("🔓 已整改，本人复检解封", callback_data=f"{callback_prefix}:{event_id}"),
            InlineKeyboardButton("👤 联系管理员", url="https://t.me/Moryfansbot"),
        )
        return keyboard
    except Exception as e:
        logger.debug(f"构建自助复检按钮失败: event={event_id} err={e}")
        return None


def _send_self_review_notice(bot, db, config: dict, event: dict, uid: int, uname: str) -> int:
    if not (config or {}).get("AD_SELF_UNBAN_ENABLED", False) or not event:
        return 0
    # 确证广告静默处置；群内自助卡只服务于存在误判可能的低风险/歧义事件。
    if str(event.get("evidence_level") or "high") not in {"low", "ambiguous"}:
        return 0
    chat_id = int(event.get("chat_id") or 0)
    try:
        claim = db.claim_ad_group_notice(str(event.get("event_id") or ""), chat_id)
        if claim.get("status") == "existing":
            return int(claim.get("notice_message_id") or 0)
        if claim.get("status") != "claimed":
            return 0
    except Exception as e:
        logger.warning(f"占用群级处置说明卡失败: uid={uid} chat={chat_id} err={e}")
        return 0
    text = (
        "⚠️ <b>疑似广告限制 · 可自助复检</b>\n\n"
        "本卡只用于证据存在歧义、可能误判的限制。被限制者请先清理消息、昵称、用户名、Bio "
        "和关联频道中的广告或联系方式，再由本人点击下方复检。\n\n"
        "复检干净会自动恢复；仍有风险内容请整改或联系管理员。"
    )
    try:
        sent = bot.send_message(
            chat_id, text, parse_mode="HTML",
            reply_markup=_build_self_review_markup(
                str(event.get("event_id") or ""), shared_group=True
            ),
        )
        message_id = int(getattr(sent, "message_id", 0) or 0)
        if message_id:
            db.set_ad_event_notice(str(event.get("event_id")), message_id)
            if hasattr(db, "track_bot_message"):
                db.track_bot_message(chat_id, message_id)
        return message_id
    except Exception as e:
        try:
            db.set_ad_event_notice(str(event.get("event_id") or ""), 0)
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
        logger.warning(f"发送广告处置说明卡失败: uid={uid} chat={chat_id} err={e}")
        return 0


def _notify_admin(
    bot,
    config: dict,
    chat_id: int,
    uid: int,
    uname: str,
    reason: str,
    deleted_count: int,
    muted: bool,
    blacklisted: bool = False,
    reactions_cleaned: bool = False,
):
    """通知管理员广告处置结果（v5.31.7 卡片化）。"""
    admin_id = config.get("ADMIN_ID", 0)
    if not admin_id:
        return
    try:
        from core.broadcast_formatter import build_alert_card_html
        body = (
            f"👤 用户：{format_user_mention(uid, uname)}\n"
            f"📋 操作：永久禁言 + 加黑名单 + 删除消息\n"
            f"🗑 删除消息：{deleted_count}条\n"
            f"🧹 清理反应：{'已尝试' if reactions_cleaned else '未执行/不支持'}\n"
            f"🔇 永久禁言：{'成功' if muted else '失败'}\n"
            f"🗄 黑名单事务：{'成功' if blacklisted else '失败'}\n"
            f"🎯 原因：{reason[:200]}"
        )
        completed = muted and blacklisted
        card = build_alert_card_html(
            title="广告账号已处理" if completed else "广告处置未完全成功",
            body=body,
            level="danger" if completed else "warning",
            footer=f"chat_id={chat_id} uid={uid}",
        )
        bot.send_message(
            admin_id,
            card,
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
    current_message_is_ad: bool = False,
    notify_admin: bool = True,
    evidence=None,
    source_type: str = "detection",
    reason_code: str = "",
    evidence_level: str = "",
) -> dict:
    """统一广告账号处置入口。

    账号证据与逐条消息证据严格分离：资料/Bio/黑名单命中可禁言并删除当前
    发言，但只有内容规则明确命中时，调用方才传 ``current_message_is_ad=True``。
    """
    reason = str(reason or "广告检测")
    # 【v5.38.22】配置级白名单豁免前置（零网络）：ADMIN_IDS/ADMIN_ID 命中直接跳过，
    # 不依赖 get_chat_member 网络查询，避免查询失败/网络抖动时仍可能误处置配置管理员
    if uid in _admin_ids(config):
        logger.warning(
            f"广告检测命中配置管理员(ADMIN_IDS/ADMIN_ID)，跳过全部处置: uid={uid} chat={chat_id} reason={reason}"
        )
        return _admin_skip_result(uid, chat_id, "admin_or_creator")
    # AD_WHITELIST 配置白名单（零网络，与检测层一致）
    wl_cfg = (config or {}).get("AD_WHITELIST", {}) or {}
    raw_wl = wl_cfg.get("user_ids", []) if isinstance(wl_cfg, dict) else []
    for item in (raw_wl or []):
        try:
            if int(item) == int(uid):
                logger.warning(
                    f"广告检测命中 AD_WHITELIST，跳过全部处置: uid={uid} chat={chat_id} reason={reason}"
                )
                return _admin_skip_result(uid, chat_id, "whitelist")
        except (TypeError, ValueError):
            continue
    if not current_msg_id and message is not None:
        current_msg_id = getattr(message, "message_id", 0) or 0
    # 【v5.38.21】群管/群主豁免：禁言、黑名单、删消息只针对普通成员，避免误封管理
    admin_status = _is_chat_admin_member(bot, chat_id, uid)
    if admin_status == "admin":
        logger.warning(
            f"广告检测命中群管/群主，跳过全部处置: uid={uid} chat={chat_id} reason={reason}"
        )
        return _admin_skip_result(uid, chat_id, "admin_or_creator")
    if admin_status == "unknown":
        # 【v5.38.22】群管身份查询失败三态降级：保留证据并通知人工复核，
        # 但跳过禁言/黑名单/删消息等不可逆惩罚，避免误封群管
        evidence_persisted = False
        if current_message_is_ad:
            evidence_persisted = _mark_current_message_ad(db, chat_id, current_msg_id)
        if notify_admin:
            _notify_admin(
                bot, config or {}, chat_id, uid, uname or str(uid), reason, 0, False,
                blacklisted=False,
            )
        logger.warning(
            f"广告检测命中但群管身份查询失败，跳过惩罚等待人工复核: uid={uid} chat={chat_id} "
            f"reason={reason} evidence_persisted={evidence_persisted}"
        )
        return _admin_skip_result(uid, chat_id, "admin_query_failed")
    evidence_persisted = False
    if current_message_is_ad:
        evidence_persisted = _mark_current_message_ad(db, chat_id, current_msg_id)
    event = _create_enforcement_event(
        db, uid, chat_id, current_msg_id, reason, evidence=evidence,
        source_type=source_type, reason_code=reason_code, evidence_level=evidence_level,
    )
    deleted_count = _cleanup_user_messages(bot, db, config or {}, uid, chat_id, current_msg_id)
    muted = _mute_forever(bot, db, chat_id, uid, reason)
    reactions_cleaned = _cleanup_user_reactions(bot, config or {}, uid, chat_id)
    persist_reason = (
        str((event or {}).get("reason_summary") or reason)
        if source_type == "blacklist_reassert" else reason
    )
    blacklisted = _persist_ad_state(bot, db, chat_id, uid, persist_reason, muted)
    if event and hasattr(db, "set_ad_event_enforcement"):
        try:
            db.set_ad_event_enforcement(
                str(event.get("event_id")), muted, blacklisted, deleted_count,
                "completed" if muted and blacklisted else "incomplete",
            )
            event = db.get_ad_enforcement_event(str(event.get("event_id"))) or event
        except Exception as e:
            logger.warning(f"更新广告处置事件结果失败: uid={uid} err={e}")
    if notify_admin:
        _notify_admin(
            bot,
            config or {},
            chat_id,
            uid,
            uname or str(uid),
            reason,
            deleted_count,
            muted,
            blacklisted=blacklisted,
            reactions_cleaned=reactions_cleaned,
        )
    notice_message_id = _send_self_review_notice(
        bot, db, config or {}, event or {}, uid, uname or str(uid)
    ) if muted and blacklisted else 0
    logger.warning(
        f"广告账号处置完成: uid={uid} chat={chat_id} "
        f"muted={muted} blacklisted={blacklisted} deleted={deleted_count} reactions_cleaned={reactions_cleaned}"
    )

    # [Puzan-OS v5.32] 处置后给群内 AI 上下文说明（默认关闭，开启 AD_AI_AUTO_REPLY_ENABLED 才生效）
    # 避免群里其他用户看到广告被删后困惑，AI 自然地说一句"清了个广告"
    if (config or {}).get("AD_AI_AUTO_REPLY_ENABLED", False) and chat_id and chat_id < 0:
        try:
            from modules.ai_advisor import explain_enforcement_to_chat
            explain_enforcement_to_chat(
                bot=bot,
                chat_id=chat_id,
                uname=uname or str(uid),
                reason=reason,
                config=config or {},
            )
        except Exception as e:
            logger.debug(f"群内说明发送失败（不影响处置）: uid={uid} err={e}")

    return {
        "code": 200 if muted and blacklisted else 500,
        "data": {
            "uid": uid,
            "chat_id": chat_id,
            "muted": muted,
            "blacklisted": blacklisted,
            "deleted_count": deleted_count,
            "evidence_persisted": evidence_persisted,
            "reactions_cleaned": reactions_cleaned,
            "event_id": str((event or {}).get("event_id") or ""),
            "root_event_id": str((event or {}).get("root_event_id") or ""),
            "notice_message_id": notice_message_id,
        },
        "msg": "success" if muted and blacklisted else "enforcement_incomplete",
    }
