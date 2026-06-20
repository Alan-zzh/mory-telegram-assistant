# -*- coding: utf-8 -*-
"""
[Codex] 用户资料广告信号检测。

Telegram Premium 的 emoji 状态有时会被广告号做成“看我简介”贴纸。
Bot API 通常只能拿到 custom_emoji_id 和贴纸元数据，不保证能读到图片里的字；
能拿到文字元数据时直接封，拿不到时只记可疑分，避免误封正常 Premium 用户。
"""

import re

from core.logging_util import get_logger
from core.ai_engine import analyze_image
from modules.ad_patterns_encoded import BIO_PATTERNS, USERNAME_PATTERNS

logger = get_logger("ad_profile_signals")


def _iter_status_ids(user) -> list:
    """兼容不同 pyTelegramBotAPI 版本的 emoji 状态字段。"""
    ids = []
    for attr in ("emoji_status_custom_emoji_id", "emoji_status_custom_emoji_ids"):
        val = getattr(user, attr, None)
        if not val:
            continue
        if isinstance(val, (list, tuple, set)):
            ids.extend([str(x) for x in val if x])
        else:
            ids.append(str(val))
    return list(dict.fromkeys(ids))


def _sticker_texts(bot, status_ids: list) -> list:
    """读取自定义 emoji 贴纸可见元数据，失败时返回空。"""
    if not bot or not status_ids or not hasattr(bot, "get_custom_emoji_stickers"):
        return []
    try:
        stickers = bot.get_custom_emoji_stickers(status_ids)
    except Exception as e:
        logger.debug(f"[Codex] 获取emoji状态贴纸失败: ids={status_ids[:3]} err={e}")
        return []

    texts = []
    for sticker in stickers or []:
        parts = []
        for attr in ("emoji", "set_name", "custom_emoji_id"):
            val = getattr(sticker, attr, "") or ""
            if val:
                parts.append(str(val))
        # file_id 是不透明凭据，不参与规则匹配，避免把随机串当内容。
        if parts:
            texts.append(" ".join(parts))
    return texts


def _download_sticker_image(bot, sticker) -> bytes:
    """优先下载缩略图；贴纸本体可能是动画/视频，不一定适合 OCR。"""
    file_id = ""
    thumb = getattr(sticker, "thumbnail", None)
    if thumb:
        file_id = getattr(thumb, "file_id", "") or ""
    if not file_id:
        file_id = getattr(sticker, "file_id", "") or ""
    if not file_id:
        return b""
    try:
        file_info = bot.get_file(file_id)
        file_path = getattr(file_info, "file_path", "") or ""
        if not file_path:
            return b""
        return bot.download_file(file_path) or b""
    except Exception as e:
        logger.debug(f"[Codex] 下载emoji状态贴纸失败: file_id={file_id} err={e}")
        return b""


def _ocr_sticker_texts(bot, status_ids: list, config: dict | None = None) -> list:
    """对自定义 emoji 状态贴纸做 OCR，识别图片里的“看我简介”等文字。"""
    if not config or not bot or not status_ids or not hasattr(bot, "get_custom_emoji_stickers"):
        return []
    try:
        stickers = bot.get_custom_emoji_stickers(status_ids)
    except Exception as e:
        logger.debug(f"[Codex] OCR前获取emoji状态贴纸失败: ids={status_ids[:3]} err={e}")
        return []

    results = []
    prompt = "请识别这张贴纸图片中的所有中文和英文文字，只返回文字内容，不要解释。没有文字就返回'无文字'。"
    for sticker in stickers or []:
        image_data = _download_sticker_image(bot, sticker)
        if not image_data:
            continue
        try:
            text = analyze_image(image_data, prompt, config)
            if text and text != "无文字":
                results.append(str(text))
        except Exception as e:
            logger.debug(f"[Codex] emoji状态贴纸OCR失败: err={e}")
    return results


def _match_ad_patterns(text: str) -> str:
    """返回命中的广告规则片段，未命中返回空。"""
    if not text:
        return ""
    for pattern in USERNAME_PATTERNS + BIO_PATTERNS:
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group()[:50]
        except re.error:
            logger.debug(f"[Codex] 资料信号跳过异常正则: {pattern[:30]}")
    return ""


def detect_profile_ad_signal(bot, user, bio: str = "", config: dict | None = None) -> dict:
    """
    检测用户资料层广告信号。

    返回:
    - is_ad=True：明确命中“看我简介”等强规则，可以直接广告处置
    - score=1：只有自定义 emoji 状态但没读到文字，只作为后续追踪信号
    """
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    username = getattr(user, "username", "") or ""
    display = f"{first_name}{last_name}".strip()
    status_ids = _iter_status_ids(user)
    sticker_texts = _sticker_texts(bot, status_ids)

    profile_parts = [display, username, bio or ""]
    status_text = " ".join(sticker_texts)

    profile_hit = _match_ad_patterns(" ".join(profile_parts))
    if profile_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"资料文字命中广告规则: {profile_hit}",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    status_hit = _match_ad_patterns(status_text)
    if status_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"emoji状态命中广告规则: {status_hit}",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    ocr_text = " ".join(_ocr_sticker_texts(bot, status_ids, config))
    ocr_hit = _match_ad_patterns(ocr_text)
    if ocr_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"emoji状态图片OCR命中广告规则: {ocr_hit}",
            "status_ids": status_ids,
            "status_text": status_text,
            "ocr_text": ocr_text,
        }

    if status_ids:
        return {
            "is_ad": False,
            "score": 1,
            "reason": "存在自定义emoji状态，未读到明确广告文字",
            "status_ids": status_ids,
            "status_text": status_text,
            "ocr_text": ocr_text,
        }

    return {
        "is_ad": False,
        "score": 0,
        "reason": "",
        "status_ids": [],
        "status_text": "",
    }
