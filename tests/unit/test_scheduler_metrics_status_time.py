"""scheduler_metrics 状态事件时间 schema 与迁移回归。"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import DB


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "migrations/versions/0012_scheduler_metrics_last_status_at.py"
    )
    spec = importlib.util.spec_from_file_location("scheduler_status_time_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def test_new_database_scheduler_metrics_has_last_status_at(tmp_path):
    db = DB(str(tmp_path / "new.db"))
    try:
        columns = {
            row[1]
            for row in db.conn.execute("PRAGMA table_info(scheduler_metrics)").fetchall()
        }
        assert "last_status_at" in columns
    finally:
        db.close()


def test_0012_migration_is_idempotent_backfills_only_provable_times_and_rolls_back(tmp_path):
    migration = _load_migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("""
            CREATE TABLE scheduler_metrics (
                job_id TEXT PRIMARY KEY,
                last_status TEXT,
                success_count INTEGER,
                fail_count INTEGER,
                miss_count INTEGER,
                last_run INTEGER,
                last_duration INTEGER,
                last_error TEXT,
                synced_at INTEGER NOT NULL
            )
        """))
        connection.execute(sa.text("""
            INSERT INTO scheduler_metrics
                (job_id, last_status, success_count, fail_count, miss_count,
                 last_run, last_duration, last_error, synced_at)
            VALUES
                ('success_job', 'success', 1, 0, 0, 100, 0, '', 900),
                ('error_job', 'error', 0, 1, 0, 200, 0, 'boom', 901),
                ('missed_job', 'missed', 0, 0, 1, 300, 0, '', 902),
                ('unknown_job', 'success', 0, 0, 0, NULL, 0, '', 903)
        """))

        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(sa.text(
            "UPDATE scheduler_metrics SET last_status_at=0 WHERE job_id='success_job'"
        ))
        migration.upgrade()

        assert "last_status_at" in {
            item["name"] for item in sa.inspect(connection).get_columns("scheduler_metrics")
        }
        assert connection.execute(sa.text(
            "SELECT job_id, last_status_at FROM scheduler_metrics ORDER BY job_id"
        )).fetchall() == [
            ("error_job", 200),
            ("missed_job", None),
            ("success_job", 100),
            ("unknown_job", None),
        ]

        migration.downgrade()
        assert "last_status_at" not in {
            item["name"] for item in sa.inspect(connection).get_columns("scheduler_metrics")
        }
        assert connection.execute(sa.text(
            "SELECT job_id, synced_at FROM scheduler_metrics ORDER BY job_id"
        )).fetchall() == [
            ("error_job", 901),
            ("missed_job", 902),
            ("success_job", 900),
            ("unknown_job", 903),
        ]

        migration.upgrade()
        assert connection.execute(sa.text(
            "SELECT last_status_at FROM scheduler_metrics WHERE job_id='missed_job'"
        )).scalar_one() is None
