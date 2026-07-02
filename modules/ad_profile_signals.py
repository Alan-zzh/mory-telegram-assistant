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


def _local_ocr(image_data: bytes) -> str:
    """本地 OCR fallback，使用 RapidOCR 在 CPU 上识别图片文字。
    未安装 rapidocr-onnxruntime 时返回空，不影响正常运行。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ""
    try:
        ocr_engine = RapidOCR()
        result, _ = ocr_engine(image_data)
        if not result:
            return ""
        texts = [item[1] for item in result if item and len(item) > 1]
        return " ".join(texts)
    except Exception as e:
        logger.debug(f"[AD] 本地OCR失败: {e}")
        return ""


def _has_vision_model(config: dict | None = None) -> bool:
    """检查是否有可用的视觉模型（用于决定降级策略）。
    config 为 None 时返回 True（避免测试/未初始化时触发降级）。
    """
    if not config:
        return True
    pools = config.get("MODEL_POOLS", {})
    vision_pool = pools.get("vision", [])
    if vision_pool:
        return True
    llm_pool = pools.get("llm", [])
    vl_keywords = ["vl", "vision", "omni", "qwen-vl", "qwen2-vl", "glm-4v", "deepseek-vl"]
    for m in llm_pool:
        name = m.get("name", "").lower()
        if any(kw in name for kw in vl_keywords):
            return True
    return False


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
    has_vl = _has_vision_model(config)
    for sticker in stickers or []:
        image_data = _download_sticker_image(bot, sticker)
        if not image_data:
            continue
        text = None
        # 优先用 API 视觉模型 OCR
        if has_vl:
            try:
                text = analyze_image(image_data, prompt, config)
                if text and text != "无文字":
                    results.append(str(text))
                    continue
            except Exception as e:
                logger.debug(f"[Codex] emoji状态贴纸API-OCR失败: err={e}")
        # API 不可用时用本地 OCR fallback
        if not text or text == "无文字":
            local_text = _local_ocr(image_data)
            if local_text:
                logger.info(f"[AD] 本地OCR识别到文字: {local_text[:80]}")
                results.append(local_text)
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
    - is_ad=True：明确命中"看我简介"等强规则，可以直接广告处置
    - score=1：只有自定义 emoji 状态但没读到文字，只作为后续追踪信号

    注意：必须用 bot.get_chat(uid) 获取 Chat 对象来读取 emoji_status_custom_emoji_id，
    因为 m.from_user (User 对象) 在 pyTelegramBotAPI 4.34.0 中不保存该字段。
    """
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    username = getattr(user, "username", "") or ""
    uid = getattr(user, "id", None) or getattr(user, "uid", None)
    display = f"{first_name}{last_name}".strip()

    # 从 User 对象先尝试拿 emoji 状态
    status_ids = _iter_status_ids(user)

    # User 对象没有时，从 bot.get_chat() 的 Chat 对象拿
    # （pyTelegramBotAPI 4.34.0 的 User 类不保存 emoji_status，但 Chat 对象有）
    if not status_ids and uid:
        try:
            chat_info = bot.get_chat(uid)
            status_ids = _iter_status_ids(chat_info)
            # 同步更新 bio
            if not bio:
                chat_bio = getattr(chat_info, "bio", "") or ""
                if chat_bio:
                    bio = chat_bio
        except Exception as e:
            logger.debug(f"[AD] get_chat获取emoji状态失败: uid={uid} err={e}")

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
        has_vl = _has_vision_model(config)
        if not has_vl and config is not None:
            base_score = 2
            reason = "存在自定义emoji状态，未读到明确广告文字（无视觉模型降级）"
            no_vl_flag = True
        else:
            base_score = 1
            reason = "存在自定义emoji状态，未读到明确广告文字"
            no_vl_flag = False
        return {
            "is_ad": False,
            "score": base_score,
            "reason": reason,
            "status_ids": status_ids,
            "status_text": status_text,
            "ocr_text": ocr_text,
            "no_vision_model": no_vl_flag,
        }

    return {
        "is_ad": False,
        "score": 0,
        "reason": "",
        "status_ids": [],
        "status_text": "",
    }
