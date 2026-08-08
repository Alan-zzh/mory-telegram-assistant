# -*- coding: utf-8 -*-
"""/myid 等工具命令分发单测。"""
from types import SimpleNamespace


def _message(text, uid=42):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=uid),
        chat=SimpleNamespace(id=-1001),
        message_id=9,
    )


class _Bot:
    def __init__(self):
        self.replied = []

    def reply_to(self, message, text):
        self.replied.append((message, text))


def test_myid_returns_user_uid():
    from core.handlers.utility_dispatch import dispatch_utility_commands

    bot = _Bot()
    m = _message("/myid", uid=8192061626)
    handled = dispatch_utility_commands(bot, "/myid", m, {}, None)

    assert handled is True
    assert len(bot.replied) == 1
    assert str(bot.replied[0][1]) == "🔢 你的 Telegram UID：8192061626"


def test_myid_with_bot_suffix_still_matches():
    from core.handlers.utility_dispatch import dispatch_utility_commands

    bot = _Bot()
    m = _message("/myid@Moryfansbot", uid=12345)
    handled = dispatch_utility_commands(bot, "/myid@Moryfansbot", m, {}, None)

    assert handled is True
    assert str(bot.replied[0][1]) == "🔢 你的 Telegram UID：12345"


def test_non_utility_command_not_handled():
    from core.handlers.utility_dispatch import dispatch_utility_commands

    bot = _Bot()
    m = _message("/unknown_cmd", uid=42)
    handled = dispatch_utility_commands(bot, "/unknown_cmd", m, {}, None)

    assert handled is False
    assert bot.replied == []