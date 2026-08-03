import sqlite3
import threading
from datetime import datetime, timezone

from modules.ad_detector import AdDetector


class _DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.executescript(
            """
            CREATE TABLE message_snapshots (
                chat_id INTEGER, msg_id INTEGER, user_id INTEGER, text TEXT, ts INTEGER,
                is_ad INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
                PRIMARY KEY(chat_id, msg_id)
            );
            CREATE TABLE global_blacklist (
                user_id INTEGER PRIMARY KEY, reason TEXT, added_by INTEGER, added_at TEXT
            );
            CREATE TABLE blacklist (uid INTEGER PRIMARY KEY, reason TEXT);
            CREATE TABLE mute_records (
                uid INTEGER, chat_id INTEGER, mute_until INTEGER, reason TEXT,
                PRIMARY KEY(uid, chat_id)
            );
            """
        )
        self.conn.executemany(
            "INSERT INTO message_snapshots(chat_id,msg_id,user_id,text,ts) VALUES(?,?,?,?,?)",
            [(-1001, 10, 42, "a", 1), (-1001, 11, 42, "b", 2), (-2002, 20, 42, "c", 3)],
        )
        self.conn.commit()

    def blacklist_add(self, uid, reason):
        self.conn.execute("INSERT OR REPLACE INTO blacklist(uid,reason) VALUES(?,?)", (uid, reason))
        self.conn.commit()

    def mark_message_ad(self, chat_id, msg_id):
        cur = self.conn.execute(
            "UPDATE message_snapshots SET is_ad=1 WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_message_deleted(self, chat_id, msg_id):
        cur = self.conn.execute(
            "UPDATE message_snapshots SET deleted=1 WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_user_ad_messages(self, uid, chat_id=None, limit=2000):
        rows = self.conn.execute(
            "SELECT chat_id,msg_id FROM message_snapshots WHERE user_id=? AND chat_id=? AND is_ad=1 LIMIT ?",
            (uid, chat_id, limit),
        ).fetchall()
        return [{"chat_id": row[0], "msg_id": row[1]} for row in rows]


class _Bot:
    def __init__(self, restrict_ok=True):
        self.deleted = []
        self.restricted = []
        self.restrict_ok = restrict_ok

    def get_me(self):
        return type("Me", (), {"id": 7})()

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid))
        return self.restrict_ok

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True


def test_pending_bans_process_all_chats_once_and_only_direct_messages():
    db = _DB()
    detector = AdDetector(config={}, db=db)
    detector.suspicious_users["42"] = {
        "score": 9,
        "first_seen": datetime.now(timezone.utc),
        "messages": [
            {"chat_id": -1001, "msg_id": 10, "score": 3, "direct_message_score": 3},
            {"chat_id": -1001, "msg_id": 11, "score": 3, "direct_message_is_ad": True},
            {"chat_id": -2002, "msg_id": 20, "score": 3, "direct_message_score": 3},
        ],
    }
    bot = _Bot()

    detector.process_pending_bans(bot, {"ENABLE_MESSAGE_DELETION": False})

    assert bot.restricted == [(-1001, 42), (-2002, 42)]
    assert bot.deleted == [(-1001, 10), (-1001, 11), (-2002, 20)]
    rows = db.conn.execute(
        "SELECT chat_id,msg_id,is_ad,deleted FROM message_snapshots ORDER BY chat_id DESC,msg_id"
    ).fetchall()
    assert all(row[2:] == (1, 1) for row in rows)
    assert "42" not in detector.suspicious_users


def test_pending_ban_account_failure_keeps_tracking_for_retry():
    db = _DB()
    detector = AdDetector(config={}, db=db)
    detector.suspicious_users["42"] = {
        "score": 3,
        "first_seen": datetime.now(timezone.utc),
        "messages": [
            {"chat_id": -1001, "msg_id": 10, "score": 3, "direct_message_score": 3},
        ],
    }

    detector.process_pending_bans(_Bot(restrict_ok=False), {"ENABLE_MESSAGE_DELETION": False})

    assert "42" in detector.suspicious_users
