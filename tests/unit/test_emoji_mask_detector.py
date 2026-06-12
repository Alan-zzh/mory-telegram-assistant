# -*- coding: utf-8 -*-
"""[Codex] emoji 面具检测应复用广告主规则。"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def test_emoji_mask_uses_ad_patterns_for_kanwojian():
    from modules.emoji_mask_detector import detect_emoji_mask

    ok, keyword, pure_text = detect_emoji_mask("看📱我📱简📱jie", {})

    assert ok is True
    assert keyword.startswith("广告正则:")
    assert pure_text == "看我简jie"

