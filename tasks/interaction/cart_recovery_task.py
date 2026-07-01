"""
tasks/interaction/cart_recovery_task.py - 购物车挽回任务

每 5 分钟检查一次处于挽回阶段的潜在用户，按时间衰减策略发送不同风格消息。
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

logger = get_logger("tasks.interaction.cart_recovery")

_CST = timezone(timedelta(hours=8))

# 阶段 → 人设风格 prompt
_STAGE_PROMPTS = {
    0: """你是Mory，一个傲娇的小姐姐。

一个用户刚才问了门槛/价格但没付费就走了，你要用傲娇的语气把他叫回来。

要求：
1. 30-50字，带点小情绪，撩人但不卑微
2. 像闺蜜私聊一样，带点"哼""喂"这种小语气词
3. 不要直接提"门槛"或"价格"，用隐晦的方式表达
4. 要让人感觉你有点在意他，但又不想表现出来
5. 结尾要有emoji
6. seed={seed}，每次必须不同

禁止：
- 不要出现"门槛"、"价格"、"付费"、"钱"这些词
- 不要太长，控制在50字以内""",

    1: """你是Mory，一个贴心的小姐姐。

一个用户2小时前问了门槛/价格但没付费，你要用"给好处"的方式把他叫回来。

要求：
1. 40-60字，暗示有专属福利/限时优惠
2. 像闺蜜私聊一样，神秘兮兮地说有好东西
3. 不要直接提"门槛"或"价格"或"优惠券"，用"福利""惊喜""名额"等词
4. 要让人感觉错过了会后悔，但不逼迫
5. 结尾要有emoji
6. seed={seed}，每次必须不同

禁止：
- 不要出现"门槛"、"价格"、"付费"、"钱"、"优惠券"这些词
- 不要太长，控制在60字以内""",

    2: """你是Mory，一个清冷但温柔的小姐姐。

一个用户昨天问了门槛/价格但没付费，你要用温柔但不纠缠的方式最后说一次。

要求：
1. 40-60字，清冷温柔，不纠缠不卑微
2. 像在告别，又像在等
3. 不要催促，不要施压，表达"我还在"即可
4. 要让人感觉有点遗憾，但又尊重对方的选择
5. 结尾要有emoji
6. seed={seed}，每次必须不同

禁止：
- 不要出现"门槛"、"价格"、"付费"、"钱"、"优惠券"这些词
- 不要太长，控制在60字以内""",
}

_STAGE_NAMES = {0: "傲娇催促", 1: "利益诱导", 2: "清冷关怀"}


def _generate_cart_recovery_message(uid: int, rm, stage: int = 0) -> str:
    """生成购物车挽回消息（按阶段选文案池），AI 失败则 fallback。"""
    seed = uid + int(time.time()) // 43200  # 每半天固定
    prompt = _STAGE_PROMPTS.get(stage, _STAGE_PROMPTS[0]).format(seed=seed)

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="cart_recovery", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成购物车挽回话术失败 stage={stage}: {e}")

    return MessageTemplates.get_cart_recovery_text(stage)


class CartRecoveryTask(BaseTask):
    """购物车挽回任务（每 5 分钟检查）。"""

    @property
    def task_id(self) -> str:
        return "cart_recovery"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "cart_recovery",
            "trigger": "cron",
            "minute": "*/5",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 120,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            _window = datetime.now(_CST).strftime("%Y-%m-%d_%H%M")
            task_key = f"cart_recovery_{_window}"
            with TaskTransactionManager(task_key, self.rm.db, resources=['bot', 'config'],
                                        min_interval_sec=300) as tx:
                if not tx.claimed:
                    return

                sent_count = 0
                pending = self.rm.db.get_pending_cart_recoveries(limit=20)

                for uid, stage in pending:
                    if sent_count >= 10:
                        break

                    try:
                        cart_msg = _generate_cart_recovery_message(uid, self.rm, stage)
                        with self.rm.locked('bot'):
                            self.rm.bot.send_message(uid, cart_msg)
                        sent_count += 1

                        next_stage = stage + 1
                        if next_stage <= 2:
                            self.rm.db.advance_recovery_stage(uid, next_stage)
                            logger.info(
                                f"🛒 购物车挽回 stage={stage}({_STAGE_NAMES.get(stage, '?')}) "
                                f"→ stage={next_stage}: uid={uid}"
                            )
                        else:
                            self.rm.db.cancel_cart_recovery(uid)
                            logger.info(f"🛒 购物车挽回终态: uid={uid}")

                    except Exception as e:
                        err_str = str(e).lower()
                        if any(kw in err_str for kw in (
                            "chat not found", "bot was blocked", "forbidden",
                            "bot was kicked", "user is deactivated"
                        )):
                            self.rm.db.delete_user(uid)
                            self.rm.db.cancel_cart_recovery(uid)
                            logger.debug(f"💔 购物车挽回跳过无效用户 uid={uid}（已清理）")
                        else:
                            logger.warning(f"购物车挽回发送失败 uid={uid} stage={stage}: {e}")

                if sent_count == 0:
                    raise TaskAbort("无发送目标")
                logger.info(f"🛒 购物车挽回本轮发送 {sent_count} 条")
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"购物车挽回失败：{e}")
