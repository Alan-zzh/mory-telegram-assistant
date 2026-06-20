# -*- coding: utf-8 -*-
"""Alembic 环境配置 - SQLite 数据库迁移"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 这是 Alembic 配置对象，提供对 Python 值的访问
config = context.config

# 解释 Python 日志配置（如果存在）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 元数据对象，用于 SQLAlchemy 模型（当前项目使用原始 SQL，设为 None）
target_metadata = None


def get_url():
    """获取数据库 URL，支持环境变量覆盖"""
    # 默认使用项目根目录的 mory.db
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mory.db")
    
    # 支持通过环境变量覆盖（用于测试或不同环境）
    db_url = os.environ.get("DATABASE_URL", f"sqlite:///{db_path}")
    
    return db_url


def run_migrations_offline():
    """在'离线'模式下运行迁移
    
    仅使用 URL 配置上下文。不需要实际的 DB API 访问。
    调用 context.execute() 将 SQL 语句输出到脚本。
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 支持：使用批处理模式进行 ALTER TABLE
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """在'在线'模式下运行迁移
    
    创建实际的引擎并与上下文关联。
    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 支持：使用批处理模式进行 ALTER TABLE
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
