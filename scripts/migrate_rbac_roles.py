#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[TRAE SOLO CN] RBAC 角色平滑迁移脚本（阶段3-F）

策略：显式超级管理员白名单 + 默认低特权初始化
- 白名单内用户（ADMIN_USER_IDS）→ admin
- 其他现有协作者 → operator（不覆盖已有角色）
- 新注册用户 → viewer（由代码层保证，不在本脚本处理）

幂等：可重复执行，INSERT OR IGNORE；表结构由 core.database/Alembic 管理。
用法：ADMIN_USER_IDS=123456,789012 python scripts/migrate_rbac_roles.py
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta

# 项目根目录
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_CST = timezone(timedelta(hours=8))


def _get_db_path() -> str:
    """获取数据库路径（支持 DASHBOARD_MODE=media 分区）"""
    mode = os.environ.get("DASHBOARD_MODE", "main")
    db_name = "mory_media.db" if mode == "media" else "mory.db"
    return os.path.join(_ROOT, db_name)


def _parse_admin_ids() -> set:
    """从 ADMIN_USER_IDS 环境变量解析超级管理员白名单（逗号分隔的 Telegram UID）"""
    raw = os.environ.get("ADMIN_USER_IDS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _require_user_roles_table(conn):
    """拒绝在独立脚本中补 DDL，避免绕过统一 schema 迁移。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(user_roles)").fetchall()}
    required = {"user_id", "role", "assigned_by", "assigned_at"}
    if not required.issubset(columns):
        raise RuntimeError("user_roles schema 未就绪；请先运行 alembic upgrade head 或启动主 Bot 初始化数据库")


def _get_existing_user_ids(conn) -> list:
    """获取 users 表中所有现有用户 UID（协作者）"""
    try:
        cur = conn.execute("SELECT uid FROM users")
        return [row[0] for row in cur.fetchall()]
    except sqlite3.OperationalError:
        # users 表不存在（全新安装）
        return []


def _count_roles(conn) -> dict:
    """统计各角色数量"""
    stats = {"admin": 0, "operator": 0, "viewer": 0}
    cur = conn.execute("SELECT role, COUNT(*) FROM user_roles GROUP BY role")
    for role, cnt in cur.fetchall():
        if role in stats:
            stats[role] = cnt
    return stats


def migrate():
    """执行 RBAC 角色迁移（幂等）"""
    db_path = _get_db_path()
    if not os.path.exists(db_path):
        print(f"[错误] 数据库不存在: {db_path}")
        sys.exit(1)

    admin_ids = _parse_admin_ids()
    print(f"[迁移] 超级管理员白名单: {sorted(admin_ids) or '(空)'}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _require_user_roles_table(conn)

        existing_uids = _get_existing_user_ids(conn)
        print(f"[迁移] 现有用户数: {len(existing_uids)}")

        now = datetime.now(_CST).isoformat()
        new_admin = 0
        new_operator = 0

        # 1. 白名单用户 → admin（INSERT OR IGNORE 不覆盖已有记录）
        for uid in admin_ids:
            cur = conn.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role, assigned_by, assigned_at) VALUES (?, 'admin', 'migration:whitelist', ?)",
                (uid, now)
            )
            if cur.rowcount > 0:
                new_admin += 1

        # 2. 其他现有用户 → operator（不覆盖已有角色）
        for uid in existing_uids:
            if uid in admin_ids:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role, assigned_by, assigned_at) VALUES (?, 'operator', 'migration:default', ?)",
                (uid, now)
            )
            if cur.rowcount > 0:
                new_operator += 1

        conn.commit()

        stats = _count_roles(conn)
        print("\n========== RBAC 迁移统计 ==========")
        print(f"  admin    : {stats['admin']}")
        print(f"  operator : {stats['operator']}")
        print(f"  viewer   : {stats['viewer']}")
        print(f"  本次新增 admin    : {new_admin}")
        print(f"  本次新增 operator : {new_operator}")
        print("===================================")
        print("[完成] 迁移幂等执行成功")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
