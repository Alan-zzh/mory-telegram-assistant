"""Feedback replies must only claim an admin notification after a real send succeeds."""
from pathlib import Path
from types import SimpleNamespace

from core.message_dispatcher import _handle_feedback
from core.handlers.ai_reply_handler import (
    _build_unresolved_handoff_reply,
    _notify_mory_for_unresolved,
)


class _Bot:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_message(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("telegram unavailable")
        self.sent.append((args, kwargs))


class _MoryBot:
    def __init__(self):
        self.replies = []

    def reply_and_track(self, _message, text, **_kwargs):
        self.replies.append(text)


def _dispatch(*, fail=False):
    bot = _Bot(fail=fail)
    mory = _MoryBot()
    message = SimpleNamespace()
    return SimpleNamespace(
        msg=message,
        ctx=SimpleNamespace(config={"ADMIN_ID": 999}, db=SimpleNamespace(), bot=bot, mory_bot=mory),
        text="这个功能有问题",
        uid=42,
        uname="Tester",
        chat_id=42,
        is_priv=True,
        is_group=False,
    ), bot, mory


def test_private_feedback_says_submitted_only_after_notification_success():
    dctx, bot, mory = _dispatch()
    assert _handle_feedback(dctx, {"mode": "feedback"}) is True
    assert len(bot.sent) == 1
    assert mory.replies == ["收到，已提交给管理员查看。"]


def test_private_feedback_does_not_claim_notification_after_send_failure():
    dctx, bot, mory = _dispatch(fail=True)
    assert _handle_feedback(dctx, {"mode": "feedback"}) is True
    assert bot.sent == []
    assert "不能确认通知是否送达" in mory.replies[0]
    assert "尽快" not in mory.replies[0]


def test_private_unban_complaint_never_restores_permissions(monkeypatch):
    """A user's claim is feedback, not authorization to clear enforcement state."""
    dctx, bot, mory = _dispatch()
    dctx.text = "我被封了，帮我解封"
    dctx.ctx.config["GROUP_ID"] = -1001

    restore_calls = []
    monkeypatch.setattr(
        "modules.ad_enforcement.restore_ad_user",
        lambda *args, **kwargs: restore_calls.append((args, kwargs)),
    )

    assert _handle_feedback(dctx, {"mode": "feedback"}) is True
    assert restore_calls == []
    assert len(bot.sent) == 1
    assert mory.replies == ["收到，你的解封申请已提交给管理员审核；审核前不会改动封禁状态。"]


def test_legacy_feedback_handler_has_no_self_unban_call():
    """The dormant compatibility handler must not preserve a privilege bypass."""
    source = (
        Path(__file__).resolve().parents[2] / "core" / "handlers" / "ai_handlers.py"
    ).read_text(encoding="utf-8")
    assert "restore_ad_user(" not in source
    assert "actor_id=uid" not in source


def test_legacy_feedback_handler_contains_no_false_delivery_promises():
    """The retained legacy dispatcher must follow the same truthfulness contract."""
    source = (
        Path(__file__).resolve().parents[2] / "core" / "handlers" / "ai_handlers.py"
    ).read_text(encoding="utf-8")
    for phrase in (
        "我帮你转达Mory",
        "我已经通知管理员，请稍等一下",
        "会尽快",
    ):
        assert phrase not in source


def test_complaint_prompt_never_claims_unverified_admin_delivery():
    """Low confidence and failed notifications share this same AI prompt path."""
    source = (
        Path(__file__).resolve().parents[2]
        / "core"
        / "handlers"
        / "ai_reply_handler.py"
    ).read_text(encoding="utf-8")
    assert "承诺转达 Mory" not in source
    assert "不要声称已转达、已通知或承诺处理时效" in source


def test_unresolved_handoff_reports_success_only_after_real_send():
    dctx, bot, _mory = _dispatch()

    assert _notify_mory_for_unresolved(dctx) is True
    assert len(bot.sent) == 1
    reply = _build_unresolved_handoff_reply("", is_priv=True, delivered=True)
    assert "已经转达给 Mory" in reply
    assert "实际回复为准" in reply
    assert "直接联系" not in reply


def test_unresolved_handoff_reports_failure_and_real_contact_path():
    dctx, bot, _mory = _dispatch(fail=True)

    assert _notify_mory_for_unresolved(dctx) is False
    assert bot.sent == []
    reply = _build_unresolved_handoff_reply("", is_priv=True, delivered=False)
    assert "没能送达 Mory" in reply
    assert "@Moryfansbot" in reply
    assert "已经转达" not in reply
