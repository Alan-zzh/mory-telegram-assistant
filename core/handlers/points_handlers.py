# -*- coding: utf-8 -*-
"""
积分处理器 - P2 优先级积分/活跃度相关处理

包含：
- P2 积分更新逻辑（含每日上限）
- P2 等级提升检查
- P2 群ID自动记录
- P2.2 消息缓存（反撤回）
- P2.5 AFK自动解除
- P2.6 检查@提及/回复的用户是否AFK
- P3.8 发言统计计数
- 任务完成度检查（speech5/speech10）
"""

from core.logging_util import get_logger

logger = get_logger("points_handlers")


def update_points_and_activity(dctx) -> bool:
    """P2 更新用户活跃度 / 群ID / 积分（原子操作，防竞态）

    注意：此函数始终返回 False（不终止分发），仅做数据更新
    """
    from modules.points_enhanced import check_level_up

    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_priv = dctx.is_priv
    is_group = dctx.is_group

    # 积分获取规则配置化 + 每日上限
    _points_rules = CONFIG.get("POINTS_RULES", {})
    _speech_pts = _points_rules.get("speech", 1)
    _daily_limit = _points_rules.get("daily_limit", 50)
    if is_group and _daily_limit > 0:
        _today_speech_pts = db.get_today_speech_points(uid)
        if _today_speech_pts >= _daily_limit:
            _speech_pts = 0  # 达到每日上限，不再获取发言积分

    _level_result = db.upsert_user_with_points(uid, uname, "private" if is_priv else "group", pts=_speech_pts)

    # 检查升级通知
    if _speech_pts > 0:
        check_level_up(bot, chat_id, uid, uname, _level_result, CONFIG)

    # 自动记录群ID（只在未设置时才记录，已设置过的不覆盖）
    if is_group:
        gid = CONFIG.get("GROUP_ID", 0)
        if gid == 0:
            CONFIG["GROUP_ID"] = chat_id
            ctx.save_config()

    return False


def cache_message_for_antidelete(dctx) -> bool:
    """P2.2 消息缓存（反撤回）

    注意：此函数始终返回 False（不终止分发），仅做缓存
    """
    try:
        from modules.antidelete import cache_message

        m = dctx.msg
        chat_id = dctx.chat_id
        uid = dctx.uid

        if m.text or m.caption:
            content = m.text or m.caption or ""
            cache_message(chat_id, m.message_id, uid, m.from_user.first_name or "", content[:500], m.content_type)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return False


def handle_afk_status(dctx) -> bool:
    """P2.5 AFK自动解除 + P2.6 检查@提及/回复的用户是否AFK

    注意：此函数始终返回 False（不终止分发），仅做AFK状态更新
    """
    if not dctx.is_group:
        return False

    from modules.afk import check_afk_on_message, check_afk_mention

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    chat_id = dctx.chat_id

    # P2.5：AFK自动解除（用户发言时自动取消AFK状态）
    try:
        check_afk_on_message(bot, m, CONFIG, db)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # P2.6：检查@提及/回复的用户是否AFK
    try:
        entities = m.entities or []
        for ent in entities:
            if ent.type == "text_mention" and ent.user:
                check_afk_mention(bot, m, CONFIG, db, ent.user.id)
            elif ent.type == "mention":
                mention_text = m.text[ent.offset:ent.offset + ent.length]
                try:
                    username = mention_text.lstrip("@")
                    chat_member = bot.get_chat_member(chat_id, username)
                    if chat_member and chat_member.user:
                        check_afk_mention(bot, m, CONFIG, db, chat_member.user.id)
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # 检查回复的用户是否AFK
    if m.reply_to_message and m.reply_to_message.from_user and not m.reply_to_message.from_user.is_bot:
        try:
            check_afk_mention(bot, m, CONFIG, db, m.reply_to_message.from_user.id)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    return False


def update_speech_stats(dctx) -> bool:
    """P3.8 发言统计计数 + 任务完成度检查（speech5/speech10）

    注意：此函数始终返回 False（不终止分发），仅做统计更新
    """
    if not dctx.is_group:
        return False

    from modules.speech_stats import increment_speech_count
    from modules.daily_quest import get_quest_progress, check_quest_completion

    db = dctx.ctx.db
    bot = dctx.ctx.bot
    CONFIG = dctx.ctx.config
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id

    try:
        increment_speech_count(db, uid, chat_id)
        # 检查发言任务完成
        try:
            progress = get_quest_progress(db, uid, "speech5", CONFIG)
            if progress >= 5:
                check_quest_completion(db, uid, "speech5", CONFIG, bot, chat_id, uname)
            progress = get_quest_progress(db, uid, "speech10", CONFIG)
            if progress >= 10:
                check_quest_completion(db, uid, "speech10", CONFIG, bot, chat_id, uname)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return False
