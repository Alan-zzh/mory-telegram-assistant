# -*- coding: utf-8 -*-
"""
tests/unit/test_convert_keywords.py  ·  v5.14.0

测试扩展后的 convert 模式关键词识别（modules/group_mgr._is_convert_message）
"""
import sys
import os

# 允许从项目根目录导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from modules.group_mgr import _is_convert_message, _CONVERT_KEYWORDS_SUBSTR
from core.keyword_manager import KeywordManager
from core.handlers.ai_reply_handler import (
    _build_contextual_purchase_reply,
    _build_purchase_markup,
    _direct_access_reply,
    _ensure_conversion_cta,
    _is_direct_access_request,
)


def test_original_keywords_still_work():
    """原 v5.0 关键词仍然能识别"""
    assert _is_convert_message("这个多少钱") is True
    assert _is_convert_message("价格怎么算") is True
    assert _is_convert_message("怎么买") is True
    assert _is_convert_message("门槛高吗") is True
    assert _is_convert_message("怎么开通") is True
    assert _is_convert_message("会员") is True
    print("✓ 原 6 个 convert 关键词识别正常")


def test_subscription_keywords():
    """新增订阅类关键词（截图核心场景）"""
    # 截图原句
    assert _is_convert_message("订阅一个月的有多少视频观看？") is True
    assert _is_convert_message("包月多少钱") is True
    assert _is_convert_message("包年的价格") is True
    assert _is_convert_message("月付和年付哪个划算") is True
    assert _is_convert_message("季付有优惠吗") is True
    print("✓ 订阅类关键词（订阅/月付/年付/季付/包月/包年）识别正常")


def test_content_rights_keywords():
    """权益/权限类关键词"""
    assert _is_convert_message("权益有哪些") is True
    assert _is_convert_message("解锁限制") is True
    assert _is_convert_message("购买VIP") is True
    assert _is_convert_message("付费才能看吗") is True
    assert _is_convert_message("充值后能用多久") is True
    print("✓ 权益/权限类关键词识别正常")


def test_join_contact_keywords():
    """怎么加入/联系类关键词"""
    assert _is_convert_message("怎么进群") is True
    assert _is_convert_message("怎么加会员群") is True
    assert _is_convert_message("链接给我") is True
    assert _is_convert_message("群入口在哪") is True
    assert _is_convert_message("自助机器人链接发我") is True
    assert _is_convert_message("怎么联系") is True
    assert _is_convert_message("怎么私聊") is True
    print("✓ 怎么加入/联系类关键词识别正常")


def test_viewing_keywords():
    """想看/能看类关键词"""
    assert _is_convert_message("能看多少") is True
    assert _is_convert_message("能玩几天") is True
    assert _is_convert_message("可以看吗") is True
    assert _is_convert_message("有没有") is True
    print("✓ 观看/想看类关键词识别正常")


def test_non_convert_messages():
    """无关消息不应被误判"""
    assert _is_convert_message("今天天气真好") is False
    assert _is_convert_message("哈哈哈") is False
    assert _is_convert_message("Mory") is False
    assert _is_convert_message("你好") is False
    assert _is_convert_message("") is False
    assert _is_convert_message("不定制了") is False
    assert _is_convert_message("取消订阅") is False
    assert _is_convert_message("暂时不买") is False
    print("✓ 无关消息不会误判 convert")


def test_substr_matching_basic():
    """子串匹配基本测试"""
    assert _is_convert_message("订阅呀订阅") is True
    assert _is_convert_message("我想购买点东西") is True
    assert _is_convert_message("包月了") is True
    assert _is_convert_message("定制舞") is True
    assert _is_convert_message("想定做一个专属视频") is True
    print("✓ 子串匹配正常")


def test_old_runtime_keyword_override_cannot_remove_custom_order_intent():
    manager = KeywordManager({
        "CONVERT_KEYWORDS": {
            "substr": ["价格"],
            "word": [],
        },
    })

    assert manager.is_convert_message("定制舞") is True
    assert manager.is_convert_message("想定做一个视频") is True


def test_word_boundary_matching():
    """全词匹配测试（避免误判）"""
    # "包月嫂" 不应被误判为 convert
    assert _is_convert_message("找个月嫂") is False
    # 但单独的"包月"应识别
    assert _is_convert_message("包月划算吗") is True
    print("✓ 全词匹配边界正确")


def test_direct_access_request_reply():
    """明确要入口时直接给预览群和自助下单，不交给LLM闲聊。"""
    for text in ("链接给我", "怎么加群", "群入口在哪", "自助机器人链接发我"):
        assert _is_direct_access_request(text) is True
    reply = _direct_access_reply(is_priv=False)
    assert "@moryselect" in reply
    assert "@MorychannelBot" in reply


def test_contextual_purchase_reply_skips_preview_and_closes_order():
    for text in (
        "就是这个味",
        "风格可以 挺喜欢这种风格",
        "打港舞 开场穿衣服 卡点变装",
    ):
        reply = _build_contextual_purchase_reply(text)
        assert "@MorychannelBot" in reply
        assert "预览" not in reply
        assert "@moryselect" not in reply.lower()

    markup = _build_purchase_markup()
    assert markup.keyboard[0][0].text == "🛒 自助下单"
    assert markup.keyboard[0][0].url == "https://t.me/MorychannelBot"
    assert _ensure_conversion_cta(
        "这种风格挺适合你。",
        conversion_candidate=True,
    ).endswith("@MorychannelBot 自助下单。")
    assert _ensure_conversion_cta(
        "普通闲聊。",
        conversion_candidate=False,
    ) == "普通闲聊。"


if __name__ == "__main__":
    test_original_keywords_still_work()
    test_subscription_keywords()
    test_content_rights_keywords()
    test_join_contact_keywords()
    test_viewing_keywords()
    test_non_convert_messages()
    test_substr_matching_basic()
    test_word_boundary_matching()
    print("\n🎉 所有 convert 关键词测试通过！")
