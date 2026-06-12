# -*- coding: utf-8 -*-
"""
反刷屏处理器 - P4 优先级反刷屏/限流相关处理

包含：
- P4 反刷屏机制（check_spam）
- P4 反刷屏检测（antiflood + 白名单豁免）
- 反频道转发检测
- NSFW图片检测
- P4.5 消息锁（锁群/消息类型限制）
- P4.6 慢速模式
- P4.7 服务消息自动清理
"""

from core.logging_util import get_logger, clear_logging_context

logger = get_logger("flood_handlers")


def check_antiflood(dctx) -> bool:
    """P4 反刷屏检测（antiflood + 白名单豁免）

    返回 True 表示用户刷屏被拦截，应终止分发
    """
    if not dctx.is_group or dctx.is_priv:
        return False

    from modules.antiflood import check_antiflood, handle_flood_user
    from modules.approvals import is_approved

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    chat_id = dctx.chat_id
    uid = dctx.uid

    try:
        if check_antiflood(bot, m, CONFIG, db):
            # 白名单用户豁免
            if not is_approved(db, chat_id, uid):
                handle_flood_user(bot, m, CONFIG, db)
                clear_logging_context()
                return True
    except Exception:
        pass

    return False


def check_anti_channel(dctx) -> bool:
    """反频道转发检测

    返回 True 表示频道转发消息被拦截
    """
    if not dctx.is_group or dctx.is_priv:
        return False

    from modules.anti_channel import check_anti_channel

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    try:
        if check_anti_channel(bot, m, CONFIG, db):
            clear_logging_context()
            return True
    except Exception:
        pass

    return False


def check_nsfw(dctx) -> bool:
    """NSFW图片检测

    返回 True 表示NSFW图片被拦截
    """
    m = dctx.msg
    if not dctx.is_group or dctx.is_priv:
        return False

    # 只检测图片消息
    if not (m.photo or (m.document and m.document.mime_type and m.document.mime_type.startswith("image/"))):
        return False

    from modules.nsfw_detect import check_nsfw_image

    bot = dctx.ctx.bot
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    try:
        if check_nsfw_image(bot, m, CONFIG, db):
            clear_logging_context()
            return True
    except Exception:
        pass

    return False


def check_spam(dctx) -> bool:
    """P4 反刷机制（group_mgr.check_spam）

    返回 True 表示刷屏被拦截
    """
    if not dctx.is_group:
        return False

    from modules.group_mgr import check_spam

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    if check_spam(bot, m, CONFIG, db):
        clear_logging_context()
        return True
    return False


def check_message_lock(dctx) -> bool:
    """P4.5 锁群/消息类型限制检测

    管理员和白名单用户豁免
    返回 True 表示消息被锁群拦截
    """
    if not dctx.is_group or dctx.is_priv:
        return False

    from modules.message_locks import check_message_lock
    from modules.approvals import is_approved

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    uid = dctx.uid
    chat_id = dctx.chat_id

    try:
        admin_ids = _get_admin_ids(CONFIG)
        if uid not in admin_ids and not is_approved(db, chat_id, uid) and check_message_lock(bot, m, CONFIG, db):
            if CONFIG.get("ENABLE_MESSAGE_DELETION", False):
                try:
                    bot.delete_message(chat_id, m.message_id)
                except Exception:
                    pass
            else:
                logger.warning(f"[消息锁] ENABLE_MESSAGE_DELETION 未开启，跳过删除消息")
            clear_logging_context()
            return True
    except Exception:
        pass

    return False


def check_slow_mode(dctx) -> bool:
    """P4.6 慢速模式检测

    管理员豁免
    返回 True 表示消息被慢速模式拦截
    """
    if not dctx.is_group or dctx.is_priv:
        return False

    from modules.slow_mode import check_slow_mode

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    uid = dctx.uid

    try:
        admin_ids = _get_admin_ids(CONFIG)
        if uid not in admin_ids and check_slow_mode(bot, m, CONFIG, db):
            clear_logging_context()
            return True
    except Exception:
        pass

    return False


def check_clean_service(dctx) -> bool:
    """P4.7 服务消息自动清理

    返回 True 表示服务消息已被清理
    """
    if not dctx.is_group or dctx.is_priv:
        return False

    from modules.clean_service import check_clean_service

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    try:
        if check_clean_service(bot, m, CONFIG, db):
            clear_logging_context()
            return True
    except Exception:
        pass

    return False


# ── 内部辅助函数 ──

def _get_admin_ids(CONFIG: dict) -> set:
    """获取管理员ID集合（ADMIN_IDS + ADMIN_ID）"""
    admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
    admin_id = CONFIG.get("ADMIN_ID", 0)
    if admin_id:
        admin_ids.add(admin_id)
    return admin_ids
