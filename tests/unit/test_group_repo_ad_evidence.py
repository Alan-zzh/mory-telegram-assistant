import sqlite3
import threading
from types import SimpleNamespace

from core.db_repos.group_repo import GroupRepo


def _repo():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """CREATE TABLE message_snapshots (
            chat_id INTEGER,
            msg_id INTEGER,
            user_id INTEGER,
            text TEXT,
            ts INTEGER,
            is_ad INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, msg_id)
        )"""
    )
    conn.executemany(
        "INSERT INTO message_snapshots(chat_id,msg_id,user_id,text,ts,is_ad,deleted) VALUES(?,?,?,?,?,?,?)",
        [(-1001, 10, 42, "广告", 1, 1, 0), (-1001, 11, 42, "正常聊天", 2, 0, 0)],
    )
    conn.commit()
    return GroupRepo(SimpleNamespace(conn=conn, lock=threading.RLock()))


def test_history_cleanup_query_returns_only_line_confirmed_ads():
    repo = _repo()
    assert [row["msg_id"] for row in repo.get_user_ad_messages(42, -1001)] == [10]


def test_evidence_updates_report_zero_row_truthfully():
    repo = _repo()
    assert repo.mark_message_ad(-1001, 999) is False
    assert repo.mark_message_deleted(-1001, 999) is False
    assert repo.mark_message_deleted(-1001, 10) is True
