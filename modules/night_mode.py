"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/night_mode.py  ·  夜间模式模块（参考 MissKatyPyro）           ║
║                                                                        ║
║  功能：夜间自动禁言非管理员，早上自动解禁。                              ║
║
║  流程：                                                                ║
║    1. 定时任务在设定时间开启夜间模式                                    ║
║    2. 禁言所有非管理员成员                                              ║
║    3. 定时任务在设定时间关闭夜间模式                                     ║
║    4. 解禁所有被夜间模式禁言的成员                                      ║
║
║  配置：                                                                ║
║    NIGHT_MODE_CONFIG: {                                                ║
║        "start_hour": 23,        // 开始时间（小时）                      ║
║        "end_hour": 7,           // 结束时间（小时）                      ║
║        "enable": true           // 是否启用                            ║
║    }                                                                   ║
║
║  被调用：main.py 定时任务系统 + P3.8 消息分发（拦截夜间消息）           ║
══════════════════════════════════════════════════════════════════════════╝
"""

from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

_CST = timezone(timedelta(hours=8))

logger = get_logger("night_mode")


def is_night_mode_active(config: dict) -> bool:
    """检查夜间模式是否启用"""
    night_config = config.get("NIGHT_MODE_CONFIG", {})
    if not night_config.get("enable", False):
        return False

    from datetime import datetime, timezone, timedelta
    _CST = timezone(timedelta(hours=8))
    now = datetime.now(_CST)
    start_hour = night_config.get("start_hour", 23)
    end_hour = night_config.get("end_hour", 7)

    if start_hour < end_hour:
        # 例如 1:00 - 6:00
        return start_hour <= now.hour < end_hour
    else:
        # 例如 23:00 - 7:00（跨天）
        return now.hour >= start_hour or now.hour < end_hour


def should_mute_for_night_mode(bot, m, config: dict) -> bool:
    """
    检查消息是否应该因夜间模式被拦截
    返回 True 表示应该拦截（禁言+删除消息）
    """
    if not is_night_mode_active(config):
        return False

    # 管理员豁免
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id == admin_id:
        return False

    # 检查是否是管理员（通过 get_chat_administrators）
    try:
        admins = bot.get_chat_administrators(m.chat.id)
        admin_ids = [a.user.id for a in admins]
        if m.from_user.id in admin_ids:
            return False
    except Exception as e:
        logger.debug(f"获取管理员列表异常: {e}")  # 获取管理员列表失败时不拦截

    return True


def send_night_mode_notification(bot, chat_id, config: dict, is_start: bool = True):
    """发送夜间模式开启/关闭通知"""
    night_config = config.get("NIGHT_MODE_CONFIG", {})
    start_hour = night_config.get("start_hour", 23)
    end_hour = night_config.get("end_hour", 7)

    if is_start:
        # 实现是“非管理员消息拦截删除”，不是真正的 API 禁言；
        # 文案必须如实描述，避免用户以为自己的发言权限被改了。
        msg = (
            f"🌙 夜间模式已开启！\n\n"
            f"⏰ 生效时间：{start_hour}:00 - {end_hour}:00\n"
            f"🔇 该时段内非管理员的消息会被暂时拦下（并非修改账号权限）\n"
            f"💤 管理员不受影响，请好好休息～"
        )
    else:
        h = datetime.now(_CST).hour
        if 5 <= h < 11:
            greeting = "大家早上好～"
        elif 11 <= h < 14:
            greeting = "大家中午好～"
        elif 14 <= h < 18:
            greeting = "大家下午好～"
        else:
            greeting = "大家可以正常聊天啦～"
        msg = (
            f"☀️ 夜间模式已关闭！\n\n"
            f" {greeting}可以正常聊天了！"
        )

    try:
        bot.send_message(chat_id, msg)
        logger.info(f"🌙 夜间模式通知: {'开启' if is_start else '关闭'} chat_id={chat_id}")
    except Exception as e:
        logger.warning(f"发送夜间模式通知失败: {e}")


def start_night_mode(bot, chat_id, config: dict):
    """开启夜间模式：发送通知，禁言由 should_mute_for_night_mode 按需拦截"""
    logger.info(f"🌙 开启夜间模式: chat_id={chat_id}")

    # 发送通知（pyTelegramBotAPI 没有 get_chat_members 方法，
    # 无法遍历全体成员禁言，改为消息拦截模式）
    send_night_mode_notification(bot, chat_id, config, is_start=True)
    logger.info(f"🌙 夜间模式开启完成（消息拦截模式）: chat_id={chat_id}")


def end_night_mode(bot, chat_id, config: dict):
    """关闭夜间模式：发送通知，禁言由 should_mute_for_night_mode 按需解除"""
    logger.info(f"☀️ 关闭夜间模式: chat_id={chat_id}")

    # 发送通知（pyTelegramBotAPI 没有 get_chat_members 方法，
    # 无法遍历全体成员解禁，改为消息拦截模式停止拦截）
    send_night_mode_notification(bot, chat_id, config, is_start=False)
    logger.info(f"☀️ 夜间模式关闭完成（消息拦截模式停止）: chat_id={chat_id}")
