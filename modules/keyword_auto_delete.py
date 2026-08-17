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
    "rules": [],
    "max_attempts": 5,
}

_MATCH_MODES = {"exact", "prefix", "contains"}
_MIN_DELAY_SECONDS = 1
_MAX_DELAY_SECONDS = 604800
_MAX_KEYWORDS = 50
_MAX_KEYWORD_LENGTH = 100


def normalize_keyword_auto_delete_payload(raw: dict | None) -> dict:
    """规范化模块配置，并兼容 v5.38.62 的单一延迟旧格式。"""
    raw = raw if isinstance(raw, dict) else {}
    merged = dict(DEFAULT_KEYWORD_AUTO_DELETE_CONFIG)
    merged.update(raw)

    try:
        max_attempts = int(merged.get("max_attempts", 5))
    except (TypeError, ValueError):
        max_attempts = 5

    raw_rules = raw.get("rules") if "rules" in raw else None
    if not isinstance(raw_rules, list):
        legacy_keywords = raw.get("keywords", [])
        if isinstance(legacy_keywords, str):
            legacy_keywords = [legacy_keywords]
        if not isinstance(legacy_keywords, (list, tuple)):
            legacy_keywords = []
        raw_rules = [
            {
                "keyword": keyword,
                "delay_seconds": raw.get("delay_seconds", 300),
                "match_mode": raw.get("match_mode", "exact"),
                "case_sensitive": raw.get("case_sensitive", False),
                "enabled": True,
            }
            for keyword in legacy_keywords
        ]

    rules = []
    seen_keywords = set()
    for item in raw_rules[:_MAX_KEYWORDS]:
        if isinstance(item, str):
            item = {"keyword": item}
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "").strip()[:_MAX_KEYWORD_LENGTH]
        if not keyword:
            continue
        identity = keyword.casefold()
        if identity in seen_keywords:
            continue
        seen_keywords.add(identity)
        try:
            delay_seconds = int(item.get("delay_seconds", 300))
        except (TypeError, ValueError):
            delay_seconds = 300
        match_mode = str(item.get("match_mode", "exact") or "exact").lower()
        if match_mode not in _MATCH_MODES:
            match_mode = "exact"
        rules.append(
            {
                "keyword": keyword,
                "delay_seconds": max(
                    _MIN_DELAY_SECONDS,
                    min(_MAX_DELAY_SECONDS, delay_seconds),
                ),
                "match_mode": match_mode,
                "case_sensitive": bool(item.get("case_sensitive", False)),
                "enabled": bool(item.get("enabled", True)),
            }
        )

    return {
        "enabled": bool(merged.get("enabled", False)),
        "rules": rules,
        "max_attempts": max(1, min(20, max_attempts)),
    }


def get_keyword_auto_delete_config(config: dict | None) -> dict:
    """返回经过边界收敛的关键词延迟删除配置。"""
    raw = (config or {}).get("KEYWORD_AUTO_DELETE_CONFIG", {})
    return normalize_keyword_auto_delete_payload(raw)


def match_keyword_auto_delete_rule(text: str, config: dict | None) -> dict | None:
    """返回命中的完整规则；先配置者优先。"""
    cfg = get_keyword_auto_delete_config(config)
    if not cfg["enabled"] or not cfg["rules"]:
        return None

    candidate = str(text or "").strip()
    if not candidate:
        return None

    for rule in cfg["rules"]:
        if not rule["enabled"]:
            continue
        keyword = rule["keyword"]
        compare_candidate = candidate if rule["case_sensitive"] else candidate.casefold()
        compare_keyword = keyword if rule["case_sensitive"] else keyword.casefold()
        if rule["match_mode"] == "exact" and compare_candidate == compare_keyword:
            return dict(rule)
        if rule["match_mode"] == "prefix" and compare_candidate.startswith(compare_keyword):
            return dict(rule)
        if rule["match_mode"] == "contains" and compare_keyword in compare_candidate:
            return dict(rule)
    return None


def match_keyword_auto_delete(text: str, config: dict | None) -> str | None:
    """返回命中的配置词；默认使用精确匹配以降低正常消息误删风险。"""
    rule = match_keyword_auto_delete_rule(text, config)
    return rule["keyword"] if rule else None


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


def get_message_keyword_rule(message: Any, config: dict | None) -> dict | None:
    """返回普通群用户消息命中的完整规则。"""
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    if getattr(chat, "type", "") not in ("group", "supergroup"):
        return None
    if not user or bool(getattr(user, "is_bot", False)):
        return None
    if getattr(message, "sender_chat", None) is not None:
        return None
    return match_keyword_auto_delete_rule(getattr(message, "text", "") or "", config)


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
    matched_rule: dict | None = None,
    matched_keyword: str | None = None,
    timer_factory: Callable[..., Any] = threading.Timer,
) -> dict:
    """持久化并启动单条延迟删除；返回可测试的调度回执。"""
    rule = matched_rule or get_message_keyword_rule(message, config)
    if rule is None and matched_keyword:
        cfg = get_keyword_auto_delete_config(config)
        rule = next(
            (item for item in cfg["rules"] if item["keyword"] == matched_keyword),
            None,
        )
    if not rule:
        return {"matched": False, "persisted": False, "timer_started": False}
    keyword = rule["keyword"]

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

    delay_seconds = int(rule["delay_seconds"])
    due_at = int(time.time()) + delay_seconds
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
            delay_seconds,
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
        delay_seconds,
        keyword,
        status,
    )
    return {
        "matched": True,
        "persisted": persisted,
        "timer_started": timer_started,
        "status": status,
        "keyword": keyword,
        "delay_seconds": delay_seconds,
        "due_at": due_at,
    }


def cleanup_existing_keyword_messages(
    bot: Any,
    db: Any,
    config: dict | None,
    *,
    chat_id: int | None = None,
    limit: int = 5000,
) -> dict:
    """删除快照中仍存在且匹配当前规则的历史消息，返回逐层计数回执。"""
    cfg = get_keyword_auto_delete_config(config)
    counts = {
        "scanned": 0,
        "matched": 0,
        "deleted": 0,
        "already_gone": 0,
        "failed": 0,
    }
    if not cfg["enabled"] or not can_delete_message(config or {}):
        counts["status"] = "disabled"
        return counts

    rows = db.get_keyword_message_cleanup_candidates(chat_id=chat_id, limit=limit)
    counts["scanned"] = len(rows)
    for row in rows:
        if not match_keyword_auto_delete_rule(row.get("text", ""), config):
            continue
        counts["matched"] += 1
        try:
            bot.delete_message(int(row["chat_id"]), int(row["message_id"]))
            outcome = "deleted"
        except Exception as exc:
            if _is_already_gone_error(exc):
                outcome = "already_gone"
            else:
                logger.warning(
                    "[关键词延迟删] 历史清理失败 chat=%s msg=%s error=%s",
                    row["chat_id"],
                    row["message_id"],
                    exc,
                )
                counts["failed"] += 1
                continue
        db.resolve_keyword_message_delete(
            int(row["chat_id"]),
            int(row["message_id"]),
            success=True,
            error="",
            max_attempts=cfg["max_attempts"],
        )
        counts[outcome] += 1
    counts["status"] = "completed" if counts["failed"] == 0 else "degraded"
    logger.info("[关键词延迟删] 历史清理回执 chat=%s counts=%s", chat_id, counts)
    return counts


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
