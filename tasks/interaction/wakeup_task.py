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
    prompt = f"""你是公开身份的 Mory 小助理。现在是北京时间{hour}点。

给用户生成一条叫醒消息，要求：
1. 30-50字，自然利落，像朋友叫你起床
2. 语气自然，不撒娇、不调情、不销售
3. 只根据当前时间提醒，不虚构天气、行程或生活场景
4. seed={seed}，每次必须不同

禁止：
- 不要太长，控制在50字以内
- 不要声明自己是真人，不要撒娇卖萌、刻意可爱
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
        now = datetime.now(_CST)
        time_str = now.strftime("%H:%M")

        # 只在读取时持有 db 锁，避免与 ai→config 顺序冲突。
        # 没有匹配用户是预期空集；读取失败则必须让调度器记录失败。
        with self.rm.locked('db'):
            wake_ups = [(uid, wt) for uid, wt in self.rm.db.get_all_wake_ups() if wt == time_str]

        failures = []
        for uid, _ in wake_ups:
            try:
                wake_msg = _generate_wakeup_message(uid, now, self.rm)
                with self.rm.locked('bot'):
                    self.rm.bot.send_message(uid, wake_msg)
                logger.info(f"⏰ 叫醒服务：uid={uid}")
            except Exception as e:
                logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")
                failures.append(e)

        if failures:
            raise ExceptionGroup("叫醒服务发送失败", failures)
