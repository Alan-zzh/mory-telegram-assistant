import importlib.util
import sqlite3
import threading
from pathlib import Path

import sqlalchemy as sa
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.db_repos.question_repo import QuestionRepo


def _create_user_questions(conn):
    conn.execute(
        """CREATE TABLE user_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            question_text TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT '',
            intent TEXT NOT NULL DEFAULT '',
            keyword_tag TEXT NOT NULL DEFAULT '',
            question_category TEXT NOT NULL DEFAULT 'other',
            is_convert INTEGER NOT NULL DEFAULT 0,
            ai_reply_summary TEXT NOT NULL DEFAULT '',
            faq_hit_id INTEGER DEFAULT 0,
            answer_source TEXT NOT NULL DEFAULT '',
            answer_ref TEXT NOT NULL DEFAULT '',
            ts INTEGER NOT NULL
        )"""
    )


def _create_candidates(conn):
    conn.execute(
        """CREATE TABLE faq_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_pattern TEXT NOT NULL DEFAULT '',
            question_category TEXT NOT NULL DEFAULT 'other',
            sample_questions TEXT NOT NULL DEFAULT '',
            frequency INTEGER NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT '',
            intent TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT NOT NULL DEFAULT '',
            reviewed_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )"""
    )


class _Db:
    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.RLock()


def test_question_repo_roundtrips_answer_source_and_stats():
    conn = sqlite3.connect(":memory:")
    _create_user_questions(conn)
    repo = QuestionRepo(_Db(conn))

    qid = repo.log_question(
        uid=42,
        chat_id=42,
        question_text="可以约吗",
        mode="normal",
        intent="联系Mory",
        question_category="social",
        answer_source="preset",
        answer_ref="联系与社交解锁",
        ai_reply_summary="按当前社交解锁说明操作。",
    )
    assert qid > 0
    row = repo.get_questions(days=1)[0]
    assert row["answer_source"] == "preset"
    assert row["answer_ref"] == "联系与社交解锁"

    assert repo.update_question_reply(
        qid,
        "FAQ回答",
        faq_hit_id=9,
        answer_source="faq",
        answer_ref="9",
    )
    row = repo.get_questions(days=1)[0]
    assert row["faq_hit_id"] == 9
    assert row["answer_source"] == "faq"
    repo.log_question(
        uid=42,
        chat_id=42,
        question_text="签到！！！",
        mode="normal",
        intent="external_feature",
        faq_hit_id=99,
        answer_source="delegated",
        answer_ref="other_bot_feature",
    )
    stats = repo.get_question_stats()
    assert stats["total_count"] == 1
    assert stats["recorded_total_count"] == 2
    assert stats["delegated_count"] == 1
    assert stats["faq_hit_rate"] == 100.0
    assert stats["answer_source_distribution"]["faq"] == 1
    assert stats["answer_source_distribution"]["delegated"] == 1
    assert stats["deterministic_coverage_rate"] == 100.0
    assert repo.get_top_questions(days=1) == [{
        "question_text": "可以约吗",
        "count": 1,
        "mode": "normal",
        "intent": "联系Mory",
        "question_category": "social",
    }]
    assert repo.get_category_distribution(days=1) == {"social": 1}
    page, total = repo.get_questions(limit=1, days=1, include_total=True)
    assert len(page) == 1
    assert total == 2


def test_question_stats_fail_closed_when_database_is_unavailable():
    """统计库不可读时不能伪装成全零业务数据。"""
    conn = sqlite3.connect(":memory:")
    _create_user_questions(conn)
    repo = QuestionRepo(_Db(conn))
    conn.close()

    with pytest.raises(RuntimeError, match="问题统计不可用"):
        repo.get_question_stats()


def test_distill_excludes_covered_answers_and_commands():
    conn = sqlite3.connect(":memory:")
    _create_user_questions(conn)
    _create_candidates(conn)
    repo = QuestionRepo(_Db(conn))

    for source, text in (
        ("preset", "怎么进群"),
        ("direct_access", "怎么订阅"),
        ("delegated", "多少积分兑换"),
        ("delegated", "多少积分兑换"),
        ("ai", "/start"),
        ("ai", "新的业务问题"),
        ("ai", "新的业务问题"),
    ):
        repo.log_question(
            1,
            1,
            text,
            answer_source=source,
            ai_reply_summary="已回答",
        )

    assert repo.distill_candidates(min_frequency=2, days=1) == 1
    rows = conn.execute(
        "SELECT question_pattern, frequency FROM faq_candidates"
    ).fetchall()
    assert rows == [("新的业务问题", 2)]


def test_0010_migration_is_idempotent_and_keeps_evidence_on_downgrade(tmp_path):
    migration_path = (
        Path(__file__).parents[2]
        / "migrations/versions/0010_question_answer_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("question_provenance_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text(
            """CREATE TABLE user_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                question_text TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                keyword_tag TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                is_convert INTEGER NOT NULL DEFAULT 0,
                ai_reply_summary TEXT NOT NULL DEFAULT '',
                faq_hit_id INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )"""
        ))
        connection.execute(sa.text(
            "INSERT INTO user_questions (uid, chat_id, question_text, ts) "
            "VALUES (1, 1, '旧问题', 1)"
        ))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

        columns = {item["name"] for item in sa.inspect(connection).get_columns("user_questions")}
        assert {"answer_source", "answer_ref"} <= columns
        old_row = connection.execute(sa.text(
            "SELECT answer_source, answer_ref FROM user_questions WHERE id=1"
        )).one()
        assert tuple(old_row) == ("", "")

        connection.execute(sa.text(
            "UPDATE user_questions SET answer_source='preset', answer_ref='联系与社交解锁' "
            "WHERE id=1"
        ))
        migration.downgrade()
        migration.upgrade()
        preserved = connection.execute(sa.text(
            "SELECT answer_source, answer_ref FROM user_questions WHERE id=1"
        )).one()
        assert tuple(preserved) == ("preset", "联系与社交解锁")


def test_0011_backfills_only_verified_external_records_and_rejects_candidate(tmp_path):
    migration_path = (
        Path(__file__).parents[2]
        / "migrations/versions/0011_external_feature_answer_scope.py"
    )
    assert migration_path.exists()
    spec = importlib.util.spec_from_file_location("external_feature_scope_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'scope.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text(
            """CREATE TABLE user_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL DEFAULT '',
                answer_source TEXT NOT NULL DEFAULT '',
                answer_ref TEXT NOT NULL DEFAULT ''
            )"""
        ))
        connection.execute(sa.text(
            """CREATE TABLE faq_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_pattern TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at INTEGER NOT NULL DEFAULT 0
            )"""
        ))
        for text in (
            "签到！！！", "什么？我断签了🤪", "多少积分兑换",
            "现在不可以用积分兑换了吗", "签到积分能干嘛", "签到签到",
            "积分有什么用", "航空积分怎么兑换机票",
        ):
            connection.execute(
                sa.text("INSERT INTO user_questions (question_text) VALUES (:text)"),
                {"text": text},
            )
        connection.execute(sa.text(
            "INSERT INTO faq_candidates (question_pattern) VALUES ('签到')"
        ))

        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

        rows = dict(connection.execute(sa.text(
            "SELECT question_text, answer_source FROM user_questions"
        )).all())
        for text in (
            "签到！！！", "什么？我断签了🤪", "多少积分兑换",
            "现在不可以用积分兑换了吗", "签到积分能干嘛", "签到签到",
        ):
            assert rows[text] == "delegated"
        assert rows["积分有什么用"] == ""
        assert rows["航空积分怎么兑换机票"] == ""

        candidate = connection.execute(sa.text(
            "SELECT status, reviewed_by FROM faq_candidates WHERE question_pattern='签到'"
        )).one()
        assert tuple(candidate) == ("rejected", "scope_cleanup_v5.42.3")

        migration.downgrade()
        preserved = connection.execute(sa.text(
            "SELECT answer_source, answer_ref FROM user_questions WHERE question_text='签到！！！'"
        )).one()
        assert tuple(preserved) == ("delegated", "other_bot_feature")
