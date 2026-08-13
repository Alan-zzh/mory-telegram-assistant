# -*- coding: utf-8 -*-
"""全量枚举群成员并用当前广告规则生成报告或复核后处置。

默认模式只报告：
    python scripts/scan_group.py --output /tmp/member-scan-report.json

应用报告中的高置信候选（会逐个重新取资料并重新判定）：
    python scripts/scan_group.py --apply-report /tmp/member-scan-report.json \
        --output /tmp/member-scan-apply.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.bot_initializer import _load_dynamic_states, load_config  # noqa: E402
from core.database import DB  # noqa: E402
from core.logging_util import get_logger  # noqa: E402
from core.telebot_compat import preserve_telegram_extra_fields  # noqa: E402
from modules.member_ad_scan import (  # noqa: E402
    MemberAdEvaluator,
    configured_exempt_ids,
    enforce_member_decision,
)
from version import VERSION  # noqa: E402

logger = get_logger("scripts.scan_group")

SCHEMA = "mory.member-ad-scan/v1"
PUBLIC_TELEGRAM_API_ID = 2040
PUBLIC_TELEGRAM_API_HASH = "b18441a1ff607e10a989891a5462e627"


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _fingerprint(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("fingerprint", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != SCHEMA or report.get("mode") != "report":
        raise ValueError("invalid_member_scan_report")
    if report.get("fingerprint") != _fingerprint(report):
        raise ValueError("member_scan_report_fingerprint_mismatch")
    if report.get("status") != "success":
        raise ValueError("member_scan_report_not_success")
    if report.get("version") != VERSION:
        raise ValueError(
            f"member_scan_report_version_mismatch report={report.get('version')} runtime={VERSION}"
        )
    created_ts = int(report.get("created_ts", 0) or 0)
    if created_ts <= 0 or time.time() - created_ts > 6 * 3600:
        raise ValueError("member_scan_report_expired")
    return report


def _build_runtime():
    preserve_telegram_extra_fields()
    config = load_config()
    db = DB(str(PROJECT_ROOT / "mory.db"))
    _load_dynamic_states(config, db)

    import telebot

    token = str(config.get("TOKEN", "") or "")
    group_id = int(config.get("GROUP_ID", 0) or 0)
    if not token or not group_id:
        raise RuntimeError("TOKEN_or_GROUP_ID_missing")
    bot = telebot.TeleBot(token, threaded=False)
    return config, db, bot, token, group_id


def _pyrogram_client(config: dict, token: str):
    try:
        from pyrogram import Client
    except ImportError as exc:
        raise RuntimeError("pyrogram_not_installed") from exc

    api_id = int(config.get("TELEGRAM_API_ID", 0) or PUBLIC_TELEGRAM_API_ID)
    api_hash = str(config.get("TELEGRAM_API_HASH", "") or PUBLIC_TELEGRAM_API_HASH)
    return Client(
        "mory-member-ad-scan",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
        no_updates=True,
    )


def _is_blacklisted(db, uid: int) -> bool:
    # 黑名单状态未知时必须中止，不能把查询故障当成“未拉黑”继续处罚。
    return bool(db.is_blacklisted(uid))


async def _personal_channel_messages(app, chat_info) -> tuple[list[Any], bool]:
    personal_chat = getattr(chat_info, "personal_chat", None) if chat_info else None
    channel_id = int(getattr(personal_chat, "id", 0) or 0)
    if not channel_id:
        return [], False
    messages = []
    try:
        async for message in app.get_chat_history(channel_id, limit=3):
            messages.append(message)
        return messages, False
    except Exception as exc:
        logger.debug("[全量扫描] 个人频道帖子不可读 channel=%s err=%s", channel_id, exc)
        return [], True


async def _fetch_member_profile(bot, app, user, delay: float = 0.0) -> dict[str, Any]:
    """并发安全地读取一个成员的完整资料；所有未知状态显式返回。"""
    uid = int(user.id)
    bio = str(getattr(user, "bio", "") or "")
    if delay > 0:
        # 同一批请求按固定间隔起跑，避免有界并发变成瞬时洪峰。
        await asyncio.sleep(delay)

    async def fetch_bot_profile():
        try:
            return await asyncio.to_thread(bot.get_chat, uid), None
        except Exception as exc:
            return None, exc

    async def fetch_mtproto_profile():
        try:
            return await app.get_chat(uid), None
        except Exception as exc:
            return None, exc

    (bot_chat_info, bot_error), (mtproto_chat_info, mtproto_error) = await asyncio.gather(
        fetch_bot_profile(), fetch_mtproto_profile()
    )
    chat_info = bot_chat_info or mtproto_chat_info
    for source in (bot_chat_info, mtproto_chat_info):
        value = str(getattr(source, "bio", "") or "")
        if value:
            bio = value
            break

    bot_error_code = int(getattr(bot_error, "error_code", 0) or 0) if bot_error else 0
    bot_profile_unavailable = bool(bot_error and bot_error_code == 400)
    bot_profile_error = bool(bot_error and not bot_profile_unavailable)
    profile_error = bool(bot_chat_info is None and mtproto_chat_info is None)
    if bot_error:
        logger.debug(
            "[全量扫描] Bot API资料增强不可用 uid=%s code=%s err=%s",
            uid,
            bot_error_code,
            bot_error,
        )
    if mtproto_error:
        logger.debug("[全量扫描] MTProto资料失败 uid=%s err=%s", uid, mtproto_error)

    personal_channel_requested = bool(
        int(getattr(getattr(chat_info, "personal_chat", None), "id", 0) or 0)
    )
    personal_messages, channel_error = await _personal_channel_messages(app, chat_info)
    return {
        "user": user,
        "chat_info": chat_info,
        "bio": bio,
        "profile_error": profile_error,
        "bot_profile_error": bot_profile_error,
        "bot_profile_unavailable": bot_profile_unavailable,
        "personal_messages": personal_messages,
        "personal_channel_requested": personal_channel_requested,
        "channel_error": channel_error,
    }


def _assess_report_quality(
    counts: Counter[str], expected_members: int, limited: bool
) -> dict[str, Any]:
    """分别评估枚举、资料读取和资料判定覆盖，禁止局部结果包装成功。"""
    enumerated = int(counts.get("enumerated", 0))
    profile_requests = int(counts.get("profile_requests", 0))
    profile_errors = int(counts.get("profile_errors", 0))
    bot_profile_errors = int(counts.get("bot_profile_errors", 0))
    bot_profile_unavailable = int(counts.get("bot_profile_unavailable", 0))
    checked = int(counts.get("checked", 0))
    personal_requests = int(counts.get("personal_channel_requests", 0))
    personal_errors = int(counts.get("personal_channel_post_errors", 0))

    coverage = enumerated / expected_members if expected_members else 0.0
    profile_coverage = (
        (profile_requests - profile_errors) / profile_requests if profile_requests else 1.0
    )
    evaluation_coverage = checked / profile_requests if profile_requests else 1.0
    personal_channel_coverage = (
        (personal_requests - personal_errors) / personal_requests
        if personal_requests
        else 1.0
    )
    bot_profile_transport_coverage = (
        (profile_requests - bot_profile_errors) / profile_requests
        if profile_requests
        else 1.0
    )
    bot_profile_enrichment_coverage = (
        (profile_requests - bot_profile_errors - bot_profile_unavailable) / profile_requests
        if profile_requests
        else 1.0
    )

    status = "success"
    errors: list[str] = []
    warnings: list[str] = []
    if enumerated == 0:
        status = "failed"
        errors.append("zero_members_enumerated")
    if expected_members and not limited and coverage < 0.90:
        status = "failed"
        errors.append(f"coverage_below_90_percent:{coverage:.4f}")
    if profile_requests and profile_coverage < 0.90:
        status = "failed"
        errors.append(f"profile_coverage_below_90_percent:{profile_coverage:.4f}")
    if profile_requests and evaluation_coverage < 1.0:
        status = "failed"
        errors.append(f"evaluation_coverage_incomplete:{evaluation_coverage:.4f}")
    if profile_requests and bot_profile_transport_coverage < 0.90:
        status = "failed"
        errors.append(
            "bot_profile_transport_coverage_below_90_percent:"
            f"{bot_profile_transport_coverage:.4f}"
        )
    if profile_requests and bot_profile_enrichment_coverage < 0.90:
        warnings.append(
            "bot_profile_enrichment_limited:"
            f"{bot_profile_enrichment_coverage:.4f}"
        )
    if personal_requests and personal_channel_coverage < 0.90:
        warnings.append(
            "personal_channel_post_coverage_limited:"
            f"{personal_channel_coverage:.4f}"
        )
    if limited:
        status = "partial"
        errors.append("max_members_limit_active")

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "coverage": coverage,
        "profile_coverage": profile_coverage,
        "evaluation_coverage": evaluation_coverage,
        "personal_channel_coverage": personal_channel_coverage,
        "bot_profile_transport_coverage": bot_profile_transport_coverage,
        "bot_profile_enrichment_coverage": bot_profile_enrichment_coverage,
    }


async def _resolve_group_ref(app, bot, group_id: int):
    chat_info = bot.get_chat(group_id)
    username = str(getattr(chat_info, "username", "") or "")
    group_ref: Any = f"@{username}" if username else group_id
    entity = await app.get_chat(group_ref)
    return group_ref, int(getattr(entity, "members_count", 0) or 0)


async def _report_scan(args) -> dict[str, Any]:
    config, db, bot, token, group_id = _build_runtime()
    evaluator = MemberAdEvaluator(bot, db, config)
    counts: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    started = int(time.time())

    app = _pyrogram_client(config, token)
    async with app:
        group_ref, expected_members = await _resolve_group_ref(app, bot, group_id)
        admin_ids = set()
        from pyrogram.enums import ChatMembersFilter

        async for member in app.get_chat_members(
            group_ref, filter=ChatMembersFilter.ADMINISTRATORS
        ):
            admin_ids.add(int(member.user.id))
        admin_ids.add(int((await app.get_me()).id))
        exempt_ids = configured_exempt_ids(config)

        pending_profiles: list[Any] = []

        async def consume_profiles() -> None:
            if not pending_profiles:
                return
            profiles = await asyncio.gather(*pending_profiles)
            pending_profiles.clear()
            for profile in profiles:
                user = profile["user"]
                uid = int(user.id)
                if profile["profile_error"]:
                    counts["profile_errors"] += 1
                if profile["bot_profile_error"]:
                    counts["bot_profile_errors"] += 1
                if profile["bot_profile_unavailable"]:
                    counts["bot_profile_unavailable"] += 1
                if profile["personal_channel_requested"]:
                    counts["personal_channel_requests"] += 1
                if profile["channel_error"]:
                    counts["personal_channel_post_errors"] += 1

                decision = evaluator.evaluate(
                    user=user,
                    chat_id=group_id,
                    chat_info=profile["chat_info"],
                    bio=profile["bio"],
                    personal_channel_messages=profile["personal_messages"],
                    review_avatar=True,
                    review_avatar_without_weak_signal=bool(args.avatar_all),
                    message_limit=args.message_limit,
                )
                counts["checked"] += 1
                if decision.get("is_ad"):
                    counts["high_confidence"] += 1
                    counts[f"source_{decision.get('source', 'unknown')}"] += 1
                    candidates.append({"uid": uid, **decision})
                elif decision.get("weak_signals"):
                    counts["weak_only"] += 1

            logger.info(
                "[全量扫描] enumerated=%s checked=%s high_confidence=%s",
                counts["enumerated"],
                counts["checked"],
                counts["high_confidence"],
            )

        async for member in app.get_chat_members(group_ref):
            if args.max_members and counts["enumerated"] >= args.max_members:
                counts["limited"] = 1
                break
            counts["enumerated"] += 1

            user = member.user
            uid = int(user.id)
            if (
                uid in admin_ids
                or uid in exempt_ids
                or bool(getattr(user, "is_bot", False))
                or bool(getattr(user, "is_deleted", False))
            ):
                counts["exempt_or_bot"] += 1
                continue
            if _is_blacklisted(db, uid):
                counts["already_blacklisted"] += 1
                continue
            counts["profile_requests"] += 1
            pending_profiles.append(
                _fetch_member_profile(
                    bot,
                    app,
                    user,
                    args.delay * len(pending_profiles),
                )
            )
            if len(pending_profiles) >= args.profile_concurrency:
                await consume_profiles()

        await consume_profiles()

    quality = _assess_report_quality(counts, expected_members, bool(args.max_members))

    report = {
        "schema": SCHEMA,
        "mode": "report",
        "status": quality["status"],
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_ts": int(time.time()),
        "duration_seconds": int(time.time()) - started,
        "chat_id": group_id,
        "expected_members": expected_members,
        "coverage": round(quality["coverage"], 6),
        "profile_coverage": round(quality["profile_coverage"], 6),
        "evaluation_coverage": round(quality["evaluation_coverage"], 6),
        "personal_channel_coverage": round(
            quality["personal_channel_coverage"], 6
        ),
        "bot_profile_transport_coverage": round(
            quality["bot_profile_transport_coverage"], 6
        ),
        "bot_profile_enrichment_coverage": round(
            quality["bot_profile_enrichment_coverage"], 6
        ),
        "external_auxiliary_signals_used": False,
        "avatar_mode": "all" if args.avatar_all else "weak-signal-candidates",
        "message_limit": args.message_limit,
        "counts": dict(counts),
        "errors": quality["errors"],
        "warnings": quality["warnings"],
        "candidates": candidates,
    }
    report["fingerprint"] = _fingerprint(report)
    return report


async def _apply_report(args) -> dict[str, Any]:
    source_report = _load_report(Path(args.apply_report).resolve())
    config, db, bot, token, group_id = _build_runtime()
    if int(source_report.get("chat_id", 0) or 0) != group_id:
        raise ValueError("member_scan_report_chat_mismatch")

    evaluator = MemberAdEvaluator(bot, db, config)
    counts: Counter[str] = Counter(candidates=len(source_report.get("candidates", [])))
    receipts = []
    started = int(time.time())
    exempt_ids = configured_exempt_ids(config)

    app = _pyrogram_client(config, token)
    async with app:
        group_ref, _expected = await _resolve_group_ref(app, bot, group_id)
        admin_ids = set()
        from pyrogram.enums import ChatMembersFilter

        async for member in app.get_chat_members(
            group_ref, filter=ChatMembersFilter.ADMINISTRATORS
        ):
            admin_ids.add(int(member.user.id))
        admin_ids.add(int((await app.get_me()).id))

        candidate_ids = {
            int(item.get("uid", 0) or 0)
            for item in source_report.get("candidates", [])
            if int(item.get("uid", 0) or 0)
        }
        current_users = {}
        async for member in app.get_chat_members(group_ref):
            uid = int(member.user.id)
            if uid in candidate_ids:
                current_users[uid] = member.user

        for candidate in source_report.get("candidates", []):
            uid = int(candidate.get("uid", 0) or 0)
            if not uid:
                counts["invalid_candidate"] += 1
                continue
            if uid in admin_ids or uid in exempt_ids:
                counts["exempt"] += 1
                continue
            if _is_blacklisted(db, uid):
                counts["already_blacklisted"] += 1
                continue

            try:
                member = bot.get_chat_member(group_id, uid)
                if str(getattr(member, "status", "")) in ("left", "kicked"):
                    counts["left"] += 1
                    continue
                user = current_users.get(uid) or member.user
            except Exception as exc:
                counts["membership_unknown"] += 1
                receipts.append({"uid": uid, "status": "skipped", "reason": "membership_unknown"})
                logger.warning("[扫描应用] 成员身份不可确认 uid=%s err=%s", uid, exc)
                continue

            profile = await _fetch_member_profile(bot, app, user)
            if profile["profile_error"]:
                counts["profile_unknown"] += 1
                receipts.append({"uid": uid, "status": "skipped", "reason": "profile_unknown"})
                logger.warning("[扫描应用] 资料不可确认 uid=%s", uid)
                continue
            if profile["bot_profile_error"]:
                counts["bot_profile_transport_unknown"] += 1
                receipts.append(
                    {
                        "uid": uid,
                        "status": "skipped",
                        "reason": "bot_profile_transport_unknown",
                    }
                )
                logger.warning(
                    "[扫描应用] Bot API资料增强发生传输异常 uid=%s，按未知状态跳过",
                    uid,
                )
                continue
            if profile["bot_profile_unavailable"]:
                counts["bot_profile_unavailable"] += 1
            if profile["channel_error"]:
                counts["personal_channel_post_errors"] += 1

            decision = evaluator.evaluate(
                user=user,
                chat_id=group_id,
                chat_info=profile["chat_info"],
                bio=profile["bio"],
                personal_channel_messages=profile["personal_messages"],
                review_avatar=True,
                review_avatar_without_weak_signal=source_report.get("avatar_mode") == "all",
                message_limit=int(source_report.get("message_limit", 20) or 20),
            )
            counts["rechecked"] += 1
            if not decision.get("is_ad"):
                counts["no_longer_high_confidence"] += 1
                receipts.append({"uid": uid, "status": "skipped", "reason": "no_longer_high_confidence"})
                continue

            result = enforce_member_decision(
                bot=bot,
                db=db,
                config=config,
                chat_id=group_id,
                user=user,
                decision=decision,
                notify_admin=True,
            )
            data = result.get("data", {})
            if data.get("skipped_reason"):
                counts[f"skipped_{data['skipped_reason']}"] += 1
                status = "skipped"
            elif result.get("code") == 200:
                counts["enforced"] += 1
                status = "enforced"
            else:
                counts["failed"] += 1
                status = "failed"
            receipts.append(
                {
                    "uid": uid,
                    "status": status,
                    "source": decision.get("source"),
                    "muted": bool(data.get("muted")),
                    "blacklisted": bool(data.get("blacklisted")),
                    "deleted_count": int(data.get("deleted_count", 0) or 0),
                    "skipped_reason": data.get("skipped_reason", ""),
                }
            )

    status = "success" if counts.get("failed", 0) == 0 else "failed"
    report = {
        "schema": SCHEMA,
        "mode": "apply",
        "status": status,
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_ts": int(time.time()),
        "duration_seconds": int(time.time()) - started,
        "chat_id": group_id,
        "source_report_fingerprint": source_report["fingerprint"],
        "counts": dict(counts),
        "receipts": receipts,
    }
    report["fingerprint"] = _fingerprint(report)
    return report


def _parse_args():
    parser = argparse.ArgumentParser(description="Mory 全量群成员广告扫描")
    parser.add_argument("--output", required=True, help="私有 JSON 回执路径")
    parser.add_argument("--apply-report", help="复核并应用指定报告中的高置信候选")
    parser.add_argument("--message-limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--profile-concurrency", type=int, default=8)
    parser.add_argument("--avatar-all", action="store_true", help="昂贵：复核每个成员头像")
    parser.add_argument("--max-members", type=int, default=0, help="仅调试；启用后报告不可应用")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not 1 <= args.profile_concurrency <= 16:
        raise ValueError("profile_concurrency_must_be_1_to_16")
    if args.apply_report and args.max_members:
        raise ValueError("apply_report_does_not_accept_max_members")
    if args.apply_report:
        result = asyncio.run(_apply_report(args))
    else:
        result = asyncio.run(_report_scan(args))
    _write_private_json(Path(args.output), result)
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "mode": result.get("mode"),
                "version": result.get("version"),
                "counts": result.get("counts"),
                "coverage": result.get("coverage"),
                "fingerprint": result.get("fingerprint"),
                "output": str(Path(args.output).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
