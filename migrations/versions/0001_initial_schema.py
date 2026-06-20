"""初始基线版本 - 记录现有 107 张表结构

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-06-18

此迁移脚本为基线版本，标记现有数据库结构。
不执行任何 SQL 变更，仅作为版本控制的起点。
后续所有 Schema 变更必须通过新的迁移脚本进行。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """基线版本 - 无变更
    
    现有 107 张表由 core/database.py 的 _init_tables() 管理。
    此迁移仅标记版本，不执行 SQL。
    """
    pass


def downgrade():
    """基线版本 - 不支持回滚
    
    基线版本无法回滚，因为这是版本控制的起点。
    """
    pass
