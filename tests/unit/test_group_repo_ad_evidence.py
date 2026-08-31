import sqlite3
import threading
from types import SimpleNamespace

import pytest

from core.db_repos.group_repo import GroupRepo


def _repo():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE blacklist (uid INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE global_blacklist (user_id INTEGER PRIMARY KEY)")
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
        [
            (-1001, 10, 42, "广告", 1, 1, 0),
            (-1001, 11, 42, "正常聊天", 2, 0, 0),
            (-1001, 12, 43, "旧广告", 3, 1, 1),
            (-1001, 13, 44, "非黑名单广告", 4, 1, 0),
        ],
    )
    conn.execute("INSERT INTO blacklist(uid) VALUES (42)")
    conn.execute("INSERT INTO global_blacklist(user_id) VALUES (43)")
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


def test_blacklisted_cleanup_candidates_build_full_then_pending_view():
    repo = _repo()

    full = repo.get_blacklisted_ad_cleanup_candidates(-1001, include_deleted=True)
    pending = repo.get_blacklisted_ad_cleanup_candidates(-1001, include_deleted=False)

    assert [row["msg_id"] for row in full] == [10, 12]
    assert [row["msg_id"] for row in pending] == [10]


def test_blacklisted_cleanup_candidates_refuse_silent_per_user_truncation():
    repo = _repo()
    repo.conn.execute("INSERT INTO blacklist(uid) VALUES (99)")
    repo.conn.executemany(
        "INSERT INTO message_snapshots(chat_id,msg_id,user_id,text,ts,is_ad,deleted) VALUES(?,?,?,?,?,?,?)",
        [(-1001, 1000 + index, 99, "广告", 1000 + index, 1, 1) for index in range(501)],
    )
    repo.conn.commit()

    with pytest.raises(RuntimeError, match="candidate limit exceeded"):
        repo.get_blacklisted_ad_cleanup_candidates(
            -1001,
            include_deleted=True,
            limit_per_user=500,
        )

    incremental = repo.get_blacklisted_ad_cleanup_candidates(
        -1001,
        include_deleted=False,
        limit_per_user=500,
    )
    assert len([row for row in incremental if row["user_id"] == 99]) == 0


def test_blacklisted_cleanup_candidates_returns_first_incremental_batch():
    repo = _repo()
    repo.conn.execute("INSERT INTO blacklist(uid) VALUES (99)")
    repo.conn.executemany(
        "INSERT INTO message_snapshots(chat_id,msg_id,user_id,text,ts,is_ad,deleted) VALUES(?,?,?,?,?,?,?)",
        [(-1001, 2000 + index, 99, "广告", 2000 + index, 1, 0) for index in range(501)],
    )
    repo.conn.commit()

    incremental = repo.get_blacklisted_ad_cleanup_candidates(
        -1001,
        include_deleted=False,
        limit_per_user=500,
    )

    assert len([row for row in incremental if row["user_id"] == 99]) == 500
