# -*- coding: utf-8 -*-
"""深夜劝睡门槛（v5.42.24）回归。

背景暗病：凌晨 0-5 点群里有人问"积分有什么作用吗"，消息经 FAQ 主动承接
进入 P10 主链后被深夜劝睡分支整条替换成"快去睡"，预设/正常回答永远没机会。
门槛规则：劝睡只允许挂在"主动插话"氛围路径上；点名、回复 Bot、非 normal
模式和正经提问必须走正常回答链（后置门禁只降级不换义）。
"""
from core.handlers.ai_reply_handler import (
    _looks_like_question,
    _should_send_late_night_warning,
)


def _gate(**overrides):
    base = dict(
        late_night=True,
        is_group=True,
        is_at=False,
        is_reply=False,
        mode="normal",
        text="哈哈哈",
    )
    base.update(overrides)
    return _should_send_late_night_warning(**base)


def test_late_night_warning_fires_for_idle_group_chat():
    """正常面保留：凌晨群里闲聊（概率插话路径）仍正常劝睡。"""
    assert _gate(text="哈哈哈")
    assert _gate(text="都别卷了")
    assert _gate(text="")


def test_real_question_at_night_must_not_be_replaced_by_sleep_warning():
    """截图暗病回归：正经提问不得被"快去睡"整条替换。"""
    for text in (
        "积分有什么作用吗",
        "签到有什么奖励",
        "这个群是干嘛的",
        "积分怎么获得？",
    ):
        assert _looks_like_question(text), text
        assert not _gate(text=text), text


def test_mention_and_reply_bypass_late_night_warning():
    """凌晨点名或回复 Bot 也必须正常回答，不得劝睡打发。"""
    assert not _gate(is_at=True, text="在吗")
    assert not _gate(is_reply=True, text="继续说说")


def test_non_normal_modes_bypass_late_night_warning():
    """tarot/convert/treehole 等强制回复模式不受劝睡拦截。"""
    for mode in ("tarot", "convert", "treehole", "dream", "feedback", "contact_mory"):
        assert not _gate(mode=mode), mode


def test_private_chat_and_daytime_unaffected():
    """私聊从不劝睡；非深夜窗口不劝睡。"""
    assert not _gate(is_group=False)
    assert not _gate(late_night=False)
