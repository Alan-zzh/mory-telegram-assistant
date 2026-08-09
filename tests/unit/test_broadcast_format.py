# -*- coding: utf-8 -*-
"""测试播报富文本排版函数（build_rich_greeting_html）。"""


def test_greeting_html_basic():
    """基础测试：问候卡片 → 正确渲染"""
    from core.broadcast_formatter import build_rich_greeting_html

    result = build_rich_greeting_html("afternoon", "午安呀大家，今天阳光特别好。")
    assert "<b>" in result
    assert "午安" in result