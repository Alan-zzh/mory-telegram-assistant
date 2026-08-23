# -*- coding: utf-8 -*-
"""AI 媒体工具（B1 批次自 core/ai_engine.py 原样外移（随下一版本发布））。

职责：识图分析（vision 池轮询）与 TTS 语音生成（voice_tts 池轮询）。
这两个函数原本游离在 AIEngine 类之外、与对话主循环无耦合，是最干净的
第一块拆分；行为逐字保留，core/ai_engine 继续再导出以兼容旧导入路径。
"""

from __future__ import annotations

import base64
import logging

import requests

logger = logging.getLogger(__name__)


def analyze_image(image_bytes: bytes, prompt: str, config: dict) -> str | None:
    """
    【v4.3.0新增】AI识图分析 - 让Mory能"看懂"群友发的图片

    Args:
        image_bytes: 图片二进制数据
        prompt: 分析提示词
        config: 配置字典

    Returns:
        AI对图片的分析回复，或None（失败时）
    """
    # 获取vision池的模型
    pools = config.get("MODEL_POOLS", {})
    vision_pool = list(pools.get("vision", []))

    # 如果没有vision池，尝试用llm池（仅选择明确支持多模态的模型）
    if not vision_pool:
        llm_pool = pools.get("llm", [])
        vl_keywords = ["vl", "vision", "omni", "qwen-vl", "qwen2-vl", "glm-4v", "glm-4v-plus", "deepseek-vl"]
        for m in llm_pool:
            name = m.get("name", "").lower()
            if any(kw in name for kw in vl_keywords):
                vision_pool.append(m)
                break

    if not vision_pool:
        logger.warning("⚠️ 没有可用的视觉模型，跳过图片分析")
        return None

    # 【修复v4.3.2】遍历vision_pool，跳过过期模型，失败自动尝试下一个
    api_key = config.get("API_KEY") or config.get("DASHSCOPE_KEY", "")

    if not api_key or api_key in ("", "YOUR_DASHSCOPE_API_KEY_HERE", "YOUR_DASHSCOPE_API_KEY"):
        logger.warning("⚠️ API_KEY未配置，跳过图片分析")
        return None

    img_base64 = base64.b64encode(image_bytes).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}},
                {"type": "text", "text": prompt}
            ]
        }
    ]

    raw_base = config.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    base_url = raw_base.replace("/chat/completions", "").rstrip("/")

    for model_info in vision_pool:
        model_name = model_info.get("name", "")
        expire = model_info.get("expire", "")
        if expire:
            try:
                from datetime import datetime as _dt
                expire_date = _dt.strptime(expire, "%Y-%m-%d").date()
                if expire_date < _dt.now().date():
                    logger.info(f"⏭️ 跳过过期视觉模型: {model_name} (过期: {expire})")
                    continue
            except (ValueError, TypeError):
                pass

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": 300
        }

        try:
            from core.http_client import get_http_client, HTTPRequestError
            client = get_http_client()
            data = client.post(
                f"{base_url}/chat/completions",
                json_data=payload,
                headers=headers,
                timeout=30
            )
            if isinstance(data, dict) and data.get("choices"):
                content = data["choices"][0].get("message", {}).get("content", "")
                logger.info(f"✅ 图片分析成功: {model_name}")
                return content
            logger.warning(f"⚠️ 图片分析API返回异常({model_name}): {str(data)[:200]}")
        except HTTPRequestError as e:
            logger.warning(f"⚠️ 图片分析API失败({model_name}): {e}，尝试下一个模型")
            continue
        except Exception as e:
            logger.warning(f"⚠️ 图片分析异常({model_name}): {type(e).__name__}，尝试下一个模型")
            continue

    logger.warning("⚠️ 所有视觉模型均失败，跳过图片分析")
    return None


def text_to_speech(text: str, config: dict = None) -> bytes | None:
    """
    TTS文字转语音 - 用 voice_tts 池的模型把文字转成音频
    :param text: 要转换的文字
    :param config: 配置字典（可选）
    :return: 音频数据(bytes) 或 None
    """
    if config is None:
        from core.bot_initializer import load_config
        config = load_config()

    # 获取 voice_tts 池的模型
    pools = config.get("MODEL_POOLS", {})
    tts_models = pools.get("voice_tts", [])

    if not tts_models:
        logger.warning("⚠️ 未配置 voice_tts 或 llm_standard 模型池")
        return None

    # 【修复v4.3.2】遍历tts模型池，跳过过期模型，失败自动尝试下一个
    raw_base = config.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    base_url = raw_base.replace("/chat/completions", "").rstrip("/")

    for model_info in tts_models:
        model_name = model_info.get("name", "") or model_info.get("model", "")
        api_key = config.get("API_KEY", "") or model_info.get("key", "")

        expire = model_info.get("expire", "")
        if expire:
            try:
                from datetime import datetime as _dt
                expire_date = _dt.strptime(expire, "%Y-%m-%d").date()
                if expire_date < _dt.now().date():
                    logger.info(f"⏭️ 跳过过期TTS模型: {model_name} (过期: {expire})")
                    continue
            except (ValueError, TypeError):
                pass

        if not model_name or not api_key:
            logger.warning(f"⚠️ TTS 模型配置不完整: {model_name}")
            continue

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model_name,
            "input": text,
            "voice": "Cherry",
        }

        try:
            resp = requests.post(
                f"{base_url}/audio/speech",
                headers=headers,
                json=payload,
                timeout=30
            )

            if resp.status_code == 200:
                logger.info(f"✅ TTS 生成成功({model_name}): {len(text)}字 -> {len(resp.content)}字节音频")
                return resp.content

            logger.warning(f"⚠️ TTS API 失败({model_name}): {resp.status_code}，尝试格式2")

            payload2 = {
                "model": model_name,
                "input": text,
                "voice": "alloy",
            }
            resp2 = requests.post(
                f"{base_url}/audio/speech",
                headers=headers,
                json=payload2,
                timeout=30
            )

            if resp2.status_code == 200:
                logger.info(f"✅ TTS 生成成功(格式2,{model_name}): {len(text)}字 -> {len(resp2.content)}字节音频")
                return resp2.content

            logger.warning(f"⚠️ TTS API 失败(格式2,{model_name}): {resp2.status_code}，尝试下一个模型")
        except Exception as e:
            logger.warning(f"⚠️ TTS 异常({model_name}): {type(e).__name__}，尝试下一个模型")
            continue

    logger.warning("⚠️ 所有TTS模型均失败，跳过语音生成")
    return None
