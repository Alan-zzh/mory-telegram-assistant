# -*- coding: utf-8 -*-
"""[Codex] 问候播报时间和开关必须读取配置。"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def test_greeting_time_reads_new_config():
    from tasks.support.critical_tasks import _get_greeting_time

    cfg = {"GREETING_CONFIG": {"morning_time": "07:45", "evening_time": "22:30"}}

    assert _get_greeting_time(cfg, "morning") == (7, 45)
    assert _get_greeting_time(cfg, "evening") == (22, 30)
    assert _get_greeting_time(cfg, "afternoon") == (12, 35)


def test_greeting_enabled_compat_keys():
    from tasks.support.critical_tasks import _is_greeting_enabled

    assert _is_greeting_enabled({"AUTO_GREETING": True}, "morning") is True
    assert _is_greeting_enabled({"AUTO_GREETING": False, "AUTO_GOODNIGHT": True}, "evening") is True
    assert _is_greeting_enabled({"GREETING_CONFIG": {"afternoon_enabled": True}}, "afternoon") is True


def test_greeting_window_uses_config_time():
    from tasks.support.critical_tasks import _is_greeting_window

    cfg = {"GREETING_CONFIG": {"afternoon_time": "14:20"}}

    assert _is_greeting_window(datetime(2026, 6, 12, 14, 22), cfg, "afternoon") is True
    assert _is_greeting_window(datetime(2026, 6, 12, 12, 30), cfg, "afternoon") is False
