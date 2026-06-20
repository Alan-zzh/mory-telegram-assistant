# -*- coding: utf-8 -*-
"""Dashboard认证模块 - 登录/登出/安全中间件"""
import os
import time
import hmac
import secrets
from datetime import datetime, timedelta
from flask import request, jsonify, session, g
from dashboard.helpers import get_db, login_required

# ============ 速率限制 ============
_dashboard_rate_limits = {}
_RATE_LIMIT_MAX_ENTRIES = 10000
_RATE_LIMIT_CLEANUP_INTERVAL = 300  # 每5分钟清理一次过期条目
_last_rate_cleanup = 0

# ============ 登录失败记录 ============
_login_failures = {}
_LOGIN_LOCKOUT_SECONDS = 600
_LOGIN_MAX_FAILS = 5


def _check_rate_limit(ip: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """IP速率限制检查"""
    import time as _time
    now = _time.time()
    # 定期清理过期条目，防止内存泄漏
    global _last_rate_cleanup
    if now - _last_rate_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
        expired_keys = [k for k, v in _dashboard_rate_limits.items() if now > v["reset_at"]]
        for k in expired_keys:
            del _dashboard_rate_limits[k]
        _last_rate_cleanup = now
    if len(_dashboard_rate_limits) > _RATE_LIMIT_MAX_ENTRIES:
        oldest = min(_dashboard_rate_limits, key=lambda k: _dashboard_rate_limits[k]["reset_at"])
        del _dashboard_rate_limits[oldest]
    record = _dashboard_rate_limits.get(ip)
    if not record or now > record["reset_at"]:
        _dashboard_rate_limits[ip] = {"count": 1, "reset_at": now + window_seconds}
        return True
    record["count"] += 1
    if record["count"] > max_requests:
        return False
    return True


def _get_login_fails(ip):
    """获取登录失败次数"""
    info = _login_failures.get(ip)
    if not info:
        return {"count": 0, "first_fail_at": 0}
    if time.time() - info["first_fail_at"] > _LOGIN_LOCKOUT_SECONDS:
        del _login_failures[ip]
        return {"count": 0, "first_fail_at": 0}
    return info


def _set_login_fails(ip, info):
    """记录登录失败"""
    _login_failures[ip] = info


def _clear_login_fails(ip):
    """清除登录失败记录"""
    _login_failures.pop(ip, None)


# ============ CSRF Token 管理 ============
def _generate_csrf_token():
    """生成或刷新 session 级 CSRF token"""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def _validate_csrf_token():
    """验证 CSRF token（双提交 Cookie 模式：对比 header 与 session）"""
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not token:
        return False
    return hmac.compare_digest(token, session.get("_csrf_token", ""))


# ============ 安全中间件 ============
def _security_check():
    """CSRF校验 + 速率限制中间件"""
    if request.path.startswith(('/static/', '/favicon')):
        return None
    if request.method == 'GET':
        if not _check_rate_limit(request.remote_addr):
            return jsonify({"ok": False, "msg": "请求过于频繁，请稍后再试"}), 429
        return None
    # 【TRAE SOLO CN v5.18.3审计修复】所有写操作（POST/PUT/DELETE/PATCH）统一校验 CSRF + 速率限制
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        if not _check_rate_limit(request.remote_addr, max_requests=30):
            return jsonify({"ok": False, "msg": "请求过于频繁，请稍后再试"}), 429
        if request.path == '/api/login':
            return None
        # CSRF 校验：检查 X-Requested-With + CSRF Token
        if not request.headers.get('X-Requested-With'):
            return jsonify({"ok": False, "msg": "CSRF校验失败：缺少请求头"}), 403
        if not _validate_csrf_token():
            return jsonify({"ok": False, "msg": "CSRF校验失败：Token无效"}), 403
    return None


def close_db(exception):
    """请求结束时关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


# ============ 认证路由注册 ============
# 【TRAE SOLO CN v5.18.3审计修复】删除 auth.py 中失效的 admin_required（检查 is_admin 但登录时设置的是 role），
# 统一使用 dashboard.helpers.admin_required（检查 role）。需要 admin 校验的接口请从 helpers 导入。


def _sync_role_from_db(data: dict):
    """[阶段3-F] 若请求携带 user_id，从 user_roles 表同步角色到 session。

    - 无 user_id → 保留密码默认角色（不破坏现有登录逻辑）
    - user_id 存在但 user_roles 无记录 → 默认 viewer（最小权限原则）
    - user_id 存在且有记录 → 使用 DB 角色
    """
    user_id = data.get("user_id")
    if not user_id:
        return
    try:
        from dashboard.audit import get_user_role_from_db
        db = get_db()
        session["role"] = get_user_role_from_db(db, int(user_id))
    except (ValueError, TypeError):
        pass  # user_id 无效，保留密码默认角色


def init_auth(app):
    """注册认证和安全中间件到Flask应用"""
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('DASHBOARD_HTTPS', '').lower() == 'true'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

    # 【TRAE SOLO CN v5.18.3审计修复】ProxyFix：反向代理场景下正确获取客户端真实 IP
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # 【TRAE SOLO CN v5.18.3审计修复】安全响应头，防御 clickjacking / MIME 嗅探 / XSS
    @app.after_request
    def _set_security_headers(resp):
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-XSS-Protection'] = '1; mode=block'
        if os.environ.get('DASHBOARD_HTTPS', '').lower() == 'true':
            resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return resp

    # 注册中间件
    app.before_request(_security_check)
    app.teardown_appcontext(close_db)

    # 登录接口
    @app.route("/api/login", methods=["POST"])
    def api_login():
        data = request.get_json() or {}
        pw = data.get("password", "")
        # 【安全说明】DASHBOARD_PASSWORD 从环境变量读取明文密码，
        # 适用于内网/本地 Dashboard 后台管理。
        # 生产环境建议改用 hashlib.sha256 哈希后存储在单独配置文件中，
        # 并通过 os.environ 或 secrets 模块在启动时注入。
        admin_pw = os.environ.get("DASHBOARD_PASSWORD")
        if not admin_pw or len(admin_pw) < 6:
            return jsonify({"ok": False, "msg": "系统未正确配置密码，请联系管理员"}), 403
        login_key = request.remote_addr
        fail_info = _get_login_fails(login_key)
        if fail_info["count"] >= 5:
            elapsed = time.time() - fail_info["first_fail_at"]
            if elapsed < 600:
                return jsonify({"ok": False, "msg": "登录尝试过多，请10分钟后再试"}), 429
            fail_info = {"count": 0, "first_fail_at": 0}
        viewer_pw = os.environ.get("DASHBOARD_VIEWER_PASSWORD", "")
        if hmac.compare_digest(pw, admin_pw):
            session["logged_in"] = True
            session["login_time"] = datetime.now().isoformat()
            session["role"] = "admin"
            # [阶段3-F] RBAC 角色同步：若请求携带 user_id，从 DB 读取角色覆盖默认角色
            _sync_role_from_db(data)
            _generate_csrf_token()
            _clear_login_fails(login_key)
            return jsonify({"ok": True, "csrf_token": session.get("_csrf_token", ""), "role": session.get("role", "admin")})
        if viewer_pw and len(viewer_pw) >= 6 and hmac.compare_digest(pw, viewer_pw):
            session["logged_in"] = True
            session["login_time"] = datetime.now().isoformat()
            session["role"] = "viewer"
            # [阶段3-F] RBAC 角色同步：若请求携带 user_id，从 DB 读取角色覆盖默认角色
            _sync_role_from_db(data)
            _generate_csrf_token()
            _clear_login_fails(login_key)
            return jsonify({"ok": True, "csrf_token": session.get("_csrf_token", ""), "role": session.get("role", "viewer")})
        if fail_info["count"] == 0:
            fail_info["first_fail_at"] = time.time()
        fail_info["count"] += 1
        _set_login_fails(login_key, fail_info)
        return jsonify({"ok": False, "msg": "密码错误"}), 401

    # 登出接口
    @app.route("/api/logout", methods=["POST"])
    def api_logout():
        session.clear()
        return jsonify({"ok": True})

    # 登录状态检查
    @app.route("/api/check")
    @login_required
    def api_check():
        return jsonify({"ok": True, "role": session.get("role", "admin")})

    # 获取 CSRF Token（前端登录后调用）
    @app.route("/api/csrf-token", methods=["GET"])
    @login_required
    def api_csrf_token():
        token = _generate_csrf_token()
        return jsonify({"ok": True, "csrf_token": token})
