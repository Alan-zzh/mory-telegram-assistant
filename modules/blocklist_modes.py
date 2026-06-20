"""
黑名单模式系统 - 匹配黑名单词后的处理模式

功能：
  1. 设置黑名单匹配后的处理模式（warn/ban/mute/delete）
  2. 不同模式执行不同处罚
  3. warn模式累计警告达上限后封禁

命令：
  /blocklistmode warn/ban/mute/delete → handle_blocklist_mode

数据表：blocklist_modes（chat_id, mode, ts）
"""
import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("blocklist_modes")

# 有效模式
VALID_MODES = {"warn", "ban", "mute", "delete"}


def _permanent_mute(bot, chat_id: int, uid: int):
    """[Codex] 黑名单内容链路统一永久禁言，不踢出群。"""
    try:
        from telebot.types import ChatPermissions
        bot.restrict_chat_member(
            chat_id,
            uid,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=0,
        )
    except TypeError:
        bot.restrict_chat_member(chat_id, uid, can_send_messages=False, until_date=0)


def get_blocklist_mode(db, chat_id):
    """获取群的黑名单模式，默认delete"""
    try:
        row = db.conn.execute(
            "SELECT mode FROM blocklist_modes WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        return row[0] if row else "delete"
    except Exception:
        return "delete"


def handle_blocklist_mode(bot, m, config, db):
    """处理 /blocklistmode 命令"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()
    parts = text.split()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可设置黑名单模式")
            return
    except Exception:
        return

    if len(parts) < 2:
        current = get_blocklist_mode(db, chat_id)
        mode_desc = {
            "warn": "警告（删除+警告，累计永久禁言）",
            "ban": "永久禁言（不踢人）",
            "mute": "禁言（禁言1小时）",
            "delete": "删除（仅删除消息）",
        }
        bot.reply_to(m, f"📋 当前黑名单模式：{current}\n📝 {mode_desc.get(current, '')}\n\n可用模式：warn / ban / mute / delete")
        return

    mode = parts[1].lower()
    if mode not in VALID_MODES:
        bot.reply_to(m, f"❌ 无效模式，可选：{', '.join(VALID_MODES)}")
        return

    now_ts = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT OR REPLACE INTO blocklist_modes (chat_id, mode, ts) VALUES (?,?,?)",
            (chat_id, mode, now_ts)
        )
        db.conn.commit()

    mode_desc = {
        "warn": "警告模式：删除消息+发出警告，累计警告达上限后永久禁言",
        "ban": "永久禁言模式：直接永久禁言，不踢出群",
        "mute": "禁言模式：禁言1小时",
        "delete": "删除模式：仅删除消息，不做其他处罚",
    }
    bot.reply_to(m, f"✅ 黑名单模式已设置为：{mode}\n📝 {mode_desc[mode]}")
    logger.info(f"黑名单模式设置: chat={chat_id} mode={mode} by={uid}")


def apply_blocklist_action(bot, m, config, db, chat_id, uid):
    """根据黑名单模式执行对应操作"""
    mode = get_blocklist_mode(db, chat_id)
    uname = m.from_user.first_name or "用户"

    try:
        # 先删除消息（受全局开关控制）
        if config.get("ENABLE_MESSAGE_DELETION", False):
            bot.delete_message(chat_id, m.message_id)
        else:
            logger.warning(f"[黑名单模式] ENABLE_MESSAGE_DELETION 未开启，跳过删除消息")
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    if mode == "delete":
        # 仅删除，无其他操作
        logger.info(f"黑名单删除消息: chat={chat_id} uid={uid}")
        return

    elif mode == "warn":
        # 警告模式
        warn_limit = config.get("WARN_LIMIT", 3)
        # 添加警告
        now_ts = int(time.time())
        with _db_lock:
            db.conn.execute(
                "INSERT INTO warnings (uid, chat_id, reason, warned_by, ts) VALUES (?,?,?,?,?)",
                (uid, chat_id, "黑名单词匹配", m.from_user.id, now_ts)
            )
            db.conn.commit()
            # 检查警告数
            count = db.conn.execute(
                "SELECT COUNT(*) FROM warnings WHERE uid=? AND chat_id=?",
                (uid, chat_id)
            ).fetchone()[0]

        if count >= warn_limit:
            # [Codex] 达到上限只永久禁言，不踢出群。
            _permanent_mute(bot, chat_id, uid)
            bot.send_message(chat_id, f"🔇 {uname} 因累计{count}次警告被永久禁言")
            # 清除警告
            with _db_lock:
                db.conn.execute("DELETE FROM warnings WHERE uid=? AND chat_id=?", (uid, chat_id))
                db.conn.commit()
        else:
            bot.send_message(chat_id, f"⚠️ {uname} 收到警告（{count}/{warn_limit}）\n📝 原因：黑名单词匹配")

    elif mode == "ban":
        # [Codex] ban 模式沿用命令名，但实际执行永久禁言，不踢人。
        _permanent_mute(bot, chat_id, uid)
        bot.send_message(chat_id, f"🔇 {uname} 因发送黑名单内容被永久禁言")

    elif mode == "mute":
        # 禁言1小时
        mute_duration = 3600
        bot.restrict_chat_member(
            chat_id, uid,
            until_date=int(time.time()) + mute_duration,
            can_send_messages=False
        )
        bot.send_message(chat_id, f"🔇 {uname} 因发送黑名单内容被禁言1小时")

    logger.info(f"黑名单模式执行: chat={chat_id} uid={uid} mode={mode}")
