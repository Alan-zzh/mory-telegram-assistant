# -*- coding: utf-8 -*-
"""签到误封根因、处置事件和本人自助复检闭环。"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def detector():
    from modules.ad_detector import AdDetector
    item = AdDetector(config={"AD_AI_REVIEW_ENABLED": False})
    item._check_cas = lambda _uid: (False, "")
    item._check_spb = lambda _uid: (0.0, False)
    return item


@pytest.mark.parametrize("text", [
    "私信开了", "私信关了", "别私信了", "怎么加群", "把我加群", "加我好友",
    "加我打游戏", "你加我", "支付宝可以吗", "我用支付宝了", "谢谢 @abc",
    "t.me 是什么", "飞机起飞了", "准备起飞", "点我一下", "别点我",
    "怎么联系客服", "官方客服是谁", "我在咨询客服", "看我主页了吗", "看简介了吗",
])
def test_daily_contact_language_is_not_ad(detector, text):
    result = detector.detect(username="普通用户", msg=text, bio="")
    assert result["is_ad"] is False, (text, result)
    assert isinstance(result["evidence"], list)


@pytest.mark.parametrize("text", [
    "联系我带你日赚3000", "加我微信 wx123456", "私信详情了解兼职日结", "点我主页看日赚项目",
    "洗米代收日入5000联系我",
])
def test_real_ad_combinations_still_ban_with_structured_evidence(detector, text):
    result = detector.detect(username="", msg=text, bio="")
    assert result["is_ad"] is True, (text, result)
    assert result["action"] == "ban"
    assert result["evidence_level"] == "high"
    assert all({"rule_id", "category", "field", "strength"} <= set(item) for item in result["evidence"])


class _Bot:
    def __init__(self):
        self.sent = []
        self.restricted = []
        self._message_id = 100

    def get_me(self):
        return SimpleNamespace(id=7)

    def get_chat_member(self, _chat_id, _uid):
        return SimpleNamespace(status="member", can_send_messages=True)

    def get_chat(self, uid):
        return SimpleNamespace(
            id=uid, first_name="整改用户", last_name="", username="clean_user",
            bio="普通自我介绍", personal_chat=None, emoji_status_custom_emoji_id="",
        )

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return True

    def delete_message(self, _chat_id, _message_id):
        return True

    def send_message(self, chat_id, text, **kwargs):
        self._message_id += 1
        message = SimpleNamespace(message_id=self._message_id)
        self.sent.append((chat_id, text, kwargs, message))
        return message


def _db(tmp_path):
    from core.database import DB
    return DB(str(tmp_path / "events.db"))


def test_p1_reassert_preserves_root_reason_and_deduplicates_notice(tmp_path):
    from modules.ad_enforcement import enforce_ad_user

    db = _db(tmp_path)
    bot = _Bot()
    config = {"AD_SELF_UNBAN_ENABLED": True, "AD_CLEANUP_REACTIONS": False}
    first = enforce_ad_user(
        bot, db, config, -1001, 42, "Hank", "广告检测-私聊引导",
        current_msg_id=10, evidence=[{
            "rule_id": "builtin.marketing_contact", "category": "marketing_contact",
            "field": "message", "strength": "weak",
        }], evidence_level="ambiguous", notify_admin=False,
    )
    second = enforce_ad_user(
        bot, db, config, -1001, 42, "Hank", "黑名单拦截:Hank",
        current_msg_id=11, source_type="blacklist_reassert", reason_code="blacklist_reassert",
        notify_admin=False,
    )
    root = db.get_ad_enforcement_event(first["data"]["root_event_id"])
    linked = db.get_ad_enforcement_event(second["data"]["event_id"])
    assert root["reason_summary"] == "触发类别：私聊/客服引导"
    assert linked["reason_summary"] == root["reason_summary"]
    assert linked["root_event_id"] == root["event_id"]
    assert db.conn.execute("SELECT reason FROM blacklist WHERE uid=42").fetchone()[0] == "广告检测-私聊引导"
    group_cards = [item for item in bot.sent if item[0] == -1001]
    assert len(group_cards) == 1
    markup = group_cards[0][2]["reply_markup"]
    assert markup.keyboard[0][0].text == "🔓 已整改，一键复检解封"
    assert markup.keyboard[0][1].url == "https://t.me/Moryfansbot"
    assert first["data"]["notice_message_id"] > 0
    assert second["data"]["notice_message_id"] == first["data"]["notice_message_id"]
    db.close()


def test_self_review_owner_restores_four_states_and_permissions(tmp_path, detector):
    from modules.ad_enforcement import enforce_ad_user, self_review_ad_event

    db = _db(tmp_path)
    bot = _Bot()
    config = {"AD_SELF_UNBAN_ENABLED": True, "AD_CLEANUP_REACTIONS": False}
    result = enforce_ad_user(
        bot, db, config, -1001, 42, "Hank", "歧义联系方式误判",
        evidence=[{
            "rule_id": "builtin.marketing_contact", "category": "marketing_contact",
            "field": "message", "strength": "weak",
        }], evidence_level="ambiguous", notify_admin=False,
    )
    event_id = result["data"]["event_id"]
    denied = self_review_ad_event(bot, db, config, event_id, 99, detector)
    assert denied["status"] == "not_owner"
    restored = self_review_ad_event(bot, db, config, event_id, 42, detector)
    assert restored["status"] == "restored"
    assert restored["data"]["persistence_counts"] == {
        "blacklist": 0, "global_blacklist": 0, "mute_records": 0, "ad_suspicious_users": 0,
    }
    assert restored["data"]["permission_verified"] is True
    root = db.get_ad_enforcement_event(result["data"]["root_event_id"])
    assert root["resolved_at"] > 0
    assert "无法恢复" in restored["message"]
    db.close()


def test_self_review_rate_limit_attempt_limit_and_high_risk_refusal(tmp_path, detector):
    from modules.ad_enforcement import self_review_ad_event

    db = _db(tmp_path)
    bot = _Bot()
    config = {"AD_SELF_UNBAN_ENABLED": True}
    low = db.create_ad_enforcement_event(
        42, -1001, evidence_level="ambiguous", evidence=[], expires_at=9999999999
    )
    first = db.claim_ad_recheck(low["event_id"], 42, now=1000)
    assert first["status"] == "claimed"
    assert db.claim_ad_recheck(low["event_id"], 42, now=1030)["status"] == "rate_limited"
    for now in (1061, 1122, 1183, 1244):
        assert db.claim_ad_recheck(low["event_id"], 42, now=now)["status"] == "claimed"
    assert db.claim_ad_recheck(low["event_id"], 42, now=1305)["status"] == "attempts_exhausted"

    high = db.create_ad_enforcement_event(
        43, -1001, evidence_level="high",
        evidence=[{"rule_id": "builtin.adult", "category": "adult_content", "field": "message", "strength": "strong"}],
        expires_at=9999999999,
    )
    refused = self_review_ad_event(bot, db, config, high["event_id"], 43, detector)
    assert refused["status"] == "manual_review_required"
    db.close()


def test_ad_enforcement_migration_is_idempotent_and_reversible(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    path = Path(__file__).parents[2] / "migrations/versions/0008_ad_enforcement_events.py"
    spec = importlib.util.spec_from_file_location("ad_event_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert inspector.has_table("ad_enforcement_events")
        assert {"idx_ad_events_user_open", "idx_ad_events_notice"} <= {
            item["name"] for item in inspector.get_indexes("ad_enforcement_events")
        }
        migration.downgrade()
        assert not sa.inspect(connection).has_table("ad_enforcement_events")


def test_structured_event_does_not_store_private_source_text(tmp_path):
    db = _db(tmp_path)
    event = db.create_ad_enforcement_event(
        42, -1001, reason_summary="资料风险", evidence_level="ambiguous",
        evidence=[{
            "rule_id": "profile.bio", "category": "contact_info", "field": "bio",
            "strength": "weak", "raw_text": "私人Bio完整原文不应入库",
        }],
    )
    stored = json.loads(event["evidence_json"])
    assert stored == [{
        "rule_id": "profile.bio", "category": "contact_info", "field": "bio", "strength": "weak",
    }]
    assert "私人Bio" not in event["evidence_json"]
    db.close()


def test_p1_signup_reassert_is_linked_and_never_marks_signup_as_ad(monkeypatch):
    from core import message_dispatcher
    import modules.ad_enforcement as enforcement

    calls = []
    monkeypatch.setattr(enforcement, "enforce_ad_user", lambda **kwargs: calls.append(kwargs) or {"code": 200})
    db = SimpleNamespace(is_blacklisted=lambda _uid: True)
    ctx = SimpleNamespace(bot=object(), db=db, config={})
    message = SimpleNamespace(message_id=88)
    dctx = SimpleNamespace(
        msg=message, ctx=ctx, text="签到", uid=42, uname="Hank",
        chat_id=-1001, is_group=True,
    )
    assert message_dispatcher._dispatch_p1_p3_security(dctx) is True
    assert calls[0]["source_type"] == "blacklist_reassert"
    assert calls[0]["reason_code"] == "blacklist_reassert"
    assert calls[0].get("current_message_is_ad", False) is False


def test_self_review_callback_is_registered_before_blacklist_interceptor():
    source = (Path(__file__).parents[2] / "core/handlers/callback_handlers.py").read_text(encoding="utf-8")
    assert source.index('startswith("ad_self_review:")') < source.index("def _is_blacklisted_callback")


def test_expired_and_repeated_self_review_are_fail_closed(tmp_path, detector):
    from modules.ad_enforcement import self_review_ad_event

    db = _db(tmp_path)
    bot = _Bot()
    config = {"AD_SELF_UNBAN_ENABLED": True}
    expired = db.create_ad_enforcement_event(
        42, -1001, evidence_level="ambiguous", evidence=[], expires_at=1
    )
    assert self_review_ad_event(bot, db, config, expired["event_id"], 42, detector)["status"] == "expired"
    active = db.create_ad_enforcement_event(
        43, -1001, evidence_level="ambiguous", evidence=[], expires_at=9999999999
    )
    # 模拟已由管理员或一次成功复检关闭，同一事件不能再次恢复。
    db.resolve_ad_event(active["event_id"], "restored", {"permission_verified": True})
    assert self_review_ad_event(bot, db, config, active["event_id"], 43, detector)["status"] == "resolved"
    db.close()
