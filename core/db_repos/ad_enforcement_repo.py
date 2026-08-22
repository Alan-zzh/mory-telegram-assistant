# -*- coding: utf-8 -*-
"""广告处置事件账本；只保存脱敏证据摘要，不保存完整资料原文。"""

import json
import secrets
import time


class AdEnforcementRepo:
    """广告处置、说明卡和自助复检的原子状态操作。"""

    def __init__(self, db):
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    @staticmethod
    def _row_dict(cursor, row):
        if not row:
            return None
        return {item[0]: row[index] for index, item in enumerate(cursor.description)}

    def create_ad_enforcement_event(
        self,
        user_id: int,
        chat_id: int,
        source_message_id: int = 0,
        source_type: str = "detection",
        reason_code: str = "ad_detected",
        reason_summary: str = "广告检测",
        evidence_level: str = "high",
        evidence=None,
        root_event_id: str = "",
        parent_event_id: str = "",
        expires_at: int = 0,
    ) -> dict:
        now = int(time.time())
        event_id = secrets.token_urlsafe(18)
        root_id = str(root_event_id or event_id)
        safe_evidence = []
        for item in evidence or []:
            if not isinstance(item, dict):
                continue
            safe_evidence.append({
                "rule_id": str(item.get("rule_id", ""))[:80],
                "category": str(item.get("category", ""))[:40],
                "field": str(item.get("field", ""))[:24],
                "strength": str(item.get("strength", ""))[:16],
            })
        payload = json.dumps(safe_evidence[:20], ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            self.conn.execute(
                """INSERT INTO ad_enforcement_events (
                       event_id, root_event_id, parent_event_id, user_id, chat_id,
                       source_message_id, source_type, reason_code, reason_summary,
                       evidence_level, evidence_json, enforcement_status,
                       created_at, expires_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, root_id, str(parent_event_id or ""), int(user_id), int(chat_id),
                    int(source_message_id or 0), str(source_type or "detection")[:32],
                    str(reason_code or "ad_detected")[:64], str(reason_summary or "广告检测")[:240],
                    str(evidence_level or "high")[:16], payload, "pending", now,
                    int(expires_at or now + 86400),
                ),
            )
            self.conn.commit()
        return self.get_ad_enforcement_event(event_id) or {"event_id": event_id, "root_event_id": root_id}

    def get_ad_enforcement_event(self, event_id: str):
        with self.lock:
            cursor = self.conn.execute(
                "SELECT * FROM ad_enforcement_events WHERE event_id=?", (str(event_id),)
            )
            return self._row_dict(cursor, cursor.fetchone())

    def get_open_ad_root_event(self, user_id: int, chat_id: int = 0):
        now = int(time.time())
        with self.lock:
            sql = """SELECT * FROM ad_enforcement_events
                     WHERE user_id=? AND event_id=root_event_id AND resolved_at=0
                           AND expires_at>?"""
            params = [int(user_id), now]
            if int(chat_id or 0):
                sql += " AND chat_id=?"
                params.append(int(chat_id))
            sql += " ORDER BY created_at ASC LIMIT 1"
            cursor = self.conn.execute(sql, tuple(params))
            return self._row_dict(cursor, cursor.fetchone())

    def claim_ad_group_notice(self, event_id: str, chat_id: int, now: int = 0) -> dict:
        """原子占用群级说明卡；同一群24小时内只允许一个发送者。"""
        current = int(now or time.time())
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            cursor = self.conn.execute(
                """SELECT * FROM ad_enforcement_events
                   WHERE chat_id=? AND notice_message_id!=0 AND expires_at>?
                   ORDER BY created_at ASC LIMIT 1""",
                (int(chat_id), current),
            )
            existing = self._row_dict(cursor, cursor.fetchone())
            if existing:
                self.conn.commit()
                message_id = int(existing.get("notice_message_id") or 0)
                return {
                    "status": "existing" if message_id > 0 else "pending",
                    "notice_message_id": max(message_id, 0),
                    "event": existing,
                }
            cursor = self.conn.execute(
                """UPDATE ad_enforcement_events SET notice_message_id=-1
                   WHERE event_id=? AND chat_id=? AND notice_message_id=0 AND expires_at>?""",
                (str(event_id), int(chat_id), current),
            )
            if cursor.rowcount != 1:
                self.conn.rollback()
                return {"status": "unavailable", "notice_message_id": 0}
            self.conn.commit()
            return {
                "status": "claimed", "notice_message_id": 0,
            }

    def get_active_ad_notice(self, user_id: int, chat_id: int, root_event_id: str):
        now = int(time.time())
        with self.lock:
            cursor = self.conn.execute(
                """SELECT * FROM ad_enforcement_events
                   WHERE user_id=? AND chat_id=? AND root_event_id=?
                         AND notice_message_id>0 AND resolved_at=0 AND expires_at>?
                   ORDER BY created_at DESC LIMIT 1""",
                (int(user_id), int(chat_id), str(root_event_id), now),
            )
            return self._row_dict(cursor, cursor.fetchone())

    def set_ad_event_enforcement(
        self, event_id: str, muted: bool, blacklisted: bool, deleted_count: int,
        status: str,
    ) -> bool:
        with self.lock:
            cursor = self.conn.execute(
                """UPDATE ad_enforcement_events
                   SET muted=?, blacklisted=?, deleted_count=?, enforcement_status=?
                   WHERE event_id=?""",
                (int(bool(muted)), int(bool(blacklisted)), int(deleted_count or 0), str(status)[:32], str(event_id)),
            )
            self.conn.commit()
            return cursor.rowcount == 1

    def set_ad_event_notice(self, event_id: str, notice_message_id: int) -> bool:
        with self.lock:
            cursor = self.conn.execute(
                "UPDATE ad_enforcement_events SET notice_message_id=? WHERE event_id=?",
                (int(notice_message_id or 0), str(event_id)),
            )
            self.conn.commit()
            return cursor.rowcount == 1

    def claim_ad_recheck(
        self, event_id: str, actor_user_id: int, cooldown_seconds: int = 60,
        max_attempts: int = 5, now: int = 0,
    ) -> dict:
        """原子校验本人、有效期、限频和次数，并在允许时占用一次尝试。"""
        current = int(now or time.time())
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            cursor = self.conn.execute(
                "SELECT * FROM ad_enforcement_events WHERE event_id=?", (str(event_id),)
            )
            event = self._row_dict(cursor, cursor.fetchone())
            if not event:
                self.conn.rollback()
                return {"status": "not_found"}
            if int(event["user_id"]) != int(actor_user_id):
                self.conn.rollback()
                return {"status": "not_owner", "event": event}
            if int(event.get("resolved_at") or 0) > 0:
                self.conn.rollback()
                return {"status": "resolved", "event": event}
            if int(event.get("expires_at") or 0) <= current:
                self.conn.rollback()
                return {"status": "expired", "event": event}
            attempts = int(event.get("attempt_count") or 0)
            if attempts >= int(max_attempts):
                self.conn.rollback()
                return {"status": "attempts_exhausted", "event": event}
            last_attempt = int(event.get("last_attempt_at") or 0)
            if last_attempt and current - last_attempt < int(cooldown_seconds):
                self.conn.rollback()
                return {
                    "status": "rate_limited", "retry_after": int(cooldown_seconds) - (current - last_attempt),
                    "event": event,
                }
            self.conn.execute(
                """UPDATE ad_enforcement_events
                   SET attempt_count=attempt_count+1, last_attempt_at=?
                   WHERE event_id=? AND resolved_at=0""",
                (current, str(event_id)),
            )
            self.conn.commit()
        return {"status": "claimed", "event": self.get_ad_enforcement_event(event_id)}

    def resolve_ad_event(self, root_event_id: str, resolution: str, recovery=None) -> int:
        now = int(time.time())
        recovery_json = json.dumps(recovery or {}, ensure_ascii=False, separators=(",", ":"))[:2000]
        with self.lock:
            cursor = self.conn.execute(
                """UPDATE ad_enforcement_events
                   SET resolved_at=?, resolution=?, recovery_json=?
                   WHERE root_event_id=? AND resolved_at=0""",
                (now, str(resolution or "resolved")[:64], recovery_json, str(root_event_id)),
            )
            self.conn.commit()
            return int(cursor.rowcount or 0)

    def list_unresolved_ad_events(self, user_id: int):
        with self.lock:
            cursor = self.conn.execute(
                """SELECT * FROM ad_enforcement_events
                   WHERE user_id=? AND resolved_at=0 ORDER BY created_at ASC""",
                (int(user_id),),
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
