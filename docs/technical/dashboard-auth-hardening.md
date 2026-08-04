# Dashboard 认证加固详解

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.18.3+ / v5.31.2 审计整改
> **最后更新**：2026-07-06

## 概述

Dashboard 是 Bot 的运维控制台，认证层是最后一道防线。本文档详述 v5.31.2 审计整改引入的 3 项加固：**sha256 密码哈希双模式**、**Session 滑动续期**、**SSH Key 优先认证**。

## 适用场景

- 排查"Dashboard 登录失败"时查阅
- 配置 `.env` 密码相关环境变量时查阅
- 排查"会话已过期，请重新登录"时查阅
- 配置 VPS SSH Key 认证时查阅
- 新增 Dashboard 接口时参考认证中间件用法

## sha256 密码哈希双模式（P0 Task-03）

### 问题

之前 Dashboard 密码以明文存 `.env`：`DASHBOARD_PASSWORD=my_secret`。即使 `.env` 不提交 Git，VPS 上文件泄露即明文暴露。

### 修复

新增 `DASHBOARD_PASSWORD_HASH` / `DASHBOARD_VIEWER_PASSWORD_HASH` 环境变量，存 sha256 hex 字符串。`dashboard/auth.py` 双模式校验：

```python
def _verify_password(pw: str, stored: str) -> bool:
    """双模式：sha256 哈希 + 明文向后兼容"""
    if not stored or not pw:
        return False
    # sha256 hex 长度 64 且为纯 hex → 哈希模式
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return hmac.compare_digest(_hash_password(pw), stored.lower())
    # 明文模式（向后兼容）
    return hmac.compare_digest(pw, stored)
```

### 配置方式

```bash
# 生成 sha256 哈希
python -c "import hashlib; print(hashlib.sha256(b'your_password').hexdigest())"

# 写入 .env
DASHBOARD_PASSWORD_HASH=<上面生成的 64 位 hex>
DASHBOARD_VIEWER_PASSWORD_HASH=<viewer 密码的 sha256>
```

### 优先级

`DASHBOARD_PASSWORD_HASH` 优先于 `DASHBOARD_PASSWORD`。两个都配置时优先用哈希。新部署推荐只用 `*_HASH`，旧部署可保留明文逐步迁移。

### 安全细节

- `hmac.compare_digest` 防时序攻击（攻击者无法通过响应时间差异逐字符猜密码）
- 哈希模式自动识别大小写 hex（`stored.lower()` 统一比较）
- 64 位长度但非 hex 字符串（如全 `g`）自动回退明文模式

## Session 滑动续期（P0 Task-09）

### 问题

之前依赖 Flask 默认 `PERMANENT_SESSION_LIFETIME=30min` 硬过期。用户在 Dashboard 操作 30 分钟后即使一直点击也会被强制登出，体验差。

### 修复

新增 `_touch_session()` + `_is_session_expired()`，GET 请求自动刷新过期时间：

```python
def _touch_session():
    """刷新 session 过期时间（滑动续期）"""
    if session.get("logged_in"):
        session["expires_at"] = (datetime.now(_CST) + timedelta(seconds=1800)).isoformat()

def _is_session_expired() -> bool:
    expires_at = session.get("expires_at")
    if not expires_at:
        return False
    try:
        return datetime.now(_CST) > datetime.fromisoformat(expires_at)
    except (ValueError, TypeError):
        return False
```

`_security_check` 中间件集成：

```python
def _security_check():
    # Session 过期强制登出
    if session.get("logged_in") and _is_session_expired():
        session.clear()
        return jsonify({"ok": False, "msg": "会话已过期", "session_expired": True}), 401
    if request.method == 'GET':
        _touch_session()  # GET 滑动续期
        return None
    # POST/PUT/DELETE/PATCH 不刷新（防攻击者通过持续 POST 续期）
    ...
```

### 设计权衡

- **GET 刷新**：用户浏览页面/查询数据时自动续期，正常操作不会被强制登出
- **POST 不刷新**：攻击者即使拿到 CSRF token 持续 POST 也无法无限续期
- **30 分钟窗口**：平衡安全性与体验，足够管理员完成配置操作

### 时区

`_CST = timezone(timedelta(hours=8))`，避免 VPS(UTC) 下 session 过期时间错位 8 小时。

## SSH Key 优先认证（P1 Task-10）

### 问题

`dashboard/helpers.py` 的 VPS 状态查询函数之前只支持密码认证，SSH Key 用户被迫配置 `VPS_SSH_PASS`。

### 修复

```python
# SSH 认证：优先 SSH Key（推荐），向后兼容密码模式
ssh_key_path = os.environ.get("VPS_SSH_KEY", "") or os.environ.get("VPS_SSH_KEY_PATH", "")
if ssh_key_path and os.path.exists(ssh_key_path):
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, key_filename=ssh_key_path, timeout=10)
elif VPS_PASS:
    logger.warning("VPS SSH 使用密码认证，建议配置 VPS_SSH_KEY 环境变量改用 SSH Key")
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
else:
    results["error"] = "无可用 SSH 认证方式（VPS_SSH_KEY 未设置且无密码）"
```

### 环境变量命名统一

| 模块 | 环境变量 | 说明 |
|------|---------|------|
| `core/vps_config.py` | `VPS_SSH_KEY` | 主命名（推荐） |
| `dashboard/helpers.py` | `VPS_SSH_KEY` | 统一命名（v5.31.2 修复） |
| `dashboard/helpers.py` | `VPS_SSH_KEY_PATH` | 向后兼容（不推荐新部署使用） |

`dashboard/helpers.py` 优先读 `VPS_SSH_KEY`，回退 `VPS_SSH_KEY_PATH`，避免破坏旧部署。

## 单元测试

`tests/unit/test_audit_fixes.py::TestVerifyPassword` 覆盖：
- sha256 模式正确/错误密码
- 明文模式正确/错误密码
- 空 stored / 空密码拒绝
- sha256 大写 hex 兼容
- 64 位非 hex 字符串回退明文模式

## 相关文件

- `dashboard/auth.py` — 认证主模块
- `dashboard/helpers.py` — VPS 状态查询
- `core/vps_config.py` — VPS SSH 配置（主命名源）
- `.env.example` — 环境变量模板
- `tests/unit/test_audit_fixes.py` — 单元测试
