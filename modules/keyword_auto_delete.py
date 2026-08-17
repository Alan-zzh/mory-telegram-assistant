"""可配置群消息关键词延迟删除。

只对明确命中的普通群文本生效，不做禁言、拉黑或广告判定。待删状态写入
``message_snapshots``，进程内定时器负责准点删除，周期任务负责重启恢复。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from core.helpers import can_delete_message
from core.logging_util import get_logger

logger = get_logger("keyword_auto_delete")

DEFAULT_KEYWORD_AUTO_DELETE_CONFIG = {
    "enabled": False,
    "keywords": [],
    "delay_seconds": 300,
    "match_mode": "exact",
    "case_sensitive": False,
    "max_attempts": 5,
}

_MATCH_MODES = {"exact", "prefix", "contains"}
_MIN_DELAY_SECONDS = 30
_MAX_DELAY_SECONDS = 86400
_MAX_KEYWORDS = 50
_MAX_KEYWORD_LENGTH = 100


def get_keyword_auto_delete_config(config: dict | None) -> dict:
    """返回经过边界收敛的关键词延迟删除配置。"""
    raw = (config or {}).get("KEYWORD_AUTO_DELETE_CONFIG", {})
    raw = raw if isinstance(raw, dict) else {}
    merged = dict(DEFAULT_KEYWORD_AUTO_DELETE_CONFIG)
    merged.update(raw)

    keywords = merged.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, (list, tuple)):
        keywords = []
    cleaned = []
    for item in keywords[:_MAX_KEYWORDS]:
        keyword = str(item or "").strip()[:_MAX_KEYWORD_LENGTH]
        if keyword and keyword not in cleaned:
            cleaned.append(keyword)

    try:
        delay_seconds = int(merged.get("delay_seconds", 300))
    except (TypeError, ValueError):
        delay_seconds = 300
    try:
        max_attempts = int(merged.get("max_attempts", 5))
    except (TypeError, ValueError):
        max_attempts = 5

    match_mode = str(merged.get("match_mode", "exact") or "exact").lower()
    if match_mode not in _MATCH_MODES:
        match_mode = "exact"

    return {
        "enabled": bool(merged.get("enabled", False)),
        "keywords": cleaned,
        "delay_seconds": max(_MIN_DELAY_SECONDS, min(_MAX_DELAY_SECONDS, delay_seconds)),
        "match_mode": match_mode,
        "case_sensitive": bool(merged.get("case_sensitive", False)),
        "max_attempts": max(1, min(20, max_attempts)),
    }


def match_keyword_auto_delete(text: str, config: dict | None) -> str | None:
    """返回命中的配置词；默认使用精确匹配以降低正常消息误删风险。"""
    cfg = get_keyword_auto_delete_config(config)
    if not cfg["enabled"] or not cfg["keywords"]:
        return None

    candidate = str(text or "").strip()
    if not candidate:
        return None
    compare_candidate = candidate if cfg["case_sensitive"] else candidate.casefold()

    for keyword in cfg["keywords"]:
        compare_keyword = keyword if cfg["case_sensitive"] else keyword.casefold()
        if cfg["match_mode"] == "exact" and compare_candidate == compare_keyword:
            return keyword
        if cfg["match_mode"] == "prefix" and compare_candidate.startswith(compare_keyword):
            return keyword
        if cfg["match_mode"] == "contains" and compare_keyword in compare_candidate:
            return keyword
    return None


def get_message_keyword_match(message: Any, config: dict | None) -> str | None:
    """仅匹配普通用户发送的群文本；私聊、Bot 和频道身份消息一律放行。"""
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    if getattr(chat, "type", "") not in ("group", "supergroup"):
        return None
    if not user or bool(getattr(user, "is_bot", False)):
        return None
    if getattr(message, "sender_chat", None) is not None:
        return None
    return match_keyword_auto_delete(getattr(message, "text", "") or "", config)


def _is_already_gone_error(error: Exception) -> bool:
    message = str(error).casefold()
    return any(
        token in message
        for token in (
            "message to delete not found",
            "message not found",
        )
    )


def delete_keyword_message(
    bot: Any,
    db: Any,
    config: dict | None,
    chat_id: int,
    message_id: int,
) -> str:
    """执行一次删除并固化结果，返回 deleted/already_gone/retry/failed/disabled。"""
    cfg = get_keyword_auto_delete_config(config)
    if not cfg["enabled"] or not can_delete_message(config or {}):
        logger.warning(
            "[关键词延迟删] 删除开关关闭，保留待删状态 chat=%s msg=%s",
            chat_id,
            message_id,
        )
        return "disabled"

    try:
        bot.delete_message(int(chat_id), int(message_id))
        outcome = "deleted"
    except Exception as exc:  # Telegram API 错误必须进入可观测重试状态
        if _is_already_gone_error(exc):
            outcome = "already_gone"
        else:
            try:
                state = db.resolve_keyword_message_delete(
                    int(chat_id),
                    int(message_id),
                    success=False,
                    error=str(exc)[:300],
                    max_attempts=cfg["max_attempts"],
                )
            except Exception as db_exc:
                logger.error(
                    "[关键词延迟删] 删除失败且状态落库失败 chat=%s msg=%s error=%s db_error=%s",
                    chat_id,
                    message_id,
                    exc,
                    db_exc,
                )
                return "failed"
            logger.warning(
                "[关键词延迟删] 删除失败 chat=%s msg=%s state=%s error=%s",
                chat_id,
                message_id,
                state,
                exc,
            )
            return "failed" if state == "failed" else "retry"

    try:
        db.resolve_keyword_message_delete(
            int(chat_id),
            int(message_id),
            success=True,
            error="",
            max_attempts=cfg["max_attempts"],
        )
    except Exception as exc:
        logger.error(
            "[关键词延迟删] Telegram 已删除但回执落库失败 chat=%s msg=%s error=%s",
            chat_id,
            message_id,
            exc,
        )
        return "failed"
    logger.info(
        "[关键词延迟删] 删除完成 chat=%s msg=%s outcome=%s",
        chat_id,
        message_id,
        outcome,
    )
    return outcome


def schedule_keyword_message_delete(
    bot: Any,
    message: Any,
    config: dict | None,
    db: Any,
    *,
    matched_keyword: str | None = None,
    timer_factory: Callable[..., Any] = threading.Timer,
) -> dict:
    """持久化并启动单条延迟删除；返回可测试的调度回执。"""
    keyword = matched_keyword or get_message_keyword_match(message, config)
    if not keyword:
        return {"matched": False, "persisted": False, "timer_started": False}

    chat_id = int(message.chat.id)
    message_id = int(message.message_id)
    user_id = int(message.from_user.id)
    cfg = get_keyword_auto_delete_config(config)
    if not can_delete_message(config or {}):
        logger.warning(
            "[关键词延迟删] 命中但 ENABLE_MESSAGE_DELETION=False chat=%s msg=%s",
            chat_id,
            message_id,
        )
        return {
            "matched": True,
            "persisted": False,
            "timer_started": False,
            "status": "deletion_disabled",
            "keyword": keyword,
        }

    due_at = int(time.time()) + cfg["delay_seconds"]
    try:
        persisted = bool(
            db.queue_keyword_message_delete(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                text=getattr(message, "text", "") or "",
                keyword=keyword,
                due_at=due_at,
            )
        )
    except Exception as exc:
        persisted = False
        logger.error(
            "[关键词延迟删] 待删状态落库失败，退化为进程内定时器 chat=%s msg=%s error=%s",
            chat_id,
            message_id,
            exc,
        )

    timer_started = False
    try:
        timer = timer_factory(
            cfg["delay_seconds"],
            delete_keyword_message,
            args=(bot, db, config, chat_id, message_id),
        )
        timer.daemon = True
        timer.start()
        timer_started = True
    except Exception as exc:
        logger.error(
            "[关键词延迟删] 定时器启动失败 chat=%s msg=%s persisted=%s error=%s",
            chat_id,
            message_id,
            persisted,
            exc,
        )

    status = "scheduled" if persisted and timer_started else "degraded"
    logger.info(
        "[关键词延迟删] 命中并登记 chat=%s msg=%s delay=%ss keyword=%r status=%s",
        chat_id,
        message_id,
        cfg["delay_seconds"],
        keyword,
        status,
    )
    return {
        "matched": True,
        "persisted": persisted,
        "timer_started": timer_started,
        "status": status,
        "keyword": keyword,
        "due_at": due_at,
    }


def run_due_keyword_message_deletes(bot: Any, db: Any, config: dict | None) -> dict:
    """补偿处理到期待删消息，供周期任务和真实业务探针复用。"""
    cfg = get_keyword_auto_delete_config(config)
    if not cfg["enabled"] or not can_delete_message(config or {}):
        return {"found": 0, "deleted": 0, "already_gone": 0, "retry": 0, "failed": 0}

    rows = db.get_due_keyword_message_deletes(
        now_ts=int(time.time()),
        limit=100,
        max_attempts=cfg["max_attempts"],
    )
    counts = {"found": len(rows), "deleted": 0, "already_gone": 0, "retry": 0, "failed": 0}
    for row in rows:
        outcome = delete_keyword_message(
            bot,
            db,
            config,
            int(row["chat_id"]),
            int(row["message_id"]),
        )
        if outcome in counts:
            counts[outcome] += 1
        elif outcome == "disabled":
            counts["retry"] += 1
        else:
            counts["failed"] += 1
    return counts
