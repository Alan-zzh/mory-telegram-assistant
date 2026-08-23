# -*- coding: utf-8 -*-

from types import SimpleNamespace

from core.handlers.business_handlers import (
    handle_business_update,
    register_business_handlers,
    sync_deleted_business_messages,
)


class FakeDb:
    def __init__(self):
        self.deleted = []

    def mark_message_deleted(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True


def test_sync_deleted_business_messages_marks_local_snapshots():
    db = FakeDb()
    event = {
        "business_connection_id": "bc_1",
        "chat": {"id": -1001},
        "message_ids": [11, 12],
    }

    marked = sync_deleted_business_messages(event, db)

    assert marked == 2
    assert db.deleted == [(-1001, 11), (-1001, 12)]


def test_handle_business_update_keeps_business_events_out_of_chat_pipeline():
    db = FakeDb()
    update = SimpleNamespace(
        business_connection={"id": "bc_1", "user_chat_id": 99, "is_enabled": True},
        deleted_business_messages={
            "business_connection_id": "bc_1",
            "chat": {"id": -1002},
            "message_ids": [21],
        },
        guest_message=None,
        purchased_paid_media=None,
        managed_bot=None,
    )

    handled = handle_business_update(object(), update, {}, db)

    assert handled is True
    assert db.deleted == [(-1002, 21)]


def test_register_business_handlers_installs_hook():
    bot = SimpleNamespace()
    db = FakeDb()
    ctx = SimpleNamespace(config={}, db=db)

    register_business_handlers(bot, ctx)
    bot._mory_business_update_handler(
        SimpleNamespace(
            business_connection=None,
            deleted_business_messages={"chat": {"id": -1003}, "message_ids": [31]},
            guest_message=None,
            purchased_paid_media=None,
            managed_bot=None,
        )
    )

    assert db.deleted == [(-1003, 31)]


def test_telegram_send_utils_dispatches_deleted_business_messages_to_hook():
    from core.telegram_send_utils import preserve_telegram_extra_fields
    from telebot import TeleBot, types

    preserve_telegram_extra_fields()
    calls = []
    bot = TeleBot("123456:ABCDEF")
    bot._mory_business_update_handler = calls.append

    update = types.Update.de_json({
        "update_id": 9001,
        "deleted_business_messages": {
            "business_connection_id": "bc_1",
            "chat": {"id": -1004, "type": "supergroup"},
            "message_ids": [41, 42],
        },
    })

    bot.process_new_updates([update])

    assert calls
    assert calls[0].deleted_business_messages["message_ids"] == [41, 42]
