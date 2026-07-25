import sqlite3
import threading

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
)


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


def test_record_growth_reply_writes_all_growth_tables():
    db = DummyDB()
    growth = GrowthContext(
        experiment_id="purchase_capture",
        experiment_name="高购买意图自动收口",
        variant="A",
        intent="purchase_intent",
        product="select",
        source="group",
        event="consulted",
        stage_hint="hint",
    )
    record_growth_reply(db, DummyDispatch(), growth, "convert", "多少钱", "去 @MorychannelBot", 2)
    assert db.conn.execute("SELECT COUNT(*) FROM conversion_events").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM conversation_telemetry").fetchone()[0] == 1


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


def test_recent_conversation_is_scoped_to_same_chat_and_age(monkeypatch):
    db = DummyDB()
    now = 2_000_000
    monkeypatch.setattr("core.growth_optimizer.time.time", lambda: now)
    db.conn.executemany(
        """
        INSERT INTO conversation_telemetry
        (user_id, chat_id, experiment_id, variant, message_text, bot_reply_text,
         intent, sentiment, round_num, ts)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (123, -100, "", "", "定制舞", "可以做。", "purchase_intent", "", 1, now - 10),
            (123, -200, "", "", "别的群内容", "别的群回复", "chat", "", 1, now - 10),
            (123, -100, "", "", "过期内容", "过期回复", "chat", "", 1, now - 4000),
        ],
    )
    db.conn.commit()

    history = load_recent_conversation(db, 123, -100, limit=3, max_age_seconds=1800)

    assert [item["content"] for item in history] == ["定制舞", "可以做。"]


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
