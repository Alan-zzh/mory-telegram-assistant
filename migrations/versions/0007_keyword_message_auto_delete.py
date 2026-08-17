"""Persist keyword message auto-delete recovery state.

Revision ID: 0007_keyword_message_auto_delete
Revises: 0006_onboarding_deliveries
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_keyword_message_auto_delete"
down_revision = "0006_onboarding_deliveries"
branch_labels = None
depends_on = None


_COLUMNS = {
    "auto_delete_due_at": sa.Column(
        "auto_delete_due_at", sa.Integer(), nullable=False, server_default="0"
    ),
    "auto_delete_status": sa.Column(
        "auto_delete_status", sa.Text(), nullable=False, server_default=""
    ),
    "auto_delete_keyword": sa.Column(
        "auto_delete_keyword", sa.Text(), nullable=False, server_default=""
    ),
    "auto_delete_attempts": sa.Column(
        "auto_delete_attempts", sa.Integer(), nullable=False, server_default="0"
    ),
    "auto_delete_error": sa.Column(
        "auto_delete_error", sa.Text(), nullable=False, server_default=""
    ),
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("message_snapshots"):
        return
    existing = {item["name"] for item in inspector.get_columns("message_snapshots")}
    with op.batch_alter_table("message_snapshots") as batch:
        for name, column in _COLUMNS.items():
            if name not in existing:
                batch.add_column(column)

    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("message_snapshots")}
    if "idx_msg_snapshots_auto_delete" not in indexes:
        op.create_index(
            "idx_msg_snapshots_auto_delete",
            "message_snapshots",
            ["auto_delete_status", "auto_delete_due_at"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("message_snapshots"):
        return
    indexes = {item["name"] for item in inspector.get_indexes("message_snapshots")}
    if "idx_msg_snapshots_auto_delete" in indexes:
        op.drop_index("idx_msg_snapshots_auto_delete", table_name="message_snapshots")
    existing = {item["name"] for item in inspector.get_columns("message_snapshots")}
    with op.batch_alter_table("message_snapshots") as batch:
        for name in reversed(tuple(_COLUMNS)):
            if name in existing:
                batch.drop_column(name)
