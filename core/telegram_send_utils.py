# -*- coding: utf-8 -*-
"""
Telegram 发送工具箱（v5.41.0 自 telebot_compat.py 改名：
除兼容补丁外，本模块还承载富文本/彩色按钮/HTML 转换/poll 与 checklists
等 raw API 兜底，原名"compat"名不符实）。

[Codex] pyTelegramBotAPI 兼容补丁。

当前依赖版本的 telebot.types.User 会接收 **kwargs 但不保存，导致
Telegram Bot API 新增字段（如 emoji_status_custom_emoji_id）在解析时丢失。

另外，Telegram Bot API 在近几个版本里持续给消息接口增加新参数；
但当前 pyTelegramBotAPI 4.16.1 还没有完整暴露全部签名。
这里提供一层“薄兼容”：
1. 保留 User 未知字段
2. 对 send_message / send_photo 缺失的新参数走原始 API 请求兜底
"""

import json
import logging
import os
import time
import traceback


class _TelegramAttrMapping(dict):
    """兼容 Telegram 新对象：同时支持 obj.key 与 obj["key"] 读取。"""

    __getattr__ = dict.get


DEFAULT_ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "message_reaction",
    "message_reaction_count",
    "callback_query",
    "chat_member",
    "my_chat_member",
    "chat_join_request",
    "poll",
    "poll_answer",
    "chat_boost",
    "removed_chat_boost",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
    "guest_message",
    "purchased_paid_media",
    "managed_bot",
]


class TelegramPollingExceptionHandler:
    """只接管 getUpdates 的可恢复网络异常，避免轮询风暴和重复堆栈。

    sendMessage 等业务发送异常必须继续抛给原调用方，不能被这里吞掉。
    """

    _RECOVERABLE_STATUS = {500, 502, 503, 504}
    _BACKOFF_SECONDS = (1, 2, 4, 8, 15)

    def __init__(self, sleep_func=None, warning_func=None, monotonic_func=None):
        self._sleep = sleep_func or time.sleep
        self._warning = warning_func or logging.getLogger(
            "telegram.polling"
        ).warning
        self._monotonic = monotonic_func or time.monotonic
        self._last_error_at = 0.0
        self._consecutive = 0

    @staticmethod
    def _is_get_updates_exception(exception: Exception) -> bool:
        function_name = str(getattr(exception, "function_name", "") or "").lower()
        if function_name == "getupdates":
            return True
        return any(
            frame.name in {"__retrieve_updates", "get_updates"}
            for frame in traceback.extract_tb(exception.__traceback__)
        )

    @classmethod
    def _is_recoverable(cls, exception: Exception) -> bool:
        error_code = getattr(exception, "error_code", None)
        if error_code in cls._RECOVERABLE_STATUS:
            return True
        try:
            from requests.exceptions import ConnectionError, Timeout
            return isinstance(exception, (ConnectionError, Timeout))
        except ImportError:
            return isinstance(exception, TimeoutError)

    def handle(self, exception: Exception) -> bool:
        if not self._is_get_updates_exception(exception) or not self._is_recoverable(exception):
            return False

        now = self._monotonic()
        if now - self._last_error_at > 60:
            self._consecutive = 1
        else:
            self._consecutive += 1
        self._last_error_at = now

        delay = self._BACKOFF_SECONDS[
            min(self._consecutive - 1, len(self._BACKOFF_SECONDS) - 1)
        ]
        error_code = getattr(exception, "error_code", None)
        error_name = f"HTTP {error_code}" if error_code else type(exception).__name__
        if self._consecutive in {1, 3, 6}:
            self._warning(
                f"Telegram轮询暂不可用（{error_name}，连续{self._consecutive}次），"
                f"{delay}秒后重试；服务保持运行"
            )
        self._sleep(delay)
        return True


def get_allowed_updates(config: dict | None = None):
    """读取轮询更新类型，默认打开项目已有处理器和 Telegram 10.x 新事件。"""
    cfg = config or {}
    updates = cfg.get("TELEGRAM_ALLOWED_UPDATES")
    if updates == "all":
        return None
    if isinstance(updates, list) and updates:
        configured = [str(item) for item in updates if str(item).strip()]
        return list(dict.fromkeys(configured + DEFAULT_ALLOWED_UPDATES))
    return list(DEFAULT_ALLOWED_UPDATES)


def _serialize_value(value):
    """把 TeleBot 对象安全转成 Bot API 可接受的参数。"""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return to_json()
    return value


def _make_raw_request(bot, method_name: str, params: dict, files=None):
    """当 SDK 还没跟上官方参数时，直接调用 Bot API。"""
    from telebot import apihelper, types

    result = _make_raw_result(bot, method_name, params, files=files)
    return types.Message.de_json(result)


def _make_raw_result(bot, method_name: str, params: dict, files=None):
    """调用原始 Bot API，返回未二次解析的结果。"""
    from telebot import apihelper

    clean_params = {}
    for key, value in params.items():
        if value is None:
            continue
        clean_params[key] = _serialize_value(value)

    return apihelper._make_request(
        bot.token,
        method_name,
        method="post",
        params=clean_params,
        files=files,
    )


def preserve_user_extra_fields():
    """让 telebot.types.User 保存 Bot API 新增字段。"""
    try:
        from telebot import types
    except Exception:
        return False

    user_cls = getattr(types, "User", None)
    if not user_cls or getattr(user_cls, "_mory_preserve_extra_fields", False):
        return False

    original_init = user_cls.__init__

    def patched_init(self, *args, **kwargs):
        extra = dict(kwargs)
        original_init(self, *args, **kwargs)
        for key, value in extra.items():
            if not hasattr(self, key):
                setattr(self, key, value)

    user_cls.__init__ = patched_init
    user_cls._mory_preserve_extra_fields = True
    return True


def preserve_message_extra_fields():
    """让 telebot.types.Message 保存 Bot API 10.x 新消息字段。"""
    try:
        from telebot import types
    except Exception:
        return False

    message_cls = getattr(types, "Message", None)
    if not message_cls or getattr(message_cls, "_mory_preserve_extra_fields", False):
        return False

    original_de_json = message_cls.de_json

    @classmethod
    def patched_de_json(cls, json_string):
        message = original_de_json(json_string)
        if message is None:
            return None

        obj = cls.check_json(json_string, dict_copy=False)
        passthrough_fields = (
            "direct_messages_topic",
            "sender_business_bot",
            "sender_tag",
            "rich_message",
            "business_connection_id",
            "reply_to_checklist_task_id",
            "reply_to_poll_option_id",
            "guest_bot_caller_user",
            "guest_bot_caller_chat",
            "guest_query_id",
            "suggested_post_info",
            "effect_id",
            "show_caption_above_media",
            "live_photo",
            "paid_media",
            "checklist",
            "chat_owner_left",
            "chat_owner_changed",
            "refunded_payment",
            "gift",
            "unique_gift",
            "gift_upgrade_sent",
            "chat_background_set",
            "checklist_tasks_done",
            "checklist_tasks_added",
            "direct_message_price_changed",
            "managed_bot_created",
            "paid_message_price_changed",
            "poll_option_added",
            "poll_option_deleted",
            "suggested_post_approved",
            "suggested_post_approval_failed",
            "suggested_post_declined",
            "suggested_post_paid",
            "suggested_post_refunded",
        )
        for key in passthrough_fields:
            if key in obj and not hasattr(message, key):
                setattr(message, key, obj.get(key))

        # pyTelegramBotAPI 4.34 还没有 RichMessage 类型，会把 Bot API 10
        # 的 rich_message 原样保留成 dict；较新版本则会返回对象。统一成
        # 可属性访问且仍兼容字典下标的薄包装，避免运行环境版本差异。
        rich_message = getattr(message, "rich_message", None)
        if isinstance(rich_message, dict):
            message.rich_message = _TelegramAttrMapping(rich_message)

        if getattr(message, "content_type", None) is None:
            if "rich_message" in obj:
                message.content_type = "rich_message"
            elif "live_photo" in obj:
                message.content_type = "live_photo"
        return message

    message_cls.de_json = patched_de_json
    message_cls._mory_preserve_extra_fields = True
    return True


def preserve_update_business_fields():
    """保留新 Update 字段，并让 Business 消息进入现有消息链路。"""
    try:
        from telebot import types
    except Exception:
        return False

    update_cls = getattr(types, "Update", None)
    if not update_cls or getattr(update_cls, "_mory_preserve_business_fields", False):
        return False

    original_de_json = update_cls.de_json

    @classmethod
    def patched_de_json(cls, json_string):
        update = original_de_json(json_string)
        if update is None:
            return None

        obj = cls.check_json(json_string, dict_copy=False)

        business_connection = obj.get("business_connection")
        if business_connection is not None:
            setattr(update, "business_connection", business_connection)

        business_message = obj.get("business_message")
        if business_message is not None:
            msg = types.Message.de_json(business_message)
            setattr(update, "business_message", msg)
            if msg is not None:
                setattr(msg, "_mory_update_type", "business_message")
                if update.message is None:
                    update.message = msg

        edited_business_message = obj.get("edited_business_message")
        if edited_business_message is not None:
            msg = types.Message.de_json(edited_business_message)
            setattr(update, "edited_business_message", msg)
            if msg is not None:
                setattr(msg, "_mory_update_type", "edited_business_message")
                if update.edited_message is None:
                    update.edited_message = msg

        deleted_business_messages = obj.get("deleted_business_messages")
        if deleted_business_messages is not None:
            setattr(update, "deleted_business_messages", deleted_business_messages)

        guest_message = obj.get("guest_message")
        if guest_message is not None:
            setattr(update, "guest_message", types.Message.de_json(guest_message))

        for key in ("purchased_paid_media", "managed_bot"):
            if key in obj:
                setattr(update, key, obj.get(key))

        return update

    update_cls.de_json = patched_de_json
    update_cls._mory_preserve_business_fields = True
    return True


def patch_telebot_business_update_dispatch():
    """把 SDK 暂未分发的新 Update 类型交给项目钩子处理。"""
    try:
        from telebot import TeleBot
    except Exception:
        return False

    if getattr(TeleBot, "_mory_business_update_dispatch", False):
        return False

    original_process = TeleBot.process_new_updates
    logger = logging.getLogger("telegram_send_utils")

    def patched_process_new_updates(self, updates):
        hook = getattr(self, "_mory_business_update_handler", None)
        if callable(hook):
            for update in updates or []:
                has_business_event = any(
                    getattr(update, field, None) is not None
                    for field in (
                        "business_connection",
                        "deleted_business_messages",
                        "guest_message",
                        "purchased_paid_media",
                        "managed_bot",
                    )
                )
                if not has_business_event:
                    continue
                try:
                    hook(update)
                except Exception as e:
                    logger.debug(f"Business update 钩子异常（已忽略）: {e}")
        return original_process(self, updates)

    TeleBot.process_new_updates = patched_process_new_updates
    TeleBot._mory_business_update_dispatch = True
    return True


def preserve_telegram_extra_fields():
    """统一安装 Telegram 新字段兼容补丁。"""
    changed_user = preserve_user_extra_fields()
    changed_message = preserve_message_extra_fields()
    changed_update = preserve_update_business_fields()
    changed_dispatch = patch_telebot_business_update_dispatch()
    return changed_user or changed_message or changed_update or changed_dispatch



def _normalize_link_preview_options(kwargs: dict) -> bool:
    """[v5.32] 把 link_preview_options dict 转成 LinkPreviewOptions 对象。

    pyTelegramBotAPI 4.34.0 期望对象而非 dict，传 dict 会报
    `'dict' object has no attribute 'is_disabled'`。SDK 不支持时返回 False，
    调用方应走 raw API 兜底。
    """
    lpo = kwargs.get("link_preview_options")
    if lpo is None or isinstance(lpo, str):
        return True
    if not isinstance(lpo, dict):
        return True
    try:
        from telebot.types import LinkPreviewOptions
        kwargs["link_preview_options"] = LinkPreviewOptions(**lpo)
        return True
    except Exception:
        return False


def send_message_compat(bot, chat_id, text, **kwargs):
    """兼容 send_message 新参数。"""
    # [v5.32] 修复 link_preview_options dict 不兼容 bug
    if "link_preview_options" in kwargs and not _normalize_link_preview_options(kwargs):
        # SDK 不支持 LinkPreviewOptions，走 raw API
        params = {"chat_id": chat_id, "text": text, **kwargs}
        return _make_raw_request(bot, "sendMessage", params)

    unsupported_keys = (
        "allow_paid_broadcast",
        "message_effect_id",
        "suggested_post_parameters",
        "direct_messages_topic_id",
    )
    extra = {key: kwargs.pop(key) for key in unsupported_keys if key in kwargs}
    if not any(value is not None for value in extra.values()):
        return bot.send_message(chat_id, text, **kwargs)

    params = {"chat_id": chat_id, "text": text, **kwargs, **extra}
    return _make_raw_request(bot, "sendMessage", params)


def _normalize_photo_input(photo):
    """把本地照片路径字符串转成 InputFile，避免被 SDK 当作 file_id/URL 而 400。

    - 指向存在的本地文件的 str → InputFile 二进制流（图片卡等本地生成图）
    - file_id / URL / 文件对象 / BytesIO → 原样返回
    """
    if isinstance(photo, str):
        if os.path.isfile(photo):
            try:
                from telebot.types import InputFile

                return InputFile(photo)
            except Exception:
                with open(photo, "rb") as f:
                    return f.read()
        return photo
    return photo


def send_photo_compat(bot, chat_id, photo, **kwargs):
    """兼容 send_photo 新参数；本地文件路径自动转 InputFile。"""
    photo = _normalize_photo_input(photo)
    unsupported_keys = (
        "show_caption_above_media",
        "allow_paid_broadcast",
        "message_effect_id",
        "direct_messages_topic_id",
    )
    extra = {key: kwargs.pop(key) for key in unsupported_keys if key in kwargs}
    if not any(value is not None for value in extra.values()):
        return bot.send_photo(chat_id, photo, **kwargs)

    # 内容为本地文件或 file-like 时，SDK 原生发送无法携带 unsupported 新参数，
    # 退回到 raw request；InputFile/BytesIO 仍交给 SDK 原生处理（可上传）。
    if not isinstance(photo, str):
        return bot.send_photo(chat_id, photo, **kwargs)

    params = {"chat_id": chat_id, "photo": photo, **kwargs, **extra}
    return _make_raw_request(bot, "sendPhoto", params)


def send_rich_message_compat(bot, chat_id, rich_message, **kwargs):
    """兼容 Telegram Bot API 10.1 Rich Messages。

    rich_message 可以是：
    1. str - HTML 格式字符串，自动包装为 InputRichMessage 对象 {"html": "..."}
    2. dict - 已是 InputRichMessage 对象（如 {"html": "..."} 或 {"text": {...}}），直接使用
    3. list - 旧版组件列表格式（已弃用，会尝试转为 HTML）

    官方期望 rich_message 参数是 InputRichMessage 对象（如 {"html": "<b>标题</b>"}），
    而非组件列表。早期版本错误地传入 List[Dict] 导致 400 "object expected as rich message"。
    """
    # str → 包装成 InputRichMessage 对象
    if isinstance(rich_message, str):
        rich_message = {"html": rich_message}
    # list → 旧版组件格式，尝试拼接为 HTML 字符串后包装
    elif isinstance(rich_message, list):
        html_parts = []
        for comp in rich_message:
            if not isinstance(comp, dict):
                continue
            ctype = comp.get("type", "text")
            ctext = comp.get("text", "")
            if ctype == "bold":
                html_parts.append(f"<b>{ctext}</b>")
            elif ctype == "italic":
                html_parts.append(f"<i>{ctext}</i>")
            elif ctype == "underline":
                html_parts.append(f"<u>{ctext}</u>")
            elif ctype == "strikethrough":
                html_parts.append(f"<s>{ctext}</s>")
            elif ctype == "spoiler":
                html_parts.append(f"<tg-spoiler>{ctext}</tg-spoiler>")
            elif ctype == "code":
                html_parts.append(f"<code>{ctext}</code>")
            elif ctype == "pre":
                html_parts.append(f"<pre>{ctext}</pre>")
            elif ctype == "blockquote":
                html_parts.append(f"<blockquote>{ctext}</blockquote>")
            elif ctype == "text_link":
                url = comp.get("url", "")
                html_parts.append(f'<a href="{url}">{ctext}</a>')
            else:
                html_parts.append(str(ctext))
        rich_message = {"html": "".join(html_parts)}
    # dict → 直接使用（兼容 {"html": "..."} 和 {"text": {...}} 两种格式）

    params = {"chat_id": chat_id, "rich_message": rich_message, **kwargs}
    return _make_raw_request(bot, "sendRichMessage", params)


# ── Ephemeral Messages 兼容层（Bot API 10.2 引入 / 10.3 参数重构）───────────
# 群内私密消息：只对指定用户可见，用于敏感通知（如警告/解封结果）。
# SDK 4.34.0 未封装，走 raw API 兜底。
#
# [Bot API 10.3, 2026-08-24] 官方把 sendMessage 系列的 receiver_user_id /
# callback_query_id 平铺参数替换为 ephemeral_message_parameters 对象
# （EphemeralMessageParameters，含 replace_callback_query_message 等新字段）。
# 服务端切换语义后平铺参数会 400。此处优先发送 10.3 对象格式；
# 服务端仍为 10.2 语义时自动回退平铺格式并进程内记忆，双向兼容。

_EPHEMERAL_PARAM_MODE = {"mode": "auto"}  # auto → 协商中；v3 → 对象格式；legacy → 平铺格式


def _ephemeral_identity(receiver_user_id=None, callback_query_id=None):
    """提取接收者身份键值；两者都缺省时返回空（无需身份参数）。"""
    identity = {}
    if receiver_user_id is not None:
        identity["receiver_user_id"] = receiver_user_id
    if callback_query_id is not None:
        identity["callback_query_id"] = callback_query_id
    return identity


def _send_ephemeral_raw(bot, method_name: str, base_params: dict, identity: dict):
    """按协商模式调用 ephemeral 原始 API。

    - auto：先试 10.3 对象格式，遇 400 参数拒绝则回退 10.2 平铺格式并记忆；
      回退后仍失败说明是真实参数错误，抛出第二次的原始异常。
    - v3/legacy：直接用已协商格式，不再重复探测。
    """
    if identity and _EPHEMERAL_PARAM_MODE["mode"] in {"auto", "v3"}:
        try:
            result = _make_raw_result(
                bot, method_name, {**base_params, "ephemeral_message_parameters": identity}
            )
            _EPHEMERAL_PARAM_MODE["mode"] = "v3"
            return result
        except Exception as exc:
            if _EPHEMERAL_PARAM_MODE["mode"] == "v3" or not _is_bad_request(exc):
                raise
            # 服务端不认对象参数：降级到 10.2 平铺格式并记住
            _EPHEMERAL_PARAM_MODE["mode"] = "legacy"
    payload = {**base_params, **identity}
    if identity and _EPHEMERAL_PARAM_MODE["mode"] == "auto":
        # identity 为空的调用没有可协商差异，保持 auto 不锁定
        pass
    result = _make_raw_result(bot, method_name, payload)
    if identity and _EPHEMERAL_PARAM_MODE["mode"] == "auto":
        _EPHEMERAL_PARAM_MODE["mode"] = "legacy"
    return result


def _is_bad_request(exc) -> bool:
    """识别 Bot API 400 参数拒绝。

    telebot 的 ApiTelegramException 用 ``error_code``；其余实现可能叫
    ``status_code``，两者都探测。
    """
    for attr in ("error_code", "status_code"):
        code = getattr(exc, attr, None)
        if code is None:
            continue
        try:
            return int(code) == 400
        except (TypeError, ValueError):
            continue
    return False


def _ephemeral_request_message(bot, method_name: str, params: dict, identity: dict):
    """调用 ephemeral 原始 API 并解析为 Message 对象。"""
    from telebot import types

    result = _send_ephemeral_raw(bot, method_name, params, identity)
    return types.Message.de_json(result)


def send_ephemeral_message_compat(bot, chat_id, receiver_user_id, text, **kwargs):
    """发送群内私密消息（仅 receiver_user_id 可见）。Bot API 10.2+ / 10.3 适配。

    必需参数：
        chat_id: 群聊 ID
        receiver_user_id: 接收者用户 ID
        text: 消息文本

    可选 kwargs（透传给 Bot API）：
        parse_mode, reply_markup, disable_notification 等
        10.3 起亦接受 rich_message（富文本私密消息）
    """
    params = {
        "chat_id": chat_id,
        "text": text,
        **kwargs,
    }
    return _ephemeral_request_message(
        bot, "sendEphemeralMessage", params,
        _ephemeral_identity(receiver_user_id=receiver_user_id),
    )


def edit_ephemeral_message_text_compat(
    bot, chat_id, message_id, text,
    receiver_user_id=None, callback_query_id=None, **kwargs
):
    """编辑群内私密消息文本。Bot API 10.2+；10.3 起 kwargs 可透传 rich_message。

    receiver_user_id 和 callback_query_id 至少传一个，用于 Telegram 定位接收者。
    """
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        **kwargs,
    }
    return _ephemeral_request_message(
        bot, "editEphemeralMessageText", params,
        _ephemeral_identity(receiver_user_id, callback_query_id),
    )


def delete_ephemeral_message_compat(
    bot, chat_id, message_id,
    receiver_user_id=None, callback_query_id=None, **kwargs
):
    """删除群内私密消息。Bot API 10.2+ / 10.3 适配。

    返回 True/False（delete 方法不返回 Message 对象）。
    """
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        **kwargs,
    }
    result = _send_ephemeral_raw(
        bot, "deleteEphemeralMessage", params,
        _ephemeral_identity(receiver_user_id, callback_query_id),
    )
    return bool(result)


def _html_to_rich_components(html_text: str) -> list:
    """[DEPRECATED v5.31.7] 将 HTML 卡片转换为 Rich Message 组件列表。

    已弃用：send_rich_message_compat 不再调用此函数。
    官方 Bot API 10.1 期望 InputRichMessage 对象 {"html": "..."} 而非组件列表。
    保留此函数仅供历史参考，后续版本可能删除。

    支持的 HTML 标签：
    - <b>/<strong> → bold
    - <i>/<em> → italic
    - <u>/<ins> → underline
    - <s>/<strike>/<del> → strikethrough
    - <tg-spoiler> → spoiler
    - <code> → code
    - <pre> → pre
    - <blockquote> → blockquote
    - <blockquote expandable> → blockquote (expandable)
    - <a href="..."> → text_link
    - <tg-emoji emoji-id="..."> → custom_emoji
    - <tg-map lat="..." long="..." zoom="..."> → map (Bot API 10.1)
    - <tg-copy> → copyable (Bot API 10.1)
    - <tg-expand> → expandable (Bot API 10.1)
    - <tg-s> → small (Bot API 10.1)
    - <tg-mention username="..."> → mention (Bot API 10.1)
    - <tg-person user-id="..."> → person (Bot API 10.1)
    """
    import re
    
    if not html_text or not isinstance(html_text, str):
        return [{"type": "text", "text": str(html_text or "")}]
    
    components = []
    text = html_text
    
    # 解析 HTML 标签并转换为组件
    # 这里使用简化的解析逻辑，实际生产环境可能需要更完整的 HTML parser
    
    # 处理 <b><i>...</i></b> 组合标签
    pattern_bold_italic = r'<b><i>(.*?)</i></b>|<strong><em>(.*?)</em></strong>'
    for match in re.finditer(pattern_bold_italic, text, re.DOTALL):
        content = match.group(1) or match.group(2)
        components.append({"type": "bold", "text": content})
        components.append({"type": "italic", "text": ""})  # 标记组合
    
    # 处理 <b>...</b>
    pattern_bold = r'<b>(.*?)</b>|<strong>(.*?)</strong>'
    for match in re.finditer(pattern_bold, text, re.DOTALL):
        content = match.group(1) or match.group(2)
        if not any(c.get("text") == content for c in components):
            components.append({"type": "bold", "text": content})
    
    # 处理 <i>...</i>
    pattern_italic = r'<i>(.*?)</i>|<em>(.*?)</em>'
    for match in re.finditer(pattern_italic, text, re.DOTALL):
        content = match.group(1) or match.group(2)
        if not any(c.get("text") == content for c in components):
            components.append({"type": "italic", "text": content})
    
    # 处理 <blockquote expandable>...</blockquote>
    pattern_blockquote_exp = r'<blockquote\s+expandable>(.*?)</blockquote>'
    for match in re.finditer(pattern_blockquote_exp, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "blockquote", "text": content, "expandable": True})
    
    # 处理 <blockquote>...</blockquote>
    pattern_blockquote = r'<blockquote>(.*?)</blockquote>'
    for match in re.finditer(pattern_blockquote, text, re.DOTALL):
        content = match.group(1)
        if not any(c.get("text") == content and c.get("expandable") for c in components):
            components.append({"type": "blockquote", "text": content})
    
    # 处理 <tg-spoiler>...</tg-spoiler>
    pattern_spoiler = r'<tg-spoiler>(.*?)</tg-spoiler>'
    for match in re.finditer(pattern_spoiler, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "spoiler", "text": content})
    
    # 处理 <a href="...">...</a>
    pattern_link = r'<a\s+href="([^"]+)">(.*?)</a>'
    for match in re.finditer(pattern_link, text, re.DOTALL):
        url = match.group(1)
        content = match.group(2)
        components.append({"type": "text_link", "text": content, "url": url})
    
    # 处理 <tg-emoji emoji-id="...">...</tg-emoji>
    pattern_emoji = r'<tg-emoji\s+emoji-id="([^"]+)">(.*?)</tg-emoji>'
    for match in re.finditer(pattern_emoji, text, re.DOTALL):
        emoji_id = match.group(1)
        content = match.group(2)
        components.append({"type": "custom_emoji", "text": content, "emoji_id": emoji_id})
    
    # 处理 <code>...</code>
    pattern_code = r'<code>(.*?)</code>'
    for match in re.finditer(pattern_code, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "code", "text": content})
    
    # 处理 <pre>...</pre>
    pattern_pre = r'<pre>(.*?)</pre>'
    for match in re.finditer(pattern_pre, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "pre", "text": content})
    
    # 处理 <u>...</u>
    pattern_underline = r'<u>(.*?)</u>|<ins>(.*?)</ins>'
    for match in re.finditer(pattern_underline, text, re.DOTALL):
        content = match.group(1) or match.group(2)
        components.append({"type": "underline", "text": content})
    
    # 处理 <s>...</s>
    pattern_strike = r'<s>(.*?)</s>|<strike>(.*?)</strike>|<del>(.*?)</del>'
    for match in re.finditer(pattern_strike, text, re.DOTALL):
        content = match.group(1) or match.group(2) or match.group(3)
        components.append({"type": "strikethrough", "text": content})
    
    # ── Bot API 10.1 新增标签 ──────────────────────────────────────────────
    
    # 处理 <tg-map lat="..." long="..." zoom="...">...</tg-map>
    pattern_map = r'<tg-map\s+lat="([^"]+)"\s+long="([^"]+)"(?:\s+zoom="([^"]+)")?>(.*?)</tg-map>'
    for match in re.finditer(pattern_map, text, re.DOTALL):
        lat = match.group(1)
        long_ = match.group(2)
        zoom = match.group(3) or "14"
        content = match.group(4)
        components.append({
            "type": "map",
            "text": content,
            "latitude": float(lat),
            "longitude": float(long_),
            "zoom": int(zoom),
        })
    
    # 处理 <tg-copy>...</tg-copy>
    pattern_copy = r'<tg-copy>(.*?)</tg-copy>'
    for match in re.finditer(pattern_copy, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "copyable", "text": content})
    
    # 处理 <tg-expand>...</tg-expand>
    pattern_expand = r'<tg-expand>(.*?)</tg-expand>'
    for match in re.finditer(pattern_expand, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "expandable", "text": content})
    
    # 处理 <tg-s>...</tg-s>
    pattern_small = r'<tg-s>(.*?)</tg-s>'
    for match in re.finditer(pattern_small, text, re.DOTALL):
        content = match.group(1)
        components.append({"type": "small", "text": content})
    
    # 处理 <tg-mention username="...">...</tg-mention>
    pattern_mention = r'<tg-mention\s+username="([^"]+)">(.*?)</tg-mention>'
    for match in re.finditer(pattern_mention, text, re.DOTALL):
        username = match.group(1)
        content = match.group(2)
        components.append({"type": "mention", "text": content, "username": username})
    
    # 处理 <tg-person user-id="...">...</tg-person>
    pattern_person = r'<tg-person\s+user-id="([^"]+)">(.*?)</tg-person>'
    for match in re.finditer(pattern_person, text, re.DOTALL):
        user_id = match.group(1)
        content = match.group(2)
        components.append({"type": "person", "text": content, "user_id": int(user_id)})
    
    # 如果解析后没有组件，返回原始文本
    if not components:
        # 去除 HTML 标签，返回纯文本
        clean_text = re.sub(r'<[^>]+>', '', text)
        return [{"type": "text", "text": clean_text.strip()}]
    
    return components


def send_poll_compat(bot, chat_id, question, options, **kwargs):
    """兼容 Telegram Bot API 9.6/10.0 新版投票参数。"""
    unsupported_keys = (
        "media",
        "question_entities",
        "correct_option_ids",
        "description",
        "description_parse_mode",
        "description_entities",
        "open_period",
        "allows_changing_answer",
        "allows_revoting",
        "country_codes",
        "members_only",
        "shuffle_options",
        "hide_results_until_closes",
        "allow_adding_options",
        "allow_paid_broadcast",
        "message_effect_id",
        "direct_messages_topic_id",
        "suggested_post_parameters",
    )
    extra = {key: kwargs.pop(key) for key in unsupported_keys if key in kwargs}
    if not any(value is not None for value in extra.values()):
        return bot.send_poll(chat_id, question, options, **kwargs)

    params = {"chat_id": chat_id, "question": question, "options": options, **kwargs, **extra}
    return _make_raw_request(bot, "sendPoll", params)


def send_checklist_compat(bot, business_connection_id, chat_id, checklist, **kwargs):
    """兼容 Telegram Bot API 10.1 sendChecklist。"""
    params = {
        "business_connection_id": business_connection_id,
        "chat_id": chat_id,
        "checklist": checklist,
        **kwargs,
    }
    return _make_raw_request(bot, "sendChecklist", params)


def restrict_chat_member_compat(bot, chat_id, user_id, permissions=None, **kwargs):
    """兼容 ChatPermissions 新字段，如 can_react_to_messages。"""
    permissions = permissions or {}
    params = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": permissions,
        **kwargs,
    }
    if isinstance(permissions, dict):
        if not getattr(bot, "token", None) and hasattr(bot, "restrict_chat_member"):
            return bot.restrict_chat_member(chat_id, user_id, permissions=permissions, **kwargs)
        return _make_raw_result(bot, "restrictChatMember", params)
    try:
        return bot.restrict_chat_member(chat_id, user_id, permissions=permissions, **kwargs)
    except TypeError:
        return _make_raw_result(bot, "restrictChatMember", params)


def delete_message_reaction_compat(bot, chat_id, message_id, user_id=None, actor_chat_id=None):
    """兼容 Bot API 10.0 deleteMessageReaction。"""
    if not getattr(bot, "token", None):
        return False
    return _make_raw_result(
        bot,
        "deleteMessageReaction",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "user_id": user_id,
            "actor_chat_id": actor_chat_id,
        },
    )


def delete_all_message_reactions_compat(bot, chat_id, user_id=None, actor_chat_id=None):
    """兼容 Bot API 10.0 deleteAllMessageReactions。"""
    if not getattr(bot, "token", None):
        return False
    return _make_raw_result(
        bot,
        "deleteAllMessageReactions",
        {
            "chat_id": chat_id,
            "user_id": user_id,
            "actor_chat_id": actor_chat_id,
        },
    )


def create_colored_button(text, callback_data=None, url=None, style='default', icon_emoji_id=None, disabled=False):
    """创建彩色按钮（Bot API 9.4+；10.3+ 支持灰显）。

    参数：
        text: 按钮文本
        callback_data: 回调数据（与 url 二选一）
        url: 按钮链接（与 callback_data 二选一）
        style: 按钮样式 - 'default' | 'danger' | 'success' | 'primary'
        icon_emoji_id: Custom Emoji ID（可选，显示在按钮文本前）
        disabled: 是否灰显不可点（Bot API 10.3 InlineKeyboardButton.disabled，
                  用于售罄/已结束等状态；SDK 未支持时优雅忽略）

    返回：
        telebot.types.InlineKeyboardButton 对象

    注意：
        - style 参数需要 pyTelegramBotAPI 4.34.0+ 或 Telegram Bot API 9.4+
        - 如果 SDK 版本不支持，style 参数会被忽略，按钮显示为默认样式
        - icon_emoji_id 需要 Telegram Premium 或 Bot 有 Custom Emoji 权限
    """
    from telebot import types

    # 创建基础按钮
    if url:
        button = types.InlineKeyboardButton(text=text, url=url)
    else:
        button = types.InlineKeyboardButton(text=text, callback_data=callback_data)

    # 设置样式（pyTelegramBotAPI 4.34.0+ 支持）
    if hasattr(button, 'style') and style != 'default':
        button.style = style

    # 设置 Custom Emoji 图标
    if icon_emoji_id and hasattr(button, 'icon_custom_emoji_id'):
        button.icon_custom_emoji_id = icon_emoji_id

    # 灰显（Bot API 10.3）：SDK 未封装该字段时静默忽略，按钮保持可点
    if disabled:
        try:
            button.disabled = True
        except (AttributeError, TypeError):
            pass

    return button


def create_colored_markup(buttons_config, row_width=2):
    """创建彩色按钮布局。
    
    参数：
        buttons_config: 按钮配置列表，支持两种格式：
            格式1（简化）: List[List[Dict]] - 每行按钮配置
                [
                    [{"text": "购买", "callback_data": "buy", "style": "success"}],
                    [{"text": "取消", "callback_data": "cancel", "style": "danger"}]
                ]
            格式2（完整）: Dict - 包含 buttons 和 row_width
                {
                    "buttons": [
                        [{"text": "购买", "callback_data": "buy", "style": "success"}],
                        [{"text": "取消", "callback_data": "cancel", "style": "danger"}]
                    ],
                    "row_width": 2
                }
        row_width: 每行按钮数量（默认 2，仅格式1有效）
    
    返回：
        telebot.types.InlineKeyboardMarkup 对象
    
    示例：
        markup = create_colored_markup([
            [{"text": "✅ 购买", "callback_data": "buy", "style": "success", "icon_emoji_id": "..."}],
            [{"text": "❌ 取消", "callback_data": "cancel", "style": "danger"}]
        ])
    """
    from telebot import types
    
    # 处理格式2（完整配置）
    if isinstance(buttons_config, dict):
        buttons = buttons_config.get("buttons", [])
        row_width = buttons_config.get("row_width", row_width)
    else:
        buttons = buttons_config
    
    markup = types.InlineKeyboardMarkup(row_width=row_width)
    
    for row in buttons:
        row_buttons = []
        for btn_config in row:
            if isinstance(btn_config, dict):
                button_kwargs = {
                    "text": btn_config.get("text", ""),
                    "callback_data": btn_config.get("callback_data"),
                    "url": btn_config.get("url"),
                    "style": btn_config.get("style", "default"),
                    "icon_emoji_id": btn_config.get("icon_emoji_id"),
                }
                # 仅显式配置时才透传，保持既有调用方/测试替身签名兼容
                if "disabled" in btn_config:
                    button_kwargs["disabled"] = bool(btn_config["disabled"])
                button = create_colored_button(**button_kwargs)
                row_buttons.append(button)
            elif isinstance(btn_config, types.InlineKeyboardButton):
                # 已经是按钮对象，直接使用
                row_buttons.append(btn_config)
        
        if row_buttons:
            markup.add(*row_buttons)
    
    return markup


def apply_button_style_from_config(button, button_id: str, config: dict):
    """根据配置应用按钮样式。
    
    参数：
        button: InlineKeyboardButton 对象
        button_id: 按钮标识（用于从配置中查找样式）
        config: 配置字典，包含 BUTTON_STYLE_ENABLED 和 BUTTON_COLOR_MAP
    
    返回：
        修改后的按钮对象
    
    配置示例：
        {
            "BUTTON_STYLE_ENABLED": true,
            "BUTTON_COLOR_MAP": {
                "buy": "success",
                "cancel": "danger",
                "info": "primary"
            },
            "CUSTOM_EMOJI_ENABLED": true,
            "CUSTOM_EMOJI_POOL": {
                "buy": "emoji_id_1",
                "cancel": "emoji_id_2"
            }
        }
    """
    if not config.get("BUTTON_STYLE_ENABLED", False):
        return button
    
    # 从配置中获取样式
    color_map = config.get("BUTTON_COLOR_MAP", {})
    style = color_map.get(button_id, "default")
    
    # 应用样式
    if hasattr(button, 'style') and style != 'default':
        button.style = style
    
    # 应用 Custom Emoji
    if config.get("CUSTOM_EMOJI_ENABLED", False):
        emoji_pool = config.get("CUSTOM_EMOJI_POOL", {})
        emoji_id = emoji_pool.get(button_id)
        if emoji_id and hasattr(button, 'icon_custom_emoji_id'):
            button.icon_custom_emoji_id = emoji_id
    
    return button
