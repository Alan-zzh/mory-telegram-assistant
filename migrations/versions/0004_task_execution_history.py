"""Add task_execution_history table for real task success rate.

Revision ID: 0004_task_execution_history
Revises: 0003_business_conversation_context
Create Date: 2026-07-29

背景:
    挑刺报告发现 task_log 是分布式锁表(任务执行后 DELETE 释放),
    基于该表算"任务成功率"必然 100% 失真。新增独立的 task_execution_history
    审计表,由 TaskTransactionManager 在 __enter__/__exit__ 中写入真实状态,
    /api/health/task-success-rate 读取真实成功率。
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_task_execution_history"
down_revision = "0003_business_conversation_context"
branch_labels = None
depends_on = None


def upgrade():
    """幂等建表 + 索引。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("task_execution_history"):
        op.create_table(
            "task_execution_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("task_key", sa.Text(), nullable=False),
            sa.Column("exec_date", sa.Text(), nullable=False),  # YYYY-MM-DD
            sa.Column("start_ts", sa.Integer(), nullable=False),
            sa.Column("end_ts", sa.Integer(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),  # running/success/failed/aborted
            sa.Column("error_msg", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
        )
    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes("task_execution_history")} \
        if inspector.has_table("task_execution_history") else set()
    if "idx_task_exec_key_date" not in existing_indexes:
        op.create_index(
            "idx_task_exec_key_date",
            "task_execution_history",
            ["task_key", "exec_date"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("task_execution_history"):
        if "idx_task_exec_key_date" in {item["name"] for item in inspector.get_indexes("task_execution_history")}:
            op.drop_index("idx_task_exec_key_date", table_name="task_execution_history")
        op.drop_table("task_execution_history")
