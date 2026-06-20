# -*- coding: utf-8 -*-
"""
RBAC 权限校验核心逻辑测试

测试覆盖：
- 路径到权限映射（_infer_permission）
- 豁免路径检查（_is_exempt）
- 角色权限矩阵（ROLE_PERMISSIONS）
- has_permission 函数逻辑
- 写方法过滤
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dashboard.rbac_guard import _infer_permission, _is_exempt, _WRITE_METHODS
from dashboard.audit import ROLE_PERMISSIONS, has_permission


# ──────────────────────────────────────────────────────
# 路径权限映射测试
# ──────────────────────────────────────────────────────

def test_infer_permission_config_path():
    """配置路径推断 config:write 权限"""
    perm = _infer_permission("/config/update")
    assert perm == "config:write"


def test_infer_permission_settings_path():
    """设置路径推断 config:write 权限"""
    perm = _infer_permission("/settings/save")
    assert perm == "config:write"


def test_infer_permission_faq_path():
    """FAQ 路径推断 faq:write 权限"""
    perm = _infer_permission("/faq/create")
    assert perm == "faq:write"


def test_infer_permission_orphan_path():
    """孤儿清理路径推断 orphan:clean 权限"""
    perm = _infer_permission("/orphan/cleanup")
    assert perm == "orphan:clean"


def test_infer_permission_ab_test_path():
    """AB 测试路径推断 ab_test:write 权限"""
    perm = _infer_permission("/ab-test/create")
    assert perm == "ab_test:write"


def test_infer_permission_unknown_path():
    """未知路径默认推断 config:write 权限（最严格）"""
    perm = _infer_permission("/unknown/endpoint")
    assert perm == "config:write"


# ──────────────────────────────────────────────────────
# 豁免路径测试
# ──────────────────────────────────────────────────────

def test_is_exempt_login_path():
    """登录路径被豁免"""
    assert _is_exempt("/login") is True


def test_is_exempt_health_check():
    """健康检查路径被豁免"""
    assert _is_exempt("/api/health") is True


def test_is_exempt_static_resources():
    """静态资源路径被豁免"""
    assert _is_exempt("/static/css/style.css") is True


def test_is_exempt_normal_path_not_exempt():
    """普通路径不被豁免"""
    assert _is_exempt("/config/update") is False


# ──────────────────────────────────────────────────────
# 角色权限矩阵测试
# ──────────────────────────────────────────────────────

def test_admin_has_all_permissions():
    """admin 角色拥有所有权限"""
    admin_perms = ROLE_PERMISSIONS["admin"]
    assert "config:write" in admin_perms
    assert "broadcast:write" in admin_perms
    assert "blacklist:delete" in admin_perms
    assert "faq:write" in admin_perms
    assert "orphan:clean" in admin_perms


def test_operator_has_limited_permissions():
    """operator 角色权限受限（不能改配置）"""
    operator_perms = ROLE_PERMISSIONS["operator"]
    assert "config:write" not in operator_perms
    assert "broadcast:write" in operator_perms
    assert "faq:write" in operator_perms


def test_viewer_has_read_only_permissions():
    """viewer 角色只有只读权限"""
    viewer_perms = ROLE_PERMISSIONS["viewer"]
    assert "config:read" in viewer_perms
    assert "config:write" not in viewer_perms
    assert "broadcast:write" not in viewer_perms


def test_has_permission_admin_can_write_config():
    """admin 可以写配置"""
    assert has_permission("config:write", role="admin", db=None) is True


def test_has_permission_operator_cannot_write_config():
    """operator 不能写配置"""
    assert has_permission("config:write", role="operator", db=None) is False


def test_has_permission_operator_can_write_broadcast():
    """operator 可以写广播"""
    assert has_permission("broadcast:write", role="operator", db=None) is True


def test_has_permission_viewer_cannot_write():
    """viewer 不能执行任何写操作"""
    assert has_permission("broadcast:write", role="viewer", db=None) is False
    assert has_permission("config:write", role="viewer", db=None) is False


def test_has_permission_unknown_role():
    """未知角色没有任何权限"""
    assert has_permission("config:read", role="unknown", db=None) is False


# ──────────────────────────────────────────────────────
# 写方法集合测试
# ──────────────────────────────────────────────────────

def test_write_methods_contains_post():
    """写方法集合包含 POST"""
    assert "POST" in _WRITE_METHODS


def test_write_methods_contains_put():
    """写方法集合包含 PUT"""
    assert "PUT" in _WRITE_METHODS


def test_write_methods_contains_delete():
    """写方法集合包含 DELETE"""
    assert "DELETE" in _WRITE_METHODS


def test_write_methods_contains_patch():
    """写方法集合包含 PATCH"""
    assert "PATCH" in _WRITE_METHODS


def test_write_methods_excludes_get():
    """写方法集合不包含 GET"""
    assert "GET" not in _WRITE_METHODS


def test_write_methods_excludes_head():
    """写方法集合不包含 HEAD"""
    assert "HEAD" not in _WRITE_METHODS
