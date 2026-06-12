"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/scheduled_broadcast.py  ·  定点播报增强模块                   ║
║                                                                        ║
║  功能：自定义定时播报，支持多个时间点、多种内容类型。                    ║
║
║  配置：                                                                ║
║    SCHEDULED_BROADCASTS: [                                             ║
║        {                                                               ║
║            "id": "custom_broadcast_1",                                 ║
║            "time": "10:00",         // HH:MM                           ║
║            "content": "文本内容",                                        ║
║            "type": "text",          // text/image/voice                ║
║            "frequency": "daily",     // daily/weekly/monthly           ║
║            "enabled": true                                            ║
║        }                                                               ║
║    ]                                                                   ║
║
║  被调用：main.py 定时任务系统                                          ║
══════════════════════════════════════════════════════════════════════════╝
"""

import random
from core.logging_util import get_logger

logger = get_logger("scheduled_broadcast")


def execute_scheduled_broadcast(bot, chat_id, config: dict, db=None):
    """
    执行定点播报
    被 auto_tasks.py 定时任务调用
    """
    broadcasts = config.get("SCHEDULED_BROADCASTS", [])

    for bc in broadcasts:
        if not bc.get("enabled", False):
            continue

        broadcast_id = bc.get("id", "")
        if not broadcast_id:
            continue

        # 检查今天是否已执行（防重复）
        if db:
            from datetime import datetime, timezone, timedelta
            _CST = timezone(timedelta(hours=8))
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            task_key = f"scheduled_broadcast_{broadcast_id}_{today}"
            if db.is_task_executed_today(task_key):
                logger.debug(f"⏭️ 播报 {broadcast_id} 今日已执行，跳过")
                continue
            if not db.claim_task(task_key):
                logger.debug(f"️ 播报 {broadcast_id} 被其他进程抢占，跳过")
                continue

        # 执行播报
        content_type = bc.get("type", "text")
        content = bc.get("content", "")

        if content_type == "text":
            try:
                msg = bot.send_message(chat_id, content)
                logger.info(f" 定点播报: {broadcast_id}")
                # 追踪消息
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "text")
            except Exception as e:
                logger.warning(f"定点播报发送失败 {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception:
                        pass

        elif content_type == "image":
            # content 可以是 file_id 或 URL
            try:
                msg = bot.send_photo(chat_id, content, caption=bc.get("caption", ""))
                logger.info(f"📢 定点播报(图片): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "image")
            except Exception as e:
                logger.warning(f"定点播报发送失败(图片) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception:
                        pass

        elif content_type == "voice":
            try:
                msg = bot.send_voice(chat_id, content)
                logger.info(f" 定点播报(语音): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "voice")
            except Exception as e:
                logger.warning(f"定点播报发送失败(语音) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception:
                        pass


def get_broadcast_schedule(config: dict):
    """获取播报时间表（用于定时任务注册）"""
    broadcasts = config.get("SCHEDULED_BROADCASTS", [])
    schedule = []

    for bc in broadcasts:
        if not bc.get("enabled", False):
            continue

        time_str = bc.get("time", "")
        if not time_str:
            continue

        parts = time_str.split(":")
        if len(parts) != 2:
            continue

        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            continue

        frequency = bc.get("frequency", "daily")

        schedule.append({
            "id": bc.get("id", ""),
            "hour": hour,
            "minute": minute,
            "frequency": frequency,
            "day_of_week": bc.get("day_of_week", None),  # 0-6, 周一=0
            "day_of_month": bc.get("day_of_month", None),  # 1-31
        })

    return schedule
