# -*- coding: utf-8 -*-
"""Growth optimization glue for intent, A/B, attribution, and quality loops.

This module is intentionally thin: it does not replace the existing intent router,
funnel state machine, telemetry, or quality evaluator. It connects those pieces so
the growth switches produce useful data and prompt guidance.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from core.logging_util import get_logger
from core.keyword_manager import is_convert_rejection_message
from core.telemetry import _detect_sentiment

logger = get_logger("growth_optimizer")


EXPERIMENTS: dict[str, str] = {
    "purchase_capture": "高购买意图自动收口",
    "product_recommendation": "3档产品智能推荐",
    "private_handoff": "私聊承接话术A/B",
    "broadcast_attribution": "播报内容转化归因",
    "persona_quality": "人设话术质量评分闭环",
    "cold_user_wakeup": "冷用户唤醒分层",
    "entertainment_conversion": "塔罗/树洞/解梦商业转化链",
    "button_style": "按钮文案和富文本样式实验",
    "ad_governance": "广告治理误伤漏放数据化",
    "funnel_optimization": "转化漏斗分段优化",
}

PRODUCTS = {
    "select": "至臻精选",
    "all_access": "至臻全享",
    "album": "精选图集",
}

_DIRECT_CUSTOM_ORDER_MARKERS = (
    "定制舞", "定制视频", "定制写真", "定制自拍", "定制内容", "私人定制",
    "专属定制", "专属舞", "专属视频", "给我跳", "给我拍", "按我的要求",
    "按我说的", "定做一个", "定制一个", "我要定制", "想定制", "要定制",
    "需要定制",
)

_CUSTOM_INFORMATION_MARKERS = (
    "是什么", "什么意思", "怎么理解", "介绍一下", "科普一下", "你知道",
)

_CUSTOM_THIRD_PARTY_MARKERS = (
    "她在", "他在", "别人", "看到有人", "听说有人", "好看吗",
)

_CUSTOM_REQUIREMENT_MARKERS = (
    "舞", "风格", "开场", "穿衣服", "脱衣服", "卡点", "变装", "动作",
    "音乐", "时长", "镜头", "服装", "结尾", "节奏", "姿势",
)

_CUSTOM_AFFIRMATION_MARKERS = (
    "就是这个味", "就是这种", "对就是", "这个方向", "风格可以",
    "挺喜欢", "很喜欢", "喜欢这种", "这个可以", "就按这个", "就这样",
)

_STRONG_SUBSCRIBE_READY_MARKERS = (
    "怎么下单", "我要下单", "直接下单", "下单吧", "怎么付费", "我要付费",
    "怎么订阅", "我要订阅", "订阅吧", "怎么开通", "我要开通", "怎么解锁",
    "我要解锁", "解锁吧", "充值", "续费",
)

# 这些动作短语可用于任何日常商品，必须通过正向业务门禁才允许进入订阅。
_GENERIC_PURCHASE_ACTION_MARKERS = (
    "怎么买", "我要买", "怎么购买", "我要购买", "就要这个", "选这个",
)

_BUSINESS_OBJECT_MARKERS = (
    "预览", "档位", "订阅", "定制", "mory", "套餐", "权益", "内容群", "频道",
)

_OPT_OUT_MARKERS = (
    "不要再推", "别再推", "别再推荐", "不要推荐", "别营销", "不要营销",
    "别发入口", "不要发入口", "退订提醒", "别提醒", "不要提醒",
)

_SUBSCRIPTION_PLAN_MARKERS = ("包月", "包季", "包年", "月付", "季付", "年付")

_PREVIEW_SEEN_MARKERS = (
    "看过预览", "看了预览", "预览看了", "预览看过", "看完预览", "预览看完",
    "预览群看过", "预览群看了",
)

_PREVIEW_REQUEST_MARKERS = (
    "预览", "试看", "样片", "照片", "自拍", "视频", "图集", "写真",
    "什么内容", "有什么内容", "能看什么", "有多少", "先看看", "想看看", "想看",
    "靠谱吗", "不放心", "怕被骗", "多少钱", "价格", "贵不贵", "太贵",
    "套餐", "档位", "权益", "区别", "群里有什么",
)

_PREVIEW_POSITIVE_MARKERS = (
    "挺喜欢", "很喜欢", "喜欢这个", "喜欢这种", "这个不错", "这个可以",
    "挺不错", "挺好的", "满意", "就它了",
)

_PREVIEW_NEGATIVE_MARKERS = (
    "不喜欢", "不合适", "不想要", "没兴趣", "一般", "算了", "不用了", "不买",
)

CONVERSION_TARGET_NONE = "none"
CONVERSION_TARGET_PREVIEW = "preview"
CONVERSION_TARGET_SUBSCRIBE = "subscribe"


@dataclass
class GrowthContext:
    experiment_id: str
    experiment_name: str
    variant: str
    intent: str
    product: str
    source: str
    event: str
    stage_hint: str


def load_recent_conversation(
    db: Any,
    uid: int,
    chat_id: int,
    *,
    limit: int = 3,
    max_age_seconds: int = 1800,
) -> list[dict[str, Any]]:
    """读取同一用户、同一聊天的短期业务上下文，供当前轮承接。

    优先使用独立的 ``business_conversation_context``；它不属于遥测，也不受
    ``raw_event_text`` 开关影响。仅当旧数据库尚未创建该表时才回退读取旧遥测。
    """
    if not db or not uid or not getattr(db, "conn", None):
        return []
    get_context = getattr(db, "get_recent_business_context", None)
    if callable(get_context):
        try:
            return get_context(uid, chat_id, limit=limit, max_age_seconds=max_age_seconds)
        except Exception as e:
            logger.debug(f"读取短期业务上下文失败 uid={uid} chat={chat_id}: {e}")
    safe_limit = max(1, min(int(limit or 3), 6))
    cutoff = int(time.time()) - max(60, int(max_age_seconds or 1800))
    sql = (
        "SELECT message_text, bot_reply_text, intent, ts "
        "FROM conversation_telemetry "
        "WHERE user_id=? AND chat_id=? AND ts>=? "
        "ORDER BY id DESC LIMIT ?"
    )
    try:
        lock = getattr(db, "lock", None)
        if lock:
            with lock:
                rows = db.conn.execute(sql, (uid, chat_id, cutoff, safe_limit)).fetchall()
        else:
            rows = db.conn.execute(sql, (uid, chat_id, cutoff, safe_limit)).fetchall()
    except Exception as e:
        logger.debug(f"读取近期对话失败 uid={uid} chat={chat_id}: {e}")
        return []

    history: list[dict[str, Any]] = []
    for user_text, assistant_text, intent, ts in reversed(rows):
        if user_text:
            history.append({
                "role": "user",
                "content": str(user_text)[:500],
                "intent": str(intent or ""),
                "ts": int(ts or 0),
            })
        if assistant_text:
            history.append({
                "role": "assistant",
                "content": str(assistant_text)[:500],
                "intent": str(intent or ""),
                "ts": int(ts or 0),
            })
    return history


def get_conversion_state(db: Any, uid: int, chat_id: int) -> dict[str, Any]:
    """读取已结构化的拒绝/CTA/阶段状态；数据库不可用时安全降级为空。"""
    getter = getattr(db, "get_conversion_state", None)
    if not callable(getter):
        return {}
    try:
        value = getter(uid, chat_id)
        return value if isinstance(value, dict) else {}
    except Exception as e:
        logger.debug("读取转化状态失败 uid=%s chat=%s: %s", uid, chat_id, e)
        return {}


def persist_conversion_decision(
    db: Any, uid: int, chat_id: int, target: str, reason: str
) -> None:
    """立即持久化拒绝；明确询价/购买才解除，避免概率跳过回复时丢状态。"""
    if not db or not uid:
        return
    try:
        if reason == "user_opt_out":
            setter = getattr(db, "set_conversion_opt_out", None)
            if callable(setter):
                setter(uid, chat_id)
        elif target in {CONVERSION_TARGET_PREVIEW, CONVERSION_TARGET_SUBSCRIBE}:
            clearer = getattr(db, "clear_conversion_opt_out", None)
            if callable(clearer):
                clearer(uid, chat_id)
    except Exception as e:
        logger.debug("持久化转化决策失败 uid=%s chat=%s: %s", uid, chat_id, e)


def is_direct_custom_order_request(text: str) -> bool:
    """明确描述定制服务时直接进入下单承接，不先重复发预览。"""
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    return (
        bool(compact)
        and not is_convert_rejection_message(compact)
        and not any(marker in compact for marker in _CUSTOM_INFORMATION_MARKERS)
        and not any(marker in compact for marker in _CUSTOM_THIRD_PARTY_MARKERS)
        and any(marker in compact for marker in _DIRECT_CUSTOM_ORDER_MARKERS)
    )


def _recent_assistant_has_entry(
    history: list[dict[str, Any]] | None,
    *entries: str,
) -> bool:
    normalized_entries = tuple(entry.lower() for entry in entries)
    for item in list(history or [])[-6:]:
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "").lower()
        if any(entry in content for entry in normalized_entries):
            return True
    return False


def _looks_like_custom_requirements(text: str, has_custom_context: bool) -> bool:
    marker_count = sum(1 for marker in _CUSTOM_REQUIREMENT_MARKERS if marker in text)
    actions = ("要", "想", "给我", "按", "做", "拍", "跳", "开场", "结尾", "穿衣服", "脱衣服")
    if marker_count >= 3 and any(action in text for action in actions):
        return True
    return has_custom_context and marker_count >= 2


def _is_opt_out_message(compact: str) -> bool:
    return is_convert_rejection_message(compact) or any(marker in compact for marker in _OPT_OUT_MARKERS)


def _has_explicit_preview_seen(text: str) -> bool:
    """兼容“预览我已经看过了/预览我刚看完”等自然语序。"""
    compact = re.sub(r"\s+", "", str(text or "").lower())
    return bool(
        re.search(r"预览.{0,8}(?:看过|看了|看完)", compact)
        or re.search(r"(?:看过|看了|看完).{0,8}预览", compact)
    )


def _is_explicit_generic_purchase_action(
    compact: str,
    *,
    has_business_context: bool,
) -> bool:
    """通用购买动词必须靠当前业务对象、已有上下文或纯动作句才能成立。

    不能维护“咖啡/鞋/课程”等无穷黑名单：未知日常商品默认不是本业务购买。
    """
    matches_generic = any(marker in compact for marker in _GENERIC_PURCHASE_ACTION_MARKERS)
    if not matches_generic:
        return False
    if any(marker in compact for marker in _BUSINESS_OBJECT_MARKERS):
        return True
    if has_business_context:
        return True
    return compact in _GENERIC_PURCHASE_ACTION_MARKERS


def resolve_conversion_target(
    text: str,
    history: list[dict[str, Any]] | None = None,
    *,
    mode: str = "normal",
    state: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """统一判定本轮唯一成交目标：无入口、先看预览或自助订阅。"""
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    if not compact:
        return CONVERSION_TARGET_NONE, "empty_message"
    if _is_opt_out_message(compact):
        return CONVERSION_TARGET_NONE, "user_opt_out"

    recent = list(history or [])[-6:]
    recent_order_cta = _recent_assistant_has_entry(
        recent, "@morychannelbot", "自助下单", "自助订阅"
    )
    structured_state = state or {}
    state_order_cta = (
        structured_state.get("recent_cta_target") == CONVERSION_TARGET_SUBSCRIBE
        and int(structured_state.get("recent_cta_at") or 0) >= int(time.time()) - 1800
    )
    recent_order_cta = recent_order_cta or state_order_cta

    prior_user_texts = [
        str(item.get("content") or "").lower()
        for item in recent
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    recent_custom_context = bool(structured_state.get("custom_context")) or any(
        is_direct_custom_order_request(previous)
        or _looks_like_custom_requirements(previous, has_custom_context=False)
        for previous in prior_user_texts
    )
    recent_preview_context = bool(structured_state.get("preview_context")) or any(
        any(marker in previous for marker in _PREVIEW_REQUEST_MARKERS)
        or _has_explicit_preview_seen(previous)
        for previous in prior_user_texts
    ) or _recent_assistant_has_entry(recent, "@moryselect", "预览群")
    has_business_context = recent_custom_context or recent_preview_context
    generic_purchase_action = any(marker in compact for marker in _GENERIC_PURCHASE_ACTION_MARKERS)
    explicit_subscribe = (
        any(marker in compact for marker in _STRONG_SUBSCRIBE_READY_MARKERS)
        or _is_explicit_generic_purchase_action(compact, has_business_context=has_business_context)
    )
    explicit_preview = any(marker in compact for marker in _PREVIEW_REQUEST_MARKERS)
    if structured_state.get("opt_out") and not (explicit_subscribe or explicit_preview):
        return CONVERSION_TARGET_NONE, "persisted_opt_out"

    # 上游关键词路由可能因“鞋怎么买”误判为 convert；未知商品默认不触发。
    if generic_purchase_action and not explicit_subscribe:
        return CONVERSION_TARGET_NONE, "ambiguous_purchase_action"
    if explicit_subscribe:
        return CONVERSION_TARGET_SUBSCRIBE, "explicit_purchase"
    if any(plan in compact for plan in _SUBSCRIPTION_PLAN_MARKERS) and any(
        action in compact for action in ("我要", "我选", "就选", "决定要", "开这个", "订这个", "下单")
    ):
        return CONVERSION_TARGET_SUBSCRIBE, "explicit_plan_choice"
    if any(plan in compact for plan in _SUBSCRIPTION_PLAN_MARKERS):
        return CONVERSION_TARGET_PREVIEW, "plan_question_needs_preview"
    if _has_explicit_preview_seen(compact):
        if any(marker in compact for marker in _PREVIEW_NEGATIVE_MARKERS):
            return CONVERSION_TARGET_NONE, "preview_not_interested"
        if recent_order_cta:
            return CONVERSION_TARGET_NONE, "recent_order_cta_suppressed"
        return CONVERSION_TARGET_SUBSCRIBE, "preview_confirmed"

    if any(marker in compact for marker in _CUSTOM_INFORMATION_MARKERS):
        return CONVERSION_TARGET_NONE, "custom_information_only"
    if is_direct_custom_order_request(compact):
        if recent_order_cta:
            return CONVERSION_TARGET_NONE, "recent_order_cta_suppressed"
        return CONVERSION_TARGET_SUBSCRIBE, "explicit_custom_order"
    if _looks_like_custom_requirements(compact, recent_custom_context):
        if recent_order_cta:
            return CONVERSION_TARGET_NONE, "recent_order_cta_suppressed"
        return CONVERSION_TARGET_SUBSCRIBE, "custom_requirements"
    if recent_custom_context and any(marker in compact for marker in _CUSTOM_AFFIRMATION_MARKERS):
        if recent_order_cta:
            return CONVERSION_TARGET_NONE, "recent_order_cta_suppressed"
        return CONVERSION_TARGET_SUBSCRIBE, "positive_after_custom"
    if recent_preview_context and any(marker in compact for marker in _PREVIEW_POSITIVE_MARKERS):
        if recent_order_cta:
            return CONVERSION_TARGET_NONE, "recent_order_cta_suppressed"
        return CONVERSION_TARGET_SUBSCRIBE, "positive_after_preview"
    if explicit_preview:
        return CONVERSION_TARGET_PREVIEW, "preview_or_objection"
    # ``mode=convert`` 是宽松上游分类，不能单独授权发入口；价格、内容、
    # 预览、套餐等明确业务信号已在上方逐项判定。
    return CONVERSION_TARGET_NONE, "no_conversion_signal"


def is_contextual_purchase_intent(text: str, history: list[dict[str, Any]] | None) -> bool:
    """识别“就是这个味/这种风格/卡点变装”等承接式购买意图。"""
    target, _ = resolve_conversion_target(text, history, mode="normal")
    return target == CONVERSION_TARGET_SUBSCRIBE


def is_enabled(config: dict[str, Any] | None) -> bool:
    cfg = config or {}
    return bool(cfg.get("GROWTH_OPTIMIZER_ENABLED", True))


def assign_variant(uid: int, experiment_id: str, config: dict[str, Any] | None = None) -> str:
    """Stable A/B assignment. Returns Base when A/B is disabled."""
    cfg = config or {}
    if not cfg.get("AB_TEST_ENABLED", False):
        return "Base"
    raw = f"{uid}:{experiment_id}".encode("utf-8", errors="ignore")
    bucket = int(hashlib.sha1(raw).hexdigest()[:8], 16) % 100
    split = int((cfg.get("GROWTH_AB_SPLIT", 50) or 50))
    return "A" if bucket < split else "B"


def pick_experiment(intent: str, mode: str, is_priv: bool, text: str) -> str:
    text = (text or "").lower()
    if intent == "purchase_intent" or mode == "convert":
        if any(k in text for k in ("区别", "哪个", "套餐", "档", "年付", "季付", "月付", "图集", "全享")):
            return "product_recommendation"
        return "purchase_capture"
    if is_priv:
        return "private_handoff"
    if mode in ("tarot", "treehole", "dream", "fortune"):
        return "entertainment_conversion"
    if intent == "complaint":
        return "persona_quality"
    if intent == "flirt":
        return "funnel_optimization"
    if any(k in text for k in ("按钮", "点哪里", "链接", "入口", "bot", "机器人")):
        return "button_style"
    return "funnel_optimization"


def recommend_product(text: str, user_profile: dict[str, Any] | None = None) -> str:
    text = (text or "").lower()
    profile = user_profile or {}
    tags = " ".join(str(x) for x in profile.get("tags", []) or [])
    interests = " ".join(str(x) for x in profile.get("interests", []) or [])
    blob = f"{text} {tags} {interests}"
    if any(k in blob for k in ("全享", "全部", "年付", "长期", "所有", "vip", "至尊")):
        return "all_access"
    if any(k in blob for k in ("图集", "照片", "图片", "相册", "photo")):
        return "album"
    return "select"


def event_for_intent(intent: str, mode: str, text: str) -> str:
    text = text or ""
    if mode == "convert" or intent == "purchase_intent":
        if any(k in text for k in ("下单", "付款", "支付", "开通", "买", "订阅")):
            return "carted"
        return "consulted"
    if intent in ("flirt", "consult") or mode in ("tarot", "treehole", "dream"):
        return "interested"
    if intent == "complaint":
        return "complaint"
    return "touched"


def build_growth_context(dctx: Any, mode: str, conv_count: int, user_profile: dict[str, Any] | None = None) -> GrowthContext:
    """Build prompt guidance and attribution metadata for the current reply."""
    config = getattr(dctx.ctx, "config", {}) or {}
    intent_data = getattr(dctx, "intent", None) or {}
    intent = intent_data.get("intent", "chat")
    text = getattr(dctx, "text", "") or ""
    experiment_id = pick_experiment(intent, mode, bool(getattr(dctx, "is_priv", False)), text)
    product = recommend_product(text, user_profile)
    variant = assign_variant(getattr(dctx, "uid", 0), experiment_id, config)
    event = event_for_intent(intent, mode, text)
    source = "private" if getattr(dctx, "is_priv", False) else "group"
    stage_hint = build_stage_hint(
        experiment_id,
        variant,
        intent,
        mode,
        product,
        conv_count,
        conversion_target=getattr(dctx, "conversion_target", "none"),
    )
    return GrowthContext(
        experiment_id=experiment_id,
        experiment_name=EXPERIMENTS.get(experiment_id, experiment_id),
        variant=variant,
        intent=intent,
        product=product,
        source=source,
        event=event,
        stage_hint=stage_hint,
    )


def build_stage_hint(
    experiment_id: str,
    variant: str,
    intent: str,
    mode: str,
    product: str,
    conv_count: int,
    *,
    conversion_target: str = "subscribe",
) -> str:
    product_name = PRODUCTS.get(product, PRODUCTS["select"])
    prefix = f"\n【增长实验-{EXPERIMENTS.get(experiment_id, experiment_id)}-{variant}】"
    if conversion_target == "preview":
        return (
            prefix
            + "当前仍是了解阶段：先回答问题，只自然带一次 @moryselect 预览入口；"
            "不要出现下单入口、价格承诺或催促。"
        )
    if conversion_target == "none":
        return (
            prefix
            + "当前没有成交目标：保持人设并承接正在聊的话题，不因轮数或实验分组硬塞私聊、预览或下单入口。"
        )
    if experiment_id == "purchase_capture":
        return prefix + "用户已明确要继续。回应当前需求后只带一次 @MorychannelBot 查看当前选项并自助完成，不催不硬卖。"
    if experiment_id == "product_recommendation":
        if variant == "A":
            return prefix + f"结合现有事实说明{product_name}适合谁，再补一句可去 @MorychannelBot 看当前档位；不能编造价格或权益。"
        return prefix + f"围绕用户当前需求说明{product_name}，再轻带 @MorychannelBot；不列未经确认的价格或福利。"
    if experiment_id == "private_handoff":
        if variant == "A":
            return prefix + "私聊承接用温柔直接型：简短回答问题，再给下一步入口。"
        return prefix + "私聊承接用悬念型：给一点信息但保留空间，引导继续问或去 @MorychannelBot。"
    if experiment_id == "entertainment_conversion":
        return prefix + "先完整回应当前体验；只有本轮成交目标明确时才轻带 @MorychannelBot，不能破坏情绪。"
    if experiment_id == "persona_quality":
        return prefix + "优先自然、共情、人设稳定。不要像客服，不要长篇解释；投诉先安抚再给处理路径。"
    if experiment_id == "button_style":
        return prefix + "用户明确索要下单入口。只给 @MorychannelBot，回复短且与按钮一致。"
    if experiment_id == "funnel_optimization":
        if conv_count >= 3:
            return prefix + "用户已有多轮互动。继续承接当前话题；本轮已明确要下单时才带 @MorychannelBot，不靠聊天轮数硬推。"
        return prefix + "记录当前漏斗阶段，回复保持真人感，避免过早强推。"
    return prefix + "回复保持自然，并留下可追踪的下一步行动。"


def _ensure_conversion_columns(conn: Any) -> None:
    cursor = conn.execute("PRAGMA table_info(conversion_events)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    column_defs = {
        "source": "TEXT DEFAULT ''",
        "campaign_id": "TEXT DEFAULT ''",
        "attribution_model": "TEXT DEFAULT ''",
        "weight": "REAL DEFAULT 0",
        "is_memory_assisted": "INTEGER DEFAULT 0",
    }
    for column, definition in column_defs.items():
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE conversion_events ADD COLUMN {column} {definition}")


def log_attribution_event(db: Any, uid: int, event: str, mode: str, source: str, campaign_id: str) -> None:
    if not db or not uid:
        return
    try:
        lock = getattr(db, "lock", None)
        conn = getattr(db, "conn", None)
        if conn is None:
            return
        if lock:
            with lock:
                _insert_conversion(conn, uid, event, mode, source, campaign_id)
                conn.commit()
        else:
            _insert_conversion(conn, uid, event, mode, source, campaign_id)
            conn.commit()
    except Exception as e:
        logger.debug(f"增长归因事件写入失败 uid={uid} event={event}: {e}")


def _insert_conversion(conn: Any, uid: int, event: str, mode: str, source: str, campaign_id: str) -> None:
    _ensure_conversion_columns(conn)
    conn.execute(
        "INSERT INTO conversion_events(uid, event, ts, mode, source, campaign_id) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, event, int(time.time()), mode or "", source or "", campaign_id or ""),
    )


def log_telemetry_event(db: Any, uid: int, chat_id: int, experiment_id: str, variant: str,
                        event_type: str, event_meta: dict[str, Any] | None = None) -> None:
    if not db or not uid or not hasattr(db, "log_telemetry"):
        return
    try:
        db.log_telemetry(uid, chat_id, experiment_id, variant, event_type, 0.0, event_meta or {})
    except Exception as e:
        logger.debug(f"增长遥测事件写入失败 uid={uid} event={event_type}: {e}")


def record_growth_reply(db: Any, dctx: Any, growth: GrowthContext, mode: str,
                        user_message: str, bot_reply: str, round_num: int = 0,
                        config: dict[str, Any] | None = None,
                        *, persist_business_context: bool = True) -> None:
    """Persist growth metrics; conversation text requires explicit config opt-in."""
    if not growth:
        return
    uid = getattr(dctx, "uid", 0)
    chat_id = getattr(dctx, "chat_id", 0)
    if persist_business_context:
        _record_business_context(db, dctx, user_message, bot_reply, growth.intent)
    log_attribution_event(db, uid, growth.event, mode, growth.source, growth.experiment_id)
    log_telemetry_event(
        db, uid, chat_id, growth.experiment_id, growth.variant,
        "engage",
        {"intent": growth.intent, "product": growth.product, "source": growth.source},
    )
    try:
        if hasattr(db, "log_conversation_telemetry"):
            evolution_config = (config or {}).get("REPLY_EVOLUTION_CONFIG", {}) or {}
            raw_event_text = bool(evolution_config.get("raw_event_text", False))
            stored_message = (user_message or "")[:500] if raw_event_text else ""
            stored_reply = (bot_reply or "")[:500] if raw_event_text else ""
            db.log_conversation_telemetry(
                uid,
                chat_id,
                growth.experiment_id,
                growth.variant,
                stored_message,
                stored_reply,
                growth.intent,
                _detect_sentiment(user_message or ""),
                int(round_num or 0),
            )
    except Exception as e:
        logger.debug(f"增长对话遥测写入失败 uid={uid}: {e}")


def _record_business_context(
    db: Any,
    dctx: Any,
    user_message: str,
    bot_reply: str,
    intent: str = "",
) -> None:
    """把可回复的短期上下文独立写入业务表，不污染 raw-off 遥测。"""
    recorder = getattr(db, "record_business_context", None)
    if not callable(recorder):
        return
    try:
        recorder(
            getattr(dctx, "uid", 0),
            getattr(dctx, "chat_id", 0),
            user_message,
            bot_reply,
            intent=intent,
            conversion_target=getattr(dctx, "conversion_target", "none"),
            conversion_reason=getattr(dctx, "conversion_reason", ""),
        )
    except Exception as e:
        logger.debug("短期业务上下文写入失败 uid=%s: %s", getattr(dctx, "uid", 0), e)


def record_business_reply_context(
    db: Any,
    dctx: Any,
    user_message: str,
    bot_reply: str,
    intent: str = "",
) -> None:
    """供增长开关关闭的主回复路径调用；语义与 record_growth_reply 保持一致。"""
    _record_business_context(db, dctx, user_message, bot_reply, intent)


def summarize_growth(db: Any, days: int = 7) -> list[dict[str, Any]]:
    """Aggregate the ten growth tracks from conversion_events and telemetry_events."""
    if not db or not hasattr(db, "conn"):
        return []
    cutoff = int(time.time()) - max(1, min(int(days), 90)) * 86400
    result = []
    try:
        c = db.conn.cursor()
        _ensure_conversion_columns(db.conn)
        for experiment_id, name in EXPERIMENTS.items():
            c.execute(
                "SELECT event, COUNT(*) FROM conversion_events "
                "WHERE ts>=? AND campaign_id=? GROUP BY event",
                (cutoff, experiment_id),
            )
            event_counts = {row[0]: row[1] for row in c.fetchall()}
            telemetry_counts = {}
            try:
                c.execute(
                    "SELECT event_type, COUNT(*) FROM telemetry_events "
                    "WHERE ts>=? AND experiment_id=? GROUP BY event_type",
                    (cutoff, experiment_id),
                )
                telemetry_counts = {row[0]: row[1] for row in c.fetchall()}
            except Exception:
                telemetry_counts = {}
            total = sum(event_counts.values())
            result.append({
                "experiment_id": experiment_id,
                "name": name,
                "events": event_counts,
                "telemetry": telemetry_counts,
                "total_events": total,
            })
        return result
    except Exception as e:
        logger.warning(f"增长优化汇总失败: {e}")
        return []


def experiments_as_json() -> str:
    return json.dumps(EXPERIMENTS, ensure_ascii=False, sort_keys=True)
