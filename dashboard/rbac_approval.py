# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  dashboard/rbac_approval.py  ·  RBAC 权限变更审批流（阶段3-E）           ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 权限变更申请：申请人提交角色变更请求（pending）                      ║
║    2. 审批通过：admin 审批后实际授予角色（UPDATE user_roles）              ║
║    3. 审批拒绝：admin 拒绝申请                                             ║
║    4. 申请人取消：仅 pending 状态可取消                                    ║
║    5. 查询申请列表/详情                                                    ║
║                                                                            ║
║  配置项：                                                                  ║
║    RBAC_APPROVAL_ENABLED（默认 False）：关闭时 create_request 直接拒绝     ║
║                                                                            ║
║  与现有 RBAC 的关系：                                                      ║
║    - 现有 audit.py 的 grant_permission 是给「角色」授予「权限」            ║
║    - 本模块是给「用户」授予「角色」（UPDATE user_roles.role）              ║
║    - 审批通过后同步写 audit_logs 审计日志                                  ║
║                                                                            ║
║  状态机：                                                                  ║
║    pending → approved / rejected / cancelled                               ║
║    终态不可变更                                                            ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from core.logging_util import get_logger

logger = get_logger("rbac_approval")

# 北京时区
_CST = timezone(timedelta(hours=8))

# 合法角色集合（与 audit.py ROLE_PERMISSIONS 保持一致）
_VALID_ROLES = {"admin", "operator", "viewer"}

# 申请状态枚举
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"

# 终态集合（不可再变更）
_TERMINAL_STATUS = {STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED}


def _read_config(key: str, default=None):
    """读取配置项（带容错，不阻断主流程）"""
    try:
        from dashboard.helpers import read_config
        cfg = read_config()
        return cfg.get(key, default)
    except Exception as e:
        logger.warning(f"读取配置 {key} 失败，使用默认值: {e}")
        return default


def _get_db():
    """获取数据库连接（请求上下文内复用 dashboard.helpers.get_db）"""
    from dashboard.helpers import get_db
    return get_db()


def _ensure_user_roles_table(db) -> None:
    """
    幂等确保 user_roles 表存在（与 scripts/migrate_rbac_roles.py 一致）。
    表不存在时审批通过将无法写入角色，故在此兜底创建。
    """
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'viewer',
                assigned_by TEXT,
                assigned_at TIMESTAMP
            )
        """)
        db.commit()
    except Exception as e:
        logger.error(f"创建 user_roles 表失败: {e}")


def _grant_role_to_user(db, user_id: int, role: str, assigned_by: str) -> bool:
    """
    实际授予用户角色（写入 user_roles 表）。

    Args:
        db: 数据库连接
        user_id: 被授权用户 ID
        role: 目标角色（admin/operator/viewer）
        assigned_by: 授权者标识（如 'admin:123456'）

    Returns:
        True=成功，False=失败
    """
    try:
        _ensure_user_roles_table(db)
        now = datetime.now(_CST).isoformat()
        # INSERT OR REPLACE：用户已存在则更新角色，不存在则新增
        db.execute(
            "INSERT OR REPLACE INTO user_roles (user_id, role, assigned_by, assigned_at) VALUES (?, ?, ?, ?)",
            (user_id, role, assigned_by, now),
        )
        db.commit()
        return True
    except Exception as e:
        logger.error(f"授予用户 {user_id} 角色 {role} 失败: {e}")
        return False


def _log_audit_internal(operator_id: int, operator_name: str, role: str,
                        permission: str, endpoint: str, method: str,
                        allowed: bool, ip: str, payload_summary: str = ""):
    """写入审计日志（复用 dashboard.audit.log_audit，失败不阻断）"""
    try:
        from dashboard.audit import log_audit
        log_audit(
            operator_id=operator_id,
            operator_name=operator_name,
            role=role,
            permission=permission,
            endpoint=endpoint,
            method=method,
            allowed=allowed,
            ip=ip,
            payload_summary=payload_summary,
        )
    except Exception as e:
        logger.warning(f"写审计日志失败（非致命）: {e}")


def create_request(requester_id: int, target_user_id: int,
                   requested_role: str, reason: str = "") -> dict:
    """
    创建权限变更申请。

    Args:
        requester_id: 申请人 user_id
        target_user_id: 被授权用户 user_id
        requested_role: 申请的角色（admin/operator/viewer）
        reason: 申请理由

    Returns:
        {"ok": bool, "msg": str, "request_id": int|None}
    """
    # 1. 配置开关检查（新功能默认关闭）
    if not _read_config("RBAC_APPROVAL_ENABLED", False):
        return {"ok": False, "msg": "审批流未启用", "request_id": None}

    # 2. 参数校验
    if requested_role not in _VALID_ROLES:
        return {"ok": False, "msg": f"非法角色：{requested_role}", "request_id": None}
    if not requester_id or not target_user_id:
        return {"ok": False, "msg": "申请人/被授权用户 ID 不能为空", "request_id": None}

    try:
        db = _get_db()
        now = datetime.now(_CST).isoformat()
        cur = db.execute(
            """INSERT INTO permission_change_requests
               (requester_id, target_user_id, requested_role, reason, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (requester_id, target_user_id, requested_role, reason or "",
             STATUS_PENDING, now, now),
        )
        db.commit()
        req_id = cur.lastrowid
        logger.info(f"权限申请已创建: id={req_id} requester={requester_id} "
                    f"target={target_user_id} role={requested_role}")
        return {"ok": True, "msg": "申请已提交", "request_id": req_id}
    except sqlite3.Error as e:
        logger.error(f"创建权限申请失败: {e}")
        return {"ok": False, "msg": "数据库错误，请查看服务器日志获取详情", "request_id": None}
    except Exception as e:
        logger.error(f"创建权限申请异常: {e}")
        return {"ok": False, "msg": "内部错误", "request_id": None}


def approve_request(request_id: int, approver_id: int) -> dict:
    """
    审批通过：更新申请状态 + 实际授予角色 + 记录审计日志。

    Args:
        request_id: 申请 ID
        approver_id: 审批人 user_id

    Returns:
        {"ok": bool, "msg": str}
    """
    try:
        db = _get_db()
        # 1. 查询申请
        req = get_request(request_id)
        if not req:
            return {"ok": False, "msg": "申请不存在"}
        if req["status"] != STATUS_PENDING:
            return {"ok": False, "msg": f"申请状态非 pending（当前: {req['status']}）"}

        # 2. 实际授予角色（UPDATE user_roles）
        assigned_by = f"admin:{approver_id}"
        ok = _grant_role_to_user(db, req["target_user_id"], req["requested_role"], assigned_by)
        if not ok:
            return {"ok": False, "msg": "角色授予失败，请检查日志"}

        # 3. 更新申请状态
        now = datetime.now(_CST).isoformat()
        db.execute(
            """UPDATE permission_change_requests
               SET status=?, approver_id=?, approved_at=?, updated_at=?
               WHERE id=? AND status=?""",
            (STATUS_APPROVED, approver_id, now, now, request_id, STATUS_PENDING),
        )
        db.commit()

        # 4. 记录审计日志
        _log_audit_internal(
            operator_id=approver_id,
            operator_name=f"admin:{approver_id}",
            role="admin",
            permission="users:write",
            endpoint="/api/rbac/approve",
            method="POST",
            allowed=True,
            ip="internal",
            payload_summary=(f"approve req#{request_id} "
                             f"target={req['target_user_id']} role={req['requested_role']}"),
        )
        logger.info(f"权限申请已审批通过: id={request_id} approver={approver_id}")
        return {"ok": True, "msg": "审批通过"}
    except sqlite3.Error as e:
        logger.error(f"审批通过失败: {e}")
        return {"ok": False, "msg": "数据库错误，请查看服务器日志获取详情"}
    except Exception as e:
        logger.error(f"审批通过异常: {e}")
        return {"ok": False, "msg": "内部错误"}


def reject_request(request_id: int, approver_id: int, reason: str = "") -> dict:
    """
    审批拒绝。

    Args:
        request_id: 申请 ID
        approver_id: 审批人 user_id
        reason: 拒绝理由（可选）

    Returns:
        {"ok": bool, "msg": str}
    """
    try:
        db = _get_db()
        req = get_request(request_id)
        if not req:
            return {"ok": False, "msg": "申请不存在"}
        if req["status"] != STATUS_PENDING:
            return {"ok": False, "msg": f"申请状态非 pending（当前: {req['status']}）"}

        now = datetime.now(_CST).isoformat()
        db.execute(
            """UPDATE permission_change_requests
               SET status=?, approver_id=?, updated_at=?
               WHERE id=? AND status=?""",
            (STATUS_REJECTED, approver_id, now, request_id, STATUS_PENDING),
        )
        db.commit()

        _log_audit_internal(
            operator_id=approver_id,
            operator_name=f"admin:{approver_id}",
            role="admin",
            permission="users:write",
            endpoint="/api/rbac/reject",
            method="POST",
            allowed=True,
            ip="internal",
            payload_summary=(f"reject req#{request_id} reason={reason[:100]}"),
        )
        logger.info(f"权限申请已拒绝: id={request_id} approver={approver_id}")
        return {"ok": True, "msg": "已拒绝"}
    except sqlite3.Error as e:
        logger.error(f"审批拒绝失败: {e}")
        return {"ok": False, "msg": "数据库错误，请查看服务器日志获取详情"}
    except Exception as e:
        logger.error(f"审批拒绝异常: {e}")
        return {"ok": False, "msg": "内部错误"}


def cancel_request(request_id: int, requester_id: int) -> dict:
    """
    申请人取消申请（仅 pending 可取消）。

    Args:
        request_id: 申请 ID
        requester_id: 申请人 user_id（仅本人可取消）

    Returns:
        {"ok": bool, "msg": str}
    """
    try:
        db = _get_db()
        req = get_request(request_id)
        if not req:
            return {"ok": False, "msg": "申请不存在"}
        if req["requester_id"] != requester_id:
            return {"ok": False, "msg": "仅申请人本人可取消"}
        if req["status"] != STATUS_PENDING:
            return {"ok": False, "msg": f"申请状态非 pending（当前: {req['status']}）"}

        now = datetime.now(_CST).isoformat()
        db.execute(
            """UPDATE permission_change_requests
               SET status=?, updated_at=?
               WHERE id=? AND status=?""",
            (STATUS_CANCELLED, now, request_id, STATUS_PENDING),
        )
        db.commit()
        logger.info(f"权限申请已取消: id={request_id} requester={requester_id}")
        return {"ok": True, "msg": "已取消"}
    except sqlite3.Error as e:
        logger.error(f"取消申请失败: {e}")
        return {"ok": False, "msg": "数据库错误，请查看服务器日志获取详情"}
    except Exception as e:
        logger.error(f"取消申请异常: {e}")
        return {"ok": False, "msg": "内部错误"}


def list_requests(status: str = STATUS_PENDING, limit: int = 50) -> list:
    """
    列出权限变更申请。

    Args:
        status: 状态过滤（pending/approved/rejected/cancelled），传 'all' 查全部
        limit: 返回条数上限（最大 200）

    Returns:
        list[dict]，按 created_at 倒序
    """
    try:
        db = _get_db()
        limit = max(1, min(int(limit), 200))
        if status == "all":
            sql = "SELECT * FROM permission_change_requests ORDER BY created_at DESC LIMIT ?"
            rows = db.execute(sql, (limit,)).fetchall()
        else:
            sql = "SELECT * FROM permission_change_requests WHERE status=? ORDER BY created_at DESC LIMIT ?"
            rows = db.execute(sql, (status, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"查询申请列表失败: {e}")
        return []


def get_request(request_id: int) -> dict:
    """
    查询申请详情。

    Args:
        request_id: 申请 ID

    Returns:
        dict 或 None
    """
    try:
        db = _get_db()
        row = db.execute(
            "SELECT * FROM permission_change_requests WHERE id=?",
            (request_id,),
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"查询申请详情失败: {e}")
        return None


def get_rbac_audit_data() -> dict:
    """
    收集 RBAC 权限审计数据（供定时任务和 API 共用）。

    Returns:
        {
            "role_counts": {role: count},
            "recent_changes": [...],     # 最近 30 天权限变更申请
            "orphan_permissions": [...], # 孤儿权限（user_roles 有记录但 users 表无此用户）
            "total_users": int,
        }
    """
    result = {
        "role_counts": {"admin": 0, "operator": 0, "viewer": 0},
        "recent_changes": [],
        "orphan_permissions": [],
        "total_users": 0,
    }
    try:
        db = _get_db()
        _ensure_user_roles_table(db)

        # 1. 各角色用户数
        try:
            cur = db.execute(
                "SELECT role, COUNT(*) FROM user_roles GROUP BY role"
            )
            for role, cnt in cur.fetchall():
                if role in result["role_counts"]:
                    result["role_counts"][role] = cnt
        except Exception as e:
            logger.warning(f"统计角色数量失败: {e}")

        # 2. user_roles 总数
        try:
            result["total_users"] = db.execute(
                "SELECT COUNT(*) FROM user_roles"
            ).fetchone()[0]
        except Exception as e:
            logger.warning(f"统计 user_roles 总数失败: {e}")

        # 3. 最近 30 天权限变更申请
        try:
            cutoff_ts = datetime.now(_CST).timestamp() - 30 * 86400
            cutoff_str = datetime.fromtimestamp(cutoff_ts, _CST).isoformat()
            rows = db.execute(
                """SELECT * FROM permission_change_requests
                   WHERE created_at >= ?
                   ORDER BY created_at DESC LIMIT 200""",
                (cutoff_str,),
            ).fetchall()
            result["recent_changes"] = [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"查询最近权限变更失败: {e}")

        # 4. 孤儿权限：user_roles 有记录但 users 表无此 uid
        try:
            rows = db.execute(
                """SELECT ur.user_id, ur.role, ur.assigned_by, ur.assigned_at
                   FROM user_roles ur
                   LEFT JOIN users u ON ur.user_id = u.uid
                   WHERE u.uid IS NULL"""
            ).fetchall()
            result["orphan_permissions"] = [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"查询孤儿权限失败: {e}")

    except Exception as e:
        logger.error(f"收集 RBAC 审计数据失败: {e}")
    return result
