from types import SimpleNamespace

from core.database import DB
from core.message_dispatcher import DispatchContext, _dispatch_p3_52_keyword_auto_delete
from modules import keyword_auto_delete as kad
from tasks.maintenance.keyword_message_auto_delete_task import KeywordMessageAutoDeleteTask


def _config(**overrides):
    keyword_cfg = {
        "enabled": True,
        "keywords": ["/me@afoolGroupBot"],
        "delay_seconds": 300,
        "match_mode": "exact",
        "case_sensitive": False,
        "max_attempts": 2,
    }
    keyword_cfg.update(overrides)
    return {
        "ENABLE_MESSAGE_DELETION": True,
        "KEYWORD_AUTO_DELETE_CONFIG": keyword_cfg,
    }


def _message(text="/me@afoolGroupBot", *, chat_type="supergroup", is_bot=False, sender_chat=None):
    return SimpleNamespace(
        text=text,
        message_id=77,
        chat=SimpleNamespace(id=-100123, type=chat_type),
        from_user=SimpleNamespace(id=42, is_bot=is_bot),
        sender_chat=sender_chat,
    )


class _FakeTimer:
    instances = []

    def __init__(self, delay, fn, args=()):
        self.delay = delay
        self.fn = fn
        self.args = args
        self.daemon = False
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True


class _Bot:
    def __init__(self, error=None):
        self.error = error
        self.deleted = []
        self.restricted = []
        self.banned = []

    def delete_message(self, chat_id, message_id):
        if self.error:
            raise self.error
        self.deleted.append((chat_id, message_id))


def test_exact_match_covers_screenshot_and_rejects_normal_counterexamples():
    config = _config()

    assert kad.match_keyword_auto_delete("/me@afoolGroupBot", config) == "/me@afoolGroupBot"
    assert kad.match_keyword_auto_delete(" /ME@AFOOLGROUPBOT ", config) == "/me@afoolGroupBot"
    assert kad.match_keyword_auto_delete("/menu@afoolGroupBot", config) is None
    assert kad.match_keyword_auto_delete("请发送 /me@afoolGroupBot 看资料", config) is None
    assert kad.match_keyword_auto_delete("/me@afoolGroupBot 123", config) is None


def test_multiple_rules_keep_independent_delays_and_legacy_config_stays_compatible():
    config = _config(
        rules=[
            {
                "keyword": "/me@afoolGroupBot",
                "delay_seconds": 300,
                "match_mode": "exact",
                "case_sensitive": False,
                "enabled": True,
            },
            {
                "keyword": "垃圾前缀",
                "delay_seconds": 12,
                "match_mode": "prefix",
                "case_sensitive": False,
                "enabled": True,
            },
        ]
    )

    rule = kad.match_keyword_auto_delete_rule("垃圾前缀123", config)
    assert rule["keyword"] == "垃圾前缀"
    assert rule["delay_seconds"] == 12
    assert kad.get_keyword_auto_delete_config(_config())["rules"][0]["delay_seconds"] == 300


def test_per_rule_delay_is_used_by_scheduler(tmp_path):
    db = DB(str(tmp_path / "keyword-delete-per-rule.db"))
    _FakeTimer.instances.clear()
    config = _config(
        rules=[
            {
                "keyword": "/me@afoolGroupBot",
                "delay_seconds": 9,
                "match_mode": "exact",
                "case_sensitive": False,
                "enabled": True,
            }
        ]
    )
    try:
        receipt = kad.schedule_keyword_message_delete(
            _Bot(), _message(), config, db, timer_factory=_FakeTimer
        )

        assert receipt["delay_seconds"] == 9
        assert _FakeTimer.instances[0].delay == 9
    finally:
        db.close()


def test_only_plain_group_user_messages_are_candidates():
    config = _config()

    assert kad.get_message_keyword_match(_message(), config)
    assert kad.get_message_keyword_match(_message(chat_type="private"), config) is None
    assert kad.get_message_keyword_match(_message(is_bot=True), config) is None
    assert kad.get_message_keyword_match(_message(sender_chat=SimpleNamespace(id=-9)), config) is None
    assert kad.get_message_keyword_match(_message(), _config(enabled=False)) is None


def test_schedule_persists_300_second_queue_and_starts_daemon_timer(tmp_path):
    db = DB(str(tmp_path / "keyword-delete.db"))
    _FakeTimer.instances.clear()
    try:
        receipt = kad.schedule_keyword_message_delete(
            _Bot(),
            _message(),
            _config(),
            db,
            timer_factory=_FakeTimer,
        )

        assert receipt["status"] == "scheduled"
        assert receipt["persisted"] is True
        assert receipt["timer_started"] is True
        assert len(_FakeTimer.instances) == 1
        assert _FakeTimer.instances[0].delay == 300
        assert _FakeTimer.instances[0].daemon is True
        assert _FakeTimer.instances[0].started is True
        state = db.get_keyword_message_delete_state(-100123, 77)
        assert state["status"] == "pending"
        assert state["keyword"] == "/me@afoolGroupBot"
        assert state["deleted"] == 0
    finally:
        db.close()


def test_global_delete_switch_blocks_queue_and_timer(tmp_path):
    db = DB(str(tmp_path / "keyword-delete-off.db"))
    _FakeTimer.instances.clear()
    config = _config()
    config["ENABLE_MESSAGE_DELETION"] = False
    try:
        receipt = kad.schedule_keyword_message_delete(
            _Bot(), _message(), config, db, timer_factory=_FakeTimer
        )

        assert receipt["status"] == "deletion_disabled"
        assert receipt["persisted"] is False
        assert receipt["timer_started"] is False
        assert _FakeTimer.instances == []
        assert db.get_keyword_message_delete_state(-100123, 77) is None
    finally:
        db.close()


def test_delete_receipt_marks_snapshot_without_any_punishment(tmp_path):
    db = DB(str(tmp_path / "keyword-delete-success.db"))
    bot = _Bot()
    try:
        db.queue_keyword_message_delete(-100123, 77, 42, "/me@afoolGroupBot", "/me@afoolGroupBot", 1)

        outcome = kad.delete_keyword_message(bot, db, _config(), -100123, 77)

        assert outcome == "deleted"
        assert bot.deleted == [(-100123, 77)]
        assert bot.restricted == []
        assert bot.banned == []
        state = db.get_keyword_message_delete_state(-100123, 77)
        assert state["status"] == "deleted"
        assert state["deleted"] == 1
    finally:
        db.close()


def test_transient_delete_failure_retries_then_becomes_explicit_failed(tmp_path):
    db = DB(str(tmp_path / "keyword-delete-fail.db"))
    bot = _Bot(RuntimeError("telegram temporarily unavailable"))
    try:
        db.queue_keyword_message_delete(-100123, 77, 42, "/me@afoolGroupBot", "/me@afoolGroupBot", 1)

        assert kad.delete_keyword_message(bot, db, _config(), -100123, 77) == "retry"
        assert kad.delete_keyword_message(bot, db, _config(), -100123, 77) == "failed"
        state = db.get_keyword_message_delete_state(-100123, 77)
        assert state["status"] == "failed"
        assert state["attempts"] == 2
        assert "temporarily unavailable" in state["error"]
        assert state["deleted"] == 0
    finally:
        db.close()


def test_due_queue_recovers_after_timer_loss(tmp_path):
    db = DB(str(tmp_path / "keyword-delete-recovery.db"))
    bot = _Bot()
    try:
        db.queue_keyword_message_delete(-100123, 77, 42, "/me@afoolGroupBot", "/me@afoolGroupBot", 1)

        counts = kad.run_due_keyword_message_deletes(bot, db, _config())

        assert counts == {"found": 1, "deleted": 1, "already_gone": 0, "retry": 0, "failed": 0}
        assert db.get_keyword_message_delete_state(-100123, 77)["status"] == "deleted"
    finally:
        db.close()


def test_admin_cleanup_deletes_all_current_snapshot_matches_without_punishment(tmp_path):
    db = DB(str(tmp_path / "keyword-delete-cleanup.db"))
    bot = _Bot()
    try:
        db.snapshot_message(-100123, 70, 1, "/me@afoolGroupBot", 1)
        db.snapshot_message(-100123, 71, 2, "/ME@AFOOLGROUPBOT", 2)
        db.snapshot_message(-100123, 72, 3, "正常聊天", 3)

        counts = kad.cleanup_existing_keyword_messages(bot, db, _config(), chat_id=-100123)

        assert counts == {
            "scanned": 3,
            "matched": 2,
            "deleted": 2,
            "already_gone": 0,
            "failed": 0,
            "status": "completed",
        }
        assert bot.deleted == [(-100123, 71), (-100123, 70)]
        assert bot.restricted == []
        assert bot.banned == []
        assert db.get_keyword_message_delete_state(-100123, 70)["deleted"] == 1
        assert db.get_keyword_message_delete_state(-100123, 72)["deleted"] == 0
    finally:
        db.close()


def test_dispatch_stage_stops_later_chat_pipeline_after_match(monkeypatch):
    scheduled = []

    def fake_schedule(bot, message, config, db, *, matched_rule=None, **_kwargs):
        scheduled.append((message.message_id, matched_rule["keyword"] if matched_rule else None))
        return {"status": "scheduled"}

    monkeypatch.setattr(kad, "schedule_keyword_message_delete", fake_schedule)
    ctx = SimpleNamespace(bot=_Bot(), db=object(), config=_config())
    dctx = DispatchContext(
        ctx=ctx,
        msg=_message(),
        uid=42,
        chat_id=-100123,
        is_group=True,
        text="/me@afoolGroupBot",
    )

    assert _dispatch_p3_52_keyword_auto_delete(dctx) is True
    assert scheduled == [(77, "/me@afoolGroupBot")]

    dctx.msg = _message("/menu@afoolGroupBot")
    assert _dispatch_p3_52_keyword_auto_delete(dctx) is False


def test_recovery_task_runs_every_minute():
    task = KeywordMessageAutoDeleteTask(SimpleNamespace(config=_config()))
    schedule = task.schedule()[0]

    assert schedule["trigger"] == "interval"
    assert schedule["minutes"] == 1
    assert schedule["options"]["max_instances"] == 1


def test_recovery_task_is_not_registered_while_feature_is_disabled():
    task = KeywordMessageAutoDeleteTask(SimpleNamespace(config={}))

    assert task.schedule() == []
