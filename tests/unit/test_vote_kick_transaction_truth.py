# -*- coding: utf-8 -*-
"""投票踢人事务必须失败可见，且关键动作可恢复。"""

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from modules import vote_kick


class _TrackingLock:
    def __init__(self):
        self._lock = threading.RLock()
        self._depth = 0

    @property
    def held(self):
        return self._depth > 0

    def __enter__(self):
        self._lock.acquire()
        self._depth += 1
        return self

    def __exit__(self, *_args):
        self._depth -= 1
        self._lock.release()


class _Connection:
    """真实 SQLite 外包一层，用于在执行后精准注入故障。"""

    def __init__(self, inner, lock, *, fail_sql=None, fail_commit_after_sql=None):
        self.inner = inner
        self.lock = lock
        self.fail_sql = fail_sql
        self.fail_commit_after_sql = fail_commit_after_sql
        self._last_sql = ""
        self.statements = []

    def execute(self, sql, params=()):
        assert self.lock.held is True
        normalized = " ".join(sql.split())
        self._last_sql = normalized
        self.statements.append((normalized, params))
        cursor = self.inner.execute(sql, params)
        if self.fail_sql and self.fail_sql in normalized:
            raise RuntimeError("injected database failure")
        return cursor

    def commit(self):
        assert self.lock.held is True
        if self.fail_commit_after_sql and self.fail_commit_after_sql in self._last_sql:
            raise RuntimeError("injected commit failure")
        self.inner.commit()

    def rollback(self):
        assert self.lock.held is True
        self.inner.rollback()


class _Bot:
    def __init__(self, lock, raw_conn, *, send_error=None, kick_error=None, member_status="member"):
        self.lock = lock
        self.raw_conn = raw_conn
        self.send_error = send_error
        self.kick_error = kick_error
        self.member_status = member_status
        self.calls = []

    def send_message(self, *_args, **_kwargs):
        assert self.lock.held is False
        self.calls.append(("send",))
        if self.send_error:
            raise self.send_error
        return SimpleNamespace(message_id=77)

    def kick_chat_member(self, chat_id, target_uid):
        assert self.lock.held is False
        status = self.raw_conn.execute(
            "SELECT status FROM vote_kicks ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        self.calls.append(("kick", chat_id, target_uid, status))
        if self.kick_error:
            raise self.kick_error

    def get_chat_member(self, chat_id, target_uid):
        assert self.lock.held is False
        self.calls.append(("member", chat_id, target_uid))
        return SimpleNamespace(status=self.member_status)

    def edit_message_text(self, *_args, **_kwargs):
        assert self.lock.held is False
        self.calls.append(("edit",))

    def answer_callback_query(self, *_args, **_kwargs):
        assert self.lock.held is False
        self.calls.append(("answer",))


def _make_db(monkeypatch, *, fail_sql=None, fail_commit_after_sql=None):
    raw = sqlite3.connect(":memory:", check_same_thread=False)
    raw.execute(
        """CREATE TABLE vote_kicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            target_uid INTEGER NOT NULL,
            initiator_id INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            yes_votes TEXT DEFAULT '',
            no_votes TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            msg_id INTEGER DEFAULT 0,
            end_ts INTEGER NOT NULL,
            ts INTEGER NOT NULL
        )"""
    )
    raw.commit()
    lock = _TrackingLock()
    monkeypatch.setattr(vote_kick, "_db_lock", lock)
    conn = _Connection(
        raw,
        lock,
        fail_sql=fail_sql,
        fail_commit_after_sql=fail_commit_after_sql,
    )
    return SimpleNamespace(conn=conn), raw, lock


def _insert_vote(raw, *, status="active", yes_votes="1,2,3,4", end_ts=2000, ts=1):
    raw.execute(
        "INSERT INTO vote_kicks "
        "(chat_id,target_uid,initiator_id,reason,yes_votes,no_votes,status,msg_id,end_ts,ts) "
        "VALUES (-1001,42,7,'',?,'',?,99,?,?)",
        (yes_votes, status, end_ts, ts),
    )
    raw.commit()
    return raw.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_claim_execute_failure_rolls_back_without_telegram(monkeypatch):
    db, raw, lock = _make_db(
        monkeypatch,
        fail_sql="UPDATE vote_kicks SET status='processing'",
    )
    _insert_vote(raw, end_ts=999)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw)

    with pytest.raises(RuntimeError, match="injected database failure"):
        vote_kick.check_expired_votes(bot, {}, db)

    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "active"
    assert bot.calls == []


def test_sent_message_persistence_failure_keeps_record_and_propagates(monkeypatch):
    db, raw, lock = _make_db(
        monkeypatch,
        fail_sql="UPDATE vote_kicks SET msg_id=",
    )
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw)
    message = SimpleNamespace(chat=SimpleNamespace(id=-1001), from_user=SimpleNamespace(id=7))

    with pytest.raises(RuntimeError, match="injected database failure"):
        vote_kick.handle_vote_kick(bot, message, {}, db, 42)

    assert bot.calls == [("send",)]
    assert raw.execute("SELECT status,msg_id FROM vote_kicks").fetchone() == ("active", 0)
    assert not any(sql.startswith("DELETE FROM vote_kicks") for sql, _ in db.conn.statements)


def test_send_timeout_keeps_record_because_delivery_is_unknown(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw, send_error=TimeoutError("result unknown"))
    message = SimpleNamespace(chat=SimpleNamespace(id=-1001), from_user=SimpleNamespace(id=7))

    with pytest.raises(TimeoutError, match="result unknown"):
        vote_kick.handle_vote_kick(bot, message, {}, db, 42)

    assert raw.execute("SELECT status,msg_id FROM vote_kicks").fetchone() == ("active", 0)
    assert not any(sql.startswith("DELETE FROM vote_kicks") for sql, _ in db.conn.statements)


def test_expired_callback_rejects_vote_and_never_kicks(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    vote_id = _insert_vote(raw, end_ts=999)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw)
    call = SimpleNamespace(data=f"vk_yes_{vote_id}", from_user=SimpleNamespace(id=5), id="cb-1")

    vote_kick.handle_vote_kick_callback(bot, call, {}, db)

    assert raw.execute("SELECT yes_votes,status FROM vote_kicks").fetchone() == ("1,2,3,4", "active")
    assert bot.calls == [("answer",)]


def test_passing_callback_claims_then_closes_after_kick(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    vote_id = _insert_vote(raw, end_ts=2000, ts=1)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw)
    call = SimpleNamespace(data=f"vk_yes_{vote_id}", from_user=SimpleNamespace(id=5), id="cb-1")

    vote_kick.handle_vote_kick_callback(bot, call, {}, db)

    assert raw.execute("SELECT yes_votes,status FROM vote_kicks").fetchone() == (
        "1,2,3,4,5",
        "closed_removed",
    )
    assert bot.calls == [
        ("kick", -1001, 42, "processing"),
        ("edit",),
        ("answer",),
    ]


def test_kick_failure_returns_active_and_expiry_retries(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    vote_id = _insert_vote(raw, end_ts=2000, ts=1)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw, kick_error=RuntimeError("telegram unavailable"))
    call = SimpleNamespace(data=f"vk_yes_{vote_id}", from_user=SimpleNamespace(id=5), id="cb-1")

    with pytest.raises(RuntimeError, match="telegram unavailable"):
        vote_kick.handle_vote_kick_callback(bot, call, {}, db)
    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "active"

    bot.kick_error = None
    monkeypatch.setattr(vote_kick.time, "time", lambda: 3000)
    vote_kick.check_expired_votes(bot, {}, db)

    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "closed_removed"
    assert [call[0] for call in bot.calls].count("kick") == 2
    assert bot.calls[-2:] == [("kick", -1001, 42, "processing"), ("edit",)]


def test_scheduler_recovers_processing_after_restart(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    _insert_vote(raw, status="processing", yes_votes="1,2,3,4,5", end_ts=5000)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw)

    vote_kick.check_expired_votes(bot, {}, db)

    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "closed_removed"
    assert bot.calls == [("kick", -1001, 42, "processing"), ("edit",)]


def test_processing_retry_confirms_already_removed_target(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    _insert_vote(raw, status="processing", yes_votes="1,2,3,4,5", end_ts=5000)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(
        lock,
        raw,
        kick_error=RuntimeError("request result unknown"),
        member_status="kicked",
    )

    vote_kick.check_expired_votes(bot, {}, db)

    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "closed_removed"
    assert bot.calls == [
        ("kick", -1001, 42, "processing"),
        ("member", -1001, 42),
        ("edit",),
    ]


def test_left_member_does_not_masquerade_as_successful_ban(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    _insert_vote(raw, status="processing", yes_votes="1,2,3,4,5", end_ts=5000)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(
        lock,
        raw,
        kick_error=RuntimeError("ban result unknown"),
        member_status="left",
    )

    with pytest.raises(RuntimeError, match="ban result unknown"):
        vote_kick.check_expired_votes(bot, {}, db)

    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "active"


def test_final_close_commit_failure_recovers_without_losing_action(monkeypatch):
    db, raw, lock = _make_db(
        monkeypatch,
        fail_commit_after_sql="SET status='closed_removed'",
    )
    vote_id = _insert_vote(raw, end_ts=2000, ts=1)
    monkeypatch.setattr(vote_kick.time, "time", lambda: 1000)
    bot = _Bot(lock, raw)
    call = SimpleNamespace(data=f"vk_yes_{vote_id}", from_user=SimpleNamespace(id=5), id="cb-1")

    with pytest.raises(RuntimeError, match="injected commit failure"):
        vote_kick.handle_vote_kick_callback(bot, call, {}, db)
    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "processing"

    db.conn.fail_commit_after_sql = None
    bot.kick_error = RuntimeError("already removed")
    bot.member_status = "kicked"
    vote_kick.check_expired_votes(bot, {}, db)

    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "closed_removed"
    assert bot.calls == [
        ("kick", -1001, 42, "processing"),
        ("kick", -1001, 42, "processing"),
        ("member", -1001, 42),
        ("edit",),
    ]


def test_callback_and_expiry_threads_share_single_processing_owner(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    vote_id = _insert_vote(raw, end_ts=2000, ts=1)
    kick_started = threading.Event()
    release_kick = threading.Event()
    scheduler_finished = threading.Event()
    errors = []

    class _BlockingBot(_Bot):
        def kick_chat_member(self, chat_id, target_uid):
            assert self.lock.held is False
            status = self.raw_conn.execute(
                "SELECT status FROM vote_kicks WHERE id=?", (vote_id,)
            ).fetchone()[0]
            self.calls.append(("kick", chat_id, target_uid, status))
            kick_started.set()
            assert release_kick.wait(2)

    bot = _BlockingBot(lock, raw)
    call = SimpleNamespace(data=f"vk_yes_{vote_id}", from_user=SimpleNamespace(id=5), id="cb-1")
    monkeypatch.setattr(
        vote_kick.time,
        "time",
        lambda: 1000 if threading.current_thread().name == "callback" else 3000,
    )

    def _run_callback():
        try:
            vote_kick.handle_vote_kick_callback(bot, call, {}, db)
        except Exception as error:
            errors.append(error)

    def _run_scheduler():
        try:
            vote_kick.check_expired_votes(bot, {}, db)
        except Exception as error:
            errors.append(error)
        finally:
            scheduler_finished.set()

    callback_thread = threading.Thread(target=_run_callback, name="callback")
    scheduler_thread = threading.Thread(target=_run_scheduler, name="scheduler")
    callback_thread.start()
    assert kick_started.wait(2)
    scheduler_thread.start()
    assert scheduler_finished.wait(0.1) is False
    release_kick.set()
    callback_thread.join(2)
    scheduler_thread.join(2)

    assert errors == []
    assert callback_thread.is_alive() is False
    assert scheduler_thread.is_alive() is False
    assert raw.execute("SELECT status FROM vote_kicks").fetchone()[0] == "closed_removed"
    assert [call for call in bot.calls if call[0] == "kick"] == [
        ("kick", -1001, 42, "processing")
    ]


def test_waiting_callback_rechecks_deadline_after_flow_lock(monkeypatch):
    db, raw, lock = _make_db(monkeypatch)
    first_id = _insert_vote(raw, end_ts=2000, ts=1)
    second_id = _insert_vote(raw, end_ts=2000, ts=1)
    raw.execute("UPDATE vote_kicks SET target_uid=43 WHERE id=?", (second_id,))
    raw.commit()
    kick_started = threading.Event()
    release_kick = threading.Event()
    second_finished = threading.Event()
    errors = []
    second_clock = {"now": 1999}

    class _BlockingBot(_Bot):
        def kick_chat_member(self, chat_id, target_uid):
            assert self.lock.held is False
            self.calls.append(("kick", chat_id, target_uid))
            if target_uid == 42:
                kick_started.set()
                assert release_kick.wait(2)

    bot = _BlockingBot(lock, raw)
    first_call = SimpleNamespace(data=f"vk_yes_{first_id}", from_user=SimpleNamespace(id=5), id="cb-1")
    second_call = SimpleNamespace(data=f"vk_yes_{second_id}", from_user=SimpleNamespace(id=5), id="cb-2")

    def _clock():
        if threading.current_thread().name == "second-callback":
            return second_clock["now"]
        return 1000

    monkeypatch.setattr(vote_kick.time, "time", _clock)

    def _run(call):
        try:
            vote_kick.handle_vote_kick_callback(bot, call, {}, db)
        except Exception as error:
            errors.append(error)

    first_thread = threading.Thread(target=lambda: _run(first_call), name="first-callback")

    def _run_second():
        try:
            _run(second_call)
        finally:
            second_finished.set()

    second_thread = threading.Thread(target=_run_second, name="second-callback")
    first_thread.start()
    assert kick_started.wait(2)
    second_thread.start()
    assert second_finished.wait(0.1) is False
    second_clock["now"] = 2001
    release_kick.set()
    first_thread.join(2)
    second_thread.join(2)

    assert errors == []
    assert raw.execute(
        "SELECT yes_votes,status FROM vote_kicks WHERE id=?", (second_id,)
    ).fetchone() == ("1,2,3,4", "active")
    assert [call for call in bot.calls if call[0] == "kick"] == [("kick", -1001, 42)]
