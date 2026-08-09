# -*- coding: utf-8 -*-
"""v5.18.0 适配模块单元测试"""
import json
import unittest
from unittest.mock import MagicMock

# 测试 core/profile_learner
from core.profile_learner import (
    detect_interests,
    is_vip_user,
    is_high_value_user,
    calculate_level,
    get_user_profile_summary,
    should_apply_personalization,
    ProfileLearner,
)


class TestProfileLearner(unittest.TestCase):
    """用户画像学习器测试。"""

    def test_detect_interests_tarot(self):
        """检测塔罗兴趣。"""
        self.assertIn("tarot", detect_interests("帮我看看塔罗牌"))
        self.assertIn("tarot", detect_interests("I want a tarot reading"))

    def test_detect_interests_treehole(self):
        """检测树洞兴趣。"""
        self.assertIn("treehole", detect_interests("心情不好，想哭"))
        self.assertIn("treehole", detect_interests("最近压力很大，焦虑"))

    def test_detect_interests_shopping(self):
        """检测购物兴趣。"""
        self.assertIn("shopping", detect_interests("多少钱？"))
        self.assertIn("shopping", detect_interests("我想订阅至臻全享"))

    def test_detect_interests_empty(self):
        """空文本返回空列表。"""
        self.assertEqual(detect_interests(""), [])
        self.assertEqual(detect_interests(None), [])

    def test_detect_interests_multiple(self):
        """检测多个兴趣。"""
        interests = detect_interests("我想看塔罗，最近心情不好")
        self.assertIn("tarot", interests)
        self.assertIn("treehole", interests)

    def test_is_vip_user_by_level(self):
        """等级 >= 5 视为 VIP。"""
        self.assertTrue(is_vip_user("", 5))
        self.assertTrue(is_vip_user("", 10))
        self.assertFalse(is_vip_user("", 3))

    def test_is_vip_user_by_keyword(self):
        """关键词触发 VIP。"""
        self.assertTrue(is_vip_user("我想包年订阅", 0))
        self.assertTrue(is_vip_user("999 至臻全享", 0))
        self.assertFalse(is_vip_user("随便看看", 0))

    def test_is_high_value_user(self):
        """高价值用户检测。"""
        self.assertTrue(is_high_value_user("续费再来一份"))
        self.assertTrue(is_high_value_user("", ["high_value"]))
        self.assertFalse(is_high_value_user("随便看看"))

    def test_calculate_level(self):
        """等级计算。"""
        self.assertEqual(calculate_level(0), 0)
        self.assertEqual(calculate_level(15), 1)
        self.assertEqual(calculate_level(100), 10)
        self.assertEqual(calculate_level(50, days_active=60), 7)

    def test_profile_learner_disabled(self):
        """默认关闭时不学习。"""
        db = MagicMock()
        learner = ProfileLearner(db, config={"USER_PROFILE_ENABLED": False})
        result = learner.learn_from_message(123, "我想看塔罗")
        self.assertIsNone(result)
        db.upsert_user_profile.assert_not_called()

    def test_profile_learner_enabled(self):
        """开启时学习画像。"""
        db = MagicMock()
        db.get_user_persona_profile = MagicMock(return_value={
            "user_id": 123, "tags": [], "level": 0, "interests": [], "conversation_rounds": 0,
        })
        learner = ProfileLearner(db, config={"USER_PROFILE_ENABLED": True})
        result = learner.learn_from_message(123, "帮我看看塔罗")
        self.assertIsNotNone(result)
        self.assertIn("tarot", result["interests"])
        db.upsert_user_profile.assert_called_once()

    def test_get_user_profile_summary(self):
        """画像摘要。"""
        profile = {"tags": ["vip", "active"], "level": 6, "interests": ["tarot"]}
        summary = get_user_profile_summary(profile)
        self.assertTrue(summary["is_vip"])
        self.assertTrue(summary["is_active"])
        self.assertEqual(summary["level"], 6)
        self.assertIn("tarot", summary["interests"])

    def test_get_user_profile_summary_none(self):
        """无画像返回默认。"""
        summary = get_user_profile_summary(None)
        self.assertFalse(summary["is_vip"])
        self.assertEqual(summary["level"], 0)
        self.assertEqual(summary["interests"], [])

    def test_should_apply_personalization(self):
        """个性化判断。"""
        self.assertFalse(should_apply_personalization(None))
        self.assertFalse(should_apply_personalization({}))
        self.assertTrue(should_apply_personalization({"tags": ["vip"]}))
        self.assertTrue(should_apply_personalization({"interests": ["tarot"]}))
        self.assertTrue(should_apply_personalization({"level": 3}))


# 测试 core/broadcast_formatter v4.0 user_profile
class TestBroadcastFormatterUserProfile(unittest.TestCase):
    """测试 v4.0 用户画像个性化富文本。"""

    def test_vip_user_title(self):
        """VIP 画像只做克制的视觉变化，不暴露机械身份标签。"""
        from core.broadcast_formatter import build_rich_broadcast_html
        result = build_rich_broadcast_html(
            title="晚安",
            body="做个好梦",
            period="night",
            user_profile={"tags": ["vip"], "level": 5, "interests": []},
        )
        self.assertIn("✨", result)
        self.assertNotIn("VIP专属", result)
        self.assertNotIn("精选推荐", result)

    def test_high_value_user_title(self):
        """高等级画像沿用克制视觉提示，不恢复已删除的营销标签。"""
        from core.broadcast_formatter import build_rich_broadcast_html
        result = build_rich_broadcast_html(
            title="晚安",
            body="做个好梦",
            period="night",
            user_profile={"tags": [], "level": 6, "interests": []},
        )
        self.assertIn("✨", result)
        self.assertNotIn("VIP专属", result)
        self.assertNotIn("精选推荐", result)

    def test_tarot_user_interest(self):
        """塔罗兴趣用户显示塔罗 emoji。"""
        from core.broadcast_formatter import build_rich_broadcast_html
        result = build_rich_broadcast_html(
            title="晚安",
            body="做个好梦",
            period="night",
            user_profile={"tags": [], "level": 0, "interests": ["tarot"]},
        )
        self.assertIn("🔮", result)

    def test_no_profile_default(self):
        """无画像时使用默认渲染。"""
        from core.broadcast_formatter import build_rich_broadcast_html
        result = build_rich_broadcast_html(
            title="默认标题",
            body="默认内容",
            period="morning",
            user_profile=None,
        )
        # 不应包含个性化标识
        self.assertNotIn("VIP专属", result)
        self.assertNotIn("精选推荐", result)


# 测试 core/telebot_compat 彩色按钮
class TestColoredButton(unittest.TestCase):
    """测试彩色按钮工具函数。"""

    def test_create_colored_button_callback(self):
        """创建 callback 按钮。"""
        from core.telebot_compat import create_colored_button
        btn = create_colored_button(text="购买", callback_data="buy", style="success")
        self.assertEqual(btn.text, "购买")
        self.assertEqual(btn.callback_data, "buy")

    def test_create_colored_button_url(self):
        """创建 url 按钮。"""
        from core.telebot_compat import create_colored_button
        btn = create_colored_button(text="访问", url="https://t.me/MorychannelBot")
        self.assertEqual(btn.text, "访问")
        self.assertEqual(btn.url, "https://t.me/MorychannelBot")

    def test_create_colored_markup(self):
        """创建彩色按钮布局。"""
        from core.telebot_compat import create_colored_markup
        markup = create_colored_markup([
            [{"text": "购买", "callback_data": "buy", "style": "success"}],
            [{"text": "取消", "callback_data": "cancel", "style": "danger"}],
        ])
        # 验证 markup 存在
        self.assertIsNotNone(markup)

    def test_apply_button_style_from_config_disabled(self):
        """关闭时不应用样式。"""
        from core.telebot_compat import apply_button_style_from_config
        from telebot import types
        btn = types.InlineKeyboardButton(text="测试", callback_data="test")
        result = apply_button_style_from_config(btn, "buy", {"BUTTON_STYLE_ENABLED": False})
        self.assertEqual(result.text, "测试")


if __name__ == "__main__":
    unittest.main()
