# -*- coding: utf-8 -*-
"""
数据库迁移管理工具

使用 Alembic 管理 SQLite Schema 版本。
所有 Schema 变更必须通过此工具生成迁移脚本，禁止直接修改数据库。

用法：
    # 查看当前版本
    python scripts/db_migrate.py status

    # 查看迁移历史
    python scripts/db_migrate.py history

    # 生成新迁移（自动检测变更）
    python scripts/db_migrate.py generate "描述"

    # 执行迁移
    python scripts/db_migrate.py upgrade

    # 回滚到上一版本
    python scripts/db_migrate.py downgrade

    # 标记当前数据库为基线版本（首次使用时执行）
    python scripts/db_migrate.py stamp_baseline
"""

import os
import sys

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)


def _run_alembic(*args):
    """执行 Alembic 命令"""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    return command, alembic_cfg, args


def status():
    """查看当前迁移状态"""
    command, cfg, _ = _run_alembic()
    command.current(cfg, verbose=True)


def history():
    """查看迁移历史"""
    command, cfg, _ = _run_alembic()
    command.history(cfg, verbose=True)


def generate(description):
    """生成新迁移脚本"""
    command, cfg, _ = _run_alembic()
    command.revision(cfg, message=description, autogenerate=True)
    print(f"✅ 迁移脚本已生成：{description}")
    print("⚠️  请检查生成的脚本，确保变更正确")


def upgrade():
    """执行迁移到最新版本"""
    command, cfg, _ = _run_alembic()
    command.upgrade(cfg, "head")
    print("✅ 数据库已更新到最新版本")


def downgrade():
    """回滚到上一版本"""
    command, cfg, _ = _run_alembic()
    command.downgrade(cfg, "-1")
    print("✅ 数据库已回滚到上一版本")


def stamp_baseline():
    """标记当前数据库为基线版本（0001_initial_schema）

    首次使用 Alembic 时执行，将现有数据库标记为已迁移到基线版本。
    不会执行任何 SQL，只在 alembic_version 表中记录版本号。
    """
    command, cfg, _ = _run_alembic()
    command.stamp(cfg, "0001_initial_schema")
    print("✅ 数据库已标记为基线版本 0001_initial_schema")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == "status":
        status()
    elif action == "history":
        history()
    elif action == "generate":
        if len(sys.argv) < 3:
            print("❌ 请提供迁移描述：python scripts/db_migrate.py generate \"描述\"")
            sys.exit(1)
        generate(sys.argv[2])
    elif action == "upgrade":
        upgrade()
    elif action == "downgrade":
        downgrade()
    elif action == "stamp_baseline":
        stamp_baseline()
    else:
        print(f"❌ 未知操作：{action}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
