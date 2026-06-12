"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/anti_raid.py  ·  反突袭保护模块                               ║
║                                                                        ║
║  功能：检测并应对群组突袭（短时间内大量入群）                           ║
║                                                                        ║
║  check_raid()          -> 检测突袭并触发锁群                           ║
║  check_raid_mode()     -> 检查突袭模式是否激活                         ║
║  deactivate_raid()     -> 解除突袭警报                                 ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.logging_util import get_logger

logger = get_logger("anti_raid")

# 默认突袭检测配置
DEFAULT_ANTI_RAID_CONFIG = {
    "threshold": 5,          # 触发阈值：window内入群人数
    "window_seconds": 60,    # 检测窗口（秒）
    "lock_duration": 300     # 锁群时长（秒）
}


def _get_config(config):
    """获取突袭检测配置，合并默认值"""
    user_config = config.get("ANTI_RAID_CONFIG", {})
    merged = dict(DEFAULT_ANTI_RAID_CONFIG)
    merged.update(user_config)
    return merged


def check_raid(bot, m, config, db):
    """检测突袭（在new_chat_members事件中调用）

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: 数据库实例

    Returns:
        bool: True表示检测到突袭
    """
    chat_id = m.chat.id
    raid_cfg = _get_config(config)
    threshold = raid_cfg["threshold"]
    window = raid_cfg["window_seconds"]
    lock_duration = raid_cfg["lock_duration"]

    now = int(time.time())
    window_start = now - window

    # 统计窗口内入群人数
    with db.conn:
        row = db.conn.execute(
            "SELECT COUNT(*) FROM group_join_log WHERE chat_id=? AND ts>?",
            (chat_id, window_start)
        ).fetchone()

    count = row[0] if row else 0

    if count < threshold:
        return False

    # 触发突袭模式
    logger.warning(f"🚨 突袭检测触发! chat={chat_id} count={count} window={window}s")

    # 设置系统状态
    db.set_system_state(f"raid_mode_{chat_id}", "1")
    db.set_system_state(f"raid_unlock_ts_{chat_id}", str(now + lock_duration))

    admin_id = config.get("ADMIN_ID", 0)
    admin_msg = (
        f"🚨 <b>突袭警报！</b>\n"
        f"📊 {count}人在{window}秒内入群，已自动锁群\n"
        f"⏱ 锁群时长：{lock_duration // 60}分钟\n"
        f"🔒 群组已进入保护模式"
    )
    try:
        if admin_id:
            bot.send_message(admin_id, admin_msg, parse_mode="HTML")
        else:
            logger.warning("⚠️ ADMIN_ID未配置，突袭警报无法私信发送，回退到群聊")
            bot.send_message(chat_id, admin_msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ 发送突袭警报失败: {e}")

    return True


def check_raid_mode(chat_id, db):
    """检查突袭模式是否激活

    Args:
        chat_id: 群组ID
        db: 数据库实例

    Returns:
        bool: True表示突袭模式激活中
    """
    raid_mode = db.get_system_state(f"raid_mode_{chat_id}")
    if raid_mode != "1":
        return False

    # 检查是否已过锁群时间
    unlock_ts_str = db.get_system_state(f"raid_unlock_ts_{chat_id}")
    if unlock_ts_str:
        try:
            unlock_ts = int(unlock_ts_str)
            if int(time.time()) >= unlock_ts:
                # 自动解除
                db.set_system_state(f"raid_mode_{chat_id}", "0")
                db.set_system_state(f"raid_unlock_ts_{chat_id}", "0")
                logger.info(f"✅ 突袭模式自动解除: chat={chat_id}")
                return False
        except (ValueError, TypeError) as exc:
            logger.warning(f"反突袭时间戳解析异常 chat={chat_id}: {exc}")

    return True


def deactivate_raid(bot, chat_id, config, db):
    """解除突袭警报

    Args:
        bot: TeleBot实例
        chat_id: 群组ID
        config: 配置字典
        db: 数据库实例
    """
    db.set_system_state(f"raid_mode_{chat_id}", "0")
    db.set_system_state(f"raid_unlock_ts_{chat_id}", "0")

    admin_id = config.get("ADMIN_ID", 0)
    try:
        if admin_id:
            bot.send_message(admin_id, "✅ 突袭警报已解除", parse_mode="HTML")
        else:
            bot.send_message(chat_id, "✅ 突袭警报已解除", parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ 发送解除警报失败: {e}")

    logger.info(f"✅ 突袭警报已手动解除: chat={chat_id}")
