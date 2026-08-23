# -*- coding: utf-8 -*-
"""
媒体与频道处理器 - 处理图片、语音、频道帖子、退群等消息

包含：
- on_photo 处理器（图片消息）
- on_voice 处理器（语音消息）
- 频道帖子捕获处理器（新帖 + 编辑帖）
- left_chat_member 处理器（退群）
"""

from core.logging_util import get_logger
from core.helpers import format_user_mention
from core.telegram_send_utils import delete_all_message_reactions_compat, delete_message_reaction_compat

logger = get_logger("media_handlers")


def _handle_trusted_channel_forward(bot, m, ctx) -> bool:
    """自有频道媒体转发走可信联动并终止普通媒体/广告管线。"""
    try:
        from modules.linked_channel_sync import handle_group_forward
        return bool(handle_group_forward(bot, m, ctx.config, db=ctx.db))
    except Exception as e:
        logger.warning(f"自有频道媒体联动异常: {e}")
        return False


def register_media_handlers(bot, ctx):
    """注册媒体与频道处理器到bot实例"""

    def _is_private_blacklisted(m) -> bool:
        """私聊黑名单用户的媒体消息不再中继或触发 AI。"""
        if getattr(getattr(m, "chat", None), "type", "") != "private":
            return False
        uid = getattr(getattr(m, "from_user", None), "id", 0) or 0
        if not uid or not getattr(ctx, "db", None):
            return False
        try:
            admin_ids = set((ctx.config or {}).get("ADMIN_IDS", []) or [])
            admin_id = (ctx.config or {}).get("ADMIN_ID", 0)
            if admin_id:
                admin_ids.add(admin_id)
            if uid in admin_ids:
                return False
            if ctx.db.is_blacklisted(uid):
                logger.info(f"🚫 黑名单私聊媒体拦截: uid={uid} type={getattr(m, 'content_type', '')}")
                return True
        except Exception as e:
            logger.debug(f"私聊媒体黑名单检查失败 uid={uid}: {e}")
        return False

    def _relay_private_media(m, note: str) -> bool:
        """私聊媒体消息立即转给管理员，便于管理员直接回复。"""
        if m.chat.type != "private" or not ctx.config.get("RELAY_MODE_ENABLED", False):
            return False
        try:
            from core.handlers.relay_handler import relay_original_message_to_admin
            return relay_original_message_to_admin(
                bot, ctx.db, ctx.config, m, source_type="private", note=note
            )
        except Exception as relay_err:
            logger.debug(f"媒体中继失败（静默）: {relay_err}")
            return False

    def _group_media_security_block(m) -> bool:
        """群媒体安全预检：黑名单 + caption 广告。命中处置返回 True（阻断后续）。"""
        chat = getattr(m, "chat", None)
        if not chat or getattr(chat, "type", "") not in ("group", "supergroup"):
            return False
        # 视频/图片等由专用 handler 先于主分发器消费，必须在这里复用 P0.1。
        # 只有 CHANNEL_IDS 中的自有频道可命中；其他频道继续走广告/反频道治理。
        if _handle_trusted_channel_forward(bot, m, ctx):
            return True
        uid = getattr(getattr(m, "from_user", None), "id", 0) or 0
        if not uid:
            return False
        try:
            admin_ids = set((ctx.config or {}).get("ADMIN_IDS", []) or [])
            admin_id = (ctx.config or {}).get("ADMIN_ID", 0)
            if admin_id:
                admin_ids.add(admin_id)
            if uid in admin_ids:
                return False
            if ctx.db and ctx.db.is_blacklisted(uid):
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=ctx.db,
                    config=ctx.config,
                    chat_id=chat.id,
                    uid=uid,
                    uname=getattr(m.from_user, "first_name", "") or str(uid),
                    reason="黑名单用户媒体消息",
                    message=m,
                    current_msg_id=getattr(m, "message_id", 0),
                    current_message_is_ad=True,
                    notify_admin=False,
                )
                return True
            caption = (getattr(m, "caption", None) or "").strip()
            from modules.ad_detector import AdDetector
            ad_text = AdDetector.extract_message_ad_text(m, caption)
            if not ad_text:
                return False
            # 复用文本消息的完整广告链，避免媒体入口使用错误 detect 参数签名后静默放行。
            from types import SimpleNamespace
            from core.handlers.security_handlers import check_ad_detection
            dctx = SimpleNamespace(
                ctx=ctx,
                msg=m,
                uid=uid,
                uname=(getattr(m.from_user, "first_name", "") or str(uid)),
                chat_id=chat.id,
                is_group=True,
                is_priv=False,
                text=ad_text,
            )
            return bool(check_ad_detection(dctx))
        except Exception as e:
            logger.warning(f"群媒体安全预检异常: {e}")
        return False

    # ── 图片处理（打码+识图）───────────────────────────────────────────
    @bot.message_handler(content_types=["photo"])
    def on_photo(m):
        try:
            if _is_private_blacklisted(m):
                return
            if _group_media_security_block(m):
                return
            _relay_private_media(m, "🖼️ 私聊图片")
            from modules.content import handle_photo
            handle_photo(bot, m, ctx.config, ctx.mory_bot, ctx.ai)
        except Exception as e:
            logger.error(f"图片处理异常：{e}")

    # ── 语音消息：自动转发给管理员 + 尝试AI识别回复 ────────────────
    @bot.message_handler(content_types=["voice"])
    def on_voice(m):
        try:
            if _is_private_blacklisted(m):
                return
            uid = m.from_user.id
            uname = m.from_user.first_name or "神秘人"
            chat_id = m.chat.id
            is_priv = m.chat.type == "private"

            # 获取语音文件信息
            file_info = bot.get_file(m.voice.file_id)
            duration = getattr(m.voice, 'duration', 0)  # 秒

            # 转发给管理员
            admin_id = ctx.config.get("ADMIN_ID", 0)
            # 仅私聊语音转发给管理员
            if admin_id and is_priv:
                try:
                    if ctx.config.get("RELAY_MODE_ENABLED", False):
                        _relay_private_media(m, f"🎤 私聊语音\n⏱ 时长: {duration}秒")
                    else:
                        bot.forward_message(admin_id, chat_id, m.message_id,
                                            disable_notification=True)
                        bot.send_message(admin_id,
                            f"🎤 语音通知\n👤 {format_user_mention(uid, uname)} 发来一条语音"
                            f"\n⏱ 时长: {duration}秒\n💬 来源: {'私聊' if is_priv else '群聊'}",
                            parse_mode="HTML")
                    logger.info(f"🎤 语音转发: uid={uid} duration={duration}s")
                except Exception as e:
                    logger.error(f"🎤 语音转发失败: {e}")

            # 私聊中尝试用AI回复（提示用户可以发文字）
            if is_priv:
                resp = ctx.ai.ask("对方发了一条语音消息，你听不见，用俏皮的方式让他发文字给你", mode="normal")
                if resp:
                    bot.send_message(chat_id, resp)

        except Exception as e:
            logger.error(f"语音处理异常：{e}")

    @bot.message_handler(content_types=["video", "document", "audio", "sticker"])
    def on_private_media(m):
        """群媒体安全预检 + 私聊附件中继。"""
        try:
            if _is_private_blacklisted(m):
                return
            if _group_media_security_block(m):
                return
            note_map = {
                "video": "🎬 私聊视频",
                "document": "📎 私聊文件",
                "audio": "🎵 私聊音频",
                "sticker": "🙂 私聊贴纸",
            }
            _relay_private_media(m, note_map.get(getattr(m, "content_type", ""), "📦 私聊附件"))
        except Exception as e:
            logger.error(f"私聊附件中继异常：{e}")

    # ── 流失打捞（退群）─────────────────────────────────────────────────
    @bot.message_handler(content_types=["left_chat_member"])
    def on_left(m):
        try:
            from modules.group_mgr import handle_left_member
            handle_left_member(bot, m, ctx.config, ctx.db)
        except Exception as e:
            logger.error(f"流失打捞异常：{e}")

    # ── 频道帖子实时捕获 ──────────────────────────────────────────────
    @bot.channel_post_handler(func=lambda m: True)
    def on_channel_post(m):
        """捕获频道新帖，记录到 channel_posts 表"""
        cid = m.chat.id
        # 仅处理配置中的目标频道
        channel_ids = ctx.config.get("CHANNEL_IDS", [])
        target_ids = set()
        for ch in channel_ids:
            target_ids.add(ch.get("id", 0) if isinstance(ch, dict) else ch)
        if cid not in target_ids:
            return
        views = getattr(m, 'views', 0) or 0
        forwards = getattr(m, 'forward_count', 0) or 0
        content_type = m.content_type if hasattr(m, 'content_type') else "text"
        content_type = m.content_type if hasattr(m, 'content_type') else "text"
        ctx.db.track_channel_post(cid, m.message_id, int(m.date.timestamp()), views, forwards, content_type)
        logger.info(f"📺 频道帖子捕获: chat_id={cid} msg_id={m.message_id} views={views} type={content_type}")
        # 关联频道联动（点赞 + 登记自动评论），默认关闭
        try:
            from modules.linked_channel_sync import handle_channel_post
            handle_channel_post(bot, m, ctx.config, db=ctx.db)
        except Exception as e:
            logger.debug(f"关联频道联动（点赞/评论登记）异常: {e}")

    # ── 频道帖子编辑事件捕获 ──────────────────────────────────────────
    @bot.edited_channel_post_handler(func=lambda m: True)
    def on_edited_channel_post(m):
        """捕获频道帖子编辑事件，更新浏览量"""
        cid = m.chat.id
        channel_ids = ctx.config.get("CHANNEL_IDS", [])
        target_ids = set()
        for ch in channel_ids:
            target_ids.add(ch.get("id", 0) if isinstance(ch, dict) else ch)
        if cid not in target_ids:
            return
        views = getattr(m, 'views', 0) or 0
        forwards = getattr(m, 'forward_count', 0) or 0
        ctx.db.update_channel_post_views(cid, m.message_id, views, forwards)
        logger.debug(f"📺 频道帖子浏览量更新: chat_id={cid} msg_id={m.message_id} views={views}")

    try:
        @bot.message_reaction_handler(func=lambda update: True)
        def on_message_reaction(update):
            """处理 Telegram 反应事件，清理黑名单用户留下的反应。"""
            try:
                _handle_message_reaction_update(bot, update, ctx.config, ctx.db)
            except Exception as e:
                logger.debug(f"消息反应处理异常: {e}")

        @bot.message_reaction_count_handler(func=lambda update: True)
        def on_message_reaction_count(update):
            """反应计数事件目前只做轻量观测，避免高频写库。"""
            try:
                chat_id = getattr(getattr(update, "chat", None), "id", 0)
                message_id = getattr(update, "message_id", 0)
                reactions = getattr(update, "reactions", []) or []
                total = sum(int(getattr(item, "total_count", 0) or 0) for item in reactions)
                logger.debug(f"消息反应计数: chat={chat_id} msg={message_id} total={total}")
            except Exception as e:
                logger.debug(f"消息反应计数处理异常: {e}")
    except (AttributeError, TypeError):
        logger.info("message_reaction_handler 不可用，跳过反应治理")


def _handle_message_reaction_update(bot, update, config: dict, db) -> bool:
    """清理黑名单用户新增反应，返回 True 表示已尝试处理。"""
    if not (config or {}).get("AD_CLEANUP_REACTIONS", True):
        return False

    user = getattr(update, "user", None)
    if not user:
        return False
    uid = getattr(user, "id", 0) or 0
    if not uid or not db or not hasattr(db, "is_blacklisted"):
        return False

    try:
        if not db.is_blacklisted(uid):
            return False
    except Exception as e:
        logger.debug(f"反应黑名单检查失败: uid={uid} err={e}")
        return False

    new_reaction = getattr(update, "new_reaction", []) or []
    if not new_reaction:
        return False

    chat_id = getattr(getattr(update, "chat", None), "id", 0) or 0
    message_id = getattr(update, "message_id", 0) or 0
    if not chat_id or not message_id:
        return False

    ok = False
    try:
        ok = bool(delete_message_reaction_compat(bot, chat_id, message_id, user_id=uid))
    except Exception as e:
        logger.debug(f"删除黑名单用户单条反应失败: chat={chat_id} msg={message_id} uid={uid} err={e}")
    if not ok:
        try:
            ok = bool(delete_all_message_reactions_compat(bot, chat_id, user_id=uid))
        except Exception as e:
            logger.debug(f"删除黑名单用户全部反应失败: chat={chat_id} uid={uid} err={e}")

    logger.info(f"黑名单用户反应清理: chat={chat_id} msg={message_id} uid={uid} ok={ok}")
    return True
