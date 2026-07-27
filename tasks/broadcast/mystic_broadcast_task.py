"""早间黄历、午间塔罗与晚间易经播报任务。"""

from __future__ import annotations

from typing import Any, Dict, List

from core.broadcast_formatter import build_mystic_html, build_rich_mystic_card_message
from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import (
    TaskAbort,
    record_abort,
    retry_task,
    schedule_auto_delete,
    send_and_track,
)
from tasks.support.mystic_content import build_mystic_broadcast, is_usable_mystic_broadcast
from tasks.support.task_config import get_mystic_time, is_mystic_enabled


logger = get_logger("tasks.broadcast.mystic")

_PERIOD_LABELS = {
    "morning": "早间",
    "afternoon": "午间",
    "evening": "晚间",
}


def build_mystic_cta_markup(payload: dict):
    """每张卡最多一个、且与正文说明一致的 CTA。"""
    cta = payload.get("cta")
    if not isinstance(cta, dict):
        return None
    from telebot import types
    from core.telebot_compat import create_colored_button

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(create_colored_button(
        text=str(cta["label"]),
        url=str(cta["url"]),
        style=str(cta.get("style", "default")),
    ))
    return markup


def execute_mystic_broadcast_task(rm, task_name: str, period: str) -> None:
    """生成、发送并追踪一张传统文化栏目卡片。"""
    if not is_mystic_enabled(rm.config):
        logger.debug("玄学播报未开启，跳过")
        return

    try:
        with TaskTransactionManager(task_name, rm.db, resources=None, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            gid = int(rm.config.get("GROUP_ID", 0) or 0)
            if not gid:
                record_abort(task_name, "GROUP_ID为0")
                raise TaskAbort("GROUP_ID为0")

            payload = build_mystic_broadcast(rm.config, period)
            if not is_usable_mystic_broadcast(payload):
                record_abort(task_name, "玄学播报内容未通过门禁")
                raise TaskAbort("玄学播报内容未通过门禁")

            rich_message = build_rich_mystic_card_message(payload)
            html_message = build_mystic_html(payload)
            reply_markup = build_mystic_cta_markup(payload)
            cfg = rm.config or {}
            rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))
            format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
            sent = None

            if rich_enabled and format_version in {"rich", "auto"}:
                try:
                    from core.telebot_compat import send_rich_message_compat

                    with rm.locked("bot"):
                        sent = send_rich_message_compat(
                            rm.bot,
                            gid,
                            rich_message,
                            reply_markup=reply_markup,
                        )
                    if sent and hasattr(sent, "message_id"):
                        schedule_auto_delete(rm, gid, sent.message_id, 24 * 3600)
                        rm.db.track_channel_message(gid, sent.message_id, "text")
                        rm.db.track_bot_message(gid, sent.message_id)
                    else:
                        sent = None
                except Exception as exc:
                    logger.warning(f"{payload['title']} Rich Message 发送失败，回退 HTML: {exc}")
                    sent = None

            if sent is None:
                sent = send_and_track(
                    rm,
                    gid,
                    html_message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )

            if not sent or not hasattr(sent, "message_id"):
                record_abort(task_name, "玄学播报发送失败")
                raise TaskAbort("玄学播报发送失败")

            try:
                rm.db.track_broadcast(gid, "mystic", sent.message_id)
            except Exception as exc:
                logger.debug(f"玄学播报追踪入库失败: {exc}")
            logger.info(
                f"✅ {payload['title']}已发送"
                f"（mode={payload['mode']}，msg={sent.message_id}，"
                f"cta={(payload.get('cta') or {}).get('target', 'none')}）"
            )
    except TaskAbort:
        pass
    except Exception as exc:
        logger.error(f"玄学播报失败：{exc}")
        retry_task(
            rm,
            lambda rm_inner: execute_mystic_broadcast_task(rm_inner, task_name, period),
            task_name,
        )


class MysticBroadcastTask(BaseTask):
    """早、午、晚三档传统文化栏目。"""

    @property
    def task_id(self) -> str:
        return "mystic_broadcast"

    def schedule(self) -> List[Dict[str, Any]]:
        schedule_list = []
        for period in ("morning", "afternoon", "evening"):
            hour, minute = get_mystic_time(self.rm.config, period)
            schedule_list.append({
                "job_id": f"mystic_{period}",
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
        period = str(ctx.params.get("period", "morning"))
        task_name = f"mystic_{period}"
        logger.info(f"🔮 触发{_PERIOD_LABELS.get(period, period)}传统文化播报")
        execute_mystic_broadcast_task(ctx.rm, task_name, period)
