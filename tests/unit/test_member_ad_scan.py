# -*- coding: utf-8 -*-
"""存量成员扫描必须复用当前规则、默认只报告并拒绝零覆盖假绿。"""

from pathlib import Path
from types import SimpleNamespace

import pytest


class _DB:
    def __init__(self, messages=None):
        self.messages = list(messages or [])

    def get_user_messages(self, _uid, _chat_id, limit=20):
        return self.messages[:limit]


class _User:
    id = 42
    first_name = "普通"
    last_name = "用户"
    username = ""
    is_bot = False


def _clean_profile_result(**overrides):
    result = {
        "is_ad": False,
        "score": 0,
        "reason": "",
        "source": "none",
    }
    result.update(overrides)
    return result


def test_profile_high_confidence_uses_current_profile_detector(monkeypatch):
    from modules import ad_profile_signals
    from modules.member_ad_scan import MemberAdEvaluator

    monkeypatch.setattr(
        ad_profile_signals,
        "detect_profile_ad_signal",
        lambda *_args, **_kwargs: _clean_profile_result(
            is_ad=True,
            score=3,
            reason="个人频道三锚点",
            source="personal_chat",
        ),
    )
    evaluator = MemberAdEvaluator(SimpleNamespace(), _DB(), {})

    result = evaluator.evaluate(user=_User(), chat_id=-1001)

    assert result["is_ad"] is True
    assert result["source"] == "personal_chat"
    assert result["current_message_is_ad"] is False


def test_latest_message_rule_marks_only_that_snapshot_as_ad(monkeypatch):
    from modules import ad_profile_signals
    from modules.member_ad_scan import MemberAdEvaluator

    monkeypatch.setattr(
        ad_profile_signals,
        "detect_profile_ad_signal",
        lambda *_args, **_kwargs: _clean_profile_result(),
    )
    db = _DB([
        {
            "chat_id": -1001,
            "msg_id": 88,
            "text": "加我微信日赚千元",
            "deleted": 0,
        }
    ])
    evaluator = MemberAdEvaluator(SimpleNamespace(), db, {})

    result = evaluator.evaluate(user=_User(), chat_id=-1001, review_avatar=False)

    assert result["is_ad"] is True
    assert result["source"] == "message_snapshot"
    assert result["current_msg_id"] == 88
    assert result["current_message_is_ad"] is True


def test_clean_profile_and_message_do_not_call_avatar_without_weak_signal(monkeypatch):
    from modules import ad_profile_signals, avatar_detector
    from modules.member_ad_scan import MemberAdEvaluator

    monkeypatch.setattr(
        ad_profile_signals,
        "detect_profile_ad_signal",
        lambda *_args, **_kwargs: _clean_profile_result(),
    )
    calls = []
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_marketing",
        lambda *_args, **_kwargs: calls.append(True) or (False, "正常", 0, {}),
    )
    evaluator = MemberAdEvaluator(SimpleNamespace(), _DB(), {})

    result = evaluator.evaluate(user=_User(), chat_id=-1001, review_avatar=True)

    assert result["is_ad"] is False
    assert calls == []


def test_ordinary_username_is_not_direct_ad_evidence(monkeypatch):
    from modules import ad_profile_signals
    from modules.member_ad_scan import MemberAdEvaluator

    monkeypatch.setattr(
        ad_profile_signals,
        "detect_profile_ad_signal",
        lambda *_args, **_kwargs: _clean_profile_result(),
    )
    user = SimpleNamespace(
        id=43,
        first_name="Alice",
        last_name="Smith",
        username="alice313",
        is_bot=False,
    )

    result = MemberAdEvaluator(SimpleNamespace(), _DB(), {}).evaluate(
        user=user,
        chat_id=-1001,
        review_avatar=False,
    )

    assert result["is_ad"] is False
    assert result["weak_signals"] == []


def test_high_confidence_avatar_can_block_only_after_explicit_review(monkeypatch):
    from modules import ad_profile_signals, avatar_detector
    from modules.member_ad_scan import MemberAdEvaluator

    monkeypatch.setattr(
        ad_profile_signals,
        "detect_profile_ad_signal",
        lambda *_args, **_kwargs: _clean_profile_result(score=1, reason="资料弱信号"),
    )
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_marketing",
        lambda *_args, **_kwargs: (
            True,
            "AI视觉复核: marketing(明确二维码)",
            2,
            {"type": "marketing", "confidence": 0.97},
        ),
    )
    evaluator = MemberAdEvaluator(SimpleNamespace(), _DB(), {})

    result = evaluator.evaluate(user=_User(), chat_id=-1001)

    assert result["is_ad"] is True
    assert result["source"] == "avatar"


def test_enforcement_rejects_weak_decision():
    from modules.member_ad_scan import enforce_member_decision

    with pytest.raises(ValueError, match="weak_or_clean"):
        enforce_member_decision(
            bot=SimpleNamespace(),
            db=SimpleNamespace(),
            config={},
            chat_id=-1001,
            user=_User(),
            decision={"is_ad": False},
        )


def test_configured_admins_and_whitelist_are_exempt_before_detection():
    from modules.member_ad_scan import configured_exempt_ids

    assert configured_exempt_ids(
        {
            "ADMIN_ID": "11",
            "ADMIN_IDS": [12, "13"],
            "AD_WHITELIST": {"user_ids": [14, "bad"]},
        }
    ) == {11, 12, 13, 14}


def test_known_member_scan_zero_coverage_is_failure(monkeypatch):
    from modules import member_ad_scan

    class _Conn:
        def execute(self, query, _params=()):
            rows = [(42,)] if query == "SELECT uid FROM users" else []
            return SimpleNamespace(fetchall=lambda: rows)

    class _Bot:
        def get_chat_administrators(self, _chat_id):
            return []

        def get_me(self):
            return SimpleNamespace(id=7)

        def get_chat_member(self, _chat_id, _uid):
            raise RuntimeError("network unavailable")

    with pytest.raises(RuntimeError, match="member_scan_zero_coverage"):
        member_ad_scan.scan_known_group_members(
            bot=_Bot(),
            db=SimpleNamespace(conn=_Conn()),
            config={},
            chat_id=-1001,
            delay_seconds=0,
        )


def test_report_fingerprint_detects_tampering():
    from scripts.scan_group import _fingerprint

    report = {"schema": "mory.member-ad-scan/v1", "mode": "report", "counts": {"checked": 9}}
    report["fingerprint"] = _fingerprint(report)
    assert report["fingerprint"] == _fingerprint(report)

    report["counts"]["checked"] = 10
    assert report["fingerprint"] != _fingerprint(report)


def test_profile_fetch_preserves_unknown_state_without_crashing(monkeypatch):
    import asyncio

    from scripts.scan_group import _fetch_member_profile

    class _Bot:
        def get_chat(self, _uid):
            raise RuntimeError("telegram unavailable")

    class _App:
        async def get_chat(self, _uid):
            return SimpleNamespace(bio="fallback bio")

    monkeypatch.setattr(
        "scripts.scan_group._personal_channel_messages",
        lambda *_args, **_kwargs: _async_value(([], False)),
    )
    result = asyncio.run(_fetch_member_profile(_Bot(), _App(), _User()))

    assert result["profile_error"] is False
    assert result["bot_profile_error"] is True
    assert result["bot_profile_unavailable"] is False
    assert result["bio"] == "fallback bio"
    assert result["personal_channel_requested"] is False


def test_report_quality_fails_closed_on_incomplete_profile_coverage():
    from collections import Counter

    from scripts.scan_group import _assess_report_quality

    counts = Counter(
        enumerated=100,
        profile_requests=80,
        profile_errors=9,
        checked=80,
        personal_channel_requests=10,
        personal_channel_post_errors=0,
    )
    result = _assess_report_quality(counts, expected_members=100, limited=False)

    assert result["status"] == "failed"
    assert result["profile_coverage"] == pytest.approx(71 / 80)
    assert result["errors"] == ["profile_coverage_below_90_percent:0.8875"]


def test_report_quality_reports_each_coverage_dimension():
    from collections import Counter

    from scripts.scan_group import _assess_report_quality

    counts = Counter(
        enumerated=95,
        profile_requests=90,
        profile_errors=4,
        checked=90,
        personal_channel_requests=20,
        personal_channel_post_errors=1,
    )
    result = _assess_report_quality(counts, expected_members=100, limited=False)

    assert result["status"] == "success"
    assert result["coverage"] == pytest.approx(0.95)
    assert result["profile_coverage"] == pytest.approx(86 / 90)
    assert result["evaluation_coverage"] == 1.0
    assert result["personal_channel_coverage"] == pytest.approx(0.95)
    assert result["bot_profile_transport_coverage"] == 1.0


def test_report_quality_allows_explicit_botapi_400_unavailability():
    from collections import Counter

    from scripts.scan_group import _assess_report_quality

    counts = Counter(
        enumerated=100,
        profile_requests=100,
        profile_errors=0,
        checked=100,
        bot_profile_unavailable=90,
    )
    result = _assess_report_quality(counts, expected_members=100, limited=False)

    assert result["status"] == "success"
    assert result["profile_coverage"] == 1.0
    assert result["bot_profile_transport_coverage"] == 1.0
    assert result["bot_profile_enrichment_coverage"] == pytest.approx(0.1)
    assert result["warnings"] == ["bot_profile_enrichment_limited:0.1000"]


def test_report_quality_fails_on_botapi_transport_errors():
    from collections import Counter

    from scripts.scan_group import _assess_report_quality

    counts = Counter(
        enumerated=100,
        profile_requests=100,
        profile_errors=0,
        checked=100,
        bot_profile_errors=11,
    )
    result = _assess_report_quality(counts, expected_members=100, limited=False)

    assert result["status"] == "failed"
    assert result["errors"] == [
        "bot_profile_transport_coverage_below_90_percent:0.8900"
    ]


def test_apply_path_skips_bot_transport_unknown_before_evaluation():
    source = Path("scripts/scan_group.py").read_text(encoding="utf-8")
    unknown_branch = source.index('"reason": "bot_profile_transport_unknown"')
    evaluation = source.index("decision = evaluator.evaluate(", unknown_branch)

    assert "continue" in source[unknown_branch:evaluation]


async def _async_value(value):
    return value
