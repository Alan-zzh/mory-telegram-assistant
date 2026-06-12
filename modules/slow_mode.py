"""
慢速模式模块

功能：限制群内消息发送频率，防止刷屏。
  - 管理员可设置慢速模式间隔（5~3600秒）
  - 违反间隔的消息自动删除
  - 关闭后恢复正常

存储：system_states 表
  - slow_mode_{chat_id} → 间隔秒数（0=关闭）
  - slow_last_{chat_id}_{uid} → 用户上次发言时间戳
"""

import time
from core.helpers import can_delete_message
from core.logging_util import get_logger

logger = get_logger("slow_mode")


def handle_slow_mode(bot, m, config, db, interval_str):
    """设置或关闭慢速模式

    Args:
        bot: Telegram Bot 实例
        m: 消息对象
        config: 配置字典
        db: 数据库实例
        interval_str: 间隔参数字符串，"0"/"关"/"off" 关闭，否则为秒数
    """
    chat_id = m.chat.id

    # 关闭慢速模式
    if interval_str.strip() in ("0", "关", "off"):
        db.set_system_state(f"slow_mode_{chat_id}", "0")
        bot.reply_to(m, "慢速模式已关闭")
        logger.info(f"慢速模式关闭: chat_id={chat_id}")
        return

    # 解析间隔秒数
    try:
        interval = int(interval_str.strip())
    except ValueError:
        bot.reply_to(m, "⚠️ 间隔必须是整数秒（5~3600）")
        return

    if interval < 5:
        bot.reply_to(m, "⚠️ 间隔最少5秒")
        return
    if interval > 3600:
        bot.reply_to(m, "⚠️ 间隔最多3600秒（1小时）")
        return

    db.set_system_state(f"slow_mode_{chat_id}", str(interval))
    bot.reply_to(m, f"慢速模式已开启：每{interval}秒可发送1条消息")
    logger.info(f"慢速模式开启: chat_id={chat_id} interval={interval}s")


def check_slow_mode(bot, m, config, db):
    """检查消息是否违反慢速模式

    Args:
        bot: Telegram Bot 实例
        m: 消息对象
        config: 配置字典
        db: 数据库实例

    Returns:
        True: 消息应被删除（违反慢速模式）
        False: 消息允许通过
    """
    chat_id = m.chat.id
    uid = m.from_user.id

    # 读取慢速模式间隔
    interval_str = db.get_system_state(f"slow_mode_{chat_id}", "0")
    try:
        interval = int(interval_str)
    except (ValueError, TypeError):
        interval = 0

    if interval <= 0:
        return False

    # 检查用户上次发言时间
    now = int(time.time())
    last_key = f"slow_last_{chat_id}_{uid}"
    last_str = db.get_system_state(last_key, "0")
    try:
        last_time = int(last_str)
    except (ValueError, TypeError):
        last_time = 0

    if now - last_time < interval:
        # 违反慢速模式
        if can_delete_message(config):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception as e:
                logger.warning(f"删除慢速模式消息失败: chat_id={chat_id} uid={uid} err={e}")
        else:
            logger.info(f"[慢速模式] 消息删除已禁用，跳过删除消息")
        logger.info(f"慢速模式拦截: chat_id={chat_id} uid={uid} elapsed={now - last_time}s")
        return True

    # 更新用户最后发言时间
    db.set_system_state(last_key, str(now))
    return False
