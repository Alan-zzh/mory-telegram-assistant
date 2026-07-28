# -*- coding: utf-8 -*-
"""
[Puzan-OS v5.32] AI 辅助决策模块

为广告检测系统接入 AI 复核能力，避免静态规则误判/漏判：

1. review_borderline_ad：边界评分（score=2-3）时调用 LLM 复核，判断是否真的广告
2. warn_suspicious_user：可疑但未达封禁阈值时，AI 主动询问/引导用户
3. explain_enforcement_to_chat：广告处置后给群内上下文说明，避免其他用户困惑

设计原则：
- 所有 AI 调用默认关闭，避免无意义 token 消耗
- AI 失败时静默降级，不阻断主流程
- AI 结果只作为辅助信号，最终决策权在规则引擎
- 复用 AIEngine.ask() 接口，使用 llm_light 模型池降低成本
"""

import json
import random
from typing import Optional

from core.logging_util import get_logger

logger = get_logger("ai_advisor")


# ──────────────────────────────────────────────────────
# 1. 边界评分 AI 复核
# ──────────────────────────────────────────────────────

_AD_REVIEW_PROMPT_TEMPLATE = """[广告复核模式]
你是一个群聊广告检测助手。请判断下面这条消息是否为广告/营销/引流内容。

【用户消息】
{text}

【规则引擎评分】{score}（阈值3，2-3 为边界区间）
【规则命中】{reason}

【判断标准】
- 广告：明确营销话术/赚钱承诺/色情引流/拉人头/项目推广/联系方式诱导
- 正常：用户自然讨论/玩笑/吐槽/真实分享/中性提问
- 边界：含可疑词但语境中性（如"今天股票涨了"vs"带你炒股稳赚"）

【返回格式】严格 JSON：
{{"is_ad": true/false, "confidence": 0.0-1.0, "reason": "≤30字判断理由"}}

只返回 JSON，不要任何解释。"""


def review_borderline_ad(
    text: str,
    score: int,
    reason: str,
    config: dict,
    user_id: int = None,
    ai_engine=None,
) -> dict:
    """AI 复核边界评分（score=2-3 区间）。

    Args:
        text: 被检测的原始消息文本
        score: 规则引擎评分
        reason: 规则引擎命中的原因
        config: 配置字典
        user_id: 用户ID（用于日志）
        ai_engine: AIEngine 实例（可选，未传则惰性创建）

    Returns:
        {"is_ad": bool, "confidence": float, "reason": str, "used_ai": bool}
        AI 失败时 used_ai=False，沿用规则引擎结论。
    """
    cfg = config or {}

    # 默认关闭，需显式开启
    if not cfg.get("AD_AI_REVIEW_ENABLED", False):
        return {"is_ad": False, "confidence": 0.0, "reason": "AI复核未开启", "used_ai": False}

    # 只在边界区间复核
    if score < 2 or score >= 3:
        return {"is_ad": False, "confidence": 0.0, "reason": "非边界区间", "used_ai": False}

    text_clean = (text or "").strip()[:500]
    if not text_clean:
        return {"is_ad": False, "confidence": 0.0, "reason": "空文本", "used_ai": False}

    try:
        if ai_engine is None:
            from core.ai_engine import AIEngine
            ai_engine = AIEngine(cfg)

        prompt = _AD_REVIEW_PROMPT_TEMPLATE.format(
            text=text_clean,
            score=score,
            reason=(reason or "未命中明确规则")[:100],
        )

        # 使用 llm_light 池降低成本
        raw = ai_engine.ask(prompt, mode="normal", retry=2)
        if not raw:
            return {"is_ad": False, "confidence": 0.0, "reason": "AI无响应", "used_ai": False}

        # 解析 JSON
        raw_stripped = raw.strip()
        # 兼容模型可能包裹 markdown 代码块
        if raw_stripped.startswith("```"):
            raw_stripped = raw_stripped.strip("`")
            if raw_stripped.lower().startswith("json"):
                raw_stripped = raw_stripped[4:].strip()

        result = json.loads(raw_stripped)
        is_ad = bool(result.get("is_ad", False))
        confidence = float(result.get("confidence", 0.0))
        ai_reason = str(result.get("reason", ""))[:100]

        logger.info(
            f"[AI-AD-Review] uid={user_id} score={score} ai_is_ad={is_ad} "
            f"confidence={confidence:.2f} reason={ai_reason}"
        )
        return {
            "is_ad": is_ad,
            "confidence": confidence,
            "reason": ai_reason,
            "used_ai": True,
        }
    except json.JSONDecodeError as e:
        logger.debug(f"[AI-AD-Review] JSON解析失败 uid={user_id}: {e} raw={raw[:80] if raw else ''}")
        return {"is_ad": False, "confidence": 0.0, "reason": "AI响应格式错误", "used_ai": False}
    except Exception as e:
        logger.warning(f"[AI-AD-Review] 调用失败 uid={user_id}: {e}")
        return {"is_ad": False, "confidence": 0.0, "reason": f"AI调用异常: {e}", "used_ai": False}


# ──────────────────────────────────────────────────────
# 2. 可疑用户 AI 警告（未达封禁阈值时的引导）
# ──────────────────────────────────────────────────────

_WARN_PROMPT_TEMPLATE = """[可疑用户引导模式]
你是群里的助理Mory。一个用户发了有点可疑但还没到封禁程度的消息，请用你的清冷人设给一句温和提醒，让他自觉收手。

【用户消息】{text}
【可疑点】{reason}

【要求】
- 1句话，≤30字
- 清冷人设，句号收尾，不撒娇不卖萌
- 不直接说"你是广告"，用反问或提醒语气
- 不要解释规则
- 不要称呼"老板"

只返回那句话，不要任何前后缀。"""

_WARN_FALLBACKS = [
    "群规了解一下，别发这些。",
    "这条不太合适，下次注意。",
    "嗯…这条有点擦边，收一下。",
    "群里有规矩的，注意一下措辞。",
]


def warn_suspicious_user(
    bot,
    chat_id: int,
    uid: int,
    text: str,
    reason: str,
    config: dict,
    ai_engine=None,
) -> bool:
    """AI 主动警告可疑用户（未达封禁阈值时）。

    Returns:
        True=发送成功，False=发送失败或功能未开启
    """
    cfg = config or {}
    if not cfg.get("AD_AI_AUTO_REPLY_ENABLED", False):
        return False

    if not bot or not chat_id:
        return False

    try:
        if ai_engine is None:
            from core.ai_engine import AIEngine
            ai_engine = AIEngine(cfg)

        prompt = _WARN_PROMPT_TEMPLATE.format(
            text=(text or "")[:200],
            reason=(reason or "可疑信号")[:80],
        )
        warn_text = ai_engine.ask(prompt, mode="normal", retry=2)
        if not warn_text or len(warn_text.strip()) < 2:
            warn_text = random.choice(_WARN_FALLBACKS)
        else:
            warn_text = warn_text.strip().split("\n")[0][:60]

        bot.send_message(chat_id, warn_text)
        logger.info(f"[AI-Warn] 已警告可疑用户 uid={uid} chat={chat_id} text={warn_text[:30]}")
        return True
    except Exception as e:
        logger.warning(f"[AI-Warn] 警告失败 uid={uid}: {e}")
        return False


# ──────────────────────────────────────────────────────
# 3. 处置后群内上下文说明
# ──────────────────────────────────────────────────────

_EXPLAIN_PROMPT_TEMPLATE = """[群内说明模式]
你是群里的助理Mory。刚处理了一个广告号（永久禁言+删除消息），请用你的清冷人设给群里其他用户一句简短说明，让他们知道发生了什么，不要渲染恐慌。

【被处置用户】{uname}
【处置原因】{reason}

【要求】
- 1句话，≤25字
- 清冷人设，句号收尾
- 不要解释规则细节
- 不要渲染恐慌，不要说"严厉打击"
- 不要称呼"老板"
- 像随口说一句那样自然

只返回那句话，不要任何前后缀。"""

_EXPLAIN_FALLBACKS = [
    "刚清掉一个发广告的，大家继续聊。",
    "处理了一个广告号，不用在意。",
    "清掉了一个打广告的，正常聊就行。",
    "刚有人发广告被处理了，放心聊。",
]


def explain_enforcement_to_chat(
    bot,
    chat_id: int,
    uname: str,
    reason: str,
    config: dict,
    ai_engine=None,
) -> bool:
    """广告处置后给群内 AI 上下文说明。

    Returns:
        True=发送成功，False=发送失败或功能未开启
    """
    cfg = config or {}
    if not cfg.get("AD_AI_AUTO_REPLY_ENABLED", False):
        return False

    if not bot or not chat_id:
        return False

    try:
        if ai_engine is None:
            from core.ai_engine import AIEngine
            ai_engine = AIEngine(cfg)

        prompt = _EXPLAIN_PROMPT_TEMPLATE.format(
            uname=(uname or "某用户")[:30],
            reason=(reason or "广告检测")[:80],
        )
        explain_text = ai_engine.ask(prompt, mode="normal", retry=2)
        if not explain_text or len(explain_text.strip()) < 2:
            explain_text = random.choice(_EXPLAIN_FALLBACKS)
        else:
            explain_text = explain_text.strip().split("\n")[0][:60]

        bot.send_message(chat_id, explain_text)
        logger.info(f"[AI-Explain] 已发群内说明 chat={chat_id} text={explain_text[:30]}")
        return True
    except Exception as e:
        logger.warning(f"[AI-Explain] 说明失败 chat={chat_id}: {e}")
        return False


# ──────────────────────────────────────────────────────
# 4. 头像 AI 复核（视觉模型判断头像是否含营销话术）
# ──────────────────────────────────────────────────────

_AVATAR_REVIEW_PROMPT = """你是 Telegram 入群头像安全审核器。请直接观察整张头像，
不要只做 OCR，也不要因为贴纸、文字遮挡而忽略主体画面。

只允许返回下面一个标签，不要 JSON、解释、标点或其他文字：
- ADULT_HIGH：主体画面明确裸露或强烈性化地突出臀部、私密部位、胸部，或展示性行为
- MARKETING_HIGH：主体是明确的加好友、客服、下注、代购、色情资源等营销引流海报
- QR_HIGH：主体包含清晰可扫码二维码
- SAFE：正常真人、卡通、风景、宠物、品牌标志；普通运动或泳装但未刻意突出私密部位
- UNSURE：画面太小、模糊、遮挡，或证据不足

只有证据明确时返回 *_HIGH；拿不准必须返回 UNSURE。"""


_AVATAR_LABEL_RESULTS = {
    "ADULT_HIGH": (True, "adult", 0.99, "明确成人低俗头像"),
    "MARKETING_HIGH": (True, "marketing", 0.97, "明确营销引流头像"),
    "QR_HIGH": (True, "qr", 0.97, "明确二维码头像"),
    "SAFE": (False, "normal", 0.98, "头像正常"),
    "UNSURE": (False, "unknown", 0.0, "视觉证据不足"),
}


def review_avatar_with_vision(
    image_bytes: bytes,
    config: dict,
    user_id: int = None,
) -> dict:
    """用视觉模型复核头像。

    Returns:
        {"is_ad": bool, "type": str, "confidence": float, "desc": str, "used_ai": bool}
    """
    cfg = config or {}
    if not cfg.get("AD_AVATAR_AI_REVIEW_ENABLED", False):
        return {"is_ad": False, "type": "unknown", "confidence": 0.0, "desc": "未开启", "used_ai": False}

    if not image_bytes:
        return {"is_ad": False, "type": "unknown", "confidence": 0.0, "desc": "无图片数据", "used_ai": False}

    try:
        from core.ai_engine import analyze_image
        raw = analyze_image(image_bytes, _AVATAR_REVIEW_PROMPT, cfg)
        if not raw:
            return {"is_ad": False, "type": "unknown", "confidence": 0.0, "desc": "AI无响应", "used_ai": False}

        raw_stripped = raw.strip()
        if raw_stripped.startswith("```"):
            raw_stripped = raw_stripped.strip("`")
            if raw_stripped.lower().startswith("json"):
                raw_stripped = raw_stripped[4:].strip()

        label = raw_stripped.strip().upper()
        if label in _AVATAR_LABEL_RESULTS:
            is_ad, ad_type, confidence, desc = _AVATAR_LABEL_RESULTS[label]
        else:
            # 兼容灰度发布期间旧模型返回的 JSON；新提示词只接受固定标签。
            result = json.loads(raw_stripped)
            is_ad = bool(result.get("is_ad", False))
            ad_type = str(result.get("type", "unknown"))
            try:
                confidence = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            desc = str(result.get("desc", ""))[:50]

        logger.info(
            f"[AI-Avatar-Review] uid={user_id} is_ad={is_ad} type={ad_type} "
            f"confidence={confidence:.2f} desc={desc}"
        )
        return {
            "is_ad": is_ad,
            "type": ad_type,
            "confidence": confidence,
            "desc": desc,
            "used_ai": True,
        }
    except json.JSONDecodeError as e:
        logger.debug(f"[AI-Avatar-Review] JSON解析失败 uid={user_id}: {e}")
        return {"is_ad": False, "type": "unknown", "confidence": 0.0, "desc": "AI响应格式错误", "used_ai": False}
    except Exception as e:
        logger.warning(f"[AI-Avatar-Review] 调用失败 uid={user_id}: {e}")
        return {"is_ad": False, "type": "unknown", "confidence": 0.0, "desc": f"AI调用异常: {e}", "used_ai": False}
