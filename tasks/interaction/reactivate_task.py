"""
tasks/interaction/reactivate_task.py - 醋意挽回任务

每小时检查 3 天未活跃的用户，发送个性化醋意挽回消息。
"""

import random
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort
from tasks.support.message_templates import MessageTemplates

logger = get_logger("tasks.interaction.reactivate")

_CST = timezone(timedelta(hours=8))


def _generate_reactivate_message(uid: int, rm) -> str:
    """AI 生成醋意挽回消息。"""
    seed = uid + int(time.time()) // 86400
    prompt = f"""你是Mory，一个有点小醋意的小姐姐。

一个用户已经3天没来聊天了，你要写一条消息把他叫回来。

要求：
1. 40-60字，撒娇吃醋风格
2. 像闺蜜私聊一样，带点小委屈小醋意
3. 不要太直白，要撩人要心痒痒
4. 可以暗示：你是不是有别人了/你是不是把我忘了/是不是我哪里不够好
5. 结尾要有emoji
6. seed={seed}，每次必须不同

禁止：
- 不要出现"3天"这个具体数字
- 不要太长，控制在60字以内"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="reactivate", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成挽回话术失败: {e}")
    return MessageTemplates.get_reactivate_fallback()


class ReactivateTask(BaseTask):
    """醋意挽回任务（每小时）。"""

    @property
    def task_id(self) -> str:
        return "reactivate"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "reactivate",
            "trigger": "cron",
            "minute": 5,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            _window = datetime.now(_CST).strftime("%Y-%m-%d_%H")
            task_key = f"reactivate_{_window}"
            with TaskTransactionManager(task_key, self.rm.db, resources=['bot', 'config'], min_interval_sec=3600) as tx:
                if not tx.claimed:
                    return

                ts = int(time.time())
                three_days_ago = ts - 259200
                inactive = self.rm.db.get_inactive_users(three_days_ago, self.rm.config.get("ADMIN_ID", 0))

                sent_count = 0
                for uid, _name in inactive[:3]:
                    if random.random() < 0.25:
                        try:
                            reactivate_msg = _generate_reactivate_message(uid, self.rm)
                            self.rm.bot.send_message(uid, reactivate_msg)
                            self.rm.db.reset_last_active(uid)
                            sent_count += 1
                            logger.info(f"💌 醋意挽回：{uid}")
                        except Exception as e:
                            err_str = str(e).lower()
                            if "chat not found" in err_str or "bot was blocked" in err_str or "forbidden" in err_str:
                                self.rm.db.delete_user(uid)
                                logger.debug(f"💔 醋意挽回跳过无效用户 uid={uid}（已清理）")
                            else:
                                logger.warning(f"醋意挽回发送失败 uid={uid}：{e}")

                if sent_count == 0:
                    raise TaskAbort("无发送目标")
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"醋意挽回失败：{e}")
