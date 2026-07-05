import sqlite3
import threading

from core.db_repos.tracking_repo import TrackingRepo
from tasks.maintenance.burn_orphan_task import BurnOrphanTask


class _DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.lock = threading.RLock()
        self.conn.execute(
            """CREATE TABLE reply_tracking (
                bot_msg_id INTEGER,
                chat_id INTEGER,
                user_msg_id INTEGER,
                ts INTEGER,
                replied INTEGER DEFAULT 0,
                PRIMARY KEY (bot_msg_id, chat_id)
            )"""
        )
        self.conn.execute(
            """CREATE TABLE channel_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                content_type TEXT,
                posted_at INTEGER,
                initial_views INTEGER DEFAULT 0,
                current_views INTEGER DEFAULT 0,
                last_checked_at INTEGER
            )"""
        )
        self.conn.execute(
            """CREATE TABLE broadcast_tracking (
                chat_id INTEGER,
                category TEXT,
                msg_id INTEGER,
                ts INTEGER,
                PRIMARY KEY (chat_id, category)
            )"""
        )


def test_get_orphan_messages_deletes_replied_group_bot_replies(monkeypatch):
    db = _DB()
    repo = TrackingRepo(db)
    now = 10_000
    monkeypatch.setattr("core.db_repos.tracking_repo.time.time", lambda: now)

    rows = [
        (1, -100, 11, now - 1900, 0),
        (2, -100, 12, now - 1900, 1),
        (3, -100, 0, now - 1900, 1),
        (4, -100, 13, now - 100, 1),
    ]
    db.conn.executemany(
        "INSERT INTO reply_tracking(bot_msg_id, chat_id, user_msg_id, ts, replied) VALUES (?,?,?,?,?)",
        rows,
    )
    db.conn.commit()

    assert repo.get_orphan_messages(window=1800) == [
        (1, -100, 11),
        (2, -100, 12),
        (3, -100, 0),
    ]


def test_burn_orphan_schedule_runs_every_six_hours():
    schedule = BurnOrphanTask(rm=object()).schedule()[0]

    assert schedule["trigger"] == "cron"
    assert schedule["hour"] == "*/6"
    assert schedule["minute"] == 0


def test_expired_channel_messages_and_record_cleanup(monkeypatch):
    db = _DB()
    repo = TrackingRepo(db)
    now = 10_000
    monkeypatch.setattr("core.db_repos.tracking_repo.time.time", lambda: now)

    db.conn.execute(
        """INSERT INTO channel_tracking(chat_id, message_id, content_type, posted_at, last_checked_at)
           VALUES (-100, 21, 'text', ?, ?)""",
        (now - 1900, now - 1900),
    )
    db.conn.execute(
        """INSERT INTO broadcast_tracking(chat_id, category, msg_id, ts)
           VALUES (-100, 'greeting', 21, ?)""",
        (now - 1900,),
    )
    db.conn.execute(
        """INSERT INTO reply_tracking(bot_msg_id, chat_id, user_msg_id, ts, replied)
           VALUES (21, -100, 0, ?, 1)""",
        (now - 1900,),
    )
    db.conn.commit()

    assert repo.get_expired_channel_messages(window=1800) == [(21, -100, 0)]

    repo.delete_bot_message_records(-100, 21)

    assert db.conn.execute("SELECT COUNT(*) FROM channel_tracking").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM broadcast_tracking").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM reply_tracking").fetchone()[0] == 0
