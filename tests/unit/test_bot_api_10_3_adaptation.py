# -*- coding: utf-8 -*-
"""Bot API 10.3（2026-08-24 官方 changelog）适配单测。

覆盖两块官方变更在本项目的融入：
1. Ephemeral Messages 参数重构：官方把 sendMessage 系列的
   receiver_user_id / callback_query_id 平铺参数替换为
   ephemeral_message_parameters 对象。compat 层优先发对象格式，
   服务端仍为 10.2 语义（400 参数拒绝）时回退平铺格式并进程内记忆。
2. InlineKeyboardButton.disabled 灰显按钮（10.3 新增）：
   当前 SDK 未封装该字段，要求优雅退化——不抛错、不污染序列化。
"""

import json

import pytest
from telebot.apihelper import ApiTelegramException

from core import telegram_send_utils as tsu


@pytest.fixture(autouse=True)
def _reset_ephemeral_mode():
    tsu._EPHEMERAL_PARAM_MODE["mode"] = "auto"
    yield
    tsu._EPHEMERAL_PARAM_MODE["mode"] = "auto"


class _BotStub:
    token = "unit-test-token"


class _RawRecorder:
    """替身 _make_raw_result，记录调用并按剧本返回/抛错。"""

    def __init__(self, *, fail_v3_once=False, fail_all=False):
        self.calls = []
        self.fail_v3_once = fail_v3_once
        self.fail_all = fail_all

    def __call__(self, bot, method_name, params, files=None):
        self.calls.append((method_name, dict(params)))
        if self.fail_all:
            raise ApiTelegramException(
                method_name,
                400,
                {"ok": False, "error_code": 400, "description": "Bad Request: text is empty"},
            )
        if self.fail_v3_once and "ephemeral_message_parameters" in params and len(self.calls) == 1:
            raise ApiTelegramException(
                method_name,
                400,
                {
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: unknown field ephemeral_message_parameters",
                },
            )
        return {
            "message_id": 77,
            "chat": {"id": -100123, "type": "supergroup", "title": "t"},
            "date": 1,
        }


# ── 1. Ephemeral Messages 10.3 参数重构适配 ──────────────────────────────────


def test_send_ephemeral_prefers_v3_object_params_and_caches(monkeypatch):
    rec = _RawRecorder()
    monkeypatch.setattr(tsu, "_make_raw_result", rec)

    sent = tsu.send_ephemeral_message_compat(_BotStub(), -100123, 42, "<b>hi</b>", parse_mode="HTML")

    assert sent is not None
    method, params = rec.calls[0]
    assert method == "sendEphemeralMessage"
    assert params["ephemeral_message_parameters"] == {"receiver_user_id": 42}
    assert "receiver_user_id" not in params
    assert params["parse_mode"] == "HTML"
    assert tsu._EPHEMERAL_PARAM_MODE["mode"] == "v3"

    tsu.send_ephemeral_message_compat(_BotStub(), -100123, 43, "again")
    assert len(rec.calls) == 2
    assert rec.calls[1][1]["ephemeral_message_parameters"] == {"receiver_user_id": 43}


def test_send_ephemeral_falls_back_to_legacy_on_400(monkeypatch):
    rec = _RawRecorder(fail_v3_once=True)
    monkeypatch.setattr(tsu, "_make_raw_result", rec)

    tsu.send_ephemeral_message_compat(_BotStub(), -100123, 42, "hi")

    assert len(rec.calls) == 2
    first_method, first_params = rec.calls[0]
    second_method, second_params = rec.calls[1]
    assert first_method == second_method == "sendEphemeralMessage"
    assert "ephemeral_message_parameters" in first_params
    assert second_params["receiver_user_id"] == 42
    assert "ephemeral_message_parameters" not in second_params
    assert tsu._EPHEMERAL_PARAM_MODE["mode"] == "legacy"

    # 记忆 legacy 后不再重复探测对象格式
    tsu.send_ephemeral_message_compat(_BotStub(), -100123, 43, "again")
    assert len(rec.calls) == 3
    assert rec.calls[2][1]["receiver_user_id"] == 43


def test_edit_ephemeral_uses_object_params_and_forwards_rich_message(monkeypatch):
    rec = _RawRecorder()
    monkeypatch.setattr(tsu, "_make_raw_result", rec)

    tsu.edit_ephemeral_message_text_compat(
        _BotStub(), -100123, 77, "updated",
        receiver_user_id=42,
        rich_message={"html": "<i>updated</i>"},
    )

    method, params = rec.calls[0]
    assert method == "editEphemeralMessageText"
    assert params["ephemeral_message_parameters"] == {"receiver_user_id": 42}
    assert params["rich_message"] == {"html": "<i>updated</i>"}


def test_edit_ephemeral_with_callback_query_identity(monkeypatch):
    rec = _RawRecorder()
    monkeypatch.setattr(tsu, "_make_raw_result", rec)

    tsu.delete_ephemeral_message_compat(
        _BotStub(), -100123, 77, callback_query_id="cq-1"
    )

    method, params = rec.calls[0]
    assert method == "deleteEphemeralMessage"
    assert params["ephemeral_message_parameters"] == {"callback_query_id": "cq-1"}


def test_real_param_error_surfaces_after_fallback(monkeypatch):
    # 服务端为 10.2 语义且真实参数非法：回退后仍失败必须抛出原始错误，
    # 不允许吞错假成功。
    rec = _RawRecorder(fail_all=True)
    monkeypatch.setattr(tsu, "_make_raw_result", rec)

    with pytest.raises(ApiTelegramException):
        tsu.send_ephemeral_message_compat(_BotStub(), -100123, 42, "")
    assert len(rec.calls) == 2
    assert tsu._EPHEMERAL_PARAM_MODE["mode"] == "legacy"


def test_non_400_error_does_not_trigger_fallback(monkeypatch):
    class _Forbidden(ApiTelegramException):
        pass

    def fake_raw(bot, method_name, params, files=None):
        raise _Forbidden(method_name, 403, {"ok": False, "error_code": 403, "description": "bot blocked"})

    monkeypatch.setattr(tsu, "_make_raw_result", fake_raw)

    with pytest.raises(ApiTelegramException):
        tsu.send_ephemeral_message_compat(_BotStub(), -100123, 42, "hi")
    # 非 400 直接上抛，模式保持 auto、只调用一次
    assert tsu._EPHEMERAL_PARAM_MODE["mode"] == "auto"


# ── 2. InlineKeyboardButton.disabled 灰显按钮（Bot API 10.3）────────────────


def test_create_colored_button_disabled_degrades_gracefully():
    btn = tsu.create_colored_button(text="已售罄", callback_data="buy", disabled=True)

    # 当前 SDK 未封装 disabled：实例属性可设置，但 to_json 显式字段列表
    # 不包含它 → 发给 API 的 payload 干净，不会触发未知字段 400。
    serialized = json.dumps(btn.to_json())
    assert "disabled" not in serialized


def test_create_colored_button_default_has_no_disabled():
    btn = tsu.create_colored_button(text="购买", callback_data="buy")
    assert not getattr(btn, "disabled", False)


def test_create_colored_markup_passes_disabled_only_when_configured():
    markup = tsu.create_colored_markup(
        [
            [{"text": "已售罄", "callback_data": "buy", "disabled": True}],
            [{"text": "普通", "callback_data": "info"}],
        ]
    )
    rows = list(markup.keyboard)
    assert getattr(rows[0][0], "disabled", False) is True
    assert not getattr(rows[1][0], "disabled", False)


def test_create_colored_markup_keeps_legacy_fake_signature(monkeypatch):
    # 既有测试替身签名没有 disabled 形参；未显式配置时不得多传关键字。
    calls = {}

    def fake_create_colored_button(text, url=None, callback_data=None, style="default", icon_emoji_id=None):
        calls["text"] = text
        from telebot import types

        return types.InlineKeyboardButton(text=text, callback_data=callback_data)

    monkeypatch.setattr(tsu, "create_colored_button", fake_create_colored_button)

    tsu.create_colored_markup([[{"text": "看看", "url": "https://t.me/moryselect"}]])
    assert calls["text"] == "看看"
