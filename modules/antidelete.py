# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/antidelete.py  ·  反撤回（消息缓存）模块                        ║
║                                                                        ║
║  功能：                                                                ║
║    cache_message  - 缓存群组消息（main.py每条消息调用）                 ║
║    handle_snipe   - 查看最近被撤回的消息                                ║
║                                                                        ║
║  原理：pyTelegramBotAPI不原生支持deleted_messages事件，                 ║
║        因此采用消息缓存+手动查询的方式：                                ║
║        1. 每条群消息都缓存到内存和数据库                                ║
║        2. /snipe命令查询数据库中最近被标记为已删除的消息                ║
║        3. 仅管理员可用 /snipe                                          ║
║  被调用：main.py 消息处理 + 指令分发                                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("antidelete")

_CST = timezone(timedelta(hours=8))

# 内存消息缓存：{ chat_id: [ {msg_id, uid, content, content_type, ts}, ... ] }
_msg_cache = {}
_cache_lock = Lock()

# 每个群最大缓存条数
MAX_CACHE_PER_CHAT = 50


def _init_table(db):
    """初始化deleted_messages表（幂等）"""
    with _db_lock:
        db.conn.execute("""CREATE TABLE IF NOT EXISTS deleted_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            msg_id INTEGER,
            uid INTEGER,
            sender_name TEXT,
            content TEXT,
            content_type TEXT,
            ts INTEGER,
            deleted_ts INTEGER
        )""")
        db.conn.commit()


def cache_message(chat_id: int, msg_id: int, uid: int, sender_name: str,
                  content: str, content_type: str = "text"):
    """缓存群组消息，供后续反撤回查询

    由main.py在每条群消息处理时调用。

    Args:
        chat_id: 群组ID
        msg_id: 消息ID
        uid: 发送者ID
        sender_name: 发送者名称
        content: 消息内容
        content_type: 内容类型（text/photo/sticker等）
    """
    ts = int(time.time())
    entry = {
        "msg_id": msg_id,
        "uid": uid,
        "sender_name": sender_name,
        "content": content[:1000] if content else "",  # 限制长度
        "content_type": content_type,
        "ts": ts,
    }

    with _cache_lock:
        if chat_id not in _msg_cache:
            _msg_cache[chat_id] = []
        cache = _msg_cache[chat_id]
        cache.append(entry)
        # 保留最近MAX_CACHE_PER_CHAT条
        if len(cache) > MAX_CACHE_PER_CHAT:
            _msg_cache[chat_id] = cache[-MAX_CACHE_PER_CHAT:]


def record_deleted_message(db, chat_id: int, msg_id: int):
    """将缓存中的消息标记为已删除并写入数据库

    当检测到消息被删除时调用（可由外部逻辑触发）。

    Args:
        db: DB类实例
        chat_id: 群组ID
        msg_id: 被删除的消息ID
    """
    with _cache_lock:
        cache = _msg_cache.get(chat_id, [])
        entry = None
        for item in cache:
            if item["msg_id"] == msg_id:
                entry = item
                break

    if not entry:
        return

    # 写入数据库
    _init_table(db)
    with _db_lock:
        try:
            db.conn.execute(
                "INSERT INTO deleted_messages (chat_id, msg_id, uid, sender_name, content, content_type, ts, deleted_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, msg_id, entry["uid"], entry["sender_name"],
                 entry["content"], entry["content_type"], entry["ts"], int(time.time()))
            )
            db.conn.commit()
        except Exception as e:
            logger.error(f"记录已删除消息失败: {e}")

    # 从内存缓存移除
    with _cache_lock:
        cache = _msg_cache.get(chat_id, [])
        _msg_cache[chat_id] = [item for item in cache if item["msg_id"] != msg_id]


def handle_snipe(bot, m, config, db):
    """查看最近被撤回的消息（仅管理员）

    用法：/snipe

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    chat_id = m.chat.id

    # 权限检查：仅管理员
    try:
        member = bot.get_chat_member(chat_id, m.from_user.id)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可使用 /snipe")
            return
    except Exception as e:
        logger.error(f"检查管理员权限失败: {e}")
        bot.reply_to(m, "❌ 权限检查失败，请稍后再试")
        return

    _init_table(db)

    # 查询该群最近一条被删除的消息
    try:
        row = db.conn.execute(
            "SELECT uid, sender_name, content, content_type, ts, deleted_ts "
            "FROM deleted_messages WHERE chat_id=? ORDER BY deleted_ts DESC LIMIT 1",
            (chat_id,)
        ).fetchone()
    except Exception as e:
        logger.error(f"查询已删除消息失败: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")
        return

    if not row:
        bot.reply_to(m, "👻 没有捕获到被撤回的消息")
        return

    uid, sender_name, content, content_type, ts, deleted_ts = row

    # 格式化时间
    try:
        send_time = datetime.fromtimestamp(ts, tz=_CST).strftime("%H:%M:%S")
        delete_time = datetime.fromtimestamp(deleted_ts, tz=_CST).strftime("%H:%M:%S")
    except Exception:
        send_time = str(ts)
        delete_time = str(deleted_ts)

    # 内容类型图标
    type_icon = {"text": "📝", "photo": "🖼", "sticker": "🎭", "video": "🎬"}.get(content_type, "📄")

    text = f"🔍 捕获到一条撤回消息\n"
    text += f"━━━━━━━━━━━━━\n"
    text += f"👤 发送者：{sender_name}（{uid}）\n"
    text += f"{type_icon} 内容：{content or '（无文本内容）'}\n"
    text += f"🕐 发送时间：{send_time}\n"
    text += f"🗑 撤回时间：{delete_time}"

    bot.reply_to(m, text)


def cleanup_old_records(db, max_age: int = 86400):
    """清理过期的已删除消息记录（默认保留24小时）

    Args:
        db: DB类实例
        max_age: 最大保留时间（秒）
    """
    _init_table(db)
    cutoff = int(time.time()) - max_age
    with _db_lock:
        try:
            db.conn.execute("DELETE FROM deleted_messages WHERE deleted_ts < ?", (cutoff,))
            db.conn.commit()
        except Exception as e:
            logger.error(f"清理过期删除记录失败: {e}")
