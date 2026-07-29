# -*- coding: utf-8 -*-
"""头像视觉审核回归：固定标签、低误判阈值和 OCR 降级。"""

from io import BytesIO
from types import SimpleNamespace


class _Bot:
    def get_user_profile_photos(self, user_id, limit=1):
        photo = SimpleNamespace(file_id="avatar-1")
        return SimpleNamespace(photos=[[photo]])

    def get_file(self, file_id):
        return SimpleNamespace(file_path="avatars/avatar-1.jpg")

    def download_file(self, file_path):
        return b"avatar-bytes"


def test_avatar_label_parser_blocks_only_high_confidence(monkeypatch):
    from core import ai_engine
    from modules.ai_advisor import review_avatar_with_vision

    config = {"AD_AVATAR_AI_REVIEW_ENABLED": True}
    expected = {
        "ADULT_HIGH": (True, "adult"),
        "MARKETING_HIGH": (True, "marketing"),
        "QR_HIGH": (True, "qr"),
        "SAFE": (False, "normal"),
        "UNSURE": (False, "unknown"),
    }
    for raw, (is_ad, ad_type) in expected.items():
        monkeypatch.setattr(ai_engine, "analyze_image", lambda *args, value=raw, **kwargs: value)
        result = review_avatar_with_vision(b"image", config, user_id=42)
        assert result["used_ai"] is True
        assert result["is_ad"] is is_ad
        assert result["type"] == ad_type


def test_local_nsfw_model_uses_only_explicit_high_confidence_classes(monkeypatch):
    from modules import avatar_detector

    class _Detector:
        def detect(self, image_data):
            return [
                {"class": "BUTTOCKS_EXPOSED", "score": 0.813},
                {"class": "FEMALE_GENITALIA_EXPOSED", "score": 0.784},
                {"class": "ANUS_EXPOSED", "score": 0.745},
                {"class": "BELLY_EXPOSED", "score": 0.99},
            ]

    monkeypatch.setattr(avatar_detector, "_get_nude_detector", lambda: _Detector())
    result = avatar_detector.review_avatar_nsfw_local(b"image")

    assert result["used_local"] is True
    assert result["is_ad"] is True
    assert result["type"] == "adult"
    assert {item["class"] for item in result["detections"]} == {
        "BUTTOCKS_EXPOSED",
        "FEMALE_GENITALIA_EXPOSED",
        "ANUS_EXPOSED",
    }


def test_local_nsfw_model_ignores_covered_and_ambiguous_body_regions(monkeypatch):
    from modules import avatar_detector

    class _Detector:
        def detect(self, image_data):
            return [
                {"class": "BUTTOCKS_COVERED", "score": 0.99},
                {"class": "FEMALE_BREAST_COVERED", "score": 0.99},
                {"class": "BELLY_EXPOSED", "score": 0.99},
                {"class": "ARMPITS_EXPOSED", "score": 0.99},
                {"class": "BUTTOCKS_EXPOSED", "score": 0.79},
            ]

    monkeypatch.setattr(avatar_detector, "_get_nude_detector", lambda: _Detector())
    result = avatar_detector.review_avatar_nsfw_local(b"image")

    assert result["used_local"] is True
    assert result["is_ad"] is False
    assert result["detections"] == []


def test_weak_color_and_geometry_features_never_become_enforcement_evidence():
    from PIL import Image
    from modules import avatar_detector

    image = Image.new("RGB", (640, 640), (180, 140, 100))
    image_bytes = BytesIO()
    image.save(image_bytes, format="JPEG")

    is_suspicious, reason = avatar_detector._analyze_image(image_bytes.getvalue())

    assert is_suspicious is False
    assert "已忽略" in reason


def test_legacy_avatar_ban_api_cannot_enforce_weak_heuristics(monkeypatch):
    from modules import avatar_detector

    monkeypatch.setattr(
        avatar_detector,
        "check_user_avatar",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("旧头像封禁接口不得再调用弱启发式")
        ),
    )

    assert avatar_detector.check_and_ban_if_porn_avatar(
        _Bot(), 42, -1001, "普通用户"
    ) is False


def test_avatar_safe_result_does_not_repeat_ocr(monkeypatch):
    from modules import ai_advisor, avatar_detector

    ocr_calls = []
    monkeypatch.setattr(
        ai_advisor,
        "review_avatar_with_vision",
        lambda *args, **kwargs: {
            "is_ad": False,
            "type": "normal",
            "confidence": 0.98,
            "desc": "头像正常",
            "used_ai": True,
        },
    )
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_ocr_text",
        lambda *args, **kwargs: ocr_calls.append(True) or (False, "", 0),
    )
    monkeypatch.setattr(
        avatar_detector,
        "review_avatar_nsfw_local",
        lambda *args: {"is_ad": False, "type": "normal", "used_local": True},
    )

    result = avatar_detector.check_avatar_marketing(
        _Bot(), 42, {"AD_AVATAR_AI_REVIEW_ENABLED": True}
    )

    assert result[0] is False
    assert ocr_calls == []


def test_avatar_unsure_falls_back_to_ocr(monkeypatch):
    from modules import ai_advisor, avatar_detector

    monkeypatch.setattr(
        ai_advisor,
        "review_avatar_with_vision",
        lambda *args, **kwargs: {
            "is_ad": False,
            "type": "unknown",
            "confidence": 0.0,
            "desc": "视觉证据不足",
            "used_ai": True,
        },
    )
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_ocr_text",
        lambda *args, **kwargs: (True, "扫码进群", 2),
    )
    monkeypatch.setattr(
        avatar_detector,
        "review_avatar_nsfw_local",
        lambda *args: {"is_ad": False, "type": "normal", "used_local": True},
    )

    result = avatar_detector.check_avatar_marketing(
        _Bot(), 42, {"AD_AVATAR_AI_REVIEW_ENABLED": True}
    )

    assert result[0] is True
    assert result[2] == 2
    assert "OCR命中" in result[1]


def test_member_avatar_gate_enforces_high_but_not_borderline(monkeypatch):
    from core.handlers import member_handlers
    from modules import avatar_detector

    user = SimpleNamespace(id=42, first_name="普通昵称", last_name="")
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )
    monkeypatch.setattr(avatar_detector, "check_user_avatar", lambda *args: (False, "头像正常"))
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_similarity",
        lambda *args: (False, "无相似头像", []),
    )

    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_marketing",
        lambda *args: (
            True,
            "AI视觉复核: adult(明确成人低俗头像)",
            2,
            {"type": "adult"},
        ),
    )
    assert member_handlers._review_member_avatar(_Bot(), user, {}, object(), -1001) is True
    assert len(enforced) == 1

    enforced.clear()
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_marketing",
        lambda *args: (
            True,
            "AI视觉可疑: adult(证据不足)",
            1,
            {"type": "adult"},
        ),
    )
    assert member_handlers._review_member_avatar(_Bot(), user, {}, object(), -1001) is False
    assert enforced == []


def test_member_avatar_gate_never_consults_legacy_color_heuristic(monkeypatch):
    from core.handlers import member_handlers
    from modules import avatar_detector

    user = SimpleNamespace(id=42, first_name="kin", last_name="")
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_marketing",
        lambda *args: (
            False,
            "头像正常",
            0,
            {"type": "normal", "used_ai": True},
        ),
    )
    monkeypatch.setattr(
        avatar_detector,
        "check_avatar_similarity",
        lambda *args: (False, "无相似头像", []),
    )
    monkeypatch.setattr(
        avatar_detector,
        "check_user_avatar",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("入群头像审核不得调用旧颜色启发式")
        ),
    )

    assert member_handlers._review_member_avatar(
        _Bot(), user, {}, object(), -1001
    ) is False
    assert enforced == []
