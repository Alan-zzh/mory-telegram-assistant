import sqlite3
import threading
import time

from core.intent_router import IntentRouter
from core.growth_optimizer import (
    assign_variant,
    build_stage_hint,
    is_contextual_purchase_intent,
    is_direct_custom_order_request,
    load_recent_conversation,
    log_attribution_event,
    record_growth_reply,
    resolve_conversion_target,
    summarize_growth,
    GrowthContext,
    get_conversion_state,
    persist_conversion_decision,
)
from core.db_repos.conversation_context_repo import ConversationContextRepo


class DummyDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.lock = threading.RLock()
        self.conn.execute(
            "CREATE TABLE conversion_events(uid INTEGER, event TEXT, ts INTEGER, mode TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE telemetry_events(user_id INTEGER, chat_id INTEGER, experiment_id TEXT, variant TEXT, event_type TEXT, event_value REAL, event_meta TEXT, ts INTEGER)"
        )
        self.conn.execute(
            "CREATE TABLE conversation_telemetry(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, experiment_id TEXT, variant TEXT, message_text TEXT, bot_reply_text TEXT, intent TEXT, sentiment TEXT, round_num INTEGER, ts INTEGER)"
        )
        self.conn.commit()
        self.conversation_context = ConversationContextRepo(self)
        assert self.conversation_context._ensure_schema()

    def log_telemetry(self, user_id, chat_id, experiment_id, variant, event_type, event_value=0.0, event_meta=None):
        self.conn.execute(
            "INSERT INTO telemetry_events(user_id, chat_id, experiment_id, variant, event_type, event_value, event_meta, ts) VALUES (?,?,?,?,?,?,?,1)",
            (user_id, chat_id, experiment_id, variant, event_type, event_value, "{}"),
        )
        self.conn.commit()

    def log_conversation_telemetry(self, user_id, chat_id, experiment_id, variant, message_text, bot_reply_text, intent="", sentiment="", round_num=0):
        self.conn.execute(
            "INSERT INTO conversation_telemetry(user_id, chat_id, experiment_id, variant, message_text, bot_reply_text, intent, sentiment, round_num, ts) VALUES (?,?,?,?,?,?,?,?,?,1)",
            (user_id, chat_id, experiment_id, variant, message_text, bot_reply_text, intent, sentiment, round_num),
        )
        self.conn.commit()

    def get_recent_business_context(self, *args, **kwargs):
        return self.conversation_context.get_recent_business_context(*args, **kwargs)

    def get_conversion_state(self, *args, **kwargs):
        return self.conversation_context.get_conversion_state(*args, **kwargs)

    def set_conversion_opt_out(self, *args, **kwargs):
        return self.conversation_context.set_conversion_opt_out(*args, **kwargs)

    def clear_conversion_opt_out(self, *args, **kwargs):
        return self.conversation_context.clear_conversion_opt_out(*args, **kwargs)

    def record_business_context(self, *args, **kwargs):
        return self.conversation_context.record_business_context(*args, **kwargs)


class DummyCtx:
    config = {"AB_TEST_ENABLED": True}


class DummyDispatch:
    uid = 123
    chat_id = -100
    text = "多少钱怎么买"
    is_priv = False
    ctx = DummyCtx()


def test_assign_variant_stable_when_enabled():
    cfg = {"AB_TEST_ENABLED": True}
    assert assign_variant(42, "purchase_capture", cfg) == assign_variant(42, "purchase_capture", cfg)
    assert assign_variant(42, "purchase_capture", {"AB_TEST_ENABLED": False}) == "Base"


def test_stage_hint_mentions_purchase_path():
    hint = build_stage_hint("purchase_capture", "A", "purchase_intent", "convert", "select", 1)
    assert "@MorychannelBot" in hint
    assert "明确要继续" in hint

    preview_hint = build_stage_hint(
        "purchase_capture",
        "A",
        "purchase_intent",
        "convert",
        "select",
        1,
        conversion_target="preview",
    )
    assert "@moryselect" in preview_hint
    assert "@MorychannelBot" not in preview_hint


def test_log_attribution_event_adds_columns_and_row():
    db = DummyDB()
    log_attribution_event(db, 1, "consulted", "convert", "group", "purchase_capture")
    row = db.conn.execute("SELECT uid, event, mode, source, campaign_id FROM conversion_events").fetchone()
    assert row == (1, "consulted", "convert", "group", "purchase_capture")


def _purchase_growth():
    return GrowthContext(
        experiment_id="purchase_capture",
        experiment_name="高购买意图自动收口",
        variant="A",
        intent="purchase_intent",
        product="select",
        source="group",
        event="consulted",
        stage_hint="hint",
    )


def test_record_growth_reply_defaults_to_structured_data_without_raw_text():
    db = DummyDB()
    record_growth_reply(
        db,
        DummyDispatch(),
        _purchase_growth(),
        "convert",
        "多少钱",
        "先去 @moryselect 看预览",
        2,
    )
    assert db.conn.execute("SELECT COUNT(*) FROM conversion_events").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0] == 1
    row = db.conn.execute(
        """SELECT message_text, bot_reply_text, intent, sentiment, round_num
           FROM conversation_telemetry"""
    ).fetchone()
    assert row == ("", "", "purchase_intent", "positive", 2)
    # 原文遥测关闭不影响短期承接；上下文在独立业务表中，非进化/分析输入。
    history = load_recent_conversation(db, 123, -100)
    assert [item["content"] for item in history] == ["多少钱", "先去 @moryselect 看预览"]


def test_record_growth_reply_persists_raw_text_only_when_explicitly_enabled():
    db = DummyDB()
    record_growth_reply(
        db,
        DummyDispatch(),
        _purchase_growth(),
        "convert",
        "我要下单",
        "去 @MorychannelBot 自助完成",
        round_num=4,
        config={"REPLY_EVOLUTION_CONFIG": {"raw_event_text": True}},
    )

    row = db.conn.execute(
        """SELECT message_text, bot_reply_text, intent, sentiment, round_num
           FROM conversation_telemetry"""
    ).fetchone()
    assert row == (
        "我要下单",
        "去 @MorychannelBot 自助完成",
        "purchase_intent",
        "positive",
        4,
    )


def test_summarize_growth_returns_ten_tracks():
    db = DummyDB()
    log_attribution_event(db, 1, "consulted", "convert", "group", "purchase_capture")
    summary = summarize_growth(db, days=7)
    assert len(summary) == 10
    purchase = next(x for x in summary if x["experiment_id"] == "purchase_capture")
    assert purchase["events"]["consulted"] == 1


def test_screenshot_followups_inherit_custom_purchase_intent():
    history = [
        {
            "role": "user",
            "content": "定制舞",
            "intent": "chat",
        },
        {
            "role": "assistant",
            "content": "先去预览看看。",
            "intent": "chat",
        },
    ]

    assert is_direct_custom_order_request("定制舞") is True
    assert is_direct_custom_order_request("定制舞是什么？介绍一下") is False
    assert resolve_conversion_target("可以定制什么内容") == (
        "none", "custom_information_only"
    )
    assert is_contextual_purchase_intent("就是这个味", history) is True
    history.append({"role": "user", "content": "就是这个味", "intent": "purchase_intent"})
    assert is_contextual_purchase_intent("风格可以 挺喜欢这种风格", history) is True
    assert is_contextual_purchase_intent("打港舞 开场穿衣服 卡点变装", history) is True


def test_recent_order_entry_suppresses_repeated_custom_cta():
    history = [
        {"role": "user", "content": "定制舞"},
        {"role": "assistant", "content": "去 @MorychannelBot 看当前选项。"},
    ]
    assert resolve_conversion_target("就是这个味", history, mode="convert") == (
        "none",
        "recent_order_cta_suppressed",
    )


def test_contextual_purchase_excludes_unrelated_and_rejection_messages():
    history = [
        {"role": "user", "content": "定制舞", "intent": "purchase_intent"},
        {"role": "assistant", "content": "可以定制。", "intent": "purchase_intent"},
    ]

    assert is_contextual_purchase_intent("今天天气不错", history) is False
    assert is_contextual_purchase_intent("算了，不需要了", history) is False
    assert is_contextual_purchase_intent("不定制了", history) is False
    assert is_direct_custom_order_request("不定制了") is False
    assert is_contextual_purchase_intent("这种风格不错", []) is False


def test_conversion_resolver_rejects_daily_life_false_positives_and_preview_dislike():
    for text in ("电影刚看了", "书看完了", "咖啡怎么买", "鞋怎么买", "相机怎么买", "课程怎么买"):
        assert resolve_conversion_target(text, [], mode="convert")[0] == "none"
    assert resolve_conversion_target("预览看过但不喜欢", [], mode="convert") == (
        "none", "preview_not_interested"
    )


def test_generic_purchase_action_requires_business_context_or_standalone_action():
    assert resolve_conversion_target("怎么买", [], mode="convert") == ("subscribe", "explicit_purchase")
    assert resolve_conversion_target("这个档位怎么买", [], mode="convert") == ("subscribe", "explicit_purchase")
    state = {"preview_context": True}
    assert resolve_conversion_target("这个怎么买", [], mode="convert", state=state) == (
        "subscribe", "explicit_purchase"
    )


def test_plan_question_previews_and_explicit_preview_seen_subscribes():
    assert resolve_conversion_target("包月划算吗") == (
        "preview",
        "plan_question_needs_preview",
    )
    assert resolve_conversion_target("预览看过了") == (
        "subscribe",
        "preview_confirmed",
    )
    assert resolve_conversion_target("预览我已经看过了") == (
        "subscribe",
        "preview_confirmed",
    )
    assert resolve_conversion_target("预览我刚看完") == (
        "subscribe",
        "preview_confirmed",
    )
    assert resolve_conversion_target("预览看过了但不喜欢") == (
        "none",
        "preview_not_interested",
    )


def test_opt_out_state_survives_next_turn_and_only_explicit_inquiry_clears_it():
    db = DummyDB()
    persist_conversion_decision(db, 123, -100, "none", "user_opt_out")
    state = get_conversion_state(db, 123, -100)
    assert state["opt_out"] is True
    for text in ("今天天气不错", "继续聊刚才那个", "别营销", "别发入口"):
        assert resolve_conversion_target(text, [], mode="normal", state=state)[0] == "none"
    target, reason = resolve_conversion_target("多少钱", [], mode="convert", state=state)
    assert (target, reason) == ("preview", "preview_or_objection")
    persist_conversion_decision(db, 123, -100, target, reason)
    assert get_conversion_state(db, 123, -100)["opt_out"] is False


def test_structured_cta_dedup_survives_reload_when_raw_telemetry_is_off():
    db = DummyDB()
    db.record_business_context(
        123, -100, "我想定制舞", "去 @MorychannelBot 看当前选项。",
        intent="purchase_intent", conversion_target="subscribe", conversion_reason="explicit_custom_order",
    )
    # 模拟进程重启：以同一 SQLite 连接构建新的仓库实例。
    db.conversation_context = ConversationContextRepo(db)
    history = load_recent_conversation(db, 123, -100)
    state = get_conversion_state(db, 123, -100)
    assert resolve_conversion_target("就是这个味", history, mode="convert", state=state) == (
        "none", "recent_order_cta_suppressed"
    )


def test_recent_conversation_is_scoped_to_same_chat_and_age(monkeypatch):
    db = DummyDB()
    now = 2_000_000
    monkeypatch.setattr("core.growth_optimizer.time.time", lambda: now)
    db.conn.executemany(
        """
        INSERT INTO business_conversation_context
        (user_id, chat_id, user_text, assistant_text, intent, conversion_target, conversion_reason, ts)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [
            (123, -100, "定制舞", "可以做。", "purchase_intent", "subscribe", "explicit_custom_order", now - 10),
            (123, -200, "别的群内容", "别的群回复", "chat", "none", "", now - 10),
            (123, -100, "过期内容", "过期回复", "chat", "none", "", now - 4000),
        ],
    )
    db.conn.commit()

    history = load_recent_conversation(db, 123, -100, limit=3, max_age_seconds=1800)

    assert [item["content"] for item in history] == ["定制舞", "可以做。"]


def test_expired_business_context_is_physically_deleted_without_new_message():
    db = DummyDB()
    now = int(time.time())
    db.conn.execute(
        """
        INSERT INTO business_conversation_context
        (user_id, chat_id, user_text, assistant_text, intent, conversion_target, conversion_reason, ts)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (321, -100, "过期用户原文", "过期助手原文", "chat", "none", "", now - 1900),
    )
    db.conn.commit()

    deleted = ConversationContextRepo(db).cleanup_expired_business_context(now_ts=now)
    remaining = db.conn.execute(
        "SELECT COUNT(*) FROM business_conversation_context WHERE user_id=?",
        (321,),
    ).fetchone()[0]

    assert deleted == 1
    assert remaining == 0


def test_intent_router_uses_recent_conversation_for_short_followup():
    fake_ai = type(
        "_FakeAI",
        (),
        {
            "_INTENT_KEYWORDS": {},
            "_classify_intent": staticmethod(lambda _text: "chat"),
        },
    )()
    router = IntentRouter(
        fake_ai,
        {
            "INTENT_ROUTING_ENABLED": True,
            "INTENT_LLM_ENABLED": False,
        },
    )

    result = router.classify(
        "就是这个味",
        conversation_history=[
            {"role": "user", "content": "定制舞", "intent": "chat"},
        ],
    )

    assert result == {
        "intent": "purchase_intent",
        "confidence": 0.95,
        "source": "context_rule",
    }
