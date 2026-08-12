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

            chat_info = None
            bio = str(getattr(user, "bio", "") or "")
            try:
                chat_info = bot.get_chat(uid)
                bio = str(getattr(chat_info, "bio", "") or bio)
            except Exception as exc:
                counts["profile_errors"] += 1
                logger.debug("[全量扫描] get_chat失败 uid=%s err=%s", uid, exc)
                if not bio:
                    try:
                        full_user = await app.get_chat(uid)
                        bio = str(getattr(full_user, "bio", "") or "")
                    except Exception:
                        pass

            personal_messages, channel_error = await _personal_channel_messages(app, chat_info)
            if channel_error:
                counts["personal_channel_post_errors"] += 1

            decision = evaluator.evaluate(
                user=user,
                chat_id=group_id,
                chat_info=chat_info,
                bio=bio,
                personal_channel_messages=personal_messages,
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

            if counts["enumerated"] % 200 == 0:
                logger.info(
                    "[全量扫描] enumerated=%s checked=%s high_confidence=%s",
                    counts["enumerated"],
                    counts["checked"],
                    counts["high_confidence"],
                )
            if args.delay > 0:
                await asyncio.sleep(args.delay)

    coverage = counts["enumerated"] / expected_members if expected_members else 0.0
    status = "success"
    errors = []
    if counts["enumerated"] == 0:
        status = "failed"
        errors.append("zero_members_enumerated")
    if expected_members and not args.max_members and coverage < 0.90:
        status = "failed"
        errors.append(f"coverage_below_90_percent:{coverage:.4f}")
    if args.max_members:
        status = "partial"
        errors.append("max_members_limit_active")

    report = {
        "schema": SCHEMA,
        "mode": "report",
        "status": status,
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_ts": int(time.time()),
        "duration_seconds": int(time.time()) - started,
        "chat_id": group_id,
        "expected_members": expected_members,
        "coverage": round(coverage, 6),
        "external_auxiliary_signals_used": False,
        "avatar_mode": "all" if args.avatar_all else "weak-signal-candidates",
        "message_limit": args.message_limit,
        "counts": dict(counts),
        "errors": errors,
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
                user = member.user
            except Exception as exc:
                counts["membership_unknown"] += 1
                receipts.append({"uid": uid, "status": "skipped", "reason": "membership_unknown"})
                logger.warning("[扫描应用] 成员身份不可确认 uid=%s err=%s", uid, exc)
                continue

            try:
                chat_info = bot.get_chat(uid)
                bio = str(getattr(chat_info, "bio", "") or "")
            except Exception as exc:
                counts["profile_unknown"] += 1
                receipts.append({"uid": uid, "status": "skipped", "reason": "profile_unknown"})
                logger.warning("[扫描应用] 资料不可确认 uid=%s err=%s", uid, exc)
                continue

            personal_messages, channel_error = await _personal_channel_messages(app, chat_info)
            if channel_error:
                counts["personal_channel_post_errors"] += 1

            decision = evaluator.evaluate(
                user=user,
                chat_id=group_id,
                chat_info=chat_info,
                bio=bio,
                personal_channel_messages=personal_messages,
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
    parser.add_argument("--avatar-all", action="store_true", help="昂贵：复核每个成员头像")
    parser.add_argument("--max-members", type=int, default=0, help="仅调试；启用后报告不可应用")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
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
