"""Persist one-time onboarding delivery per user and chat surface.

Revision ID: 0006_onboarding_deliveries
Revises: 0005_reply_style_samples_scene
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_onboarding_deliveries"
down_revision = "0005_reply_style_samples_scene"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("onboarding_deliveries"):
        op.create_table(
            "onboarding_deliveries",
            sa.Column("uid", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.Integer(), nullable=False),
            sa.Column("surface", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("claimed_at", sa.Integer(), nullable=False),
            sa.Column("delivered_at", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("uid", "chat_id", "surface"),
        )
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("onboarding_deliveries")}
    if "idx_onboarding_status" not in indexes:
        op.create_index(
            "idx_onboarding_status",
            "onboarding_deliveries",
            ["status", "claimed_at"],
        )


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("onboarding_deliveries"):
        op.drop_table("onboarding_deliveries")
