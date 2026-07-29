# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  dashboard/rbac_guard.py  ·  RBAC 请求级守卫（v5.24.0 阶段2-A）           ║
║                                                                            ║
║  功能：                                                                    ║
║    Flask before_request 钩子，对所有写操作（POST/PUT/DELETE/PATCH）        ║
║    自动校验 RBAC 权限，零侵入覆盖全部 93+ 写接口。                         ║
║                                                                            ║
║  策略：                                                                    ║
║    1. 只拦截写方法（GET/HEAD/OPTIONS 豁免）                                ║
║    2. 豁免路径：登录/健康检查/静态资源                                     ║
║    3. 根据请求路径自动推断所需权限                                          ║
║    4. 无权限返回 403 + 记录审计日志                                         ║
║    5. 已有 @admin_required 的接口兼容（admin 拥有全部权限）                ║
║                                                                            ║
║  路径到权限映射：                                                          ║
║    /config/ /settings/ /group/ /keywords/ → config:write                  ║
║    /faq/ → faq:write                                                       ║
║    /orphan/ → orphan:clean                                                 ║
║    /ab-test/ → ab_test:write                                               ║
║    /engage/ → engage:write                                                 ║
║    /broadcasts → broadcast:write                                           ║
║    /audit/cleanup → audit:write                                            ║
║    默认 → config:write（最严格）                                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from flask import jsonify, session, request
from dashboard.audit import get_current_role, has_permission, log_audit, _summarize_payload

# 写方法
_WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# 豁免路径前缀（不校验权限）
# 【v5.38.9 安全修复】收紧豁免列表:
#   1. 移除 /api/scheduler/jobs /api/scheduler/stats /api/audit/logs /api/audit/stats /api/attribution/
#      这些路径暴露调度任务清单、审计日志、归因数据,未登录可读属于数据泄露
#   2. /api/health 仅根路径(精确匹配)豁免,子路径如 /api/health/score /api/health/jobs 必须登录
# 所有 /api/* 路径默认要求登录 + 对应权限,只有 /api/health 根路径允许未登录探活
_EXEMPT_PREFIXES = (
    "/login", "/api/login", "/api/auth", "/static/",
)

# 需要精确匹配(==)的豁免路径,避免 startswith 误豁免子路径
_EXEMPT_EXACT_PATHS = {
    "/api/health",  # 仅根路径用于探活;/api/health/score /api/health/jobs 等子路径必须登录
}

# 路径前缀到权限的映射（按最长匹配优先）
_PATH_PERMISSION_MAP = [
    ("/config/", "config:write"),
    ("/settings/", "config:write"),
    ("/group/", "config:write"),
    ("/keywords/", "config:write"),
    ("/faq/", "faq:write"),
    ("/orphan/", "orphan:clean"),
    ("/ab-test/", "ab_test:write"),
    ("/engage/", "engage:write"),
    ("/broadcasts", "broadcast:write"),
    ("/audit/cleanup", "audit:write"),
]


def _infer_permission(path: str) -> str:
    """根据请求路径推断所需权限"""
    for prefix, perm in _PATH_PERMISSION_MAP:
        if path.startswith(prefix):
            return perm
    return "config:write"  # 默认最严格


def _is_exempt(path: str) -> bool:
    """检查路径是否豁免

    【v5.38.9】/api/health 改为精确匹配,避免 startswith 误豁免 /api/health/score
    /api/health/jobs /api/health/audit 等子路径(它们含敏感运维数据,必须登录)。
    """
    if path in _EXEMPT_EXACT_PATHS:
        return True
    return path.startswith(_EXEMPT_PREFIXES)


def enforce_rbac():
    """
    Flask before_request 钩子：对所有写操作自动校验 RBAC 权限。

    注册方式（在 create_app 中）：
        from dashboard.rbac_guard import enforce_rbac
        app.before_request(enforce_rbac)

    权限查询策略（阶段3-F DB 驱动）：
        1. 优先从 role_permissions 表动态查询权限
        2. DB 不可用或表为空时，回退到 ROLE_PERMISSIONS 硬编码字典（向后兼容）
    """
    # 1. 只拦截写方法
    if request.method not in _WRITE_METHODS:
        return None

    path = request.path

    # 2. 豁免路径
    if _is_exempt(path):
        return None

    # 3. 登录检查
    if not session.get("logged_in"):
        return jsonify({"ok": False, "msg": "未登录"}), 401

    # 4. 推断权限
    permission = _infer_permission(path)
    role = get_current_role()

    # 5. 获取 DB 连接（失败回退到硬编码字典）
    db = None
    try:
        from dashboard.helpers import get_db
        db = get_db()
    except Exception:
        db = None  # 无请求上下文或 DB 异常，has_permission 内部会回退到字典

    allowed = has_permission(permission, role, db=db)

    # 6. 记录审计日志
    operator_id = session.get("uid", 0)
    operator_name = session.get("username", "unknown")
    log_audit(
        operator_id=operator_id,
        operator_name=operator_name,
        role=role,
        permission=permission,
        endpoint=path,
        method=request.method,
        allowed=allowed,
        ip=request.remote_addr or "unknown",
        payload_summary=_summarize_payload(),
    )

    # 7. 无权限拒绝
    if not allowed:
        return jsonify({"ok": False, "msg": f"权限不足：需要 {permission}"}), 403

    return None
