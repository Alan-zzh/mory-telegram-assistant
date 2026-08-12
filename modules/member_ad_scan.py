# -*- coding: utf-8 -*-
"""存量群成员广告扫描的统一判定与处置入口。

默认只生成报告。调用方只有在明确的 apply 阶段才可把高置信决定交给
``enforce_ad_user``；管理员、白名单、查询未知和弱证据都不得处罚。
"""

from __future__ import annotations

import time
from builtins import ExceptionGroup
from collections import Counter
from typing import Any, Iterable

from core.logging_util import get_logger

logger = get_logger("member_ad_scan")


def _display_name(user: Any) -> str:
    first_name = str(getattr(user, "first_name", "") or "")
    last_name = str(getattr(user, "last_name", "") or "")
    username = str(getattr(user, "username", "") or "")
    display = f"{first_name}{last_name}".strip()
    return f"{display} @{username}".strip() if username else display


def configured_exempt_ids(config: dict) -> set[int]:
    """返回零网络可确认的项目管理员和广告白名单。"""
    values: list[Any] = []
    config = config or {}
    values.append(config.get("ADMIN_ID", 0))
    admin_ids = config.get("ADMIN_IDS", []) or []
    values.extend(admin_ids if isinstance(admin_ids, (list, tuple, set)) else [admin_ids])
    whitelist = config.get("AD_WHITELIST", {}) or {}
    if isinstance(whitelist, dict):
        raw = whitelist.get("user_ids", []) or []
        values.extend(raw if isinstance(raw, (list, tuple, set)) else [raw])
    result: set[int] = set()
    for item in values:
        try:
            uid = int(item)
        except (TypeError, ValueError):
            continue
        if uid > 0:
            result.add(uid)
    return result


def _decision(
    *,
    is_ad: bool = False,
    source: str = "none",
    reason: str = "",
    score: int = 0,
    current_msg_id: int = 0,
    current_message_is_ad: bool = False,
    weak_signals: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "is_ad": bool(is_ad),
        "source": str(source),
        "reason": str(reason or "")[:500],
        "score": int(score or 0),
        "current_msg_id": int(current_msg_id or 0),
        "current_message_is_ad": bool(current_message_is_ad),
        "weak_signals": [str(item)[:160] for item in weak_signals if item],
    }


class MemberAdEvaluator:
    """复用当前资料、内容和高置信头像规则评估一个现存群成员。"""

    def __init__(self, bot, db, config: dict):
        self.bot = bot
        self.db = db
        self.config = config or {}

        # 存量扫描只使用确定性的本地规则。CAS/SPB 是辅助信号，不能单独定罪，
        # 全量扫描也不能为数千人制造外部探针风暴；边界 AI 留给头像候选复核。
        from modules.ad_detector import AdDetector

        detector_config = dict(self.config)
        detector_config["AD_AI_REVIEW_ENABLED"] = False
        self.detector = AdDetector(detector_config, db=None)

    def _stored_messages(self, uid: int, chat_id: int, limit: int) -> list[dict]:
        if not self.db or not hasattr(self.db, "get_user_messages"):
            return []
        try:
            return list(self.db.get_user_messages(uid, chat_id, limit=limit) or [])
        except Exception as exc:
            logger.warning(
                "[成员扫描] 读取消息快照失败 uid=%s chat=%s err=%s",
                uid,
                chat_id,
                exc,
            )
            return []

    def evaluate(
        self,
        *,
        user,
        chat_id: int,
        chat_info=None,
        bio: str = "",
        personal_channel_messages: Iterable[Any] | None = None,
        review_avatar: bool = True,
        review_avatar_without_weak_signal: bool = False,
        message_limit: int = 20,
    ) -> dict[str, Any]:
        uid = int(getattr(user, "id", 0) or 0)
        display = _display_name(user)
        bio = str(bio or getattr(chat_info, "bio", "") or "")[:1000]
        weak_signals: list[str] = []

        from modules.ad_profile_signals import detect_profile_ad_signal

        profile_result = detect_profile_ad_signal(
            self.bot,
            user,
            bio,
            self.config,
            chat_info=chat_info,
            personal_channel_messages=personal_channel_messages,
        )
        profile_score = int(profile_result.get("score", 0) or 0)
        if profile_result.get("is_ad"):
            return _decision(
                is_ad=True,
                source=str(profile_result.get("source") or "profile"),
                reason=str(profile_result.get("reason") or "资料层高置信命中"),
                score=max(3, profile_score),
            )
        if profile_score > 0:
            weak_signals.append(
                f"profile:{profile_result.get('reason', 'weak')} score={profile_score}"
            )

        # 使用与在线消息入口相同的最新本地规则，覆盖显示名和 Bio 的组合。
        local_profile = self.detector.detect(
            username=display,
            msg="",
            user_id=None,
            bot=None,
            bio=bio,
            chat_id=None,
        )
        local_profile_score = int(local_profile.get("score", 0) or 0)
        if local_profile.get("is_ad") and local_profile.get("action") == "ban":
            return _decision(
                is_ad=True,
                source="profile_rules",
                reason=str(local_profile.get("reason") or "显示名/Bio规则命中"),
                score=max(3, local_profile_score),
            )
        if local_profile_score > 0:
            weak_signals.append(
                f"profile_rules:{local_profile.get('reason', 'weak')} score={local_profile_score}"
            )

        # 重新跑已保存的最近消息，让发布后新增的确定性规则能清理历史漏网账号。
        max_message_score = 0
        for row in self._stored_messages(uid, chat_id, max(1, int(message_limit))):
            if bool(row.get("deleted")):
                continue
            text = str(row.get("text", "") or "").strip()
            if not text:
                continue
            result = self.detector.detect(
                username=display,
                msg=text,
                user_id=None,
                bot=None,
                bio=bio,
                chat_id=None,
            )
            score = int(result.get("score", 0) or 0)
            max_message_score = max(max_message_score, score)
            if result.get("is_ad") and result.get("action") == "ban":
                return _decision(
                    is_ad=True,
                    source="message_snapshot",
                    reason=str(result.get("reason") or "历史消息规则命中"),
                    score=max(3, score),
                    current_msg_id=int(row.get("msg_id", 0) or 0),
                    current_message_is_ad=True,
                )
        if max_message_score > 0:
            weak_signals.append(f"message_rules:score={max_message_score}")

        weak_score = max(profile_score, local_profile_score, max_message_score)
        should_review_avatar = bool(
            review_avatar
            and (review_avatar_without_weak_signal or weak_score > 0)
        )
        if should_review_avatar:
            try:
                from modules.avatar_detector import check_avatar_marketing

                avatar_hit, avatar_reason, avatar_score, avatar_meta = check_avatar_marketing(
                    self.bot, uid, self.config
                )
                avatar_score = int(avatar_score or 0)
                avatar_type = str((avatar_meta or {}).get("type", "") or "")
                if avatar_hit and avatar_score >= 2:
                    return _decision(
                        is_ad=True,
                        source="avatar",
                        reason=str(avatar_reason or "头像高置信广告证据"),
                        score=max(3, avatar_score),
                        weak_signals=weak_signals,
                    )
                if avatar_hit or avatar_score > 0:
                    weak_signals.append(
                        f"avatar:{avatar_reason or avatar_type or 'weak'} score={avatar_score}"
                    )
            except Exception as exc:
                logger.warning("[成员扫描] 头像复核失败 uid=%s err=%s", uid, exc)
                weak_signals.append("avatar_review_failed")

        return _decision(score=weak_score, weak_signals=weak_signals)


def enforce_member_decision(
    *,
    bot,
    db,
    config: dict,
    chat_id: int,
    user,
    decision: dict[str, Any],
    notify_admin: bool = False,
) -> dict[str, Any]:
    """把复核后的强证据决定交给统一处置链。"""
    if not decision.get("is_ad"):
        raise ValueError("weak_or_clean_decision_cannot_be_enforced")

    from modules.ad_enforcement import enforce_ad_user

    return enforce_ad_user(
        bot=bot,
        db=db,
        config=config or {},
        chat_id=int(chat_id),
        uid=int(getattr(user, "id", 0) or 0),
        uname=_display_name(user),
        reason=f"存量成员扫描[{decision.get('source', 'unknown')}]: {decision.get('reason', '')}"[:500],
        current_msg_id=int(decision.get("current_msg_id", 0) or 0),
        current_message_is_ad=bool(decision.get("current_message_is_ad")),
        notify_admin=bool(notify_admin),
    )


def collect_known_group_uids(db, chat_id: int) -> tuple[set[int], list[Exception]]:
    """聚合数据库里已见过的 UID，供启动扫描使用。"""
    all_uids: set[int] = set()
    failures: list[Exception] = []
    queries = [
        ("SELECT uid FROM users", ()),
        ("SELECT user_id FROM group_join_log", ()),
        ("SELECT user_id FROM ad_suspicious_users", ()),
        ("SELECT uid FROM user_levels", ()),
        ("SELECT DISTINCT uid FROM speech_daily", ()),
        ("SELECT DISTINCT uid FROM deleted_messages", ()),
        ("SELECT DISTINCT uid FROM checkin_records", ()),
        ("SELECT DISTINCT uid FROM points_log", ()),
        ("SELECT uid FROM user_tags", ()),
        ("SELECT uid FROM user_notes", ()),
        ("SELECT DISTINCT uid FROM achievements", ()),
        ("SELECT DISTINCT uid FROM redpacket_claims", ()),
        ("SELECT DISTINCT uid FROM lottery_participants", ()),
        ("SELECT uid FROM group_members WHERE chat_id=?", (int(chat_id),)),
    ]
    for query, params in queries:
        try:
            rows = db.conn.execute(query, params).fetchall()
            for row in rows:
                try:
                    uid = int(row[0])
                except (TypeError, ValueError, IndexError):
                    continue
                if uid > 0:
                    all_uids.add(uid)
        except Exception as exc:
            logger.error("[成员扫描] UID聚合失败 query=%s err=%s", query, exc)
            failures.append(exc)
    return all_uids, failures


def scan_known_group_members(
    *,
    bot,
    db,
    config: dict,
    chat_id: int,
    enforce: bool = False,
    delay_seconds: float = 0.08,
) -> dict[str, Any]:
    """扫描数据库已知成员；零覆盖或大面积 API 失败必须失败，不得假绿。"""
    admins = bot.get_chat_administrators(chat_id)
    admin_ids = {int(item.user.id) for item in admins}
    admin_ids.add(int(bot.get_me().id))
    exempt_ids = configured_exempt_ids(config or {})

    uids, failures = collect_known_group_uids(db, chat_id)
    evaluator = MemberAdEvaluator(bot, db, config or {})
    counts: Counter[str] = Counter(discovered=len(uids))
    candidates: list[dict[str, Any]] = []
    api_failures: list[Exception] = []

    for uid in sorted(uids):
        if uid in admin_ids or uid in exempt_ids:
            counts["exempt"] += 1
            continue
        try:
            member = bot.get_chat_member(chat_id, uid)
        except Exception as exc:
            text = str(exc).lower()
            if "user not found" in text or "participant_id_invalid" in text or "bad request" in text:
                counts["stale"] += 1
            else:
                counts["api_errors"] += 1
                if len(api_failures) < 20:
                    api_failures.append(exc)
            continue
        if str(getattr(member, "status", "")) in ("left", "kicked"):
            counts["left"] += 1
            continue
        user = getattr(member, "user", None)
        if not user or bool(getattr(user, "is_bot", False)):
            counts["bots"] += 1
            continue

        chat_info = None
        bio = ""
        try:
            chat_info = bot.get_chat(uid)
            bio = str(getattr(chat_info, "bio", "") or "")
        except Exception as exc:
            counts["profile_errors"] += 1
            logger.debug("[成员扫描] get_chat失败 uid=%s err=%s", uid, exc)

        decision = evaluator.evaluate(
            user=user,
            chat_id=chat_id,
            chat_info=chat_info,
            bio=bio,
            review_avatar=True,
        )
        counts["checked"] += 1
        if decision.get("is_ad"):
            counts["high_confidence"] += 1
            candidates.append({"uid": uid, **decision})
            if enforce:
                result = enforce_member_decision(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    user=user,
                    decision=decision,
                    notify_admin=False,
                )
                data = result.get("data", {})
                if data.get("skipped_reason"):
                    counts[f"skipped_{data['skipped_reason']}"] += 1
                elif result.get("code") == 200:
                    counts["enforced"] += 1
                else:
                    counts["enforcement_failed"] += 1
                    failures.append(RuntimeError(str(result.get("msg") or "enforcement_incomplete")))
        elif decision.get("weak_signals"):
            counts["weak_only"] += 1

        if delay_seconds > 0:
            time.sleep(float(delay_seconds))

    checked = int(counts.get("checked", 0))
    if uids and checked == 0:
        raise RuntimeError(
            f"member_scan_zero_coverage discovered={len(uids)} api_errors={counts.get('api_errors', 0)}"
        )
    if checked and counts.get("api_errors", 0) > max(10, checked // 5):
        failures.append(
            RuntimeError(
                f"member_scan_api_error_rate_high checked={checked} api_errors={counts['api_errors']}"
            )
        )
    failures.extend(api_failures)

    summary = {
        "mode": "enforce" if enforce else "report",
        "chat_id": int(chat_id),
        "counts": dict(counts),
        "candidates": candidates,
        "status": "failed" if failures else "success",
    }
    if failures:
        raise ExceptionGroup("known member scan failed or degraded", failures)
    return summary
