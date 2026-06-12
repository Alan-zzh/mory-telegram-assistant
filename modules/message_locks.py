"""消息类型锁定模块 - 群组消息类型开关控制"""

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger(__name__)

LOCK_TYPE_MAP = {
    "链接": "links", "links": "links",
    "图片": "photos", "photos": "photos",
    "贴纸": "stickers", "stickers": "stickers",
    "动图": "gifs", "gifs": "gifs", "gif": "gifs",
    "视频": "videos", "videos": "videos",
    "语音": "voice", "voice": "voice",
    "转发": "forward", "forward": "forward",
    "阿拉伯语": "arabic", "arabic": "arabic",
    "rtl": "rtl", "RTL": "rtl",
    "投票": "polls", "polls": "polls",
    "@": "mention", "mention": "mention",
}

# 内部类型 → 中文显示名
_INTERNAL_TO_CN = {
    "links": "链接", "photos": "图片", "stickers": "贴纸",
    "gifs": "动图", "videos": "视频", "voice": "语音",
    "forward": "转发", "arabic": "阿拉伯语", "rtl": "RTL文字",
    "polls": "投票",
    "mention": "@",
}


def _resolve_lock_type(lock_type_str):
    """将用户输入的类型字符串解析为内部类型，返回 (internal_type, display_name) 或 None"""
    key = lock_type_str.strip().lower() if lock_type_str else ""
    internal = LOCK_TYPE_MAP.get(key)
    if internal:
        return internal, _INTERNAL_TO_CN.get(internal, internal)
    return None


def handle_lock(bot, m, config, db, lock_type_str):
    """锁定一种消息类型"""
    result = _resolve_lock_type(lock_type_str)
    if not result:
        supported = "、".join(sorted(set(LOCK_TYPE_MAP.keys()) - set(LOCK_TYPE_MAP.values())))
        bot.reply_to(m, f"未知的锁定类型。支持的类型：{supported}")
        return

    internal_type, display_name = result
    chat_id = m.chat.id
    import time
    now = int(time.time())

    with _db_lock:
        db.conn.execute(
            "INSERT INTO message_locks (chat_id, lock_type, enabled, ts) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(chat_id, lock_type) DO UPDATE SET enabled=1, ts=?",
            (chat_id, internal_type, now, now),
        )
        db.conn.commit()

    logger.info("消息锁定: chat_id=%s type=%s", chat_id, internal_type)
    bot.reply_to(m, f"已锁定 {display_name}，非管理员发送该类型消息将被删除")


def handle_unlock(bot, m, config, db, lock_type_str):
    """解锁一种消息类型"""
    result = _resolve_lock_type(lock_type_str)
    if not result:
        supported = "、".join(sorted(set(LOCK_TYPE_MAP.keys()) - set(LOCK_TYPE_MAP.values())))
        bot.reply_to(m, f"未知的锁定类型。支持的类型：{supported}")
        return

    internal_type, display_name = result
    chat_id = m.chat.id

    with _db_lock:
        db.conn.execute(
            "UPDATE message_locks SET enabled=0 WHERE chat_id=? AND lock_type=?",
            (chat_id, internal_type),
        )
        db.conn.commit()

    logger.info("消息解锁: chat_id=%s type=%s", chat_id, internal_type)
    bot.reply_to(m, f"已解锁 {display_name}")


def handle_lock_list(bot, m, config, db):
    """显示当前群组所有锁定的消息类型"""
    chat_id = m.chat.id

    with _db_lock:
        rows = db.conn.execute(
            "SELECT lock_type FROM message_locks WHERE chat_id=? AND enabled=1",
            (chat_id,),
        ).fetchall()

    if not rows:
        bot.reply_to(m, "当前没有锁定任何消息类型")
        return

    names = [_INTERNAL_TO_CN.get(r[0], r[0]) for r in rows]
    bot.reply_to(m, "当前锁定的消息类型：\n" + "\n".join(f"• {n}" for n in names))


def check_message_lock(bot, m, config, db):
    """检查消息是否违反锁定规则，返回 True 表示应删除"""
    chat_id = m.chat.id

    with _db_lock:
        rows = db.conn.execute(
            "SELECT lock_type FROM message_locks WHERE chat_id=? AND enabled=1",
            (chat_id,),
        ).fetchall()

    if not rows:
        return False

    locked_types = {r[0] for r in rows}

    # 链接
    if "links" in locked_types:
        text = m.text or m.caption or ""
        has_url_entity = False
        if m.entities:
            for ent in m.entities:
                if ent.type in ("url", "text_link"):
                    has_url_entity = True
                    break
        if has_url_entity or "http" in text.lower():
            return True

    # 图片
    if "photos" in locked_types and m.content_type == "photo":
        return True

    # 贴纸
    if "stickers" in locked_types and m.content_type == "sticker":
        return True

    # 动图
    if "gifs" in locked_types and m.content_type == "animation":
        return True

    # 视频
    if "videos" in locked_types and m.content_type == "video":
        return True

    # 语音
    if "voice" in locked_types and m.content_type == "voice":
        return True

    # 转发
    if "forward" in locked_types and m.forward_date is not None:
        return True

    # 阿拉伯语
    if "arabic" in locked_types:
        text = m.text or m.caption or ""
        if any("\u0600" <= ch <= "\u06FF" for ch in text):
            return True

    # RTL文字（希伯来语、阿拉伯语等从右到左书写系统）
    if "rtl" in locked_types and m.text and any('\u0590' <= c <= '\u08FF' for c in m.text):
        return True

    # 投票
    if "polls" in locked_types and m.content_type == "poll":
        return True

    # @提及
    if "mention" in locked_types:
        if m.entities:
            for ent in m.entities:
                if ent.type == "mention":
                    return True

    return False
