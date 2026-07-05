"""
tasks/interaction/leak_task.py - 背刺泄密任务

每周一次在群里"偷偷"爆料关于 Mory 的小秘密，增强人设真实感。
"""

import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort, retry_task, send_and_track
from tasks.support.message_templates import MessageTemplates

logger = get_logger("tasks.interaction.leak")

_CST = timezone(timedelta(hours=8))


def _generate_leak_text(rm) -> str:
    """AI 生成背刺泄密文案。"""
    seed = random.randint(100000, 999999)
    scene_hint = random.choice([
        "在便利店买东西", "一个人看电视剧", "刷手机的时候",
        "发呆的时候", "跟闺蜜聊天", "自拍的时候", "做饭的时候",
        "洗澡前", "刚睡醒", "走路的时候", "吃零食的时候",
        "整理房间", "加班的时候", "逛街的时候", "坐地铁的时候",
        "打视频电话", "化妆的时候", "喝奶茶的时候", "拍照片",
    ])
    prompt = (
        f"种子{seed}，场景：{scene_hint}。"
        f"用极度八卦、偷偷摸摸的语气，泄露一个关于Mory非常可爱、"
        f"生活化的小癖好或小秘密。要求：\n"
        f"1. 必须是全新的、独特的内容，绝对不能重复\n"
        f"2. 要有画面感和生活气息\n"
        f"3. 控制在25字以内\n"
        f"4. 不要出现任何编号、序号或列表格式\n"
        f"5. 只说Mory，不以任何'老板/boss'自称"
    )

    try:
        with rm.locked('ai'):
            leak = rm.ai.ask(prompt, mode="leak", seed=seed)
        if leak:
            return leak.strip()
    except Exception as e:
        logger.debug(f"AI生成背刺泄密文案失败: {e}")
    return ""


class LeakTask(BaseTask):
    """背刺泄密任务（每周一次）。"""

    @property
    def task_id(self) -> str:
        return "leak"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "leak",
            "trigger": "cron",
            "day_of_week": "wed",
            "hour": 0,
            "minute": 5,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            with TaskTransactionManager("leak", self.rm.db, resources=None,
                                        min_interval_sec=86400) as tx:
                if not tx.claimed:
                    return

                now = datetime.now(_CST)
                current_week = now.isocalendar()[1]
                gid = self.rm.config.get("GROUP_ID", 0)
                last_leak_week = self.rm.config.get("_LAST_LEAK_WEEK", -1)

                if gid == 0 or current_week == last_leak_week or now.weekday() < 2:
                    raise TaskAbort("条件不满足", expected=True)

                leak = _generate_leak_text(self.rm)
                if not leak:
                    raise TaskAbort("AI 生成失败")

                leak_prefix = MessageTemplates.get_leak_prefix()
                sent = send_and_track(self.rm, gid, f"{leak_prefix}{leak}")
                if not sent:
                    raise TaskAbort("发送失败")

                self.rm.config["_LAST_LEAK_WEEK"] = current_week
                save_fn = self.rm.save_config_fn
                if save_fn:
                    save_fn()
                logger.info(f"🤫 背刺泄密触发(周{current_week})：{leak[:30]}")
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"背刺泄密失败：{e}")
            retry_task(self.rm, self.run, "leak")
