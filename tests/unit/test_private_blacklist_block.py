# -*- coding: utf-8 -*-
"""[Codex] 手动拉黑后的私聊用户不能继续中继或触发 AI。"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeDB:
    def __init__(self, blacklisted=True):
        self.blacklisted = blacklisted

    def is_blacklisted(self, uid):
        return self.blacklisted and uid == 42


class _FakeBot:
    def __init__(self):
        self.deleted = []
        self.restricted = []
        self.sent = []

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


class _FakeMessage:
    content_type = "text"
    message_id = 100
    text = "还想聊"


def _make_dctx(is_priv=True, is_group=False):
    from core.message_dispatcher import DispatchContext

    ctx = type("Ctx", (), {
        "config": {"ADMIN_ID": 777, "ADMIN_IDS": [777], "RELAY_MODE_ENABLED": True},
        "db": _FakeDB(),
        "bot": _FakeBot(),
    })()
    return DispatchContext(
        ctx=ctx,
        msg=_FakeMessage(),
        uid=42,
        uname="黑名单用户",
        chat_id=42,
        is_priv=is_priv,
        is_group=is_group,
        text="还想聊",
    )


def test_p0_blocks_private_blacklisted_before_relay_or_ai():
    from core.message_dispatcher import _dispatch_p0_member

    dctx = _make_dctx(is_priv=True, is_group=False)

    assert _dispatch_p0_member(dctx) is True
    assert dctx.ctx.bot.sent == []


def test_p1_private_blacklisted_does_not_run_group_enforcement():
    from core.message_dispatcher import _dispatch_p1_p3_security

    dctx = _make_dctx(is_priv=True, is_group=False)

    assert _dispatch_p1_p3_security(dctx) is True
    assert dctx.ctx.bot.deleted == []
    assert dctx.ctx.bot.restricted == []
