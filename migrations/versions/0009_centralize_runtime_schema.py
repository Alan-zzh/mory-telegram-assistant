"""Centralize runtime-owned SQLite schema in core.database.

Revision ID: 0009_centralize_runtime_schema
Revises: 0008_ad_enforcement_events
Create Date: 2026-08-24

The project historically let individual feature modules create tables or add
columns on their first request.  That made the live schema depend on traffic
paths and let Dashboard-only processes observe a different database shape from
the Bot.  ``core.database.DB._init_tables`` is now the only runtime schema
owner; this migration upgrades existing databases before those call paths are
removed.
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_centralize_runtime_schema"
down_revision = "0008_ad_enforcement_events"
branch_labels = None
depends_on = None


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {item["name"] for item in inspector.get_indexes(table_name)}


def _add_column_if_missing(bind, table_name: str, column: sa.Column) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def _create_support_tables(bind) -> None:
    """Create tables that used to be lazily created by feature modules."""
    inspector = sa.inspect(bind)

    if not inspector.has_table("llm_cost_logs"):
        op.create_table(
            "llm_cost_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uid", sa.Integer()),
            sa.Column("model_name", sa.Text()),
            sa.Column("task_type", sa.Text()),
            sa.Column("input_tokens", sa.Integer()),
            sa.Column("output_tokens", sa.Integer()),
            sa.Column("estimated_cost", sa.Float()),
            sa.Column("tier", sa.Text()),
            sa.Column("timestamp", sa.Integer()),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "llm_cost_logs", "idx_llm_cost_logs_timestamp"):
        op.create_index("idx_llm_cost_logs_timestamp", "llm_cost_logs", ["timestamp"])
    if not _has_index(inspector, "llm_cost_logs", "idx_llm_cost_logs_uid_timestamp"):
        op.create_index("idx_llm_cost_logs_uid_timestamp", "llm_cost_logs", ["uid", "timestamp"])

    if not inspector.has_table("scheduler_metrics"):
        op.create_table(
            "scheduler_metrics",
            sa.Column("job_id", sa.Text(), primary_key=True),
            sa.Column("last_status", sa.Text()),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("miss_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_run", sa.Integer()),
            sa.Column("last_duration", sa.Integer()),
            sa.Column("last_error", sa.Text()),
            sa.Column("synced_at", sa.Integer(), nullable=False),
        )

    if not inspector.has_table("zombie_scans"):
        op.create_table(
            "zombie_scans",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("chat_id", sa.Integer(), nullable=False),
            sa.Column("operator_uid", sa.Integer(), nullable=False),
            sa.Column("zombie_uids", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("msg_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ts", sa.Integer(), nullable=False),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "zombie_scans", "idx_zombie_scans_chat_status"):
        op.create_index("idx_zombie_scans_chat_status", "zombie_scans", ["chat_id", "status", "ts"])

    if not inspector.has_table("user_roles"):
        op.create_table(
            "user_roles",
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("role", sa.Text(), nullable=False, server_default="viewer"),
            sa.Column("assigned_by", sa.Text()),
            sa.Column("assigned_at", sa.TIMESTAMP()),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "user_roles", "idx_user_roles_role"):
        op.create_index("idx_user_roles_role", "user_roles", ["role"])

    if not inspector.has_table("role_permissions"):
        op.create_table(
            "role_permissions",
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column("permission", sa.Text(), nullable=False),
            sa.Column("assigned_by", sa.Text()),
            sa.Column("assigned_at", sa.TIMESTAMP()),
            sa.PrimaryKeyConstraint("role", "permission"),
        )

    if not inspector.has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ts", sa.Integer(), nullable=False),
            sa.Column("operator_id", sa.Integer()),
            sa.Column("operator_name", sa.Text()),
            sa.Column("role", sa.Text()),
            sa.Column("permission", sa.Text()),
            sa.Column("endpoint", sa.Text()),
            sa.Column("method", sa.Text()),
            sa.Column("allowed", sa.Integer()),
            sa.Column("ip", sa.Text()),
            sa.Column("payload_summary", sa.Text()),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "audit_logs", "idx_audit_logs_ts"):
        op.create_index("idx_audit_logs_ts", "audit_logs", ["ts"])
    if not _has_index(inspector, "audit_logs", "idx_audit_logs_operator_ts"):
        op.create_index("idx_audit_logs_operator_ts", "audit_logs", ["operator_id", "ts"])


def _upgrade_funnel_state(bind) -> None:
    """Make funnel state genuinely multi-bot instead of a lazy bot_id column."""
    inspector = sa.inspect(bind)
    if not inspector.has_table("funnel_state"):
        op.create_table(
            "funnel_state",
            sa.Column("uid", sa.Integer(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False, server_default="touched"),
            sa.Column("state_ts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("recovery_stage", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recovery_ts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bot_id", sa.Text(), nullable=False, server_default="mory"),
            sa.PrimaryKeyConstraint("uid", "bot_id"),
        )
    else:
        pk_columns = inspector.get_pk_constraint("funnel_state").get("constrained_columns") or []
        if pk_columns != ["uid", "bot_id"]:
            columns = {item["name"] for item in inspector.get_columns("funnel_state")}
            op.create_table(
                "_funnel_state_v2",
                sa.Column("uid", sa.Integer(), nullable=False),
                sa.Column("state", sa.Text(), nullable=False, server_default="touched"),
                sa.Column("state_ts", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
                sa.Column("recovery_stage", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("recovery_ts", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("bot_id", sa.Text(), nullable=False, server_default="mory"),
                sa.PrimaryKeyConstraint("uid", "bot_id"),
            )
            bot_id_expr = "COALESCE(NULLIF(bot_id, ''), 'mory')" if "bot_id" in columns else "'mory'"
            op.execute(
                "INSERT INTO _funnel_state_v2 "
                "(uid, state, state_ts, version, recovery_stage, recovery_ts, bot_id) "
                "SELECT uid, COALESCE(state, 'touched'), COALESCE(state_ts, 0), "
                "COALESCE(version, 1), COALESCE(recovery_stage, 0), "
                f"COALESCE(recovery_ts, 0), {bot_id_expr} FROM funnel_state"
            )
            op.drop_table("funnel_state")
            op.rename_table("_funnel_state_v2", "funnel_state")

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "funnel_state", "idx_funnel_state_state"):
        op.create_index("idx_funnel_state_state", "funnel_state", ["state"])
    if not _has_index(inspector, "funnel_state", "idx_funnel_state_recovery"):
        op.create_index("idx_funnel_state_recovery", "funnel_state", ["state", "recovery_stage", "recovery_ts"])


def _upgrade_ab_test_stats(bind) -> None:
    """Make the Repo's ON CONFLICT target real without losing historical counts."""
    inspector = sa.inspect(bind)
    if not inspector.has_table("ab_test_stats"):
        return

    duplicate_groups = bind.execute(sa.text(
        "SELECT group_name, format_version, MIN(id) AS keep_id, "
        "SUM(sent_count) AS sent_count, SUM(conversion_count) AS conversion_count, "
        "MAX(ts) AS latest_ts FROM ab_test_stats "
        "GROUP BY group_name, format_version HAVING COUNT(*) > 1"
    )).mappings().all()
    for row in duplicate_groups:
        bind.execute(sa.text(
            "UPDATE ab_test_stats SET sent_count=:sent_count, "
            "conversion_count=:conversion_count, ts=:latest_ts WHERE id=:keep_id"
        ), dict(row))
        bind.execute(sa.text(
            "DELETE FROM ab_test_stats WHERE group_name=:group_name "
            "AND format_version=:format_version AND id<>:keep_id"
        ), dict(row))

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "ab_test_stats", "uq_ab_test_stats_group_format"):
        op.create_index(
            "uq_ab_test_stats_group_format",
            "ab_test_stats",
            ["group_name", "format_version"],
            unique=True,
        )


def upgrade():
    bind = op.get_bind()
    _create_support_tables(bind)
    _upgrade_funnel_state(bind)
    _upgrade_ab_test_stats(bind)
    _add_column_if_missing(bind, "user_profiles", sa.Column("memory_summary", sa.Text(), nullable=True, server_default=""))
    _add_column_if_missing(bind, "user_profiles", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    _add_column_if_missing(bind, "checkin_records", sa.Column("current_streak", sa.Integer(), nullable=True, server_default="0"))
    for name, type_, default in (
        ("source", sa.Text(), ""),
        ("campaign_id", sa.Text(), ""),
        ("attribution_model", sa.Text(), ""),
        ("weight", sa.Float(), "0"),
        ("is_memory_assisted", sa.Integer(), "0"),
    ):
        _add_column_if_missing(
            bind,
            "conversion_events",
            sa.Column(name, type_, nullable=True, server_default=default),
        )


def downgrade():
    """Return only the incompatible funnel key to the former single-bot shape.

    All other additions are backwards compatible and intentionally retained so
    a code rollback cannot delete observability, RBAC or attribution evidence.
    Multiple bot rows for one uid cannot be represented by the old table, so
    fail closed instead of silently deleting the newer bot state.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("funnel_state"):
        return
    pk_columns = inspector.get_pk_constraint("funnel_state").get("constrained_columns") or []
    if pk_columns != ["uid", "bot_id"]:
        return

    duplicates = bind.execute(sa.text(
        "SELECT uid FROM funnel_state GROUP BY uid HAVING COUNT(*) > 1 LIMIT 1"
    )).fetchone()
    if duplicates:
        raise RuntimeError(
            "cannot downgrade funnel_state: multi-bot rows exist for uid="
            f"{duplicates[0]}; restore a backup or remove the extra bot state explicitly"
        )

    op.create_table(
        "_funnel_state_v1",
        sa.Column("uid", sa.Integer(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="touched"),
        sa.Column("state_ts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recovery_stage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_ts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "INSERT INTO _funnel_state_v1 "
        "(uid, state, state_ts, version, recovery_stage, recovery_ts) "
        "SELECT uid, state, state_ts, version, recovery_stage, recovery_ts FROM funnel_state"
    )
    op.drop_table("funnel_state")
    op.rename_table("_funnel_state_v1", "funnel_state")
    op.create_index("idx_funnel_state_state", "funnel_state", ["state"])
    op.create_index("idx_funnel_state_recovery", "funnel_state", ["state", "recovery_stage", "recovery_ts"])
