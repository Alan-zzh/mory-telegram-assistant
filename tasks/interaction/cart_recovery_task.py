"""购物车召回任务：默认关闭；启用后每个候选只发一次温和预览提醒。"""

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

_RECOVERY_PROMPT = """你是公开身份的 Mory 小助理。
用户之前表达过了解意向。写一条一次性的温和提醒：
1. 只引导先去 @moryselect 看当前预览
2. 25-55字，明确由用户自行判断，不催促
3. 不给价格、福利、名额、规格或其他未经证实信息
4. 不导私聊、不直接导下单，不制造稀缺、后悔、亏欠或亲密关系
5. seed={seed}
只输出消息正文。"""

_CART_FORBIDDEN_MARKERS = (
    "@morychannelbot", "@moryfansbot", "http", "私聊", "定制", "下单", "订阅",
    "价格", "福利", "优惠", "名额", "限时", "最后", "错过", "稀缺", "大家都",
    "别人都", "刚醒", "刚洗", "咖啡", "沙发", "窗外", "被窝",
)


def _is_safe_cart_recovery_message(value: object) -> bool:
    """一次性预览提醒必须只有一个 @moryselect，拒绝模型偷偷追加成交或施压。"""
    if not isinstance(value, str):
        return False
    text = value.strip()
    lowered = text.lower()
    return (
        10 <= len(text) <= 90
        and lowered.count("@moryselect") == 1
        and "@" not in lowered.replace("@moryselect", "")
        and not any(marker in lowered for marker in _CART_FORBIDDEN_MARKERS)
    )


def _generate_cart_recovery_message(uid: int, rm, stage: int = 0) -> str:
    """生成购物车挽回消息（按阶段选文案池），AI 失败则 fallback。"""
    seed = uid + int(time.time()) // 43200  # 每半天固定
    prompt = _RECOVERY_PROMPT.format(seed=seed)

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="cart_recovery", seed=seed)
        if _is_safe_cart_recovery_message(msg):
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
        cfg = self.rm.config.get("CART_RECOVERY_CONFIG", {}) if self.rm.config else {}
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            return []
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
            cfg = self.rm.config.get("CART_RECOVERY_CONFIG", {})
            if not isinstance(cfg, dict) or not cfg.get("enabled", False):
                logger.info("购物车召回未开启，跳过")
                return
            _window = datetime.now(_CST).strftime("%Y-%m-%d_%H%M")
            task_key = f"cart_recovery_{_window}"
            with TaskTransactionManager(task_key, self.rm.db, resources=None,
                                        min_interval_sec=300) as tx:
                if not tx.claimed:
                    return

                sent_count = 0
                failures = []
                max_per_round = max(0, min(int(cfg.get("max_per_round", 10)), 20))
                pending = self.rm.db.get_pending_cart_recoveries(limit=max_per_round)

                for uid, stage in pending:
                    if sent_count >= max_per_round:
                        break

                    try:
                        cart_msg = _generate_cart_recovery_message(uid, self.rm, stage)
                        with self.rm.locked('bot'):
                            self.rm.bot.send_message(uid, cart_msg)
                        sent_count += 1

                        # 无论旧数据处于哪个 stage，成功发送后立即终止，避免重复骚扰。
                        self.rm.db.cancel_cart_recovery(uid)
                        logger.info(f"🛒 购物车单次预览提醒完成并取消: uid={uid} old_stage={stage}")

                    except Exception as e:
                        err_str = str(e).lower()
                        if any(kw in err_str for kw in (
                            "chat not found", "bot was blocked", "forbidden",
                            "bot was kicked", "user is deactivated"
                        )):
                            try:
                                self.rm.db.delete_user(uid)
                                self.rm.db.cancel_cart_recovery(uid)
                                logger.debug(f"💔 购物车挽回跳过无效用户 uid={uid}（已清理）")
                            except Exception as cleanup_err:
                                logger.error(f"购物车无效用户清理失败 uid={uid}: {cleanup_err}")
                                failures.append(cleanup_err)
                        else:
                            logger.warning(f"购物车挽回发送失败 uid={uid} stage={stage}: {e}")
                            failures.append(e)

                if failures:
                    raise ExceptionGroup("购物车挽回发送失败", failures)
                if sent_count == 0:
                    raise TaskAbort("无发送目标", expected=True)
                logger.info(f"🛒 购物车挽回本轮发送 {sent_count} 条")
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            logger.error(f"购物车挽回失败：{e}")
            raise
