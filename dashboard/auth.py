# -*- coding: utf-8 -*-
"""Dashboard认证模块 - 登录/登出/安全中间件"""
import os
import time
import hmac
import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, session, g
from dashboard.helpers import get_db, login_required

# 【Loop 16】CST 时区，避免 VPS(UTC) 下登录时间错位 8 小时
_CST = timezone(timedelta(hours=8))

# 【P0 修复 Task-09】Session 滑动续期：每次请求自动刷新过期时间（默认 30 分钟）
_SESSION_LIFETIME_SECONDS = 1800  # 30 分钟
# 【WARN-4 修复】Session 绝对最大会话时间：无论滑动续期如何，超过此时间必须重新登录
# 防止攻击者登录后通过持续 GET 请求无限续期
_SESSION_ABSOLUTE_MAX_SECONDS = 8 * 3600  # 8 小时

# ============ 速率限制 ============
_dashboard_rate_limits = {}
_RATE_LIMIT_MAX_ENTRIES = 10000
_RATE_LIMIT_CLEANUP_INTERVAL = 300  # 每5分钟清理一次过期条目
_last_rate_cleanup = 0
# 【v5.31.2 修复】Flask threaded=True 下并发请求会绕过限流/暴力破解保护，加锁保护
_rate_limit_lock = threading.Lock()

# ============ 登录失败记录 ============
_login_failures = {}
_LOGIN_LOCKOUT_SECONDS = 600
_LOGIN_MAX_FAILS = 5
_login_failures_lock = threading.Lock()


def _check_rate_limit(ip: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """IP速率限制检查（线程安全）"""
    import time as _time
    now = _time.time()
    global _last_rate_cleanup
    with _rate_limit_lock:
        # 定期清理过期条目，防止内存泄漏
        if now - _last_rate_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
            expired_keys = [k for k, v in _dashboard_rate_limits.items() if now > v["reset_at"]]
            for k in expired_keys:
                _dashboard_rate_limits.pop(k, None)  # 并发安全删除
            _last_rate_cleanup = now
        if len(_dashboard_rate_limits) > _RATE_LIMIT_MAX_ENTRIES:
            oldest = min(_dashboard_rate_limits, key=lambda k: _dashboard_rate_limits[k]["reset_at"])
            _dashboard_rate_limits.pop(oldest, None)
        record = _dashboard_rate_limits.get(ip)
        if not record or now > record["reset_at"]:
            _dashboard_rate_limits[ip] = {"count": 1, "reset_at": now + window_seconds}
            return True
        record["count"] += 1
        if record["count"] > max_requests:
            return False
        return True


def _get_login_fails(ip):
    """获取登录失败次数（线程安全）"""
    with _login_failures_lock:
        info = _login_failures.get(ip)
        if not info:
            return {"count": 0, "first_fail_at": 0}
        if time.time() - info["first_fail_at"] > _LOGIN_LOCKOUT_SECONDS:
            _login_failures.pop(ip, None)  # 并发安全删除
            return {"count": 0, "first_fail_at": 0}
        # 返回副本避免外部修改影响内部状态
        return dict(info)


def _set_login_fails(ip, info):
    """记录登录失败（线程安全）"""
    with _login_failures_lock:
        # 【v5.31.2 修复】加上限保护，防止攻击者用大量不同 IP 各失败 1 次后不再访问导致内存累积
        if len(_login_failures) > _RATE_LIMIT_MAX_ENTRIES:
            oldest = min(_login_failures, key=lambda k: _login_failures[k].get("first_fail_at", 0))
            _login_failures.pop(oldest, None)
        _login_failures[ip] = info


def _clear_login_fails(ip):
    """清除登录失败记录（线程安全）"""
    with _login_failures_lock:
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


# ============ 密码哈希工具（P0 Task-03）============
def _hash_password(pw: str) -> str:
    """计算密码 sha256 哈希（小写 hex）"""
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def _verify_password(pw: str, stored: str) -> bool:
    """双模式密码校验：支持 sha256 哈希 + 向后兼容明文

    判断逻辑：
    - stored 长度 == 64 且为 hex → 视为 sha256 哈希，比较哈希值
    - 否则 → 视为明文，直接 compare_digest（向后兼容旧部署）

    新部署推荐在 .env 设置 DASHBOARD_PASSWORD_HASH（sha256）替代 DASHBOARD_PASSWORD。
    生成哈希：python -c "import hashlib; print(hashlib.sha256(b'your_password').hexdigest())"
    """
    if not stored or not pw:
        return False
    # sha256 hex 长度 64，且为纯 hex 字符 → 哈希模式
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return hmac.compare_digest(_hash_password(pw), stored.lower())
    # 明文模式（向后兼容）
    return hmac.compare_digest(pw, stored)


# ============ Session 滑动续期（P0 Task-09）============
def _touch_session():
    """刷新 session 过期时间（滑动续期）

    每次 GET 请求自动调用，避免操作中 30 分钟硬过期被强制登出。
    POST 等写操作不刷新（防止攻击者通过持续 POST 续期）。
    【WARN-4 修复】滑动续期不能超过绝对最大会话时间（8 小时）。
    """
    if session.get("logged_in"):
        now = datetime.now(_CST)
        new_expires = now + timedelta(seconds=_SESSION_LIFETIME_SECONDS)
        # 【WARN-4 修复】检查绝对最大会话时间：滑动续期不能超过 absolute_expires_at
        absolute_expires_at = session.get("absolute_expires_at")
        if absolute_expires_at:
            try:
                abs_dt = datetime.fromisoformat(absolute_expires_at)
                if new_expires > abs_dt:
                    new_expires = abs_dt  # 截断到绝对过期时间
            except (ValueError, TypeError):
                pass  # absolute_expires_at 格式异常，忽略（不阻断续期）
        session["expires_at"] = new_expires.isoformat()


def _is_session_expired() -> bool:
    """检查 session 是否过期

    【WARN-4 修复】双重检查：
    1. 滑动过期时间（expires_at）：每次 GET 请求刷新，30 分钟无活动即过期
    2. 绝对最大会话时间（absolute_expires_at）：登录时设置，8 小时后必须重新登录
    """
    expires_at = session.get("expires_at")
    if not expires_at:
        return False  # 未设置过期时间，依赖 Flask 默认 PERMANENT_SESSION_LIFETIME
    try:
        now = datetime.now(_CST)
        if now > datetime.fromisoformat(expires_at):
            return True  # 滑动过期
        # 【WARN-4 修复】检查绝对最大会话时间
        absolute_expires_at = session.get("absolute_expires_at")
        if absolute_expires_at and now > datetime.fromisoformat(absolute_expires_at):
            return True  # 绝对过期
        return False
    except (ValueError, TypeError):
        return False


# ============ 安全中间件 ============
def _security_check():
    """CSRF校验 + 速率限制中间件"""
    if request.path.startswith(('/static/', '/favicon')):
        return None
    # [P0 修复 Task-09] Session 过期强制登出（即使 Flask 默认 PERMANENT_SESSION_LIFETIME 未生效）
    if session.get("logged_in") and _is_session_expired():
        session.clear()
        if request.path != '/api/login':
            return jsonify({"ok": False, "msg": "会话已过期，请重新登录", "session_expired": True}), 401
    if request.method == 'GET':
        if not _check_rate_limit(request.remote_addr):
            return jsonify({"ok": False, "msg": "请求过于频繁，请稍后再试"}), 429
        # [P0 修复 Task-09] GET 请求滑动续期
        _touch_session()
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
        # [P0 修复 Task-03] 双模式密码校验：
        #   优先 DASHBOARD_PASSWORD_HASH（sha256 hex），向后兼容 DASHBOARD_PASSWORD（明文）
        #   新部署推荐用 sha256：python -c "import hashlib; print(hashlib.sha256(b'your_password').hexdigest())"
        admin_pw_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
        admin_pw_plain = os.environ.get("DASHBOARD_PASSWORD", "")
        # 至少有一种密码配置，且长度合规
        has_hash = bool(admin_pw_hash) and len(admin_pw_hash) == 64
        has_plain = bool(admin_pw_plain) and len(admin_pw_plain) >= 6
        if not has_hash and not has_plain:
            return jsonify({"ok": False, "msg": "系统未正确配置密码，请联系管理员"}), 403
        login_key = request.remote_addr
        fail_info = _get_login_fails(login_key)
        if fail_info["count"] >= 5:
            elapsed = time.time() - fail_info["first_fail_at"]
            if elapsed < 600:
                return jsonify({"ok": False, "msg": "登录尝试过多，请10分钟后再试"}), 429
            fail_info = {"count": 0, "first_fail_at": 0}
        viewer_pw_hash = os.environ.get("DASHBOARD_VIEWER_PASSWORD_HASH", "")
        viewer_pw_plain = os.environ.get("DASHBOARD_VIEWER_PASSWORD", "")

        # 管理员校验：优先哈希，回退明文
        admin_ok = (has_hash and _verify_password(pw, admin_pw_hash)) or \
                   (has_plain and _verify_password(pw, admin_pw_plain))
        if admin_ok:
            session["logged_in"] = True
            login_dt = datetime.now(_CST)
            session["login_time"] = login_dt.isoformat()
            # [P0 修复 Task-09] 设置滑动过期时间
            session["expires_at"] = (login_dt + timedelta(seconds=_SESSION_LIFETIME_SECONDS)).isoformat()
            # 【WARN-4 修复】设置绝对最大会话时间：8 小时后必须重新登录
            session["absolute_expires_at"] = (login_dt + timedelta(seconds=_SESSION_ABSOLUTE_MAX_SECONDS)).isoformat()
            session["role"] = "admin"
            # [阶段3-F] RBAC 角色同步：若请求携带 user_id，从 DB 读取角色覆盖默认角色
            _sync_role_from_db(data)
            _generate_csrf_token()
            _clear_login_fails(login_key)
            return jsonify({"ok": True, "csrf_token": session.get("_csrf_token", ""), "role": session.get("role", "admin")})

        # viewer 校验：优先哈希，回退明文
        viewer_has_hash = bool(viewer_pw_hash) and len(viewer_pw_hash) == 64
        viewer_has_plain = bool(viewer_pw_plain) and len(viewer_pw_plain) >= 6
        viewer_ok = (viewer_has_hash and _verify_password(pw, viewer_pw_hash)) or \
                    (viewer_has_plain and _verify_password(pw, viewer_pw_plain))
        if viewer_ok:
            session["logged_in"] = True
            login_dt = datetime.now(_CST)
            session["login_time"] = login_dt.isoformat()
            # [P0 修复 Task-09] 设置滑动过期时间
            session["expires_at"] = (login_dt + timedelta(seconds=_SESSION_LIFETIME_SECONDS)).isoformat()
            # 【WARN-4 修复】设置绝对最大会话时间：8 小时后必须重新登录
            session["absolute_expires_at"] = (login_dt + timedelta(seconds=_SESSION_ABSOLUTE_MAX_SECONDS)).isoformat()
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
