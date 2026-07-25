"""Add privacy-separated short-lived business conversation context.

Revision ID: 0003_business_conversation_context
Revises: 0002_reply_style_samples
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_business_conversation_context"
down_revision = "0002_reply_style_samples"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("business_conversation_context"):
        op.create_table(
            "business_conversation_context",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.Integer(), nullable=False),
            sa.Column("user_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("assistant_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("intent", sa.Text(), nullable=False, server_default=""),
            sa.Column("conversion_target", sa.Text(), nullable=False, server_default="none"),
            sa.Column("conversion_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("ts", sa.Integer(), nullable=False),
        )
    inspector = sa.inspect(bind)
    if "idx_business_context_recent" not in {item["name"] for item in inspector.get_indexes("business_conversation_context")}:
        op.create_index("idx_business_context_recent", "business_conversation_context", ["user_id", "chat_id", "ts"])
    if not inspector.has_table("conversation_conversion_state"):
        op.create_table(
            "conversation_conversion_state",
            sa.Column("user_id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("chat_id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("opt_out_until", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("custom_context_until", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("preview_context_until", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recent_cta_target", sa.Text(), nullable=False, server_default=""),
            sa.Column("recent_cta_at", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("conversation_conversion_state"):
        op.drop_table("conversation_conversion_state")
    if inspector.has_table("business_conversation_context"):
        if "idx_business_context_recent" in {item["name"] for item in inspector.get_indexes("business_conversation_context")}:
            op.drop_index("idx_business_context_recent", table_name="business_conversation_context")
        op.drop_table("business_conversation_context")
