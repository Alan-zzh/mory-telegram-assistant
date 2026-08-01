"""非活跃用户问候任务（默认关闭，无销售或关系施压）。"""

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

_REACTIVATE_FORBIDDEN_MARKERS = (
    "@", "http", "下单", "购买", "订阅", "预览", "价格", "福利", "优惠", "名额",
    "私聊", "定制", "回复我", "回我", "吃醋", "别人", "忘了我", "亏欠", "陪你",
    "刚醒", "刚洗", "咖啡", "沙发", "窗外", "被窝",
)


def _is_safe_reactivate_message(value: object) -> bool:
    """主动召回不能接受模型塞入的成交、关系施压或虚构生活。"""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return 10 <= len(text) <= 70 and not any(
        marker in text.lower() for marker in _REACTIVATE_FORBIDDEN_MARKERS
    )


def _generate_reactivate_message(uid: int, rm) -> str:
    """AI 生成一次中性问候。"""
    seed = uid + int(time.time()) // 86400
    prompt = f"""你是公开身份的 Mory 小助理。
给一位最近没有活跃的用户写一条可忽略的中性问候。

要求：
1. 20-45字，自然、简短、不要求回复
2. 只表达关心，不谈购买、预览、福利或价格
3. 不吃醋、不撒娇、不制造亏欠感，不假装与用户有亲密关系
4. 不含任何入口、CTA、销售、定制、私聊或关系施压
5. seed={seed}

禁止：
- 不提具体未活跃天数
- 不声称自己是真人，不虚构生活场景"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="reactivate", seed=seed)
        if _is_safe_reactivate_message(msg):
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成挽回话术失败: {e}")
    return MessageTemplates.get_reactivate_fallback()


class ReactivateTask(BaseTask):
    """非活跃用户问候（默认关闭）。"""

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
            cfg = self.rm.config.get("REACTIVATE_CONFIG", {})
            if not isinstance(cfg, dict) or not cfg.get("enabled", False):
                logger.info("非活跃用户问候未开启，跳过")
                return
            _window = datetime.now(_CST).strftime("%Y-%m-%d_%H")
            task_key = f"reactivate_{_window}"
            with TaskTransactionManager(task_key, self.rm.db, resources=None, min_interval_sec=3600) as tx:
                if not tx.claimed:
                    return

                ts = int(time.time())
                three_days_ago = ts - 259200
                inactive = self.rm.db.get_inactive_users(three_days_ago, self.rm.config.get("ADMIN_ID", 0))

                sent_count = 0
                failures = []
                max_per_run = max(0, min(int(cfg.get("max_per_run", 3)), 10))
                sample_rate = max(0.0, min(float(cfg.get("sample_rate", 0.25)), 1.0))
                for uid, _name in inactive[:max_per_run]:
                    if random.random() < sample_rate:
                        try:
                            reactivate_msg = _generate_reactivate_message(uid, self.rm)
                            with self.rm.locked('bot'):
                                self.rm.bot.send_message(uid, reactivate_msg)
                            self.rm.db.reset_last_active(uid)
                            sent_count += 1
                            logger.info(f"💌 非活跃用户问候：{uid}")
                        except Exception as e:
                            err_str = str(e).lower()
                            if "chat not found" in err_str or "bot was blocked" in err_str or "forbidden" in err_str:
                                try:
                                    self.rm.db.delete_user(uid)
                                    logger.debug(f"非活跃用户问候跳过无效用户 uid={uid}（已清理）")
                                except Exception as cleanup_err:
                                    logger.error(f"非活跃无效用户清理失败 uid={uid}: {cleanup_err}")
                                    failures.append(cleanup_err)
                            else:
                                logger.warning(f"非活跃用户问候发送失败 uid={uid}：{e}")
                                failures.append(e)

                if failures:
                    raise ExceptionGroup("非活跃用户问候发送失败", failures)
                if sent_count == 0:
                    raise TaskAbort("无发送目标", expected=True)
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            logger.error(f"非活跃用户问候失败：{e}")
            raise
