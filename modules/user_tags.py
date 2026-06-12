# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/user_tags.py  ·  管理员标签/备注模块                           ║
║                                                                        ║
║  功能：                                                                ║
║    handle_add_tag    - 管理员给用户打标签                               ║
║    handle_add_note   - 管理员给用户添加备注                             ║
║    handle_view_tags  - 查看用户标签和备注                               ║
║    get_user_tags     - 获取用户所有标签（供用户画像使用）                ║
║    get_user_notes    - 获取用户所有备注                                 ║
║                                                                        ║
║  数据表：                                                              ║
║    user_tags  (id, uid, tag, added_by, ts)  UNIQUE(uid, tag)           ║
║    user_notes (id, uid, note, added_by, ts)                            ║
║  被调用：main.py 管理员指令 + 用户画像模块                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("user_tags")

_CST = timezone(timedelta(hours=8))


def handle_add_tag(bot, m, config, db, target_uid: int, tag: str):
    """管理员给用户打标签

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
        target_uid: 目标用户ID
        tag: 标签内容
    """
    admin_uid = m.from_user.id
    ts = int(time.time())

    if not tag.strip():
        bot.reply_to(m, "❌ 标签内容不能为空")
        return

    tag = tag.strip()[:50]  # 限制标签长度

    try:
        # 检查是否已存在相同标签
        row = db.conn.execute(
            "SELECT 1 FROM user_tags WHERE uid=? AND tag=?",
            (target_uid, tag)
        ).fetchone()
        if row:
            bot.reply_to(m, f"⚠️ 该用户已有标签「{tag}」")
            return

        db.conn.execute(
            "INSERT INTO user_tags (uid, tag, added_by, ts) VALUES (?,?,?,?)",
            (target_uid, tag, admin_uid, ts)
        )
        db.conn.commit()
        logger.info(f"🏷 管理员 uid={admin_uid} 给 uid={target_uid} 打标签: {tag}")
        bot.reply_to(m, f"✅ 已给用户 {target_uid} 添加标签「{tag}」")
    except Exception as e:
        logger.error(f"添加标签失败 uid={target_uid} tag={tag}: {e}")
        bot.reply_to(m, "❌ 添加标签失败，请稍后再试")


def handle_add_note(bot, m, config, db, target_uid: int, note: str):
    """管理员给用户添加备注

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
        target_uid: 目标用户ID
        note: 备注内容
    """
    admin_uid = m.from_user.id
    ts = int(time.time())

    if not note.strip():
        bot.reply_to(m, "❌ 备注内容不能为空")
        return

    note = note.strip()[:500]  # 限制备注长度

    try:
        db.conn.execute(
            "INSERT INTO user_notes (uid, note, added_by, ts) VALUES (?,?,?,?)",
            (target_uid, note, admin_uid, ts)
        )
        db.conn.commit()
        logger.info(f"📝 管理员 uid={admin_uid} 给 uid={target_uid} 添加备注: {note[:30]}...")
        bot.reply_to(m, f"✅ 已给用户 {target_uid} 添加备注")
    except Exception as e:
        logger.error(f"添加备注失败 uid={target_uid}: {e}")
        bot.reply_to(m, "❌ 添加备注失败，请稍后再试")


def handle_view_tags(bot, m, config, db, target_uid: int):
    """查看用户标签和备注

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
        target_uid: 目标用户ID
    """
    try:
        # 获取用户名
        row = db.conn.execute(
            "SELECT name FROM users WHERE uid=?", (target_uid,)
        ).fetchone()
        user_name = row[0] if row else str(target_uid)

        # 获取标签
        tags = get_user_tags(db, target_uid)

        # 获取备注
        notes = get_user_notes(db, target_uid)

        text = f"🏷 用户 {user_name} 的标签与备注\n"
        text += f"━━━━━━━━━━━━━\n"

        # 标签部分
        if tags:
            tag_str = " | ".join(t[0] for t in tags)
            text += f"📌 标签（{len(tags)}个）：{tag_str}\n"
        else:
            text += "📌 标签：暂无\n"

        # 备注部分
        if notes:
            text += f"\n📝 备注（{len(notes)}条）：\n"
            for i, (note_text, added_by, ts) in enumerate(notes, 1):
                time_str = datetime.fromtimestamp(ts, _CST).strftime("%m-%d %H:%M")
                # 获取添加者名称
                admin_row = db.conn.execute(
                    "SELECT name FROM users WHERE uid=?", (added_by,)
                ).fetchone()
                admin_name = admin_row[0] if admin_row else str(added_by)
                text += f"  {i}. {note_text}\n"
                text += f"     ——{admin_name} {time_str}\n"
        else:
            text += "\n📝 备注：暂无"

        bot.reply_to(m, text)
    except Exception as e:
        logger.error(f"查看标签备注失败 uid={target_uid}: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")


def get_user_tags(db, uid: int) -> list:
    """获取用户所有标签（供用户画像使用）

    Args:
        db: DB类实例
        uid: 用户ID

    Returns:
        [(tag, added_by, ts), ...] 标签列表
    """
    try:
        rows = db.conn.execute(
            "SELECT tag, added_by, ts FROM user_tags WHERE uid=? ORDER BY ts DESC",
            (uid,)
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    except Exception as e:
        logger.error(f"获取用户标签失败 uid={uid}: {e}")
        return []


def get_user_notes(db, uid: int) -> list:
    """获取用户所有备注

    Args:
        db: DB类实例
        uid: 用户ID

    Returns:
        [(note, added_by, ts), ...] 备注列表
    """
    try:
        rows = db.conn.execute(
            "SELECT note, added_by, ts FROM user_notes WHERE uid=? ORDER BY ts DESC",
            (uid,)
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    except Exception as e:
        logger.error(f"获取用户备注失败 uid={uid}: {e}")
        return []
