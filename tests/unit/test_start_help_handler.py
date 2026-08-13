from types import SimpleNamespace

from core.handlers import start_help_handler


class _Bot:
    def __init__(self):
        self.sent = []
        self.replied = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    def reply_to(self, message, text):
        self.replied.append((message.chat.id, text))


def _message(*, uid=101, chat_id=101, chat_type="private", text="/start"):
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        from_user=SimpleNamespace(id=uid),
    )


def test_private_start_for_regular_user_restores_normal_chat_route(monkeypatch):
    bot = _Bot()
    message = _message(uid=101)
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})
    routed = []

    monkeypatch.setattr(
        "core.message_dispatcher.master_handler",
        lambda routed_message, routed_ctx: routed.append((routed_message, routed_ctx)),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert routed == [(message, ctx)]
    assert bot.sent == []
    assert bot.replied == []


def test_private_start_for_admin_keeps_group_management_onboarding(monkeypatch):
    bot = _Bot()
    message = _message(uid=999)
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})
    routed = []

    monkeypatch.setattr(
        "core.message_dispatcher.master_handler",
        lambda routed_message, routed_ctx: routed.append((routed_message, routed_ctx)),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert routed == []
    assert len(bot.sent) == 1
    assert "给我管理员权限" in bot.sent[0][1]


def test_group_start_keeps_short_group_guidance(monkeypatch):
    bot = _Bot()
    message = _message(uid=101, chat_id=-1001, chat_type="supergroup")
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})
    routed = []

    monkeypatch.setattr(
        "core.message_dispatcher.master_handler",
        lambda routed_message, routed_ctx: routed.append((routed_message, routed_ctx)),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert routed == []
    assert bot.sent == []
    assert len(bot.replied) == 1
    assert "@我" in bot.replied[0][1]


def test_private_help_does_not_leak_admin_commands_to_regular_user():
    bot = _Bot()
    message = _message(uid=101, text="/help")
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})

    start_help_handler.handle_help_command(bot, message, ctx)

    assert len(bot.sent) == 1
    assert "用户命令清单" in bot.sent[0][1]
    assert "管理员命令清单" not in bot.sent[0][1]
