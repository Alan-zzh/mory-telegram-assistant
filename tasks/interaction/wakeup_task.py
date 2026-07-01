"""
tasks/interaction/wakeup_task.py - 叫醒服务任务

每分钟检查是否有设置了叫醒服务的用户到达指定时间，并发送个性化叫醒消息。
"""

import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext
from tasks.support.message_templates import MessageTemplates

logger = get_logger("tasks.interaction.wakeup")

_CST = timezone(timedelta(hours=8))


def _generate_wakeup_message(uid: int, now: datetime, rm) -> str:
    """AI 生成个性化叫醒语。"""
    seed = uid + int(now.timestamp())
    hour = now.hour
    prompt = f"""你是Mory，一个有血有肉的真人女孩。现在是北京时间{hour}点。

给用户生成一条叫醒消息，要求：
1. 30-50字，自然利落，像朋友叫你起床
2. 语气清冷带点傲娇，不撒娇不萌
3. 随机选择一个场景/理由叫醒他
4. seed={seed}，每次必须不同

禁止：
- 不要太长，控制在50字以内
- 不要撒娇卖萌、刻意可爱
- 不要重复相同的开头"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="wakeup", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成叫醒话术失败: {e}")
    return MessageTemplates.get_wakeup_fallback()


class WakeupTask(BaseTask):
    """叫醒服务任务（每分钟检查）。"""

    @property
    def task_id(self) -> str:
        return "wakeup_check"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "wakeup_check",
            "trigger": "cron",
            "minute": "*",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 60,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            now = datetime.now(_CST)
            time_str = now.strftime("%H:%M")

            # 只在读取时持有 db 锁，避免与 ai→config 顺序冲突
            with self.rm.locked('db'):
                wake_ups = [(uid, wt) for uid, wt in self.rm.db.get_all_wake_ups() if wt == time_str]

            for uid, _ in wake_ups:
                try:
                    wake_msg = _generate_wakeup_message(uid, now, self.rm)
                    with self.rm.locked('bot'):
                        self.rm.bot.send_message(uid, wake_msg)
                    logger.info(f"⏰ 叫醒服务：uid={uid}")
                except Exception as e:
                    logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")
        except Exception as e:
            logger.error(f"叫醒服务检查失败：{e}")
