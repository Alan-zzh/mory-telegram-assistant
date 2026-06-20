"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/federation.py  ·  联邦制跨群封禁模块                          ║
║  (参考 WilliamButcherBot/Gojo_Satoru)                                   ║
║                                                                        ║
║  功能：一个群封禁的用户，自动同步到所有加入联邦的群。                    ║
║
║  数据库表：                                                            ║
║    federation_bans                                                     ║
║    - user_id INTEGER                                                   ║
║    - banned_by INTEGER (执行封禁的管理员ID)                              ║
║    - reason TEXT                                                       ║
║    - chat_id INTEGER (原始封禁群ID)                                     ║
║    - ts INTEGER (封禁时间戳)                                            ║
║                                                                        ║
║  指令：                                                                ║
║    /fban <user_id> [reason]  - 联邦封禁                                ║
║    /unfban <user_id>         - 解除联邦封禁                             ║
║    /feds <user_id>           - 查询用户联邦封禁记录                      ║
║
║  被调用：main.py P6 管理员指令                                        ║
══════════════════════════════════════════════════════════════════════════╝
"""

from core.logging_util import get_logger

logger = get_logger("federation")


def fban_user(db, user_id: int, banned_by: int, reason: str = "联邦封禁", chat_id: int = 0):
    """
    联邦封禁用户
    """
    import time
    with db.conn:
        db.conn.execute(
            "INSERT OR REPLACE INTO federation_bans VALUES (?,?,?,?,?)",
            (user_id, banned_by, reason, chat_id, int(time.time()))
        )
        db.conn.commit()
    logger.warning(f"🚫 联邦封禁: uid={user_id} by={banned_by} reason={reason}")


def unfban_user(db, user_id: int):
    """解除联邦封禁"""
    with db.conn:
        db.conn.execute("DELETE FROM federation_bans WHERE user_id=?", (user_id,))
        db.conn.commit()
    logger.info(f"✅ 解除联邦封禁: uid={user_id}")


def is_federation_banned(db, user_id: int) -> tuple:
    """
    检查用户是否被联邦封禁
    返回 (is_banned, ban_info) 或 (False, None)
    """
    with db.conn:
        c = db.conn.cursor()
        c.execute(
            "SELECT banned_by, reason, chat_id, ts FROM federation_bans WHERE user_id=?",
            (user_id,)
        )
        row = c.fetchone()
        if row:
            return True, {
                "banned_by": row[0],
                "reason": row[1],
                "chat_id": row[2],
                "ts": row[3],
            }
        return False, None


def get_fban_count(db, user_id: int) -> int:
    """获取用户联邦封禁次数"""
    with db.conn:
        c = db.conn.cursor()
        c.execute("SELECT COUNT(*) FROM federation_bans WHERE user_id=?", (user_id,))
        return c.fetchone()[0]


def execute_fban_on_join(bot, m, config: dict, db, user, user_display: str):
    """
    新用户入群时检查联邦封禁
    如果被封禁，自动踢出并通知管理员
    """
    is_banned, ban_info = is_federation_banned(db, user.id)

    if is_banned:
        logger.warning(
            f"🚫 联邦封禁拦截: {user_display} "
            f"原因={ban_info['reason']} 原群={ban_info['chat_id']}"
        )

        # 踢出用户
        try:
            bot.kick_chat_member(m.chat.id, user.id)
            bot.unban_chat_member(m.chat.id, user.id)
        except Exception as e:
            logger.error(f"踢出联邦封禁用户失败: {e}")

        # 通知管理员
        admin_id = config.get("ADMIN_ID", 0)
        if admin_id:
            try:
                from datetime import datetime, timezone, timedelta
                _CST = timezone(timedelta(hours=8))
                ban_time = datetime.fromtimestamp(ban_info["ts"], _CST).strftime("%Y-%m-%d %H:%M")

                bot.send_message(
                    admin_id,
                    f" 联邦封禁拦截通知\n"
                    f"👤 用户：{user_display}\n"
                    f"🔨 原因：{ban_info['reason']}\n"
                    f"📍 原群：{ban_info['chat_id']}\n"
                    f"⏰ 封禁时间：{ban_time}\n"
                    f" 操作：已踢出当前群组"
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        return True

    return False


def handle_fban_command(bot, m, args: list, config: dict, db):
    """处理 /fban 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以执行联邦封禁")
        return

    if not args:
        bot.reply_to(m, "❌ 用法：/fban <user_id> [原因]")
        return

    try:
        user_id = int(args[0])
    except ValueError:
        bot.reply_to(m, "❌ 用户ID必须是数字")
        return

    reason = " ".join(args[1:]) if len(args) > 1 else "联邦封禁"
    chat_id = m.chat.id

    fban_user(db, user_id, admin_id, reason, chat_id)

    bot.reply_to(m, f"✅ 已将用户 {user_id} 加入联邦封禁\n原因：{reason}")

    # 尝试踢出当前群
    try:
        bot.kick_chat_member(chat_id, user_id)
        bot.unban_chat_member(chat_id, user_id)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
def handle_unfban_command(bot, m, args: list, config: dict, db):
    """处理 /unfban 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以解除联邦封禁")
        return

    if not args:
        bot.reply_to(m, "❌ 用法：/unfban <user_id>")
        return

    try:
        user_id = int(args[0])
    except ValueError:
        bot.reply_to(m, "❌ 用户ID必须是数字")
        return

    unfban_user(db, user_id)

    bot.reply_to(m, f"✅ 已解除用户 {user_id} 的联邦封禁")


def handle_feds_command(bot, m, args: list, config: dict, db):
    """处理 /feds 查询命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以查询联邦封禁")
        return

    if not args:
        bot.reply_to(m, "❌ 用法：/feds <user_id>")
        return

    try:
        user_id = int(args[0])
    except ValueError:
        bot.reply_to(m, "❌ 用户ID必须是数字")
        return

    count = get_fban_count(db, user_id)
    is_banned, ban_info = is_federation_banned(db, user_id)

    if is_banned:
        from datetime import datetime, timezone, timedelta
        _CST = timezone(timedelta(hours=8))
        ban_time = datetime.fromtimestamp(ban_info["ts"], _CST).strftime("%Y-%m-%d %H:%M")

        bot.reply_to(m, (
            f"📋 联邦封禁查询结果：\n"
            f"👤 用户ID：{user_id}\n"
            f"🔨 状态：已被封禁\n"
            f"📝 原因：{ban_info['reason']}\n"
            f" 原群：{ban_info['chat_id']}\n"
            f"⏰ 时间：{ban_time}"
        ))
    else:
        bot.reply_to(m, f"📋 用户 {user_id} 无联邦封禁记录")
