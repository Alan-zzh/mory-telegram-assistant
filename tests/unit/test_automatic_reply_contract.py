"""自动沟通旁路必须遵守 ReplyContract v1。"""

from contextlib import nullcontext
from types import SimpleNamespace

import modules.auto_tasks as legacy
import modules.group_mgr as group_mgr
import tasks.interaction.cart_recovery_task as cart_module
import tasks.interaction.leak_task as leak_module
import tasks.interaction.reactivate_task as reactivate_module
from core.persona_adapter import _PERSONA_ADAPTER_STRATEGIES
from tasks.interaction.cart_recovery_task import CartRecoveryTask
from tasks.interaction.leak_task import LeakTask
from tasks.interaction.reactivate_task import ReactivateTask
from tasks.support.message_templates import MessageTemplates


class _ClaimedTransaction:
    def __init__(self, *args, **kwargs):
        self.claimed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Bot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.sent))


class _AI:
    def __init__(self, reply="想先了解的话去 @moryselect 看当前预览，合不合适你自己判断。"):
        self.reply = reply
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.reply


class _DB:
    def __init__(self, pending=None, inactive=None):
        self.pending = pending or []
        self.inactive = inactive or []
        self.pending_calls = 0
        self.inactive_calls = 0
        self.cancelled = []
        self.advanced = []
        self.reset = []
        self.deleted = []

    def get_pending_cart_recoveries(self, limit=20):
        self.pending_calls += 1
        return self.pending[:limit]

    def cancel_cart_recovery(self, uid):
        self.cancelled.append(uid)

    def advance_recovery_stage(self, uid, stage):
        self.advanced.append((uid, stage))

    def get_inactive_users(self, before_ts, exclude_uid):
        self.inactive_calls += 1
        return self.inactive

    def reset_last_active(self, uid):
        self.reset.append(uid)

    def delete_user(self, uid):
        self.deleted.append(uid)


class _RM:
    def __init__(self, config, db=None, ai=None):
        self.config = config
        self.db = db or _DB()
        self.bot = _Bot()
        self.ai = ai or _AI()
        self.save_config_fn = lambda: None

    def locked(self, _name):
        return nullcontext()


def _patch_transactions(monkeypatch):
    monkeypatch.setattr(cart_module, "TaskTransactionManager", _ClaimedTransaction)
    monkeypatch.setattr(reactivate_module, "TaskTransactionManager", _ClaimedTransaction)
    monkeypatch.setattr(leak_module, "TaskTransactionManager", _ClaimedTransaction)
    monkeypatch.setattr(legacy, "TaskTransactionManager", _ClaimedTransaction)


def test_cart_recovery_disabled_blocks_modular_and_legacy(monkeypatch):
    _patch_transactions(monkeypatch)
    rm = _RM({"CART_RECOVERY_CONFIG": {"enabled": False}})

    CartRecoveryTask(rm).execute(SimpleNamespace())
    legacy._job_cart_recovery(rm)

    assert rm.db.pending_calls == 0
    assert rm.bot.sent == []


def test_cart_recovery_enabled_sends_once_then_cancels(monkeypatch):
    _patch_transactions(monkeypatch)

    modular = _RM(
        {"CART_RECOVERY_CONFIG": {"enabled": True, "max_per_round": 10}},
        db=_DB(pending=[(101, 0), (202, 2)]),
    )
    CartRecoveryTask(modular).execute(SimpleNamespace())
    assert [chat_id for chat_id, _text, _kw in modular.bot.sent] == [101, 202]
    assert modular.db.cancelled == [101, 202]
    assert modular.db.advanced == []

    legacy_rm = _RM(
        {"CART_RECOVERY_CONFIG": {"enabled": True, "max_per_round": 10}},
        db=_DB(pending=[(303, 1)]),
    )
    legacy._job_cart_recovery(legacy_rm)
    assert [chat_id for chat_id, _text, _kw in legacy_rm.bot.sent] == [303]
    assert legacy_rm.db.cancelled == [303]
    assert legacy_rm.db.advanced == []

    for _chat_id, text, _kwargs in modular.bot.sent + legacy_rm.bot.sent:
        assert "@moryselect" in text.lower()
        assert "@morychannelbot" not in text.lower()


def test_reactivate_and_leak_default_off_in_both_paths(monkeypatch):
    _patch_transactions(monkeypatch)
    rm = _RM({}, db=_DB(inactive=[(101, "u")]))

    ReactivateTask(rm).execute(SimpleNamespace())
    LeakTask(rm).execute(SimpleNamespace())
    legacy._job_reactivate(rm)
    legacy._job_leak(rm)

    assert rm.db.inactive_calls == 0
    assert rm.bot.sent == []
    assert rm.ai.calls == []


def test_reactivate_output_is_neutral_and_not_salesy():
    forbidden = (
        "吃醋", "你是不是有别人", "把我忘了", "下单", "优惠",
        "名额", "@morychannelbot", "@moryselect",
    )
    for text in MessageTemplates.REACTIVATE_FALLBACKS:
        assert not any(term in text.lower() for term in forbidden)


def test_leak_replacement_uses_reviewed_non_fact_questions(monkeypatch):
    _patch_transactions(monkeypatch)
    rm = _RM(
        {
            "LEAK_CONFIG": {"enabled": True},
            "GROUP_ID": -1001,
            "_LAST_LEAK_WEEK": -1,
        }
    )
    monkeypatch.setattr(leak_module, "datetime", SimpleNamespace(
        now=lambda _tz: SimpleNamespace(
            isocalendar=lambda: (2026, 30, 3),
            weekday=lambda: 2,
        )
    ))

    LeakTask(rm).execute(SimpleNamespace())

    assert len(rm.bot.sent) == 1
    assert rm.ai.calls == []
    text = rm.bot.sent[0][1]
    assert any(question in text for question in MessageTemplates.WEEKLY_INTERACTION_QUESTIONS)
    assert "Mory不在" not in text
    assert "秘密" not in text


def test_new_member_welcome_has_only_preview_target(monkeypatch):
    monkeypatch.setattr(group_mgr, "_bot_cached_id", None)
    monkeypatch.setattr(group_mgr, "check_username_suspicious", lambda _name: (False, ""))
    monkeypatch.setattr(
        group_mgr, "check_and_ban_if_porn_avatar",
        lambda _bot, _uid, _chat_id, _display: False,
    )
    monkeypatch.setattr(
        group_mgr, "check_avatar_ocr_text",
        lambda _bot, _uid, _config: (False, "", 0),
    )
    monkeypatch.setattr(
        group_mgr, "detect_profile_ad_signal",
        lambda _bot, _user, _bio, _config: {"is_ad": False},
    )

    class WelcomeBot(_Bot):
        def get_me(self):
            return SimpleNamespace(id=999)

        def get_chat(self, _uid):
            return SimpleNamespace(bio="")

    class WelcomeDB:
        def record_group_join(self, *_args):
            pass

        def upsert_user(self, *_args):
            pass

        def add_points(self, *_args):
            pass

    bot = WelcomeBot()
    user = SimpleNamespace(id=123, first_name="新朋友", last_name="", username=None)
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        new_chat_members=[user],
    )
    group_mgr.handle_new_members(bot, message, {}, WelcomeDB())

    assert len(bot.sent) == 1
    chat_id, text, _kwargs = bot.sent[0]
    assert chat_id == -1001
    assert text.lower().count("@moryselect") == 1
    assert "@morychannelbot" not in text.lower()
    assert "http" not in text.lower()


def test_persona_adapter_never_instructs_human_impersonation_or_aggressive_flirt():
    rendered = "\n".join(_PERSONA_ADAPTER_STRATEGIES.values())
    assert "绿茶+傲娇" not in rendered
    assert "情绪化的真人女孩" not in rendered
    assert "公开身份的 Mory 小助理" in rendered
    assert "不声明自己是真人" in rendered


def test_automatic_broadcast_sanitizer_removes_sales_cta_lines():
    raw = "今天有三条新闻。\n去 @MorychannelBot 自助下单\n普通观察结论。"
    safe = legacy._sanitize_automatic_broadcast_text(raw)
    assert safe == "今天有三条新闻。\n普通观察结论。"


def test_scheduled_commercial_broadcast_is_retargeted_to_preview_only():
    original = {
        "BROADCAST_TEMPLATE_VARIATION_ENABLED": True,
        "SCHEDULED_BROADCASTS": [{
            "id": "sale",
            "content": "想订阅就去 @MorychannelBot",
            "button_text": "自助下单",
            "button_url": "https://t.me/MorychannelBot",
        }],
    }
    safe = legacy._build_reply_contract_broadcast_config(original)
    item = safe["SCHEDULED_BROADCASTS"][0]

    assert safe["BROADCAST_TEMPLATE_VARIATION_ENABLED"] is False
    assert item["content"] == "想订阅就去 @moryselect"
    assert item["button_text"] == "🎞 查看当前预览"
    assert item["button_url"] == "https://t.me/moryselect"
    assert original["SCHEDULED_BROADCASTS"][0]["button_text"] == "自助下单"


def test_adversarial_ai_output_falls_back_for_both_reactivate_and_cart_paths():
    unsafe_reactivate = _AI("你是不是把我忘了？快来私聊我，下单还有最后名额。")
    unsafe_cart = _AI("仅剩最后名额，去 @moryselect 再去 @MorychannelBot 下单，私聊我。")

    for generator in (reactivate_module._generate_reactivate_message, legacy._generate_reactivate_message):
        text = generator(101, _RM({}, ai=unsafe_reactivate))
        assert "@" not in text
        assert "下单" not in text
        assert "私聊" not in text

    for generator in (cart_module._generate_cart_recovery_message, legacy._generate_cart_recovery_message):
        text = generator(101, _RM({}, ai=unsafe_cart))
        assert text.lower().count("@moryselect") == 1
        assert "@morychannelbot" not in text.lower()
        assert "私聊" not in text


def test_modular_scheduled_broadcast_sanitizes_virtual_life_and_order_conflicts(monkeypatch):
    from modules import scheduled_broadcast

    captured = []

    def fake_send(_bot, _chat_id, text, **kwargs):
        captured.append((text, kwargs))
        return SimpleNamespace(message_id=1)

    monkeypatch.setattr(scheduled_broadcast, "send_message_compat", fake_send)
    config = {
        "BROADCAST_TEMPLATE_VARIATION_ENABLED": True,
        "SCHEDULED_BROADCASTS": [{
            "id": "unsafe", "enabled": True, "type": "text",
            "content": "刚泡好咖啡，窗外很安静。\n想下单就去 @MorychannelBot",
            "footer": "窝在沙发上等你私聊。",
            "button_text": "自助下单", "button_url": "https://t.me/MorychannelBot",
        }],
    }
    scheduled_broadcast.execute_scheduled_broadcast(_Bot(), -1001, config, db=None)

    assert len(captured) == 1
    text, kwargs = captured[0]
    assert not any(term in text for term in ("咖啡", "窗外", "沙发", "私聊", "@MorychannelBot"))
    assert "@moryselect" in text.lower()
    button = kwargs["reply_markup"].keyboard[0][0]
    assert button.url == "https://t.me/moryselect"
