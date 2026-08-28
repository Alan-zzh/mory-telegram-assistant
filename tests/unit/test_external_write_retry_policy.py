# -*- coding: utf-8 -*-
"""外部写请求必须显式关闭自动重试，避免未知投递结果造成重复资源。"""

from types import SimpleNamespace


def test_telegraph_create_requests_explicitly_disable_retries(monkeypatch):
    from modules import telegraph

    class Client:
        def __init__(self):
            self.get_calls = []
            self.post_calls = []

        def get(self, url, **kwargs):
            self.get_calls.append((url, kwargs))
            return {"ok": True, "result": {"access_token": "test-token"}}

        def post(self, url, **kwargs):
            self.post_calls.append((url, kwargs))
            return {"ok": True, "result": {"url": "https://telegra.ph/test"}}

    class Bot:
        def __init__(self):
            self.replies = []

        def reply_to(self, message, text):
            self.replies.append((message, text))

    client = Client()
    monkeypatch.setattr(telegraph, "get_http_client", lambda: client)
    message = SimpleNamespace(
        text="/telegraph 标题 内容",
        reply_to_message=None,
        from_user=SimpleNamespace(id=42),
    )
    bot = Bot()

    telegraph.handle_telegraph(bot, message, {}, object())

    assert client.get_calls[0][1]["retry_times"] == 0
    assert client.post_calls[0][1]["retry_times"] == 0
    assert "https://telegra.ph/test" in bot.replies[0][1]


def test_ai_image_analysis_explicitly_disables_post_retries(monkeypatch):
    import core.http_client as http_client
    from core.ai_media_tools import analyze_image

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return {"choices": [{"message": {"content": "正常图片"}}]}

    client = Client()
    monkeypatch.setattr(http_client, "get_http_client", lambda: client)

    result = analyze_image(
        b"image",
        "请简述图片内容",
        {
            "API_KEY": "test-key",
            "BASE_URL": "https://example.test/v1/chat/completions",
            "MODEL_POOLS": {"vision": [{"name": "vision-test"}]},
        },
    )

    assert result == "正常图片"
    assert client.calls[0][1]["retry_times"] == 0
