"""Track the event time of the latest scheduler status.

Revision ID: 0012_scheduler_metrics_last_status_at
Revises: 0011_external_feature_answer_scope
Create Date: 2026-09-01

``synced_at`` is only a flush time and must never be presented as an event
time.  Legacy ``last_run`` proves the status time only for success/error rows;
the old MISSED handler did not update it, so those rows remain unknown.
"""

import sqlalchemy as sa
from alembic import op


revision = "0012_scheduler_metrics_last_status_at"
down_revision = "0011_external_feature_answer_scope"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scheduler_metrics"):
        return

    columns = {item["name"] for item in inspector.get_columns("scheduler_metrics")}
    if "last_status_at" not in columns:
        op.add_column(
            "scheduler_metrics",
            sa.Column("last_status_at", sa.Integer(), nullable=True),
        )

    bind.execute(sa.text(
        """UPDATE scheduler_metrics
           SET last_status_at=last_run
           WHERE COALESCE(last_status_at, 0)=0
             AND last_status IN ('success', 'error')
             AND COALESCE(last_run, 0) > 0"""
    ))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scheduler_metrics"):
        return
    columns = {item["name"] for item in inspector.get_columns("scheduler_metrics")}
    if "last_status_at" in columns:
        with op.batch_alter_table("scheduler_metrics") as batch_op:
            batch_op.drop_column("last_status_at")
