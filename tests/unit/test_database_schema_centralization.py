"""中央数据库 schema 与 0009 旧库升级回归。"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import DB


def _load_migration():
    path = Path(__file__).parents[2] / "migrations/versions/0009_centralize_runtime_schema.py"
    spec = importlib.util.spec_from_file_location("centralize_runtime_schema", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def test_new_database_has_all_runtime_owned_tables_and_ab_upsert_key(tmp_path):
    db = DB(str(tmp_path / "new.db"))
    try:
        tables = {
            row[0]
            for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {
            "llm_cost_logs", "scheduler_metrics", "zombie_scans", "user_roles",
            "role_permissions", "audit_logs", "funnel_state", "ab_test_stats",
        }.issubset(tables)
        checkin_columns = {row[1] for row in db.conn.execute("PRAGMA table_info(checkin_records)").fetchall()}
        assert "current_streak" in checkin_columns

        funnel_columns = db.conn.execute("PRAGMA table_info(funnel_state)").fetchall()
        primary_key_columns = [row[1] for row in sorted(funnel_columns, key=lambda row: row[5]) if row[5]]
        assert primary_key_columns == ["uid", "bot_id"]

        db.record_ab_test_sent("group-a", "html", 2)
        db.record_ab_test_conversion("group-a", "html", 1)
        assert db.conn.execute(
            "SELECT sent_count, conversion_count FROM ab_test_stats "
            "WHERE group_name='group-a' AND format_version='html'"
        ).fetchone() == (2, 1)
    finally:
        db.close()


def test_0009_upgrades_legacy_schema_and_merges_ab_duplicates(tmp_path):
    migration = _load_migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("""
            CREATE TABLE funnel_state (
                uid INTEGER PRIMARY KEY, state TEXT NOT NULL, state_ts INTEGER NOT NULL,
                version INTEGER NOT NULL, recovery_stage INTEGER NOT NULL,
                recovery_ts INTEGER NOT NULL
            )
        """))
        connection.execute(sa.text(
            "INSERT INTO funnel_state VALUES (7, 'interested', 10, 3, 1, 2)"
        ))
        connection.execute(sa.text("""
            CREATE TABLE conversion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, event TEXT, ts INTEGER, mode TEXT
            )
        """))
        connection.execute(sa.text("""
            CREATE TABLE user_profiles (
                user_id INTEGER PRIMARY KEY, tags TEXT, level INTEGER, interests TEXT,
                last_interaction INTEGER, conversation_rounds INTEGER, created_at TEXT, updated_at TEXT
            )
        """))
        connection.execute(sa.text("""
            CREATE TABLE checkin_records (
                uid INTEGER NOT NULL, date TEXT NOT NULL, continuous_days INTEGER,
                points_earned INTEGER, ts INTEGER NOT NULL, UNIQUE(uid, date)
            )
        """))
        connection.execute(sa.text("""
            CREATE TABLE ab_test_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT, group_name TEXT NOT NULL,
                format_version TEXT NOT NULL, sent_count INTEGER, conversion_count INTEGER, ts INTEGER
            )
        """))
        connection.execute(sa.text(
            "INSERT INTO ab_test_stats (group_name, format_version, sent_count, conversion_count, ts) "
            "VALUES ('g', 'html', 2, 1, 10), ('g', 'html', 3, 4, 20)"
        ))

        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

        inspector = sa.inspect(connection)
        assert {"llm_cost_logs", "scheduler_metrics", "zombie_scans", "user_roles", "role_permissions", "audit_logs"}.issubset(
            set(inspector.get_table_names())
        )
        assert inspector.get_pk_constraint("funnel_state")["constrained_columns"] == ["uid", "bot_id"]
        assert connection.execute(sa.text(
            "SELECT uid, state, bot_id FROM funnel_state"
        )).fetchall() == [(7, "interested", "mory")]

        conversion_columns = {item["name"] for item in inspector.get_columns("conversion_events")}
        assert {"source", "campaign_id", "attribution_model", "weight", "is_memory_assisted"}.issubset(conversion_columns)
        profile_columns = {item["name"] for item in inspector.get_columns("user_profiles")}
        assert {"memory_summary", "version"}.issubset(profile_columns)
        assert "current_streak" in {item["name"] for item in inspector.get_columns("checkin_records")}
        assert connection.execute(sa.text(
            "SELECT sent_count, conversion_count, ts FROM ab_test_stats WHERE group_name='g'"
        )).fetchone() == (5, 5, 20)
        assert "uq_ab_test_stats_group_format" in {
            item["name"] for item in inspector.get_indexes("ab_test_stats")
        }

        migration.downgrade()
        assert sa.inspect(connection).get_pk_constraint("funnel_state")["constrained_columns"] == ["uid"]
        assert connection.execute(sa.text("SELECT uid, state FROM funnel_state")).fetchall() == [(7, "interested")]


def test_0009_downgrade_refuses_to_drop_multi_bot_state(tmp_path):
    migration = _load_migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'multi_bot.db'}")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(sa.text(
            "INSERT INTO funnel_state (uid, state, state_ts, version, recovery_stage, recovery_ts, bot_id) "
            "VALUES (9, 'touched', 0, 1, 0, 0, 'mory'), "
            "(9, 'carted', 0, 1, 0, 0, 'media')"
        ))
        with pytest.raises(RuntimeError, match="multi-bot rows"):
            migration.downgrade()
