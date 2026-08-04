# -*- coding: utf-8 -*-
"""
广告账号统一处置：不踢人，只永久禁言、删消息、双黑名单。
"""

from core.helpers import format_user_mention
from core.logging_util import get_logger
from core.telebot_compat import delete_all_message_reactions_compat, restrict_chat_member_compat

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
            logger.debug(f"广告消息已不存在: chat={chat_id} msg={msg_id}")
            status = "already_absent"
            should_mark_deleted = True
        else:
            logger.debug(f"删除广告消息失败: chat={chat_id} msg={msg_id} err={e}")
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


def _mute_forever(bot, db, chat_id: int, uid: int, reason: str = "广告检测") -> bool:
    """永久禁言广告账号，不踢出群。同步写入 mute_records 表。"""
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
        # 【v5.31.6 修复】禁封时写入 mute_records，与解封时清理 mute_records 对称
        if db is not None:
            try:
                db.conn.execute(
                    "INSERT OR REPLACE INTO mute_records "
                    "(uid, chat_id, mute_until, reason) VALUES (?,?,?,?)",
                    (uid, chat_id, 0, reason),
                )
                db.conn.commit()
            except Exception as me:
                logger.debug(f"写入 mute_records 失败（不影响禁言）: uid={uid} err={me}")
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
            local_result = db.blacklist_add(uid, reason)
            if local_result is False:
                ok = False
                logger.warning(f"写入本地blacklist返回失败: uid={uid}")
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
    # 【v5.31.7】解封后通知管理员（卡片化），与禁封通知对称
    try:
        admin_id = (config or {}).get("ADMIN_ID", 0)
        if admin_id:
            from core.broadcast_formatter import build_alert_card_html
            body = (
                f"👤 用户：{format_user_mention(uid, str(uid))}\n"
                f"📋 操作：移除黑名单 + 恢复权限 + 清理追踪\n"
                f"🔓 权限恢复：{'成功' if restored else '失败'}\n"
                f"🧹 追踪清理：{'成功' if tracking_cleared else '失败'}\n"
                f"👨‍⚖️ 操作者：{actor_id}"
            )
            card = build_alert_card_html(
                title="广告误封已解封",
                body=body,
                level="success",
                footer=f"chat_id={chat_id} uid={uid}",
            )
            bot.send_message(admin_id, card, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"解封通知管理员失败: uid={uid} err={e}")
    # 【v5.31.7】Ephemeral Messages 接入：给被解封用户发群内私密通知（Bot API 10.2）
    # 默认关闭，开启 EPHEMERAL_MESSAGE_ENABLED 后生效。被禁言用户可见性官方未明示，
    # 仅在已解封（restored=True）后发送，确保用户已恢复发言权限。
    if (config or {}).get("EPHEMERAL_MESSAGE_ENABLED", False) and restored and chat_id:
        try:
            from core.telebot_compat import send_ephemeral_message_compat
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
    # 【v5.31.6 修复】返回码以 removed（黑名单移除）为核心判断，
    # restored 和 tracking_cleared 是辅助操作，失败在 data 中反映但不影响主返回码
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


def _notify_admin(bot, config: dict, chat_id: int, uid: int, uname: str, reason: str, deleted_count: int, muted: bool, reactions_cleaned: bool = False):
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
            f"🎯 原因：{reason[:200]}"
        )
        card = build_alert_card_html(
            title="广告账号已处理",
            body=body,
            level="danger",
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
            _notify_admin(bot, config or {}, chat_id, uid, uname or str(uid), reason, 0, False)
        logger.warning(
            f"广告检测命中但群管身份查询失败，跳过惩罚等待人工复核: uid={uid} chat={chat_id} "
            f"reason={reason} evidence_persisted={evidence_persisted}"
        )
        return _admin_skip_result(uid, chat_id, "admin_query_failed")
    evidence_persisted = False
    if current_message_is_ad:
        evidence_persisted = _mark_current_message_ad(db, chat_id, current_msg_id)
    deleted_count = _cleanup_user_messages(bot, db, config or {}, uid, chat_id, current_msg_id)
    muted = _mute_forever(bot, db, chat_id, uid, reason)
    reactions_cleaned = _cleanup_user_reactions(bot, config or {}, uid, chat_id)
    blacklisted = _write_blacklists(bot, db, uid, reason)
    if notify_admin:
        _notify_admin(bot, config or {}, chat_id, uid, uname or str(uid), reason, deleted_count, muted, reactions_cleaned)
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
        "code": 200,
        "data": {
            "uid": uid,
            "chat_id": chat_id,
            "muted": muted,
            "blacklisted": blacklisted,
            "deleted_count": deleted_count,
            "evidence_persisted": evidence_persisted,
            "reactions_cleaned": reactions_cleaned,
        },
        "msg": "success",
    }
