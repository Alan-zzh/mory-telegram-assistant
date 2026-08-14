# -*- coding: utf-8 -*-
"""linked_channel_sync 模块单测：频道联动（点赞/评论转化/置顶取消）。"""
import threading
import time
import inspect
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


def _group_msg(
    origin_msg_id=7,
    msg_id=50,
    sender_channel=100,
    chat_id=-123,
    text="",
    caption="",
):
    m = SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type="group"),
        message_id=msg_id,
        sender_chat=SimpleNamespace(id=sender_channel, type="channel") if sender_channel else None,
        forward_origin=None,
        forward_from_message_id=origin_msg_id or 0,
        text=text,
        caption=caption,
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
        self.sent_photos = []
        self.unpinned = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=99)

    def send_photo(self, chat_id, photo, **kwargs):
        self.sent_photos.append((chat_id, photo, kwargs))
        return SimpleNamespace(message_id=100)

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


def test_trusted_channel_forward_disabled_still_stops_user_pipeline():
    """自有频道即使联动暂时关闭也只能保留，不能落入广告/AI/反频道管线。"""
    _reset_state()
    bot = _Bot()
    m = _group_msg()
    cfg = _channel_config(enabled=False)

    assert mod.handle_group_forward(bot, m, cfg) is True
    assert bot.unpinned == []
    assert bot.sent == []


def test_external_channel_forward_is_not_trusted():
    _reset_state()
    bot = _Bot()
    m = _group_msg(sender_channel=999)

    assert mod.get_trusted_forward_channel_id(m, _channel_config()) == 0
    assert mod.handle_group_forward(bot, m, _channel_config()) is False


def test_anti_channel_never_deletes_trusted_own_channel():
    from modules.anti_channel import check_anti_channel

    class _DeleteBot:
        deleted = []

        def delete_message(self, chat_id, message_id):
            self.deleted.append((chat_id, message_id))

    bot = _DeleteBot()
    m = _group_msg()
    cfg = _channel_config()
    cfg["ANTI_CHANNEL_DEFAULT"] = True
    cfg["ENABLE_MESSAGE_DELETION"] = True

    assert check_anti_channel(bot, m, cfg, db=object()) is False
    assert bot.deleted == []


def test_trusted_media_forward_reuses_linked_channel_gate():
    """视频/图片专用 handler 也必须先取消自有频道转发置顶。"""
    from core.handlers.media_handlers import _handle_trusted_channel_forward

    _reset_state()
    bot = _Bot()
    m = _group_msg()
    ctx = SimpleNamespace(config=_channel_config(auto_comment_enabled=False), db=None)

    assert _handle_trusted_channel_forward(bot, m, ctx) is True
    assert bot.unpinned == [(-123, {"message_id": 50})]


def test_media_ad_path_uses_unified_security_handler_not_invalid_detect_signature():
    from core.handlers import media_handlers

    source = inspect.getsource(media_handlers.register_media_handlers)
    assert "check_ad_detection(dctx)" in source
    assert "detect(ad_text, uid=" not in source


def test_group_forward_skips_duplicate_message():
    _reset_state()
    bot = _Bot()
    m = _group_msg()
    cfg = _channel_config(comment_style="compliment")
    assert mod.handle_group_forward(bot, m, cfg) is True
    assert mod.handle_group_forward(bot, m, cfg) is True  # 去重后仍返回 True
    assert len(bot.sent) == 1
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


def test_group_forward_without_channel_event_still_comments_and_marks_origin_consumed():
    """生产事件顺序：只有群自动转发也必须评论，后到频道事件不得再次打开。"""
    _reset_state()
    bot = _Bot()
    m = _group_msg(origin_msg_id=81, caption="新视频预告，想看完整版可以直接解锁")
    cfg = _channel_config(comment_style="contextual", auto_like_enabled=False)

    assert mod.handle_group_forward(bot, m, cfg) is True
    assert len(bot.sent) == 1
    _, text, kwargs = bot.sent[0]
    assert "这段质感太绝了" in text
    assert kwargs["reply_to_message_id"] == m.message_id
    assert kwargs["reply_markup"].keyboard[0][0].url.endswith("MorychannelBot")
    assert mod._pending_comments[(100, 81)]["consumed"] is True

    channel_post = SimpleNamespace(chat=SimpleNamespace(id=100), message_id=81)
    assert mod.handle_channel_post(bot, channel_post, cfg) is True
    assert mod._pending_comments[(100, 81)]["consumed"] is True


def test_contextual_comment_routes_custom_copy_to_contact_only():
    cfg = mod._load_config(_channel_config(comment_style="contextual"))
    text, target = mod.build_contextual_comment(cfg, "喜欢这套可以把自己的想法发来定制同款")

    assert target == mod.TARGET_CONTACT
    assert "需求发给 Mory" in text
    markup = mod.build_comment_button(target, _channel_config())
    assert len(markup.keyboard) == 1
    assert len(markup.keyboard[0]) == 1
    assert markup.keyboard[0][0].url.endswith("Moryfansbot")


def test_contextual_comment_sends_reviewed_marketing_image_card():
    _reset_state()
    bot = _Bot()
    m = _group_msg(
        origin_msg_id=82,
        caption="这组写真完整版已更新，想继续看可以自助订阅",
    )
    cfg = _channel_config(
        comment_style="contextual",
        comment_media_enabled=True,
        auto_like_enabled=False,
    )

    assert mod.handle_group_forward(bot, m, cfg) is True
    assert bot.sent == []
    assert len(bot.sent_photos) == 1
    chat_id, photo, kwargs = bot.sent_photos[0]
    assert chat_id == -123
    assert "photo_pool_" in photo.file_name
    assert kwargs["reply_to_message_id"] == 50
    assert "这组质感太绝了" in kwargs["caption"]
    assert kwargs["reply_markup"].keyboard[0][0].url.endswith("MorychannelBot")


def test_original_taste_copy_uses_menu_card_and_contact_target():
    _reset_state()
    bot = _Bot()
    m = _group_msg(origin_msg_id=83, caption="原味定制可以私聊说具体需求")
    cfg = _channel_config(comment_style="contextual", comment_media_enabled=True)

    assert mod.handle_group_forward(bot, m, cfg) is True
    _, photo, kwargs = bot.sent_photos[0]
    assert photo.file_name == "original_taste_menu.png"
    assert kwargs["reply_markup"].keyboard[0][0].url.endswith("Moryfansbot")
