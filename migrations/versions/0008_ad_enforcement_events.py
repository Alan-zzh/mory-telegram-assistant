"""Add structured ad enforcement and self-review events.

Revision ID: 0008_ad_enforcement_events
Revises: 0007_keyword_message_auto_delete
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_ad_enforcement_events"
down_revision = "0007_keyword_message_auto_delete"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ad_enforcement_events"):
        op.create_table(
            "ad_enforcement_events",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("root_event_id", sa.Text(), nullable=False),
            sa.Column("parent_event_id", sa.Text(), nullable=False, server_default=""),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.Integer(), nullable=False),
            sa.Column("source_message_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_type", sa.Text(), nullable=False),
            sa.Column("reason_code", sa.Text(), nullable=False),
            sa.Column("reason_summary", sa.Text(), nullable=False),
            sa.Column("evidence_level", sa.Text(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("enforcement_status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("muted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("blacklisted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notice_message_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_attempt_at", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("resolved_at", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
            sa.Column("recovery_json", sa.Text(), nullable=False, server_default="{}"),
        )
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("ad_enforcement_events")}
    if "idx_ad_events_user_open" not in indexes:
        op.create_index(
            "idx_ad_events_user_open", "ad_enforcement_events",
            ["user_id", "resolved_at", "expires_at"],
        )
    if "idx_ad_events_notice" not in indexes:
        op.create_index(
            "idx_ad_events_notice", "ad_enforcement_events",
            ["user_id", "chat_id", "root_event_id", "notice_message_id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ad_enforcement_events"):
        return
    indexes = {item["name"] for item in inspector.get_indexes("ad_enforcement_events")}
    if "idx_ad_events_notice" in indexes:
        op.drop_index("idx_ad_events_notice", table_name="ad_enforcement_events")
    if "idx_ad_events_user_open" in indexes:
        op.drop_index("idx_ad_events_user_open", table_name="ad_enforcement_events")
    op.drop_table("ad_enforcement_events")
