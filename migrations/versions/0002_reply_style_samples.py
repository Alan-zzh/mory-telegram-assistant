"""Create the administrator-reviewed reply style sample table.

Revision ID: 0002_reply_style_samples
Revises: 0001_initial_schema
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_reply_style_samples"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

_TABLE = "reply_style_samples"
_INDEX = "idx_reply_style_samples_active"


def upgrade():
    """Idempotently create the safe, human-approved style-sample workflow table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("label", sa.Text(), nullable=False, server_default=""),
            sa.Column("style_text", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Text(), nullable=False, server_default=""),
            sa.Column("reviewed_by", sa.Text(), nullable=False, server_default=""),
            sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("reviewed_at", sa.Integer(), nullable=False, server_default="0"),
            sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
            sa.CheckConstraint("enabled IN (0, 1)"),
        )
        inspector = sa.inspect(bind)
    if _INDEX not in {item["name"] for item in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["status", "enabled", "reviewed_at"])


def downgrade():
    """Remove the workflow table and its index when rolling back this migration."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    if _INDEX in {item["name"] for item in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
