from types import SimpleNamespace

import pytest


class _Bot:
    def __init__(self):
        self.deleted = []
        self.restricted = []

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return True


class _Conn:
    def __init__(self):
        self.executed = []

    def execute(self, *args, **_kwargs):
        self.executed.append(args)
        return []

    def commit(self):
        return None


class _DB:
    def __init__(self):
        self.conn = _Conn()
        self.blacklisted = []
        self.ad_marked = []

    def blacklist_add(self, uid, reason):
        self.blacklisted.append((uid, reason))

    def mark_message_ad(self, chat_id, msg_id):
        self.ad_marked.append((chat_id, msg_id))
        return True

    def mark_message_deleted(self, *_args):
        return True

    def get_user_ad_messages(self, *_args, **_kwargs):
        return []


def _message(text, first_name="正常用户"):
    return SimpleNamespace(
        text=text,
        message_id=88,
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=42, first_name=first_name, username=None),
    )


@pytest.mark.parametrize("text", ["微信代收3个快递", "今天帮商户代付2笔货款"])
def test_ambiguous_legacy_keywords_cannot_convict_alone(text):
    from modules.group_mgr import check_ad_content

    bot = _Bot()
    db = _DB()
    result = check_ad_content(
        bot,
        _message(text),
        {"AD_KEYWORDS": ["代收", "代付"], "ENABLE_MESSAGE_DELETION": False},
        db,
    )

    assert result is False
    assert bot.deleted == []
    assert bot.restricted == []
    assert db.blacklisted == []


def test_unambiguous_legacy_keyword_uses_unified_deletion_even_with_general_gate_off():
    from modules.group_mgr import check_ad_content

    bot = _Bot()
    db = _DB()
    result = check_ad_content(
        bot,
        _message("加我微信领取返佣"),
        {"AD_KEYWORDS": ["加我微信"], "ENABLE_MESSAGE_DELETION": False},
        db,
    )

    assert result is True
    assert bot.deleted == [(-1001, 88)]
    assert db.ad_marked == [(-1001, 88)]
    assert any("INTO blacklist" in args[0] for args in db.conn.executed)


def test_keyword_in_display_name_blocks_account_without_falsifying_normal_message():
    from modules.group_mgr import check_ad_content

    bot = _Bot()
    db = _DB()
    result = check_ad_content(
        bot,
        _message("大家早上好", first_name="加我微信客服"),
        {"AD_KEYWORDS": ["加我微信"], "ENABLE_MESSAGE_DELETION": False},
        db,
    )

    assert result is True
    assert bot.deleted == [(-1001, 88)]
    assert db.ad_marked == []
    assert any("INTO blacklist" in args[0] for args in db.conn.executed)
