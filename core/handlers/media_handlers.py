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

logger = get_logger("media_handlers")


def register_media_handlers(bot, ctx):
    """注册媒体与频道处理器到bot实例"""

    # ── 图片处理（打码+识图）───────────────────────────────────────────
    @bot.message_handler(content_types=["photo"])
    def on_photo(m):
        try:
            from modules.content import handle_photo
            handle_photo(bot, m, ctx.config, ctx.mory_bot, ctx.ai)
        except Exception as e:
            logger.error(f"图片处理异常：{e}")

    # ── 语音消息：自动转发给管理员 + 尝试AI识别回复 ────────────────
    @bot.message_handler(content_types=["voice"])
    def on_voice(m):
        try:
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
        ctx.db.track_channel_post(cid, m.message_id, int(m.date.timestamp()), views, forwards, content_type)
        logger.info(f"📺 频道帖子捕获: chat_id={cid} msg_id={m.message_id} views={views} type={content_type}")

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
