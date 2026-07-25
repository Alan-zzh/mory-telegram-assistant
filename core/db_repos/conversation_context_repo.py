# -*- coding: utf-8 -*-
"""短期业务会话上下文与转化拒绝状态。

这不是增长遥测，也不参与风格进化。``conversation_telemetry`` 可在
``raw_event_text=false`` 时完全不存原文；本仓库只为当前用户、当前聊天
保存最多 30 分钟、每段最多 500 字的必要承接文本，以及 CTA / 定制 /
预览 / 拒绝等结构化状态。这样重启后仍能自然接话和去重，又不会把原文
拿去做分析、训练或自动改写 Prompt。
"""
from __future__ import annotations

import time
from typing import Any

from core.logging_util import get_logger

logger = get_logger("db.conversation_context")

_CONTEXT_TTL_SECONDS = 1800
_OPT_OUT_TTL_SECONDS = 30 * 86400
_MAX_TEXT_LENGTH = 500


class ConversationContextRepo:
    """独立于遥测的、最小化的短期会话业务状态。"""

    def __init__(self, db: Any):
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    def _ensure_schema(self) -> bool:
        """兼容 Dashboard/测试直连 SQLite 的幂等初始化。"""
        with self.lock:
            try:
                self.conn.execute("""CREATE TABLE IF NOT EXISTS business_conversation_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_text TEXT NOT NULL DEFAULT '',
                    assistant_text TEXT NOT NULL DEFAULT '',
                    intent TEXT NOT NULL DEFAULT '',
                    conversion_target TEXT NOT NULL DEFAULT 'none',
                    conversion_reason TEXT NOT NULL DEFAULT '',
                    ts INTEGER NOT NULL
                )""")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_business_context_recent "
                    "ON business_conversation_context(user_id, chat_id, ts)"
                )
                self.conn.execute("""CREATE TABLE IF NOT EXISTS conversation_conversion_state (
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    opt_out_until INTEGER NOT NULL DEFAULT 0,
                    custom_context_until INTEGER NOT NULL DEFAULT 0,
                    preview_context_until INTEGER NOT NULL DEFAULT 0,
                    recent_cta_target TEXT NOT NULL DEFAULT '',
                    recent_cta_at INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id, chat_id)
                )""")
                self.conn.commit()
                return True
            except Exception as exc:
                logger.warning("初始化短期业务上下文失败: %s", exc)
                return False

    def get_recent_business_context(
        self, user_id: int, chat_id: int, *, limit: int = 3, max_age_seconds: int = _CONTEXT_TTL_SECONDS
    ) -> list[dict]:
        safe_limit = max(1, min(int(limit or 3), 6))
        cutoff = int(time.time()) - max(60, int(max_age_seconds or _CONTEXT_TTL_SECONDS))
        with self.lock:
            try:
                rows = self.conn.execute(
                    "SELECT user_text, assistant_text, intent, conversion_target, conversion_reason, ts "
                    "FROM business_conversation_context WHERE user_id=? AND chat_id=? AND ts>=? "
                    "ORDER BY id DESC LIMIT ?",
                    (int(user_id), int(chat_id), cutoff, safe_limit),
                ).fetchall()
            except Exception as exc:
                logger.debug("读取短期业务上下文失败 uid=%s chat=%s: %s", user_id, chat_id, exc)
                return []

        history: list[dict] = []
        for user_text, assistant_text, intent, target, reason, ts in reversed(rows):
            metadata = {
                "intent": str(intent or ""),
                "conversion_target": str(target or "none"),
                "conversion_reason": str(reason or ""),
                "ts": int(ts or 0),
            }
            if user_text:
                history.append({"role": "user", "content": str(user_text)[:_MAX_TEXT_LENGTH], **metadata})
            if assistant_text:
                history.append({"role": "assistant", "content": str(assistant_text)[:_MAX_TEXT_LENGTH], **metadata})
        return history

    def get_conversion_state(self, user_id: int, chat_id: int) -> dict:
        now = int(time.time())
        with self.lock:
            try:
                row = self.conn.execute(
                    "SELECT opt_out_until, custom_context_until, preview_context_until, "
                    "recent_cta_target, recent_cta_at, updated_at "
                    "FROM conversation_conversion_state WHERE user_id=? AND chat_id=?",
                    (int(user_id), int(chat_id)),
                ).fetchone()
            except Exception as exc:
                logger.debug("读取转化状态失败 uid=%s chat=%s: %s", user_id, chat_id, exc)
                return {}
        if not row:
            return {}
        return {
            "opt_out": int(row[0] or 0) > now,
            "opt_out_until": int(row[0] or 0),
            "custom_context": int(row[1] or 0) > now,
            "preview_context": int(row[2] or 0) > now,
            "recent_cta_target": str(row[3] or ""),
            "recent_cta_at": int(row[4] or 0),
            "updated_at": int(row[5] or 0),
        }

    def set_conversion_opt_out(self, user_id: int, chat_id: int, *, ttl_seconds: int = _OPT_OUT_TTL_SECONDS) -> bool:
        now = int(time.time())
        until = now + max(60, int(ttl_seconds or _OPT_OUT_TTL_SECONDS))
        return self._upsert_state(user_id, chat_id, opt_out_until=until, updated_at=now)

    def clear_conversion_opt_out(self, user_id: int, chat_id: int) -> bool:
        return self._upsert_state(user_id, chat_id, opt_out_until=0, updated_at=int(time.time()))

    def record_business_context(
        self,
        user_id: int,
        chat_id: int,
        user_text: str,
        assistant_text: str,
        *,
        intent: str = "",
        conversion_target: str = "none",
        conversion_reason: str = "",
    ) -> bool:
        """记录一条短期承接上下文，并同步更新结构化 CTA/阶段状态。"""
        now = int(time.time())
        target = str(conversion_target or "none")[:32]
        reason = str(conversion_reason or "")[:80]
        user_value = str(user_text or "").strip()[:_MAX_TEXT_LENGTH]
        assistant_value = str(assistant_text or "").strip()[:_MAX_TEXT_LENGTH]
        if not user_value and not assistant_value:
            return False

        with self.lock:
            try:
                self.conn.execute(
                    "INSERT INTO business_conversation_context "
                    "(user_id, chat_id, user_text, assistant_text, intent, conversion_target, conversion_reason, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (int(user_id), int(chat_id), user_value, assistant_value, str(intent or "")[:64], target, reason, now),
                )
                # 只清除过期记录；保留最近短窗口，不作为分析样本或长期画像。
                self.conn.execute("DELETE FROM business_conversation_context WHERE ts<?", (now - _CONTEXT_TTL_SECONDS,))
                self._upsert_state_locked(
                    int(user_id), int(chat_id), now,
                    custom_context_until=now + _CONTEXT_TTL_SECONDS if self._is_custom_reason(reason) else None,
                    preview_context_until=now + _CONTEXT_TTL_SECONDS if self._is_preview_reason(target, reason) else None,
                    recent_cta_target=target if target in {"preview", "subscribe"} else None,
                    recent_cta_at=now if target in {"preview", "subscribe"} else None,
                )
                self.conn.commit()
                return True
            except Exception as exc:
                logger.debug("保存短期业务上下文失败 uid=%s chat=%s: %s", user_id, chat_id, exc)
                return False

    def cleanup_expired_business_context(self, *, now_ts: int | None = None) -> int:
        """物理删除超过 TTL 的短期原文；可由独立定时任务调用。"""
        now = int(now_ts if now_ts is not None else time.time())
        cutoff = now - _CONTEXT_TTL_SECONDS
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "DELETE FROM business_conversation_context WHERE ts<?",
                    (cutoff,),
                )
                # 结构化状态不含原文；仅清理已失效且长期未更新的普通状态行。
                self.conn.execute(
                    "DELETE FROM conversation_conversion_state "
                    "WHERE opt_out_until<=? AND custom_context_until<=? "
                    "AND preview_context_until<=? AND updated_at<?",
                    (now, now, now, now - _OPT_OUT_TTL_SECONDS),
                )
                self.conn.commit()
                return max(0, int(cursor.rowcount or 0))
            except Exception as exc:
                logger.warning("清理过期短期业务上下文失败: %s", exc)
                return 0

    @staticmethod
    def _is_custom_reason(reason: str) -> bool:
        return reason in {"explicit_custom_order", "custom_requirements", "positive_after_custom"}

    @staticmethod
    def _is_preview_reason(target: str, reason: str) -> bool:
        return target == "preview" or reason in {"preview_confirmed", "positive_after_preview"}

    def _upsert_state(self, user_id: int, chat_id: int, **updates) -> bool:
        with self.lock:
            try:
                self._upsert_state_locked(int(user_id), int(chat_id), int(time.time()), **updates)
                self.conn.commit()
                return True
            except Exception as exc:
                logger.debug("更新转化状态失败 uid=%s chat=%s: %s", user_id, chat_id, exc)
                return False

    def _upsert_state_locked(self, user_id: int, chat_id: int, now: int, **updates) -> None:
        existing = self.conn.execute(
            "SELECT opt_out_until, custom_context_until, preview_context_until, recent_cta_target, recent_cta_at "
            "FROM conversation_conversion_state WHERE user_id=? AND chat_id=?",
            (user_id, chat_id),
        ).fetchone() or (0, 0, 0, "", 0)
        values = {
            "opt_out_until": int(existing[0] or 0),
            "custom_context_until": int(existing[1] or 0),
            "preview_context_until": int(existing[2] or 0),
            "recent_cta_target": str(existing[3] or ""),
            "recent_cta_at": int(existing[4] or 0),
            "updated_at": now,
        }
        values.update({key: value for key, value in updates.items() if value is not None})
        self.conn.execute(
            "INSERT INTO conversation_conversion_state "
            "(user_id, chat_id, opt_out_until, custom_context_until, preview_context_until, recent_cta_target, recent_cta_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, chat_id) DO UPDATE SET "
            "opt_out_until=excluded.opt_out_until, custom_context_until=excluded.custom_context_until, "
            "preview_context_until=excluded.preview_context_until, recent_cta_target=excluded.recent_cta_target, "
            "recent_cta_at=excluded.recent_cta_at, updated_at=excluded.updated_at",
            (user_id, chat_id, values["opt_out_until"], values["custom_context_until"],
             values["preview_context_until"], values["recent_cta_target"], values["recent_cta_at"], values["updated_at"]),
        )
