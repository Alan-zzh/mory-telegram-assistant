"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/clean_service.py  ·  服务消息自动清理模块                      ║
║                                                                        ║
║  功能：                                                                ║
║    handle_cleanservice()  -> 开关服务消息自动清理（管理员指令）          ║
║    check_clean_service()  -> 检查服务消息是否应删除（消息分发中调用）    ║
║                                                                        ║
║  指令：/cleanservice 开 或 /cleanservice 关                             ║
║                                                                        ║
║  数据表：clean_service_settings (chat_id, enabled, ts)                 ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.helpers import can_delete_message
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("clean_service")


def _is_admin(uid: int, config: dict) -> bool:
    """检查用户是否为管理员"""
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if admin_id and uid == admin_id:
        return True
    return uid in admin_ids


def _is_service_message(m) -> bool:
    """判断消息是否为服务消息（入群/退群/置顶等）

    Args:
        m: Message对象

    Returns:
        bool: True表示是服务消息
    """
    # 新成员入群
    if m.content_type == "new_chat_members":
        return True
    # 成员退群
    if m.content_type == "left_chat_member":
        return True
    # 置顶消息
    if hasattr(m, 'pinned_message') and m.pinned_message is not None:
        return True
    # 群组创建
    if hasattr(m, 'group_chat_created') and m.group_chat_created:
        return True
    # 超级群组创建
    if hasattr(m, 'supergroup_chat_created') and m.supergroup_chat_created:
        return True
    # 频道创建
    if hasattr(m, 'channel_chat_created') and m.channel_chat_created:
        return True
    # 群标题变更
    if hasattr(m, 'new_chat_title') and m.new_chat_title:
        return True
    # 群头像变更
    if hasattr(m, 'new_chat_photo') and m.new_chat_photo:
        return True
    # 群头像删除
    if hasattr(m, 'delete_chat_photo') and m.delete_chat_photo:
        return True
    # 消息自动删除时间变更
    if hasattr(m, 'message_auto_delete_timer_changed') and m.message_auto_delete_timer_changed:
        return True
    # 成员邀请
    if hasattr(m, 'successful_payment') and m.successful_payment:
        return True
    # 群迁移到超级群
    if hasattr(m, 'migrate_to_chat_id') and m.migrate_to_chat_id:
        return True
    # 语音聊天开启
    if hasattr(m, 'voice_chat_started') and m.voice_chat_started:
        return True
    # 语音聊天结束
    if hasattr(m, 'voice_chat_ended') and m.voice_chat_ended:
        return True
    # 语音聊天邀请
    if hasattr(m, 'voice_chat_participants_invited') and m.voice_chat_participants_invited:
        return True
    return False


def _get_clean_setting(db, chat_id: int) -> bool:
    """查询群的服务消息清理开关状态

    Args:
        db: DB类实例
        chat_id: 群组ID

    Returns:
        bool: True表示开启清理
    """
    try:
        row = db.conn.execute(
            "SELECT enabled FROM clean_service_settings WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        return bool(row[0]) if row else False
    except Exception as e:
        logger.error(f"查询清理设置失败 chat_id={chat_id}: {e}")
        return False


def handle_cleanservice(bot, m, config, db):
    """开关服务消息自动清理（管理员指令）

    用法：/cleanservice 开 或 /cleanservice 关

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

    # 解析开关参数
    text = m.text or ""
    parts = text.split()
    if len(parts) < 2:
        # 无参数时显示当前状态
        enabled = _get_clean_setting(db, chat_id)
        status = "✅ 已开启" if enabled else "❌ 已关闭"
        bot.reply_to(m, f"服务消息自动清理当前状态：{status}\n\n用法：/cleanservice 开 或 /cleanservice 关")
        return

    arg = parts[1].strip()
    if arg in ("开", "on", "1", "开启", "打开", "yes"):
        enabled = 1
        status_text = "✅ 已开启"
    elif arg in ("关", "off", "0", "关闭", "关掉", "no"):
        enabled = 0
        status_text = "❌ 已关闭"
    else:
        bot.reply_to(m, "❌ 参数无效，请用：/cleanservice 开 或 /cleanservice 关")
        return

    try:
        now = int(time.time())
        with _db_lock:
            db.conn.execute(
                """INSERT INTO clean_service_settings (chat_id, enabled, ts)
                   VALUES (?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET enabled=?, ts=?""",
                (chat_id, enabled, now, enabled, now)
            )
            db.conn.commit()

        bot.reply_to(m, f"服务消息自动清理{status_text}\n将自动删除：入群/退群/置顶等服务消息")
        logger.info(f"服务消息清理设置变更: chat={chat_id} enabled={enabled} by uid={uid}")

    except Exception as e:
        logger.error(f"服务消息清理设置失败: {e}")
        bot.reply_to(m, "❌ 设置失败，请稍后再试")


def check_clean_service(bot, m, config, db) -> bool:
    """检查服务消息是否应被删除（在消息分发中调用）

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例

    Returns:
        bool: True表示该消息是服务消息且应被删除
    """
    # 非群组消息不处理
    if not m.chat or m.chat.type == "private":
        return False

    # 不是服务消息不处理
    if not _is_service_message(m):
        return False

    chat_id = m.chat.id
    enabled = _get_clean_setting(db, chat_id)

    if not enabled:
        return False

    # 延迟删除服务消息（给一点缓冲时间让其他模块处理）
    if not can_delete_message(config):
        logger.info(f"[服务消息清理] 消息删除已禁用，跳过删除消息")
        return True  # 返回True表示已处理，但不执行删除

    try:
        import threading
        def _delayed_delete():
            try:
                bot.delete_message(chat_id, m.message_id)
                logger.debug(f"🗑️ 已清理服务消息: chat={chat_id} msg={m.message_id} type={m.content_type}")
            except Exception as e:
                logger.debug(f"消息删除异常: {e}")  # 消息已删除或无权限，静默忽略
        threading.Timer(3.0, _delayed_delete).start()
    except Exception as e:
        logger.warning(f"服务消息删除调度失败: {e}")

    return True
