"""
强制订阅模块 - 入群前必须订阅指定频道

功能：
  1. 管理员设置强制订阅频道 /fsub @channel
  2. 管理员取消强制订阅 /unfsub
  3. 新成员入群时检查是否订阅了指定频道
  4. 未订阅则发送警告，超时后踢出

数据表：force_subscribe（chat_id, channel_username, channel_id, enabled, ts）
默认：DISABLED（enabled=0）

命令：
  /fsub @channel  → handle_fsub（含/unfsub子命令）
  /fsub status    → 查看当前设置

被调用：
  core/handlers/command_handlers.py → handle_fsub(bot, m, CONFIG, db)
  core/handlers/member_handlers.py → check_force_subscribe(bot, m, config, db)
  core/message_dispatcher.py       → check_force_subscribe(bot, m, config, db)
"""
import time
import threading

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("force_subscribe")

KICK_TIMEOUT = 60


def _get_fsub_config(db, chat_id: int) -> dict:
    """获取群组的强制订阅配置"""
    try:
        row = db.conn.execute(
            "SELECT channel_username, channel_id, enabled FROM force_subscribe WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        if row:
            return {
                "channel_username": row[0],
                "channel_id": row[1],
                "enabled": row[2],
            }
    except Exception as e:
        logger.error(f"查询强制订阅配置失败: chat_id={chat_id} err={e}")
    return {"channel_username": "", "channel_id": 0, "enabled": 0}


def _set_fsub_config(db, chat_id: int, channel_username: str, channel_id: int, enabled: int = 1):
    """设置群组的强制订阅配置"""
    now_ts = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT OR REPLACE INTO force_subscribe (chat_id, channel_username, channel_id, enabled, ts) VALUES (?,?,?,?,?)",
            (chat_id, channel_username, channel_id, enabled, now_ts)
        )
        db.conn.commit()


def _disable_fsub(db, chat_id: int):
    """禁用群组的强制订阅"""
    with _db_lock:
        db.conn.execute(
            "UPDATE force_subscribe SET enabled=0 WHERE chat_id=?",
            (chat_id,)
        )
        db.conn.commit()


def _is_admin(bot, chat_id: int, user_id: int) -> bool:
    """检查用户是否为群管理员"""
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def _check_member_subscribed(bot, channel_id: int, user_id: int) -> bool:
    """检查用户是否订阅了指定频道"""
    try:
        member = bot.get_chat_member(channel_id, user_id)
        return member.status in ("member", "administrator", "creator", "restricted")
    except Exception as e:
        logger.warning(f"检查订阅状态失败: channel_id={channel_id} user_id={user_id} err={e}")
        return False


def handle_fsub(bot, m, config, db):
    """处理 /fsub 命令（设置/取消/查看 强制订阅）"""
    chat_id = m.chat.id
    user_id = m.from_user.id
    text = (m.text or "").strip()

    if not _is_admin(bot, chat_id, user_id):
        bot.reply_to(m, "❌ 仅管理员可设置强制订阅")
        return

    parts = text.split()

    if len(parts) >= 2 and parts[1].lower() in ("off", "disable", "取消"):
        _disable_fsub(db, chat_id)
        bot.reply_to(m, "✅ 已关闭强制订阅")
        logger.info(f"强制订阅关闭: chat_id={chat_id} by={user_id}")
        return

    if len(parts) >= 2 and parts[1].lower() in ("status", "状态", "info"):
        fsub = _get_fsub_config(db, chat_id)
        if fsub["enabled"] and fsub["channel_username"]:
            bot.reply_to(m, (
                f"📋 强制订阅状态\n"
                f"频道：@{fsub['channel_username']}\n"
                f"状态：✅ 已启用"
            ))
        else:
            bot.reply_to(m, "📋 强制订阅状态：❌ 未启用")
        return

    channel_username = ""
    for part in parts[1:]:
        if part.startswith("@"):
            channel_username = part.lstrip("@")
            break

    if not channel_username:
        bot.reply_to(m, "❌ 用法：/fsub @频道名\n/fsub off — 关闭\n/fsub status — 查看状态")
        return

    try:
        chat_info = bot.get_chat(f"@{channel_username}")
        channel_id = chat_info.id
    except Exception as e:
        bot.reply_to(m, f"❌ 找不到频道 @{channel_username}，请检查频道用户名")
        logger.warning(f"获取频道信息失败: @{channel_username} err={e}")
        return

    if channel_id == chat_id:
        bot.reply_to(m, "❌ 不能将当前群设为强制订阅频道")
        return

    _set_fsub_config(db, chat_id, channel_username, channel_id, enabled=1)
    bot.reply_to(m, f"✅ 已启用强制订阅\n频道：@{channel_username}\n新成员需订阅后才能留在群内")
    logger.info(f"强制订阅设置: chat_id={chat_id} channel=@{channel_username} by={user_id}")


def handle_unforce_subscribe(bot, m, config, db):
    """处理 /unfsub 命令（取消强制订阅）"""
    chat_id = m.chat.id
    user_id = m.from_user.id

    if not _is_admin(bot, chat_id, user_id):
        bot.reply_to(m, "❌ 仅管理员可取消强制订阅")
        return

    _disable_fsub(db, chat_id)
    bot.reply_to(m, "✅ 已关闭强制订阅")
    logger.info(f"强制订阅关闭: chat_id={chat_id} by={user_id}")


def check_force_subscribe(bot, m, config, db):
    """新成员入群时检查是否订阅了指定频道"""
    chat_id = m.chat.id

    fsub = _get_fsub_config(db, chat_id)
    if not fsub["enabled"] or not fsub["channel_id"]:
        return

    if not m.new_chat_members:
        return

    channel_id = fsub["channel_id"]
    channel_username = fsub["channel_username"]

    for user in m.new_chat_members:
        if user.is_bot:
            continue

        if _is_admin(bot, chat_id, user.id):
            continue

        if _check_member_subscribed(bot, channel_id, user.id):
            continue

        user_display = user.first_name or f"用户{user.id}"

        try:
            invite_link = bot.export_chat_invite_link(channel_id)
        except Exception:
            invite_link = f"https://t.me/{channel_username}" if channel_username else ""

        warning_text = (
            f"⚠️ {user_display}，请先订阅频道后再留在群内\n"
        )
        if invite_link:
            warning_text += f"📢 订阅频道：{invite_link}\n"
        warning_text += f"⏰ 请在 {KICK_TIMEOUT} 秒内完成订阅，否则将被移出群组"

        try:
            bot.send_message(chat_id, warning_text)
        except Exception as e:
            logger.error(f"发送订阅警告失败: {e}")

        _schedule_kick_check(bot, chat_id, user.id, user_display, channel_id, channel_username, db)


def _schedule_kick_check(bot, chat_id: int, user_id: int, user_display: str,
                         channel_id: int, channel_username: str, db):
    """延迟检查用户是否已订阅，未订阅则踢出"""
    def _check_and_kick():
        import time
        time.sleep(KICK_TIMEOUT)

        fsub = _get_fsub_config(db, chat_id)
        if not fsub["enabled"]:
            return

        if _check_member_subscribed(bot, channel_id, user_id):
            logger.info(f"强制订阅通过: uid={user_id} chat_id={chat_id}")
            return

        try:
            bot.kick_chat_member(chat_id, user_id)
            bot.unban_chat_member(chat_id, user_id)
            logger.warning(f"强制订阅踢出: uid={user_id} chat_id={chat_id}")
        except Exception as e:
            logger.error(f"踢出未订阅用户失败: uid={user_id} err={e}")

        try:
            bot.send_message(chat_id, f"🚫 {user_display} 因未订阅频道已被移出群组")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    t = threading.Thread(target=_check_and_kick, daemon=True)
    t.start()


def handle_fsub_status(bot, m, config, db):
    """查看当前群组的强制订阅设置"""
    chat_id = m.chat.id
    fsub = _get_fsub_config(db, chat_id)

    if fsub["enabled"] and fsub["channel_username"]:
        bot.reply_to(m, (
            f"📋 强制订阅状态\n"
            f"频道：@{fsub['channel_username']}\n"
            f"频道ID：{fsub['channel_id']}\n"
            f"状态：✅ 已启用"
        ))
    else:
        bot.reply_to(m, "📋 强制订阅状态：❌ 未启用")
