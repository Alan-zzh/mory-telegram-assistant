import sqlite3
import threading

from core.growth_optimizer import (
    assign_variant,
    build_stage_hint,
    log_attribution_event,
    record_growth_reply,
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
            "CREATE TABLE conversation_telemetry(user_id INTEGER, chat_id INTEGER, experiment_id TEXT, variant TEXT, message_text TEXT, bot_reply_text TEXT, intent TEXT, sentiment TEXT, round_num INTEGER, ts INTEGER)"
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
    assert "购买意向" in hint


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
