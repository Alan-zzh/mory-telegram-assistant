# -*- coding: utf-8 -*-
"""Growth optimization glue for intent, A/B, attribution, and quality loops.

This module is intentionally thin: it does not replace the existing intent router,
funnel state machine, telemetry, or quality evaluator. It connects those pieces so
the growth switches produce useful data and prompt guidance.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from core.logging_util import get_logger
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
    stage_hint = build_stage_hint(experiment_id, variant, intent, mode, product, conv_count)
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


def build_stage_hint(experiment_id: str, variant: str, intent: str, mode: str, product: str, conv_count: int) -> str:
    product_name = PRODUCTS.get(product, PRODUCTS["select"])
    prefix = f"\n【增长实验-{EXPERIMENTS.get(experiment_id, experiment_id)}-{variant}】"
    if experiment_id == "purchase_capture":
        return prefix + "用户有购买意向。先给清楚路径：去 @MorychannelBot 自助下单；再用一句自然话术降低犹豫，不催不硬卖。"
    if experiment_id == "product_recommendation":
        if variant == "A":
            return prefix + f"优先推荐{product_name}。先解释适合谁，再补一句可去 @MorychannelBot 选对应档位。"
        return prefix + f"优先推荐{product_name}。先用用户利益点表达，再轻带 @MorychannelBot，不列太多价格。"
    if experiment_id == "private_handoff":
        if variant == "A":
            return prefix + "私聊承接用温柔直接型：简短回答问题，再给下一步入口。"
        return prefix + "私聊承接用悬念型：给一点信息但保留空间，引导继续问或去 @MorychannelBot。"
    if experiment_id == "entertainment_conversion":
        return prefix + "先完成当前塔罗/树洞/解梦体验，结尾只轻轻带一句更多内容可去 @MorychannelBot，不能破坏情绪。"
    if experiment_id == "persona_quality":
        return prefix + "优先自然、共情、人设稳定。不要像客服，不要长篇解释；投诉先安抚再给处理路径。"
    if experiment_id == "button_style":
        return prefix + "用户在找入口。明确说 @MorychannelBot 是入口，回复短、按钮/链接说明清楚。"
    if experiment_id == "funnel_optimization":
        if conv_count >= 3:
            return prefix + "用户已有多轮互动。自然把关系推进到私聊或 @MorychannelBot，不要重复闲聊打转。"
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
                        user_message: str, bot_reply: str, round_num: int = 0) -> None:
    """Persist attribution, experiment, and conversation telemetry after a reply."""
    if not growth:
        return
    uid = getattr(dctx, "uid", 0)
    chat_id = getattr(dctx, "chat_id", 0)
    log_attribution_event(db, uid, growth.event, mode, growth.source, growth.experiment_id)
    log_telemetry_event(
        db, uid, chat_id, growth.experiment_id, growth.variant,
        "engage",
        {"intent": growth.intent, "product": growth.product, "source": growth.source},
    )
    try:
        if hasattr(db, "log_conversation_telemetry"):
            db.log_conversation_telemetry(
                uid,
                chat_id,
                growth.experiment_id,
                growth.variant,
                (user_message or "")[:500],
                (bot_reply or "")[:500],
                growth.intent,
                _detect_sentiment(user_message or ""),
                int(round_num or 0),
            )
    except Exception as e:
        logger.debug(f"增长对话遥测写入失败 uid={uid}: {e}")


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
