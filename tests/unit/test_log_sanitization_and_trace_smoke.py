# -*- coding: utf-8 -*-
"""v5.38.19 日志脱敏 + daily_report 留痕 smoke 测试。

纯静态源码级断言，不启动 Bot、不连 DB。验证：
1. bot_initializer / config_repo 的动态状态/系统状态日志不再打印明文值
2. daily_report_task 的 get_chat_member_count 回退不再裸 except 吞错
"""
from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_BOT_INIT_PY = _PROJECT_ROOT / "core" / "bot_initializer.py"
_CONFIG_REPO_PY = _PROJECT_ROOT / "core" / "db_repos" / "config_repo.py"
_DAILY_REPORT_PY = _PROJECT_ROOT / "tasks" / "analytics" / "daily_report_task.py"


def test_bot_initializer_dynamic_state_log_sanitized():
    """动态状态加载日志：必须用 <类型(长度)>，不能再用 ={cfg[key]} 明文打印。"""
    src = _BOT_INIT_PY.read_text(encoding="utf-8")
    # 旧明文模式（反例）：绝对不能出现
    bad = re.search(r'logger\.debug\(f[\"\u201c].*动态状态加载.*=\{cfg\[', src)
    assert bad is None, (
        "core/bot_initializer.py 仍有明文 cfg[key] 落入 DEBUG 日志，"
        "请改用 <类型(长度)> 脱敏格式"
    )
    # 新安全模式（正例）：必须至少出现一处
    good = re.search(r'动态状态加载.*=<_safe_placeholder>|动态状态加载.*=<str\(|动态状态加载.*=<None>|动态状态加载.*=<list\(|动态状态加载.*=<dict\(|动态状态加载.*=<int>', src)
    # 更宽松地断言：脱敏辅助变量 _safe 已经被用到了日志行
    uses_safe = "动态状态加载" in src and "{key}=<{_safe}>" in src
    assert uses_safe, "core/bot_initializer.py 动态状态日志未使用 _safe 脱敏占位"


def test_config_repo_system_state_update_log_sanitized():
    """系统状态更新日志：必须用 <类型(长度)>，不能再用 ={value} 明文打印。"""
    src = _CONFIG_REPO_PY.read_text(encoding="utf-8")
    # 旧明文模式（反例）：绝对不能出现
    bad = re.search(r'logger\.debug\(f[\"\u201c].*系统状态更新.*=\{value\}', src)
    assert bad is None, (
        "core/db_repos/config_repo.py 仍有明文 value 落入 DEBUG 日志，"
        "请改用 <类型(长度)> 脱敏格式"
    )
    uses_safe = "系统状态更新" in src and "{key}=<{_safe}>" in src
    assert uses_safe, "core/db_repos/config_repo.py 系统状态日志未使用 _safe 脱敏占位"


def test_daily_report_get_chat_member_count_fallback_has_trace():
    """群人数 API 失败回退：except 必须绑定异常变量 e，并写 logger.debug 留痕。"""
    src = _DAILY_REPORT_PY.read_text(encoding="utf-8")
    # 旧裸 except（反例）：get_chat_member_count 紧邻的 except Exception: 后直接赋值 不能存在
    # 精确上下文匹配：先定位 get_chat_member_count 段
    m = re.search(
        r'get_chat_member_count\(gid\)\s*\n\s*except\s+Exception\s*:\s*\n\s*total_members_group\s*=\s*rm\.db\.get_group_total_members_latest',
        src,
    )
    assert m is None, (
        "tasks/analytics/daily_report_task.py 中 get_chat_member_count "
        "回退仍为裸 except 吞错，缺少 as e + logger.debug 留痕"
    )
    # 新留痕（正例）：该段必须出现 logger.debug 和 e 引用
    trace_exists = "群人数API失败，回退DB" in src and "gid={gid} err={e}" in src
    assert trace_exists, "群人数 API 失败日志未包含 gid/err 留痕字段"


def test_sanitization_branches_cover_all_primitive_types():
    """脱敏分支至少覆盖 None / str / 容器 / 其他标量 四类（bot_initializer + config_repo 均如此）。"""
    for label, path in (
        ("bot_initializer", _BOT_INIT_PY),
        ("config_repo", _CONFIG_REPO_PY),
    ):
        src = path.read_text(encoding="utf-8")
        has_none = "_v is None" in src
        has_str = 'isinstance(_v, str)' in src
        has_container = '(list, dict, tuple, set)' in src
        has_else = "_safe = type(_v).__name__" in src
        assert has_none and has_str and has_container and has_else, (
            f"{label} 脱敏分支不全：需要覆盖 None/str/容器/其他 四类"
        )
