# -*- coding: utf-8 -*-

from types import SimpleNamespace


class _FakeDB:
    def __init__(self, blacklisted=True):
        self.blacklisted = blacklisted
        self.checked = []

    def is_blacklisted(self, uid):
        self.checked.append(uid)
        return self.blacklisted


def _reaction_update(uid=42, new_reaction=True):
    return SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        message_id=77,
        user=SimpleNamespace(id=uid),
        new_reaction=[SimpleNamespace(type="emoji", emoji="👍")] if new_reaction else [],
    )


def test_message_reaction_update_cleans_blacklisted_user_reaction(monkeypatch):
    from core.handlers import media_handlers

    calls = []
    monkeypatch.setattr(
        media_handlers,
        "delete_message_reaction_compat",
        lambda bot, chat_id, message_id, user_id=None, actor_chat_id=None: calls.append(
            (chat_id, message_id, user_id)
        ) or True,
    )

    handled = media_handlers._handle_message_reaction_update(
        bot=object(),
        update=_reaction_update(),
        config={"AD_CLEANUP_REACTIONS": True},
        db=_FakeDB(blacklisted=True),
    )

    assert handled is True
    assert calls == [(-1001, 77, 42)]


def test_message_reaction_update_ignores_normal_user(monkeypatch):
    from core.handlers import media_handlers

    calls = []
    monkeypatch.setattr(
        media_handlers,
        "delete_message_reaction_compat",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    handled = media_handlers._handle_message_reaction_update(
        bot=object(),
        update=_reaction_update(),
        config={"AD_CLEANUP_REACTIONS": True},
        db=_FakeDB(blacklisted=False),
    )

    assert handled is False
    assert calls == []


def test_message_reaction_update_respects_cleanup_switch(monkeypatch):
    from core.handlers import media_handlers

    calls = []
    monkeypatch.setattr(
        media_handlers,
        "delete_message_reaction_compat",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    handled = media_handlers._handle_message_reaction_update(
        bot=object(),
        update=_reaction_update(),
        config={"AD_CLEANUP_REACTIONS": False},
        db=_FakeDB(blacklisted=True),
    )

    assert handled is False
    assert calls == []
