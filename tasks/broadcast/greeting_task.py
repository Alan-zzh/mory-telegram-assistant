"""
tasks/broadcast/greeting_task.py - 早/午/晚安问候任务

负责按配置时间向管理群发送早安、午安、晚安问候，支持链式互删。
"""

import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from core.broadcast_cta import build_cta_markup, get_broadcast_cta
from core.broadcast_formatter import build_rich_greeting_html, build_rich_greeting_card_message
from core.broadcast_image_card import build_broadcast_image_card
from core.broadcast_image_payload import build_greeting_image_payload
from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import (
    TaskAbort,
    build_mory_contact_markup,
    retry_task,
    send_greeting,
)
from tasks.support.message_templates import MessageTemplates
from tasks.support.task_config import get_greeting_time, is_greeting_enabled, get_all_group_ids

logger = get_logger("tasks.broadcast.greeting")


class GreetingDeliveryError(RuntimeError):
    """至少一个目标群投递失败；partial 标识是否已有其他群发送成功。"""

    def __init__(self, period: str, failures: list, partial: bool):
        self.failures = failures
        self.partial = partial
        failed_groups = ",".join(str(gid) for gid, _ in failures)
        super().__init__(f"{period} 问候有 {len(failures)} 个群失败: {failed_groups}")


class GreetingTask(BaseTask):
    """早/午/晚安问候任务。"""

    @property
    def task_id(self) -> str:
        return "greeting"

    def schedule(self) -> List[Dict[str, Any]]:
        periods = ["morning", "afternoon", "evening"]
        schedule_list = []
        for period in periods:
            hour, minute = get_greeting_time(self.rm.config, period)
            schedule_list.append({
                "job_id": f"greeting_{period}",
                "trigger": "cron",
                "hour": hour,
                "minute": minute,
                "params": {"period": period},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 60,
                },
            })
        return schedule_list

    def execute(self, ctx: TaskContext) -> None:
        period = ctx.params.get("period", "morning")
        if not is_greeting_enabled(self.rm.config, period):
            logger.info(f"[Codex] {period} 问候未开启，跳过")
            return

        try:
            today = ctx.now_str("%Y-%m-%d")
            task_key = f"greeting_{period}_{today}"
            with TaskTransactionManager(task_key, self.rm.db, resources=None, min_interval_sec=7200) as tx:
                if not tx.claimed:
                    return

                group_ids = get_all_group_ids(self.rm.config)
                if not group_ids:
                    logger.warning(f"🌅 {period} 问候无管理群，跳过")
                    raise TaskAbort("无管理群")

                seed = random.randint(100000, 999999)
                msg = self.rm.ai.ask(
                    "早安" if period == "morning" else ("午安" if period == "afternoon" else "晚安"),
                    mode=period,
                    seed=seed,
                )
                if not MessageTemplates.is_usable_greeting(period, msg):
                    msg = MessageTemplates.get_fallback_greeting(period)
                    logger.info(f"🌅 {period} 问候未通过质量门禁，使用话术池兜底")

                # v5.35.6：正文与按钮分工，不再追加一段固定“温柔收尾”破坏短文案。
                msg = msg.strip()[:120]
                suffix = ""

                # [v5.38.15] 统一 CTA：文字版 closing、图片卡文案、真实按钮全部一致
                cfg = self.rm.config or {}
                cta = get_broadcast_cta(scene="greeting", period=period, config=cfg)
                closing = cta.get("closing", "")
                reply_markup = build_cta_markup(cta, config=cfg)

                # [v5.32] 同时构建 HTML 版本和 Rich Message 版本
                rich_html = build_rich_greeting_html(period, msg, suffix.strip(), closing=closing)
                rich_message_html = build_rich_greeting_card_message(period, msg, suffix.strip(), closing=closing)

                # [v5.38.15] 按需生成问候图片卡
                global_image_enabled = bool(cfg.get("BROADCAST_IMAGE_CARD_ENABLED", False))
                greeting_cfg = cfg.get("GREETING_CONFIG", {}) if isinstance(cfg, dict) else {}
                greeting_image_enabled = global_image_enabled and bool(greeting_cfg.get("image_card_enabled", False))
                image_path = ""
                if greeting_image_enabled:
                    try:
                        badge = str(greeting_cfg.get(f"{period}_badge", "") or "").strip()
                        image_payload = build_greeting_image_payload(period, msg, badge=badge)
                        _cst = timezone(timedelta(hours=8))
                        cache_key = f"greeting_{period}_{datetime.now(_cst).strftime('%Y%m%d')}"
                        image_path = build_broadcast_image_card(
                            image_payload,
                            cache_key=cache_key,
                            cta_pool="greeting",
                            config=cfg,
                            min_height=900,
                            cta_text=cta.get("image_label", ""),
                        ) or ""
                        if image_path and not os.path.isfile(image_path):
                            image_path = ""
                    except Exception as e:
                        logger.warning(f"🌅 {period} 问候图片卡生成失败，回退文字: {e}")
                        image_path = ""

                sent_count = 0
                failures = []
                for gid in group_ids:
                    try:
                        sent = send_greeting(
                            self.rm, gid, rich_html, f"greeting_{period}",
                            rich_text=rich_message_html,
                            reply_markup=reply_markup,
                            image_path=image_path,
                        )
                        if sent:
                            sent_count += 1
                            logger.info(f"🌅 {period} 问候已发送到群 {gid}：{msg}")
                        else:
                            failures.append((gid, RuntimeError("send_greeting 返回 False")))
                    except Exception as e:
                        logger.warning(f"🌅 {period} 问候发送到群 {gid} 失败: {e}")
                        failures.append((gid, e))

                if failures:
                    error = GreetingDeliveryError(period, failures, partial=sent_count > 0)
                    raise error from failures[0][1]
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            logger.error(f"{period} 问候失败：{e}")
            # 部分群已成功时不做整批自动重试，避免给成功群重复发送；调度器仍记录 ERROR。
            if not isinstance(e, GreetingDeliveryError) or not e.partial:
                retry_task(self.rm, lambda rm: self.run({"period": period}), f"greeting_{period}")
            raise
