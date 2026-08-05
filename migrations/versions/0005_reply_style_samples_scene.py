"""Add scene column to reply_style_samples for grouped style samples.

Revision ID: 0005_reply_style_samples_scene
Revises: 0004_task_execution_history
Create Date: 2026-08-06

背景:
    人工审核风格样本需要按场景分组（chat/greeting/engage/faq/broadcast）。
    本迁移为 reply_style_samples 表幂等新增 scene 列，并为场景查询建索引。
    说明：0003/0004 已分别用于 business_conversation_context 与 task_execution_history，
    因此本迁移按迁移链顺序命名为 0005。
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_reply_style_samples_scene"
down_revision = "0004_task_execution_history"
branch_labels = None
depends_on = None

_TABLE = "reply_style_samples"
_INDEX = "idx_reply_style_samples_scene"


def upgrade():
    """幂等新增 scene 列（旧库缺列时补上，新库已含列时跳过）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if "scene" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("scene", sa.Text(), nullable=False, server_default="chat"),
        )
    inspector = sa.inspect(bind)
    if _INDEX not in {item["name"] for item in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["scene"])


def downgrade():
    """幂等删除 scene 列与索引（SQLite 3.35+ 支持 DROP COLUMN）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if "scene" in columns:
        if _INDEX in {item["name"] for item in inspector.get_indexes(_TABLE)}:
            op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_column(_TABLE, "scene")
