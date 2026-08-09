# -*- coding: utf-8 -*-
"""linked_channel_sync 模块单测：频道联动（点赞/评论转化/置顶取消）。"""
import threading
import time
from datetime import datetime
from types import SimpleNamespace

from modules import linked_channel_sync as mod


def _reset_state():
    mod._pending_comments.clear()
    mod._recent_handled.clear()
    mod._rate_counts.clear()
    for lock_attr in ("_pending_lock", "_handled_lock", "_rate_lock"):
        setattr(mod, lock_attr, threading.Lock())


def _channel_config(**overrides):
    from modules.linked_channel_sync import _DEFAULT_CONFIG

    inner = dict(_DEFAULT_CONFIG)
    inner["enabled"] = True  # 测试默认开启（新功能默认关闭）
    inner.update(overrides)
    return {
        "LINKED_CHANNEL_SYNC_CONFIG": inner,
        "CHANNEL_IDS": [{"id": 100, "name": "主频道"}, 222],
        "BUTTON_STYLE_ENABLED": False,
    }


def _group_msg(origin_msg_id=7, msg_id=50, sender_channel=100, chat_id=-123):
    m = SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type="group"),
        message_id=msg_id,
        sender_chat=SimpleNamespace(id=sender_channel, type="channel") if sender_channel else None,
        forward_origin=None,
    )
    if origin_msg_id and sender_channel:
        m.forward_origin = SimpleNamespace(
            chat=SimpleNamespace(id=sender_channel, type="channel"),
            message_id=origin_msg_id,
        )
    return m


class _Bot:
    def __init__(self):
        self.sent = []
        self.unpinned = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=99)

    def unpin_chat_message(self, chat_id, **kwargs):
        self.unpinned.append((chat_id, kwargs))


def test_channel_post_registers_pending():
    _reset_state()
    bot = _Bot()
    m = SimpleNamespace(chat=SimpleNamespace(id=100), message_id=7)
    cfg = _channel_config(auto_like_enabled=False, auto_comment_enabled=True)
    assert mod.handle_channel_post(bot, m, cfg) is True
    assert (100, 7) in mod._pending_comments
    assert mod._pending_comments[(100, 7)]["consumed"] is False


def test_channel_post_disabled_returns_false():
    _reset_state()
    bot = _Bot()
    m = SimpleNamespace(chat=SimpleNamespace(id=100), message_id=7)
    cfg = _channel_config(enabled=False)
    assert mod.handle_channel_post(bot, m, cfg) is False


def test_group_forward_matches_by_origin_and_comments():
    _reset_state()
    bot = _Bot()
    mod._pending_comments[(100, 7)] = {"ts": time.time(), "consumed": False}
    m = _group_msg(origin_msg_id=7)
    cfg = _channel_config(comment_style="compliment", auto_like_enabled=False)
    assert mod.handle_group_forward(bot, m, cfg) is True
    assert len(bot.sent) == 1
    chat, text, kwargs = bot.sent[0]
    assert chat == -123
    assert kwargs.get("reply_to_message_id") == 50
    assert kwargs.get("reply_markup") is None  # compliment 无按钮


def test_group_forward_unpins_and_consumes():
    _reset_state()
    bot = _Bot()
    mod._pending_comments[(100, 7)] = {"ts": time.time(), "consumed": False}
    m = _group_msg()
    cfg = _channel_config(comment_style="compliment")
    assert mod.handle_group_forward(bot, m, cfg) is True
    assert bot.unpinned == [(-123, {"message_id": 50})]
    assert mod._pending_comments[(100, 7)]["consumed"] is True


def test_group_forward_skips_duplicate_message():
    _reset_state()
    bot = _Bot()
    m = _group_msg()
    cfg = _channel_config(comment_style="compliment")
    assert mod.handle_group_forward(bot, m, cfg) is True
    assert mod.handle_group_forward(bot, m, cfg) is True  # 去重后仍返回 True
    assert len(bot.sent) == 0
    assert len(bot.unpinned) == 1


def test_non_channel_forward_ignored():
    _reset_state()
    bot = _Bot()
    m = SimpleNamespace(
        chat=SimpleNamespace(id=-123, type="group"),
        message_id=50,
        sender_chat=None,
    )
    cfg = _channel_config()
    assert mod.handle_group_forward(bot, m, cfg) is False


def test_rate_limit_blocks_when_hour_exceeded():
    _reset_state()
    from modules.linked_channel_sync import _CST, _load_config
    cfg = _load_config(_channel_config(max_comments_per_hour=1))
    hour_key = datetime.now(_CST).strftime("%Y-%m-%d-%H")
    mod._rate_counts[hour_key] = 2
    assert mod._check_rate(cfg, 100) is False


def test_rate_records_after_comment():
    """限流在 _check_rate 原子预占；失败可 _refund_rate 退回。"""
    _reset_state()
    from modules.linked_channel_sync import _load_config
    cfg = _load_config(_channel_config(max_comments_per_hour=10))
    assert mod._check_rate(cfg, 100) is True
    assert mod._check_rate(cfg, 100) is True
    total = sum(mod._rate_counts.values())
    assert total == 2
    mod._refund_rate()
    assert sum(mod._rate_counts.values()) == 1


def test_convert_comment_has_button():
    _reset_state()
    bot = _Bot()
    mod._pending_comments[(100, 7)] = {"ts": time.time(), "consumed": False}
    m = _group_msg(origin_msg_id=7)
    cfg = _channel_config(comment_style="convert")
    assert mod.handle_group_forward(bot, m, cfg) is True
    assert len(bot.sent) == 1
    _, text, kwargs = bot.sent[0]
    markup = kwargs.get("reply_markup")
    assert markup is not None
    btn = markup.keyboard[0][0]
    assert btn.url  # 转化评论必须带可点击入口
    assert btn.text