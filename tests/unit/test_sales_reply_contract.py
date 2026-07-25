"""ReplyContract v1 sales-bypass regression tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from core.message_dispatcher import (
    _exec_send_price_list,
    _exec_send_private_guide,
    _get_function_tools,
    _handle_tool_calls,
)
from core.handlers.ai_reply_handler import (
    _cancel_cart_recovery_for_opt_out,
    _dispatch_p10_ai,
)
from modules.content import handle_easter_eggs
from modules.sales_center import handle_price_request


class _Bot:
    def __init__(self):
        self.sent = []

    def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class _MoryBot:
    def __init__(self):
        self.replies = []

    def reply_and_track(self, message, text, **kwargs):
        self.replies.append((text, kwargs))


class _Db:
    def __init__(self):
        self.cart = []
        self.events = []

    def set_cart(self, uid):
        self.cart.append(uid)

    def log_conversion_event(self, uid, event):
        self.events.append((uid, event))


class _RecoveryDb:
    def __init__(self, *, should_fail=False):
        self.cancelled = []
        self.should_fail = should_fail

    def cancel_cart_recovery(self, uid):
        if self.should_fail:
            raise RuntimeError("db unavailable")
        self.cancelled.append(uid)


def _message(text: str):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=42, first_name="Tester"),
        chat=SimpleNamespace(id=-100, type="supergroup"),
        reply_to_message=None,
    )


def test_old_sales_tools_are_not_exposed_or_allowed_to_send_private_messages():
    assert _get_function_tools() == []

    bot = _Bot()
    message = _message("多少钱")
    assert "@moryselect" in _exec_send_price_list(bot, message, {}, {})
    assert "@moryselect" in _exec_send_private_guide(bot, message, {}, {})
    assert bot.sent == []

    tool_message = {
        "content": "先回答你。",
        "tool_calls": [
            {
                "function": {
                    "name": "send_price_list",
                    "arguments": json.dumps({"category": "全部"}),
                }
            },
            {
                "function": {
                    "name": "send_private_guide",
                    "arguments": json.dumps({"reason": "群里不方便"}),
                }
            },
        ],
    }
    result = _handle_tool_calls(tool_message, bot, message, {}, _Db())
    assert result == "先回答你。"
    assert bot.sent == []


def test_p8_price_bypass_only_routes_to_preview():
    mory_bot = _MoryBot()
    db = _Db()

    assert handle_easter_eggs(mory_bot, _message("多少钱"), {}, db) is True
    reply = mory_bot.replies[0][0]
    assert "@moryselect" in reply
    assert "@MorychannelBot" not in reply
    assert "¥" not in reply
    assert db.cart == [42]
    assert db.events == [(42, "interested")]


def test_p8_explicit_purchase_routes_to_subscribe_only():
    mory_bot = _MoryBot()

    assert handle_easter_eggs(mory_bot, _message("怎么买"), {}, _Db()) is True
    reply = mory_bot.replies[0][0]
    assert "@MorychannelBot" in reply
    assert "@moryselect" not in reply.lower()


def test_optional_sales_center_uses_same_single_target_contract():
    config = {"SALES_CENTER_CONFIG": {"enabled": True}}

    preview_bot = _MoryBot()
    assert handle_price_request(preview_bot, _message("价格表"), config, _Db()) is True
    preview_reply = preview_bot.replies[0][0]
    assert "@moryselect" in preview_reply
    assert "@MorychannelBot" not in preview_reply
    assert "¥" not in preview_reply

    purchase_bot = _MoryBot()
    assert handle_price_request(purchase_bot, _message("我要下单"), config, _Db()) is True
    purchase_reply = purchase_bot.replies[0][0]
    assert "@MorychannelBot" in purchase_reply
    assert "@moryselect" not in purchase_reply.lower()


def test_explicit_opt_out_cancels_pending_cart_recovery_with_failure_isolation():
    db = _RecoveryDb()
    assert _cancel_cart_recovery_for_opt_out(db, 42, "user_opt_out") is True
    assert db.cancelled == [42]

    assert _cancel_cart_recovery_for_opt_out(db, 42, "preview_or_objection") is False
    assert db.cancelled == [42]

    failing_db = _RecoveryDb(should_fail=True)
    assert _cancel_cart_recovery_for_opt_out(
        failing_db,
        42,
        "user_opt_out",
    ) is False


def test_group_opt_out_cancels_recovery_even_when_reply_probability_skips(monkeypatch):
    db = _RecoveryDb()
    message = _message("不买了")
    context = SimpleNamespace(
        config={"REPLY_CHANCE": 0},
        db=db,
        bot=_Bot(),
        bot_username="mory_assistant_bot",
        bot_id=999,
        mory_bot=_MoryBot(),
        ai=SimpleNamespace(),
    )
    dispatch = SimpleNamespace(
        msg=message,
        ctx=context,
        text=message.text,
        uid=42,
        uname="Tester",
        chat_id=-100,
        is_priv=False,
        is_group=True,
        conversation_history=[],
        _analysis={"mode": "normal"},
    )
    monkeypatch.setattr(
        "core.handlers.ai_reply_handler.random.randint",
        lambda *_args: 100,
    )

    _dispatch_p10_ai(dispatch)

    assert db.cancelled == [42]
