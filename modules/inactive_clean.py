"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/inactive_clean.py  ·  不活跃用户清理模块                       ║
║                                                                        ║
║  功能：                                                                ║
║    handle_ghost()            -> 列出N天未活跃用户（管理员指令）          ║
║    handle_ghost_confirm()    -> 确认踢出回调                            ║
║    run_auto_inactive_clean() -> 定时自动清理不活跃用户                   ║
║                                                                        ║
║  指令：/ghost N 或 /清理不活跃 N                                        ║
║  配置项（config.json）：                                                ║
║    AUTO_KICK_INACTIVE_DAYS -> 自动踢出天数，0=关闭                      ║
║                                                                        ║
║  数据表：speech_daily (uid, date, chat_id, count)                      ║
║          users (uid, name, last_active)                                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timedelta, timezone
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("inactive_clean")

_CST = timezone(timedelta(hours=8))


def _is_admin(uid: int, config: dict) -> bool:
    """检查用户是否为管理员"""
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if admin_id and uid == admin_id:
        return True
    return uid in admin_ids


def _get_admin_ids(bot, chat_id: int, config: dict) -> set:
    """获取群管理员ID集合（优先API，降级用config）"""
    admin_ids = set()
    # 先从config获取
    config_admin_id = config.get("ADMIN_ID", 0)
    config_admin_ids = config.get("ADMIN_IDS", [])
    if config_admin_id:
        admin_ids.add(config_admin_id)
    admin_ids.update(config_admin_ids)
    # 尝试从Telegram API获取
    try:
        admins = bot.get_chat_administrators(chat_id)
        for admin in admins:
            admin_ids.add(admin.user.id)
    except Exception as e:
        logger.warning(f"获取群管理员列表失败，仅用config判断: {e}")
    return admin_ids


def _time_ago(ts: float) -> str:
    """将时间戳转换为'X天前'格式"""
    now = time.time()
    diff = now - ts
    if diff < 0:
        return "刚刚"
    days = int(diff // 86400)
    if days >= 1:
        return f"{days}天前"
    hours = int(diff // 3600)
    if hours >= 1:
        return f"{hours}小时前"
    return "1天内"


def _find_inactive_users(db, chat_id: int, days: int, admin_ids: set) -> list:
    """查找N天内未活跃的用户，返回 [(uid, name, last_active), ...]"""
    now_cst = datetime.now(_CST)
    cutoff_ts = (now_cst - timedelta(days=days)).timestamp()
    cutoff_date = (now_cst - timedelta(days=days)).strftime("%Y-%m-%d")

    with _db_lock:
        # 从users表找last_active < cutoff的用户
        rows = db.conn.execute(
            """SELECT u.uid, COALESCE(u.name, '未知'), u.last_active
               FROM users u
               WHERE u.last_active > 0 AND u.last_active < ?
               ORDER BY u.last_active ASC LIMIT 30""",
            (cutoff_ts,)
        ).fetchall()

        # 排除N天内有发言记录的用户（交叉验证speech_daily）
        inactive_users = []
        for row in rows:
            user_uid, user_name, last_active = row
            # 管理员豁免
            if user_uid in admin_ids:
                continue
            # 检查该用户N天内是否有发言
            recent = db.conn.execute(
                "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE uid=? AND date>=?",
                (user_uid, cutoff_date)
            ).fetchone()
            recent_count = recent[0] if recent else 0
            if recent_count == 0:
                inactive_users.append((user_uid, user_name, last_active))

    return inactive_users


def handle_ghost(bot, m, config, db):
    """列出N天未活跃用户（管理员指令）

    用法：/ghost 30 或 /清理不活跃 30

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    uid = m.from_user.id
    chat_id = m.chat.id

    if not _is_admin(uid, config):
        bot.reply_to(m, "❌ 仅管理员可使用此命令")
        return

    # 解析天数参数
    text = m.text or ""
    parts = text.split()
    days = 30  # 默认30天
    if len(parts) >= 2:
        try:
            days = int(parts[1])
            if days < 1:
                days = 30
        except (ValueError, TypeError):
            days = 30

    try:
        admin_ids = _get_admin_ids(bot, chat_id, config)
        inactive_users = _find_inactive_users(db, chat_id, days, admin_ids)

        if not inactive_users:
            bot.reply_to(m, f"🎉 没有超过{days}天未活跃的用户，大家都很活跃！")
            return

        # 构建列表文本
        text_lines = [f"👻 不活跃用户（{days}天未发言）\n━━━━━━━━━━━━━"]
        for i, (user_uid, user_name, last_active) in enumerate(inactive_users, 1):
            time_ago = _time_ago(last_active)
            text_lines.append(f"{i}. {user_name} (uid={user_uid}) - {time_ago}")

        text_lines.append(f"\n共 {len(inactive_users)} 人不活跃")

        list_text = "\n".join(text_lines)

        # 构建确认按钮
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ 确认踢出", callback_data=f"ghost_kick_{days}"),
            InlineKeyboardButton("❌ 取消", callback_data="ghost_cancel")
        )

        bot.send_message(chat_id, list_text, reply_markup=markup)

    except Exception as e:
        logger.error(f"不活跃用户查询失败: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")


def handle_ghost_confirm(bot, call, config, db):
    """确认踢出不活跃用户的回调处理

    Args:
        bot: TeleBot实例
        call: CallbackQuery对象
        config: 配置字典
        db: DB类实例
    """
    data = call.data or ""
    chat_id = call.message.chat.id
    caller_uid = call.from_user.id

    if not _is_admin(caller_uid, config):
        bot.answer_callback_query(call.id, "❌ 仅管理员可操作")
        return

    if data == "ghost_cancel":
        try:
            bot.edit_message_text("❌ 已取消踢出操作", chat_id, call.message.message_id)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id, "已取消")
        return

    if not data.startswith("ghost_kick_"):
        return

    # 解析天数
    try:
        days = int(data[11:])
    except (ValueError, IndexError):
        days = 30

    try:
        admin_ids = _get_admin_ids(bot, chat_id, config)
        inactive_users = _find_inactive_users(db, chat_id, days, admin_ids)

        if not inactive_users:
            try:
                bot.edit_message_text("🎉 没有需要踢出的不活跃用户", chat_id, call.message.message_id)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            bot.answer_callback_query(call.id, "无需踢出")
            return

        kicked = 0
        failed = 0
        for user_uid, user_name, _last_active in inactive_users:
            try:
                bot.kick_chat_member(chat_id, user_uid)
                kicked += 1
                logger.info(f"👻 踢出不活跃用户: uid={user_uid} name={user_name} chat={chat_id}")
            except Exception as e:
                failed += 1
                logger.warning(f"踢出不活跃用户失败: uid={user_uid} chat={chat_id} error={e}")

        result_text = f"✅ 已踢出 {kicked} 位不活跃用户（{days}天未发言）"
        if failed > 0:
            result_text += f"\n⚠️ {failed} 位踢出失败（权限不足或用户已不在群内）"

        try:
            bot.edit_message_text(result_text, chat_id, call.message.message_id)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id, f"已踢出{kicked}人")
        logger.info(f"👻 不活跃用户清理完成: chat={chat_id} kicked={kicked} failed={failed}")

    except Exception as e:
        logger.error(f"不活跃用户踢出失败: {e}")
        try:
            bot.edit_message_text("❌ 踢出操作失败，请稍后再试", chat_id, call.message.message_id)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id, "操作失败")


def run_auto_inactive_clean(bot, config, db):
    """定时自动清理不活跃用户（由统一调度器定期调用）

    读取config["AUTO_KICK_INACTIVE_DAYS"]，>0时自动踢出超过该天数未活跃的用户。
    管理员豁免。

    注意：该函数依赖 `users.last_active` 字段判断"不活跃"。但 `last_active`
    的更新时机包含非发言交互（如点击按钮、接收消息等），不代表用户完全未活跃。
    如需更精确的"不发言"判断，应结合 `speech_daily` 表交叉验证（`_find_inactive_users`
    已有此逻辑）。当前实现已在此基础上做了双重校验，但语义上仍使用"last_active"
    作为主查询条件，可能存在少部分用户 last_active 较新但实际未发言的情况。

    Args:
        bot: TeleBot实例
        config: 配置字典
        db: DB类实例
    """
    # AUTO_KICK_INACTIVE_DAYS 配置已从 int 改为 dict {"enable": bool, "days": int}
    ik_config = config.get("AUTO_KICK_INACTIVE_DAYS", 0)
    # 兼容旧配置（int 类型）
    if isinstance(ik_config, (int, float)):
        days = int(ik_config)
        if days <= 0:
            return
    elif isinstance(ik_config, dict):
        if not ik_config.get("enable", False):
            return
        days = ik_config.get("days", 30)
        if not isinstance(days, (int, float)) or days <= 0:
            return
    else:
        return

    gid = config.get("GROUP_ID", 0)
    if not gid:
        return

    try:
        admin_ids = _get_admin_ids(bot, gid, config)
        inactive_users = _find_inactive_users(db, gid, days, admin_ids)

        if not inactive_users:
            logger.debug(f"自动清理：无超过{days}天不活跃的用户")
            return

        kicked = 0
        failed = 0
        for user_uid, user_name, _last_active in inactive_users:
            try:
                bot.kick_chat_member(gid, user_uid)
                kicked += 1
                logger.info(f"👻 自动踢出不活跃用户: uid={user_uid} name={user_name} chat={gid}")
            except Exception as e:
                failed += 1
                logger.warning(f"自动踢出失败: uid={user_uid} chat={gid} error={e}")

        logger.info(f"👻 自动清理不活跃用户完成: days={days} kicked={kicked} failed={failed}")

    except Exception as e:
        logger.error(f"自动清理不活跃用户失败: {e}")
