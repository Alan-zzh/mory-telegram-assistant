"""早间黄历、午间塔罗与晚间易经播报任务。"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List

from core.broadcast_cta import build_cta_markup_combo, get_broadcast_cta_combo, is_broadcast_image_enabled
from core.broadcast_formatter import build_mystic_html, build_rich_mystic_card_message
from core.broadcast_image_card import build_broadcast_image_card, resolve_theme_options, strip_visual_emoji
from core.broadcast_image_payload import build_mystic_image_payload
from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from core.telegram_send_utils import send_photo_compat
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


def build_mystic_cta(payload: dict, config: dict = None):
    """生成玄学播报组合 CTA（真实按钮 1-2 个；图片卡不再印按钮文字）。

    组合模式由统一组件 get_broadcast_cta_combo 按北京日期确定性随机
    （preview/contact/subscribe 单按钮，或 preview+contact/subscribe 双按钮）；
    旧 payload["cta"] 仅在统一池未返回有效按钮时作为守约兜底。
    """
    legacy_cta = payload.get("cta") or {}
    combo = get_broadcast_cta_combo(
        scene="mystic",
        period=payload.get("period", ""),
        mode=payload.get("mode", "almanac"),
        config=config,
    )
    # 统一池按配置（cta_enabled=false 等）返回空按钮时，沿用旧 payload 的守约兜底
    if not combo.get("buttons") and isinstance(legacy_cta, dict) and legacy_cta.get("label"):
        fallback = {
            "target": legacy_cta.get("target", "none"),
            "label": legacy_cta.get("label", ""),
            # 图片卡不再印字；image_label 仅作兼容字段保留
            "image_label": strip_visual_emoji(legacy_cta.get("label", "")),
            "url": legacy_cta.get("url", ""),
            "mini_app": legacy_cta.get("mini_app"),
            "style": legacy_cta.get("style", "default"),
            "closing": legacy_cta.get("closing", ""),
        }
        combo = {"buttons": [fallback], "closing": fallback.get("closing", "")}
    return combo


def build_mystic_cta_markup(payload: dict, config: dict = None):
    """每张卡 1-2 个与正文说明一致的真实按钮（InlineKeyboard）。"""
    combo = build_mystic_cta(payload, config=config)
    return build_cta_markup_combo(combo, config=config)


def _build_mystic_image_card(payload: dict, config: dict = None) -> str | None:
    """生成玄学播报图片卡，返回本地 PNG 路径；失败返回 None。

    [v5.38.27] 图片卡不再印按钮文字（cta_text 传空），真实按钮以
    InlineKeyboard 附加，避免图片上“看看预览”等字样无用。
    """
    try:
        image_payload = build_mystic_image_payload(payload)
        out_path = build_broadcast_image_card(
            image_payload,
            cache_key=f"mystic_{payload.get('mode', 'almanac')}_{payload.get('date', 'unknown')}",
            config=config,
            cta_text="",
            options=resolve_theme_options(config, payload.get("period", "")),
        )
        if out_path:
            logger.info(f"[mystic] 图片卡已生成: {out_path}")
        return out_path
    except Exception as e:
        logger.warning(f"[mystic] 图片卡生成失败，将回退文字: {e}")
        return None


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
                raise TaskAbort("GROUP_ID为0", expected=True)

            payload = build_mystic_broadcast(rm.config, period)
            if not is_usable_mystic_broadcast(payload):
                record_abort(task_name, "玄学播报内容未通过门禁")
                raise TaskAbort("玄学播报内容未通过门禁", expected=True)

            cfg = rm.config or {}
            combo = build_mystic_cta(payload, config=cfg)
            buttons = combo.get("buttons") or []
            # payload["cta"] 回填单按钮结构（兼容门禁 is_usable_mystic_broadcast 与正文 closing）
            payload["cta"] = buttons[0] if buttons else {
                "target": "none",
                "label": "",
                "image_label": "",
                "url": "",
                "mini_app": None,
                "style": "default",
                "closing": "",
            }
            rich_message = build_rich_mystic_card_message(payload)
            html_message = build_mystic_html(payload)
            reply_markup = build_cta_markup_combo(combo, config=cfg)
            rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))
            format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
            mystic_cfg = cfg.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(cfg, dict) else {}
            # [v5.38.21] 与其余播报类型一致：全局总闸 AND 玄学分闸（统一 helper）
            image_card_enabled = is_broadcast_image_enabled(cfg, mystic_cfg)
            sent = None

            # [v5.38.15] 优先发送图片卡，失败回退 Rich Message / HTML
            if image_card_enabled:
                image_path = _build_mystic_image_card(payload, config=cfg)
                if image_path and os.path.isfile(image_path):
                    try:
                        with rm.locked("bot"):
                            sent = send_photo_compat(
                                rm.bot,
                                gid,
                                image_path,
                                caption=None,
                                reply_markup=reply_markup,
                            )
                        if sent and hasattr(sent, "message_id"):
                            schedule_auto_delete(rm, gid, sent.message_id, 24 * 3600)
                            rm.db.track_channel_message(gid, sent.message_id, "image")
                            rm.db.track_bot_message(gid, sent.message_id)
                            logger.info(
                                f"✅ {payload['title']}图片卡已发送"
                                f"（mode={payload['mode']}，msg={sent.message_id}）"
                            )
                    except Exception as exc:
                        logger.warning(f"{payload['title']} 图片卡发送失败，回退文字: {exc}")
                        sent = None

            if sent is None and rich_enabled and format_version in {"rich", "auto"}:
                try:
                    from core.telegram_send_utils import send_rich_message_compat

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
                f"cta={','.join(b.get('target', 'none') for b in buttons) or 'none'}）"
            )
    except TaskAbort as exc:
        if exc.expected:
            return
        raise
    except Exception as exc:
        logger.error(f"玄学播报失败：{exc}")
        retry_task(
            rm,
            lambda rm_inner: execute_mystic_broadcast_task(rm_inner, task_name, period),
            task_name,
        )
        raise


class MysticBroadcastTask(BaseTask):
    """早、午、晚三档传统文化栏目。"""

    @property
    def task_id(self) -> str:
        return "mystic_broadcast"

    def schedule(self) -> List[Dict[str, Any]]:
        # schedule 与 execute 统一检查 enabled，避免“注册成功但执行跳过”假死
        if not is_mystic_enabled(self.rm.config):
            logger.info("🔮 传统文化播报未开启，跳过调度注册")
            return []
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
