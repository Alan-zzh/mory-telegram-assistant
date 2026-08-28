# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  dashboard/audit.py  ·  操作审计日志 + RBAC 权限装饰器（v5.23.0 P1-3）    ║
║                                                                            ║
║  功能：                                                                    ║
║    1. audit_logs 表：记录所有写操作的 operator/endpoint/payload/ip/ts      ║
║    2. permission_required 装饰器：细粒度权限校验（基于 role+permission）   ║
║    3. log_audit 辅助函数：统一审计日志写入                                 ║
║                                                                            ║
║  RBAC 模型：                                                               ║
║    role: admin / operator / viewer                                         ║
║    permission: broadcast:write / blacklist:delete / config:write 等        ║
║    role_permissions 映射表定义各角色拥有的权限                             ║
║                                                                            ║
║  渐进式策略：                                                              ║
║    - 现有 admin/viewer 二级保持兼容                                        ║
║    - 新增 operator 角色（可写但不能改配置）                                ║
║    - permission_required 装饰器可选使用，admin_required 保持不变           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import json
import logging
from functools import wraps
from flask import jsonify, session, request
from datetime import datetime, timezone, timedelta
from core.config_compat import redact_sensitive_config

_CST = timezone(timedelta(hours=8))

# ============ RBAC 权限映射 ============
# role → set of permission strings
# 权限命名规范：resource:action
ROLE_PERMISSIONS = {
    "admin": {
        # admin 拥有所有权限
        "broadcast:write", "broadcast:delete",
        "blacklist:write", "blacklist:delete",
        "config:write", "config:read",
        "faq:write", "faq:delete",
        "orphan:clean",
        "ab_test:write", "ab_test:read",
        "engage:write", "engage:read",
        "users:write", "users:read",
        "audit:read",
    },
    "operator": {
        # operator 可执行业务操作但不能改配置
        "broadcast:write",
        "blacklist:write",
        "faq:write",
        "orphan:clean",
        "ab_test:write", "ab_test:read",
        "engage:write", "engage:read",
        "users:read",
    },
    "viewer": {
        # viewer 只读
        "config:read",
        "ab_test:read",
        "engage:read",
        "users:read",
        "audit:read",
    },
}


def get_current_role() -> str:
    """获取当前用户角色（默认 viewer）"""
    return session.get("role", "viewer")


def get_user_role_from_db(db, user_id: int) -> str:
    """
    从 user_roles 表读取用户角色（阶段3-F RBAC 迁移配套）。

    Args:
        db: 数据库连接（sqlite3.Connection）
        user_id: Telegram User ID

    Returns:
        角色字符串（admin/operator/viewer），无记录返回 "viewer"（默认低特权）
    """
    try:
        cur = db.execute("SELECT role FROM user_roles WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        return "viewer"
    except Exception as e:
        # 表不存在或查询异常，降级为 viewer（最小权限原则）
        logging.getLogger("dashboard.audit").debug(f"角色查询异常，降级为viewer（非致命）：{e}")
        return "viewer"


# ============ 阶段3-F：DB 驱动权限映射 ============
# role_permissions 表结构：
#   role TEXT NOT NULL
#   permission TEXT NOT NULL
#   assigned_by TEXT          -- 授权者（system / admin 用户名）
#   assigned_at TIMESTAMP     -- 授权时间
#   PRIMARY KEY (role, permission)
# 表为空时用 ROLE_PERMISSIONS 字典初始化（向后兼容）


def ensure_role_permissions_table(db) -> None:
    """
    在中央 schema 已创建的 role_permissions 表为空时写入默认权限种子。

    在 dashboard/app.py 启动时调用一次；也可在迁移脚本中调用。
    """
    try:
        # 检查是否已有数据
        cnt = db.execute("SELECT COUNT(*) FROM role_permissions").fetchone()[0]
        if cnt == 0:
            # 表为空，用硬编码字典初始化（向后兼容）
            now = datetime.now(_CST).isoformat()
            rows = []
            for role, perms in ROLE_PERMISSIONS.items():
                for perm in perms:
                    rows.append((role, perm, "bootstrap", now))
            db.executemany(
                "INSERT OR IGNORE INTO role_permissions (role, permission, assigned_by, assigned_at) VALUES (?, ?, ?, ?)",
                rows,
            )
        db.commit()
    except Exception as e:
        # 初始化失败由请求鉴权 fail-closed，不能静默扩大权限。
        import logging
        logging.getLogger("dashboard.audit").warning(f"role_permissions 表初始化失败: {e}")


def get_permissions_from_db(db, role: str) -> set | None:
    """
    从 role_permissions 表读取指定角色的权限集合。

    Args:
        db: 数据库连接（sqlite3.Connection）
        role: 角色字符串（admin/operator/viewer）

    Returns:
        权限字符串集合；查询失败返回 ``None``，以便调用方安全拒绝请求。
    """
    try:
        cur = db.execute(
            "SELECT permission FROM role_permissions WHERE role=?",
            (role,),
        )
        return {row[0] for row in cur.fetchall()}
    except Exception as e:
        # 运行时权限表异常时不能将写操作提升到静态默认权限。
        logging.getLogger("dashboard.audit").warning(f"权限集合查询失败，拒绝写操作：{e}")
        return None


def grant_permission(db, role: str, permission: str, assigned_by: str = "system") -> bool:
    """
    向 role_permissions 表授予角色权限（幂等）。

    Args:
        db: 数据库连接
        role: 角色字符串
        permission: 权限字符串（resource:action）
        assigned_by: 授权者标识（默认 'system'）

    Returns:
        True=新增成功，False=已存在（INSERT OR IGNORE 命中）
    """
    try:
        now = datetime.now(_CST).isoformat()
        cur = db.execute(
            "INSERT OR IGNORE INTO role_permissions (role, permission, assigned_by, assigned_at) VALUES (?, ?, ?, ?)",
            (role, permission, assigned_by, now),
        )
        db.commit()
        # 记录审计日志（授权操作本身）
        log_audit(
            operator_id=0,
            operator_name=assigned_by,
            role=role,
            permission=permission,
            endpoint="/api/rbac/grant",
            method="POST",
            allowed=True,
            ip="internal",
            payload_summary=f"grant {role}:{permission}",
        )
        return cur.rowcount > 0
    except Exception as e:
        import logging
        logging.getLogger("dashboard.audit").warning(f"授予权限失败: {e}")
        return False


def revoke_permission(db, role: str, permission: str) -> bool:
    """
    从 role_permissions 表撤销角色权限。

    Args:
        db: 数据库连接
        role: 角色字符串
        permission: 权限字符串（resource:action）

    Returns:
        True=删除成功，False=权限不存在
    """
    try:
        cur = db.execute(
            "DELETE FROM role_permissions WHERE role=? AND permission=?",
            (role, permission),
        )
        db.commit()
        # 记录审计日志（撤权操作本身）
        log_audit(
            operator_id=0,
            operator_name="system",
            role=role,
            permission=permission,
            endpoint="/api/rbac/revoke",
            method="DELETE",
            allowed=True,
            ip="internal",
            payload_summary=f"revoke {role}:{permission}",
        )
        return cur.rowcount > 0
    except Exception as e:
        import logging
        logging.getLogger("dashboard.audit").warning(f"撤销权限失败: {e}")
        return False


def has_permission(permission: str, role: str = None, db=None) -> bool:
    """
    检查角色是否拥有指定权限。

    Args:
        permission: 权限字符串（resource:action）
        role: 角色字符串，None 时从 session 读取
        db: 数据库连接，传入则从 DB 动态查询权限；未传仅供离线兼容调用
            使用 ROLE_PERMISSIONS 字典。线上请求有 DB 但查询失败时必须拒绝。

    Returns:
        True=有权限，False=无权限
    """
    if role is None:
        role = get_current_role()
    # DB 驱动模式：动态查询权限
    if db is not None:
        perms = get_permissions_from_db(db, role)
        if perms is None:
            return False
        return permission in perms
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


def permission_required(permission: str):
    """
    细粒度权限校验装饰器。

    用法：
        @permission_required("broadcast:write")
        def my_view():
            ...

    校验流程：
        1. 检查登录状态
        2. 检查角色是否拥有该权限
        3. 记录审计日志（ALLOWED/DENIED）
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. 登录检查
            if not session.get("logged_in"):
                return jsonify({"ok": False, "msg": "未登录"}), 401

            # 2. 权限检查：线上动态权限库不可用时必须拒绝，不能静默放宽。
            role = get_current_role()
            try:
                from dashboard.helpers import get_db
                db = get_db()
            except Exception as exc:
                logging.getLogger("dashboard.audit").warning(
                    "权限库不可用，拒绝 %s: %s", request.path, exc
                )
                return jsonify({"ok": False, "msg": "权限服务不可用，请稍后重试"}), 503
            allowed = has_permission(permission, role, db=db)

            # 3. 记录审计日志
            operator_id = session.get("uid", 0)
            operator_name = session.get("username", "unknown")
            log_audit(
                operator_id=operator_id,
                operator_name=operator_name,
                role=role,
                permission=permission,
                endpoint=request.path,
                method=request.method,
                allowed=allowed,
                ip=request.remote_addr or "unknown",
                payload_summary=_summarize_payload(),
            )

            if not allowed:
                return jsonify({"ok": False, "msg": f"权限不足：需要 {permission}"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def _summarize_payload(max_len: int = 200) -> str:
    """提取请求 payload 摘要（截断防止日志爆炸）"""
    try:
        if request.method == "GET":
            data = dict(request.args)
        elif request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = dict(request.form)
        return json.dumps(redact_sensitive_config(data), ensure_ascii=False)[:max_len]
    except Exception:
        return ""


def log_audit(operator_id: int, operator_name: str, role: str,
              permission: str, endpoint: str, method: str,
              allowed: bool, ip: str, payload_summary: str = ""):
    """
    写入审计日志到 audit_logs 表。

    表结构由 core.database/Alembic 创建：
        id INTEGER PRIMARY KEY AUTOINCREMENT
        ts INTEGER NOT NULL              -- Unix 时间戳
        operator_id INTEGER              -- 操作者 UID
        operator_name TEXT               -- 操作者用户名
        role TEXT                        -- 操作者角色
        permission TEXT                  -- 请求的权限
        endpoint TEXT                    -- API 路径
        method TEXT                      -- HTTP 方法
        allowed INTEGER                  -- 1=允许 0=拒绝
        ip TEXT                          -- 客户端 IP
        payload_summary TEXT             -- 请求参数摘要
    """
    try:
        from dashboard.helpers import get_db
        db = get_db()
        ts = int(time.time())
        db.execute("""
            INSERT INTO audit_logs (ts, operator_id, operator_name, role, permission, endpoint, method, allowed, ip, payload_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts, operator_id, operator_name, role, permission, endpoint, method, 1 if allowed else 0, ip, payload_summary))
        db.commit()
    except Exception as e:
        # 审计日志写入失败不能影响主流程
        import logging
        logging.getLogger("dashboard.audit").debug(f"审计日志写入失败: {e}")


def get_audit_logs(limit: int = 100, offset: int = 0,
                   allowed_only: bool = False, denied_only: bool = False,
                   operator_id: int = 0) -> list:
    """查询审计日志"""
    try:
        from dashboard.helpers import get_db
        db = get_db()
        where_clauses = []
        params = []
        if allowed_only:
            where_clauses.append("allowed = 1")
        if denied_only:
            where_clauses.append("allowed = 0")
        if operator_id:
            where_clauses.append("operator_id = ?")
            params.append(operator_id)
        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        sql = f"SELECT * FROM audit_logs{where_sql} ORDER BY ts DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def cleanup_old_audit_logs(days: int = 90) -> int:
    """清理超过指定天数的审计日志（默认 90 天）"""
    try:
        from dashboard.helpers import get_db
        db = get_db()
        cutoff = int(time.time()) - days * 86400
        cur = db.execute("DELETE FROM audit_logs WHERE ts < ?", (cutoff,))
        db.commit()
        return cur.rowcount
    except Exception:
        return 0


def get_audit_stats() -> dict:
    """获取审计日志统计"""
    try:
        from dashboard.helpers import get_db
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        allowed = db.execute("SELECT COUNT(*) FROM audit_logs WHERE allowed=1").fetchone()[0]
        denied = db.execute("SELECT COUNT(*) FROM audit_logs WHERE allowed=0").fetchone()[0]
        # 最近 24 小时
        day_ago = int(time.time()) - 86400
        recent = db.execute("SELECT COUNT(*) FROM audit_logs WHERE ts > ?", (day_ago,)).fetchone()[0]
        # 最近被拒绝的 TOP 5 操作者
        top_denied = db.execute("""
            SELECT operator_name, COUNT(*) as cnt
            FROM audit_logs WHERE allowed=0 AND ts > ?
            GROUP BY operator_name ORDER BY cnt DESC LIMIT 5
        """, (day_ago,)).fetchall()
        return {
            "total": total,
            "allowed": allowed,
            "denied": denied,
            "recent_24h": recent,
            "top_denied_24h": [dict(r) for r in top_denied],
        }
    except Exception:
        return {"total": 0, "allowed": 0, "denied": 0, "recent_24h": 0, "top_denied_24h": []}
