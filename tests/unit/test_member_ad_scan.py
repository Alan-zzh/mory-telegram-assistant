# -*- coding: utf-8 -*-
"""存量成员扫描必须复用当前规则、默认只报告并拒绝零覆盖假绿。"""

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
