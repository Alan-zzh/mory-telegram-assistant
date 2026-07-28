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
    _align_conversion_reply,
    _build_contextual_purchase_reply,
    _build_normal_hint,
    _build_purchase_markup,
    _build_preview_markup,
    _direct_access_reply,
    _is_direct_access_request,
    _should_offer_proactive_preview,
)
from core.growth_optimizer import resolve_conversion_target


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
    """入口回复按意图只给一个目标，不把预览和下单混在一起。"""
    for text in (
        "链接给我",
        "怎么加群",
        "群入口在哪",
        "自助机器人链接发我",
        "怎么订阅",
        "如何订阅",
        "订阅链接发我",
        "我想订阅",
    ):
        assert _is_direct_access_request(text) is True
    preview_reply = _direct_access_reply("链接给我", is_priv=False)
    assert "@moryselect" in preview_reply
    assert "@MorychannelBot" not in preview_reply
    order_reply = _direct_access_reply("自助机器人链接发我", is_priv=True)
    assert "MorychannelBot" in order_reply
    assert "moryselect" not in order_reply.lower()

    screenshot_reply = _direct_access_reply(
        "怎么订阅",
        is_priv=False,
        history=[{
            "role": "assistant",
            "content": "全套预览在 @moryselect，你先看看。",
        }],
    )
    assert "不只是想看预览" in screenshot_reply
    assert "我不催你" in screenshot_reply
    assert "@MorychannelBot" in screenshot_reply
    assert "@moryselect" not in screenshot_reply.lower()


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
        assert "可以做" not in reply
        assert "把要求填进去" not in reply

    followup = _build_contextual_purchase_reply(
        "就是这个味",
        include_cta=False,
    )
    assert followup == "对，就是这个方向，风格对上了。"
    assert "MorychannelBot" not in followup

    markup = _build_purchase_markup()
    assert markup.keyboard[0][0].text == "🛒 自助下单"
    assert markup.keyboard[0][0].url == "https://t.me/MorychannelBot"
    assert "@MorychannelBot" in _align_conversion_reply(
        "这种风格挺适合你。",
        conversion_target="subscribe",
        conversion_reason="explicit_custom_order",
    )
    assert _align_conversion_reply(
        "普通闲聊。",
        conversion_target="none",
        conversion_reason="no_conversion_signal",
    ) == "普通闲聊。"


def test_rejection_variants_stop_conversion_and_model_claims_are_removed():
    from core.growth_optimizer import resolve_conversion_target
    from core.handlers.ai_reply_handler import _sanitize_unverified_sales_claims
    from core.keyword_manager import is_convert_rejection_message

    for text in ("算了不用了", "先算了", "暂时不用", "不用了谢谢"):
        assert is_convert_rejection_message(text) is True
        target, reason = resolve_conversion_target(text, [], mode="convert")
        assert (target, reason) == ("none", "user_opt_out")

    cleaned = _sanitize_unverified_sales_claims(
        "具体的群里不太方便细说。至臻精选里都是4K原档和独家动态。"
    )
    assert cleaned == "具体的群里不太方便细说。"
    assert "4K" not in cleaned
    assert "独家" not in cleaned
    all_removed = _sanitize_unverified_sales_claims(
        "至臻精选里都是4K原档和独家动态。"
    )
    assert all_removed == ""
    assert _align_conversion_reply(
        all_removed,
        conversion_target="preview",
        conversion_reason="preview_or_objection",
    ) == "想先了解的话去 @moryselect 看预览，合不合适你自己判断。"


def test_private_sales_reply_has_no_button_and_group_has_only_one_target():
    from core.handlers.ai_reply_handler import (
        _build_sales_reply_markup,
        _recent_order_cta_sent,
    )

    assert _build_sales_reply_markup(
        is_priv=True,
        needs_handoff=False,
        conversion_target="subscribe",
    ) is None

    group_markup = _build_sales_reply_markup(
        is_priv=False,
        needs_handoff=False,
        conversion_target="subscribe",
    )
    assert len(group_markup.keyboard) == 1
    assert [button.text for button in group_markup.keyboard[0]] == ["🛒 自助下单"]
    assert _recent_order_cta_sent([
        {"role": "assistant", "content": "直接去 @MorychannelBot 自助下单。"},
        {"role": "user", "content": "就是这个味"},
    ])

    preview_markup = _build_preview_markup()
    assert len(preview_markup.keyboard) == 1
    assert preview_markup.keyboard[0][0].url == "https://t.me/moryselect"

    private_fallback = _align_conversion_reply(
        "预览：https://t.me/moryselect",
        conversion_target="preview",
        conversion_reason="preview_or_objection",
    )
    assert private_fallback.lower().count("moryselect") == 1


def test_conversion_target_matrix_keeps_funnel_order_and_context():
    assert resolve_conversion_target("定制舞是什么？介绍一下", mode="convert") == (
        "none", "custom_information_only"
    )
    assert resolve_conversion_target("订阅一个月有多少视频", mode="convert")[0] == "preview"
    assert resolve_conversion_target("价格和权益有什么区别", mode="convert")[0] == "preview"
    assert resolve_conversion_target("我要下单", mode="convert")[0] == "subscribe"
    for text in (
        "怎么订阅",
        "如何订阅",
        "在哪订阅",
        "我要订阅",
        "想订阅",
        "订阅入口发我",
        "帮我开通",
    ):
        assert resolve_conversion_target(text, mode="convert") == (
            "subscribe",
            "explicit_purchase",
        )
    assert resolve_conversion_target("定制舞", mode="convert")[0] == "subscribe"
    assert resolve_conversion_target("我想定制一段暗黑港风视频", mode="convert")[0] == "subscribe"
    assert resolve_conversion_target("不定制了", mode="convert")[0] == "none"

    history = [
        {"role": "user", "content": "定制舞"},
        {"role": "assistant", "content": "去 @MorychannelBot 看当前选项。"},
    ]
    assert resolve_conversion_target("就是这个味", history, mode="convert") == (
        "none", "recent_order_cta_suppressed"
    )
    reply = _align_conversion_reply(
        "对，这种风格很搭。再去 @MorychannelBot 下单吧。",
        conversion_target="none",
        conversion_reason="recent_order_cta_suppressed",
    )
    assert "MorychannelBot" not in reply


def test_normal_chat_does_not_hard_sell_by_round_count(monkeypatch):
    hint, _ = _build_normal_hint(6, proactive_preview=False)
    assert "@MorychannelBot" not in hint
    assert "@moryselect" not in hint

    monkeypatch.setattr("core.handlers.ai_reply_handler.random.randint", lambda *_: 100)
    assert not _should_offer_proactive_preview(
        mode="normal",
        conv_count=6,
        history=[],
        text="今天忙完了吗",
    )
    monkeypatch.setattr("core.handlers.ai_reply_handler.random.randint", lambda *_: 1)
    assert _should_offer_proactive_preview(
        mode="normal",
        conv_count=4,
        history=[],
        text="今天忙完了吗",
    )
    assert not _should_offer_proactive_preview(
        mode="normal",
        conv_count=4,
        history=[{"role": "assistant", "content": "先看 @moryselect"}],
        text="继续聊",
    )


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
