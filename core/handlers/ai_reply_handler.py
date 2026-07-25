from __future__ import annotations

import time
import random
import re
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from core.logging_util import get_logger, clear_logging_context
from core.helpers import format_user_mention

# 【v5.31.2 修复】VPS 运行在 UTC，时段/日期相关逻辑必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))

if TYPE_CHECKING:
    from core.message_dispatcher import DispatchContext

logger = get_logger("ai_reply_handler")

def _final_ai_reply_fallback(mode: str, is_priv: bool = False) -> str:
    """处理失败时给用户的兜底回复。

    [Bug-01 修复] 兜底文案统一走 ai_engine.get_fallback_text()，
    与 ai_engine._final_fallback_reply / ai_handlers._final_ai_reply_fallback 保持一致。
    """
    from core.ai_engine import get_fallback_text
    return get_fallback_text(mode, is_priv=is_priv)


_DIRECT_ACCESS_KEYWORDS = (
    "链接给我", "给链接", "发链接", "发个链接", "链接发我", "链接来一个",
    "群链接", "群入口", "入口", "地址", "网址",
    "怎么加群", "怎么进群", "怎么入群", "加群", "进群", "入群",
    "预览群", "预览链接", "自助下单", "下单链接", "下单入口",
    "自助机器人", "下单机器人", "订单机器人",
)

_QUESTION_MARKERS = (
    "什么", "怎么", "如何", "哪里", "在哪", "多少", "谁", "为何", "为什么",
    "有没有", "是不是", "能不能", "可不可以", "可以吗", "能吗", "干嘛", "吗",
)

_UNRESOLVED_REPLY_MARKERS = (
    "不确定", "不清楚", "不知道", "无法确认", "不能确认", "说不准",
    "问mory", "问 mory", "联系mory", "联系 mory",
)

_CUSTOM_DETAIL_MARKERS = (
    "舞", "舞蹈", "开场", "穿衣服", "服装", "卡点", "变装", "镜头", "风格",
)

_PREFERENCE_CONFIRM_MARKERS = (
    "就是这个", "这个味", "这种风格", "这个风格", "挺喜欢", "喜欢这种",
    "风格可以", "就这个", "就这种", "不错", "确定", "安排",
)


def _looks_like_question(text: str) -> bool:
    """识别群里应主动承接的自然语言问题。"""
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    if len(compact) < 3:
        return False
    if compact.endswith(("?", "？")):
        return True
    return any(marker in compact for marker in _QUESTION_MARKERS)


def _should_offer_handoff(
    response,
    *,
    faq_hit_id: int = 0,
    ai_attempted: bool = False,
    mode: str = "normal",
    is_priv: bool = False,
) -> bool:
    """FAQ未命中且 AI 无法可靠回答时，给用户明确的人工/自助出口。"""
    if faq_hit_id or not ai_attempted:
        return False
    if response is None:
        return True
    if not isinstance(response, str):
        return False
    if not response.strip():
        return True
    text = response.strip()
    if text == _final_ai_reply_fallback(mode, is_priv=is_priv):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _UNRESOLVED_REPLY_MARKERS)


def _build_unresolved_handoff_markup():
    """未解决问题只给人工入口，禁止和下单入口混在同一轮。"""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=1)
    markup.row(
        InlineKeyboardButton("联系 Mory", url="https://t.me/Moryfansbot"),
    )
    return markup


def _build_purchase_markup():
    """明确购买/定制意图只给下一步下单，不再把用户送回预览。"""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=1)
    markup.row(
        InlineKeyboardButton("🛒 自助下单", url="https://t.me/MorychannelBot"),
    )
    return markup


def _build_preview_markup():
    """了解、价格和内容咨询只给预览入口。"""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=1)
    markup.row(
        InlineKeyboardButton("👀 查看预览", url="https://t.me/moryselect"),
    )
    return markup


def _build_sales_reply_markup(
    *,
    is_priv: bool,
    needs_handoff: bool,
    conversion_target: str,
):
    """私聊不挂销售按钮；非私聊每轮也只保留一个目标。"""
    if is_priv:
        return None
    if needs_handoff:
        return _build_unresolved_handoff_markup()
    if conversion_target == "subscribe":
        return _build_purchase_markup()
    if conversion_target == "preview":
        return _build_preview_markup()
    return None


def _recent_order_cta_sent(history) -> bool:
    """近期助手已给过下单入口时，本轮不再机械重复。"""
    for item in list(history or [])[-6:]:
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "").lower()
        if "@morychannelbot" in content or "自助下单" in content:
            return True
    return False


def _recent_conversion_cta_sent(history) -> bool:
    """近期已有任一成交入口时，普通闲聊不再随机追加销售话术。"""
    for item in list(history or [])[-6:]:
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "").lower()
        if "@morychannelbot" in content or "@moryselect" in content:
            return True
    return False


def _is_order_access_request(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    return any(
        marker in compact
        for marker in (
            "怎么下单", "我要下单", "下单链接", "下单入口", "自助下单",
            "自助机器人", "下单机器人", "订单机器人", "怎么买", "我要买",
        )
    )


def _build_contextual_purchase_reply(text: str, *, include_cta: bool = True) -> str:
    """模型不可用时的最小承接兜底，不承诺未经业务证实的定制能力。"""
    compact = re.sub(r"\s+", "", str(text or ""))
    if any(marker in compact for marker in _PREFERENCE_CONFIRM_MARKERS):
        if not include_cta:
            return "对，就是这个方向，风格对上了。"
        return "对，就是这个方向。想继续的话去 @MorychannelBot 看当前可选内容和档位。"
    if any(marker in compact for marker in ("开场", "穿衣服", "服装", "卡点", "变装", "镜头")):
        if not include_cta:
            return "开场、服装和卡点这些细节我接住了。"
        return (
            "开场、服装和卡点这些细节我接住了。"
            "想继续的话去 @MorychannelBot 看当前可选内容和档位。"
        )
    if any(marker in compact for marker in _CUSTOM_DETAIL_MARKERS):
        if not include_cta:
            return "这个方向接得上，你可以继续说具体偏好。"
        return "这个方向接得上。想继续的话去 @MorychannelBot 看当前可选内容和档位。"
    if not include_cta:
        return "这个方向可以，接着按刚才的思路聊。"
    return "想继续的话去 @MorychannelBot 看当前可选内容和档位。"


def _strip_entry_sentence(text: str, entries: tuple[str, ...]) -> str:
    chunks = re.split(r"(?<=[。！？!?\n])", str(text or ""))
    kept = [
        chunk for chunk in chunks
        if not any(entry in chunk.lower() for entry in entries)
    ]
    return "".join(kept).strip()


def _align_conversion_reply(
    response,
    *,
    conversion_target: str,
    conversion_reason: str,
):
    """保留模型的人设承接，只校正本轮唯一入口。"""
    if not isinstance(response, str) or not response.strip():
        return response
    text = response.strip()
    if conversion_target == "none":
        text = _strip_entry_sentence(
            text,
            ("morychannelbot", "moryselect", "自助下单", "自助订阅", "下单入口", "订阅入口"),
        )
        if text:
            return text
        if conversion_reason == "recent_order_cta_suppressed":
            return "对，这个方向接得上，细节继续按你说的来。"
        return "你先说说具体想了解哪一部分，我按你问的讲。"

    if conversion_target == "subscribe":
        text = _strip_entry_sentence(text, ("moryselect", "预览群"))
        if "morychannelbot" not in text.lower():
            prefix = text.rstrip()
            if prefix and prefix[-1] not in "。！？!?～~\n":
                prefix += "。"
            text = (
                f"{prefix}想继续的话去 @MorychannelBot "
                "看看当前可选内容和档位，按提示自助完成就行。"
            )
        return text

    if conversion_target == "preview":
        text = _strip_entry_sentence(text, ("morychannelbot", "自助下单", "自助订阅"))
        if "moryselect" not in text.lower():
            prefix = text.rstrip()
            if prefix and prefix[-1] not in "。！？!?～~\n":
                prefix += "。"
            text = f"{prefix}想先了解的话去 @moryselect 看预览，合不合适你自己判断。"
        return text

    return text


def _should_offer_proactive_preview(
    *,
    mode: str,
    conv_count: int,
    history,
    text: str,
) -> bool:
    """普通聊天只在关系已热且没有近期入口时低频推进到预览。"""
    if mode != "normal" or conv_count < 4 or _recent_conversion_cta_sent(history):
        return False
    from core.keyword_manager import is_convert_rejection_message
    if is_convert_rejection_message(str(text or "")):
        return False
    return random.randint(1, 100) <= 15


def _is_direct_access_request(text: str) -> bool:
    """用户明确要入口/链接时，直接收口，避免 LLM 继续闲聊跑偏。"""
    if not text:
        return False
    compact = re.sub(r"\s+", "", text.lower())
    if any(k in compact for k in _DIRECT_ACCESS_KEYWORDS):
        return True
    if "链接" in compact and any(k in compact for k in ("给", "发", "要", "有", "哪里", "在哪")):
        return True
    if "群" in compact and any(k in compact for k in ("加", "进", "入", "入口", "链接", "在哪", "哪里")):
        return True
    if "机器人" in compact and any(k in compact for k in ("自助", "下单", "链接", "入口", "给", "发", "找")):
        return True
    return False


def _direct_access_reply(text: str, is_priv: bool = False) -> str:
    """一次只给一个入口：明确下单给订单入口，其余入口请求先给预览。"""
    compact = re.sub(r"\s+", "", str(text or "").lower())
    wants_order = any(
        marker in compact
        for marker in ("自助下单", "下单链接", "下单入口", "自助机器人", "下单机器人", "订单机器人")
    )
    if wants_order:
        return (
            "自助下单：https://t.me/MorychannelBot"
            if is_priv
            else "自助下单 @MorychannelBot"
        )
    return (
        "预览：https://t.me/moryselect"
        if is_priv
        else "预览群 @moryselect"
    )


def _dispatch_p10_ai(dctx: DispatchContext):
    from core.message_dispatcher import (
        _conv_tracker, _conv_lock, _CONV_TIMEOUT,
        _cleanup_conv_tracker, _generate_late_night_warning,
        _get_function_tools, _handle_tool_calls,
        _calc_humanized_delay, _split_for_private, _delayed_reply,
    )

    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_priv = dctx.is_priv
    is_group = dctx.is_group
    mory_bot = ctx.mory_bot
    ai = ctx.ai

    analysis = getattr(dctx, '_analysis', None)
    if analysis is None:
        from modules.group_mgr import detect_keywords
        analysis = detect_keywords(msg, CONFIG)

    mode = analysis["mode"]
    is_at    = f"@{ctx.bot_username}" in msg
    is_reply = m.reply_to_message and m.reply_to_message.from_user.id == ctx.bot_id

    fortune_bonus = False
    if mode == "normal" and random.randint(1, 100) <= 5:
        fortune_bonus = True

    # [v5.14.0] 显式列举非 normal 模式，确保 convert/tarot/treehole/dream/feedback/contact_mory
    # 模式都强制回复（不受 REPLY_CHANCE 限制），避免未来新增 mode 被误伤
    _non_normal_modes = ("convert", "tarot", "treehole", "dream", "feedback", "contact_mory")
    should_reply = (
        is_priv
        or is_at
        or is_reply
        or mode in _non_normal_modes
        or (
            CONFIG.get("FAQ_TRACKING_ENABLED", False)
            and _looks_like_question(msg)
        )
        or random.randint(1, 100) <= CONFIG.get("REPLY_CHANCE", 10)
    )

    if not should_reply:
        clear_logging_context()
        return

    from modules.content import is_late_night
    if is_late_night() and is_group:
        late_night_text = _generate_late_night_warning(ai, uname, is_group, uid)
        mory_bot.reply_and_track(m, late_night_text)
        clear_logging_context()
        return

    conv_count = 0
    if is_group and (is_at or is_reply) and mode == "normal":
        now_ts = time.time()
        _cleanup_conv_tracker()
        with _conv_lock:
            if uid in _conv_tracker:
                if now_ts - _conv_tracker[uid]["last_time"] > _CONV_TIMEOUT:
                    # [v5.33] 超时重置：内存计数归1，DB 也同步重置
                    _conv_tracker[uid] = {"count": 1, "last_time": now_ts}
                else:
                    _conv_tracker[uid]["count"] += 1
                    _conv_tracker[uid]["last_time"] = now_ts
            else:
                # [v5.33] 新会话：从 DB 读取持久化轮次作为初始基线（重启不重置）
                _db_count = 0
                try:
                    _db_count = db.users.get_conversation_turn(uid)
                except Exception as _e:
                    logger.debug(f"读取 conv_turn 失败 uid={uid}: {_e}")
                # DB 有历史则续接 +1，无则新会话从 1 开始
                _init_count = _db_count + 1 if _db_count > 0 else 1
                _conv_tracker[uid] = {"count": _init_count, "last_time": now_ts}
            conv_count = _conv_tracker[uid]["count"]
        # [v5.33] 同步到 DB 持久化（异步 try/except，不阻塞主流程）
        try:
            db.users.update_conversation_turn(uid, conv_count)
        except Exception as _e:
            logger.debug(f"同步 conv_turn 到 DB 失败 uid={uid}: {_e}")

    bot.send_chat_action(chat_id, "typing")

    # [v5.15.0] FAQ追踪：记录用户问题（FAQ_TRACKING_ENABLED 开关控制）
    _faq_qid = 0
    _faq_hit_id = 0
    try:
        if CONFIG.get('FAQ_TRACKING_ENABLED', False):
            # 根据 mode 映射 question_category
            _category_map = {
                'convert': 'pricing',
                'contact_mory': 'troubleshooting',
                'feedback': 'feedback',
                'tarot': 'content',
                'treehole': 'content',
                'dream': 'content',
            }
            _q_category = _category_map.get(mode, 'other')
            _is_convert = 1 if mode == 'convert' else 0
            _keyword_tag = analysis.get('keyword_tag', '') or ''
            _faq_qid = db.log_question(
                uid=uid,
                chat_id=chat_id,
                question_text=msg[:500],
                mode=mode,
                intent='',
                keyword_tag=_keyword_tag,
                question_category=_q_category,
                is_convert=_is_convert,
            )
            if _faq_qid:
                logger.debug(f"📋 FAQ追踪：记录问题 id={_faq_qid} uid={uid} mode={mode} category={_q_category}")
    except Exception as _faq_err:
        logger.error(f"📋 FAQ追踪记录失败（不影响AI回复）：{_faq_err}")

    use_tools = None
    if is_group and mode == "normal":
        use_tools = _get_function_tools()

    stage_hint = ""
    notify_admin_reason = ""
    conversation_history = getattr(dctx, "conversation_history", [])
    from core.growth_optimizer import resolve_conversion_target
    conversion_target, conversion_reason = resolve_conversion_target(
        msg,
        conversation_history,
        mode=mode,
    )
    current_thread_turns = 1 + sum(
        1
        for item in conversation_history
        if isinstance(item, dict) and item.get("role") == "user"
    )
    if (
        conversion_target == "none"
        and _should_offer_proactive_preview(
            mode=mode,
            conv_count=current_thread_turns,
            history=conversation_history,
            text=msg,
        )
    ):
        conversion_target = "preview"
        conversion_reason = "proactive_preview_after_warmup"
    dctx.conversion_target = conversion_target
    dctx.conversion_reason = conversion_reason

    if mode == "convert":
        stage_hint, notify_admin_reason = _build_convert_hint(
            db,
            uid,
            conv_count,
            conversion_target=conversion_target,
            conversion_reason=conversion_reason,
        )
    elif mode in ("treehole", "dream"):
        stage_hint, notify_admin_reason = _build_emotional_hint(conv_count)
    elif mode == "normal":
        stage_hint, notify_admin_reason = _build_normal_hint(
            conv_count,
            proactive_preview=conversion_reason == "proactive_preview_after_warmup",
        )

    # [TRAE SOLO CN] v5.19.0 意图路由联动：根据 dctx.intent 增强 stage_hint
    _intent = getattr(dctx, "intent", None) or {}
    _intent_label = _intent.get("intent", "chat")
    purchase_ready = conversion_target == "subscribe"
    repeat_cta_suppressed = conversion_reason == "recent_order_cta_suppressed"
    if purchase_ready and _intent_label != "purchase_intent":
        _intent = {
            "intent": "purchase_intent",
            "confidence": 0.95,
            "source": "context_rule",
        }
        dctx.intent = _intent
        _intent_label = "purchase_intent"
    if _intent.get("source", "disabled") != "disabled":
        if _intent_label == "flirt":
            stage_hint += "\n【意图-调戏】：用户在调戏/撩你。保持清冷傲娇人设，可以适当回撩但不主动，留悬念。"
        elif _intent_label == "purchase_intent":
            if repeat_cta_suppressed:
                stage_hint += "\n【意图-购买承接】：近期已经给过下单入口。本轮只接住用户确认的风格或新增细节，不重复任何链接、入口或按钮。"
            elif conversion_target == "none":
                stage_hint += "\n【意图-不推进】：规则判定本轮只需解释或停止转化，正常回答当前问题，不带任何成交入口。"
            elif conversion_target == "preview":
                stage_hint += "\n【意图-了解】：先回答用户当前问题，只自然带一次 @moryselect 预览入口，不催下单。"
            else:
                stage_hint += "\n【意图-购买】：用户已明确要继续。自然带一次 @MorychannelBot 自助入口，别催，不承诺未确认的服务、价格或交付。"
        elif _intent_label == "complaint":
            stage_hint += "\n【意图-投诉】：用户在抱怨/投诉。先共情安抚，承诺转达 Mory，别辩解。"
        elif _intent_label == "consult":
            stage_hint += "\n【意图-咨询】：用户在咨询问题。简洁回答，别长篇大论，必要时引导自助。"

    user_profile = None
    try:
        user_profile = db.users.get_user_persona_profile(uid)
    except Exception as e:
        logger.debug(f"操作异常: {e}")

    growth_ctx = None
    if CONFIG.get("GROWTH_OPTIMIZER_ENABLED", True):
        try:
            from core.growth_optimizer import build_growth_context
            growth_ctx = build_growth_context(dctx, mode, conv_count, user_profile=user_profile)
            if growth_ctx and growth_ctx.stage_hint:
                stage_hint += growth_ctx.stage_hint
        except Exception as e:
            logger.debug(f"增长优化上下文构建失败 uid={uid}: {e}")

    # [v5.15.0] FAQ自动回复匹配（AI调用前拦截，节省API费用）
    resp = None
    try:
        if CONFIG.get('FAQ_AUTO_REPLY_ENABLED', False):
            from core.handlers.ai_handlers import _try_faq_match
            faq_resp, _faq_hit_id = _try_faq_match(db, CONFIG, ai, msg, mode, analysis)
            if faq_resp is not None:
                resp = faq_resp
                logger.info(f"📋 FAQ自动回复命中 uid={uid} mode={mode} faq_id={_faq_hit_id}")
    except Exception as _faq_err:
        logger.debug(f"📋 FAQ匹配异常(静默跳过): {_faq_err}")

    direct_access_handled = False
    direct_access_order = False
    if resp is None and mode == "convert" and _is_direct_access_request(msg):
        direct_access_handled = True
        direct_access_order = _is_order_access_request(msg)
        resp = _direct_access_reply(msg, is_priv=is_priv)
        logger.info(f"🔗 直接入口回复 uid={uid} mode={mode}")

    ai_attempted = False
    if resp is None:
        ai_attempted = True
        resp = ai.ask(
            msg,
            mode=mode,
            tools=use_tools,
            is_priv=is_priv,
            stage_hint=stage_hint,
            user_profile=user_profile,
            conversation_history=getattr(dctx, "conversation_history", []),
        )

    if direct_access_handled and not direct_access_order:
        conversion_target = "preview"
        conversion_reason = "direct_preview_access"
    elif direct_access_handled:
        conversion_target = "subscribe"
        conversion_reason = "direct_order_access"
    resp = _align_conversion_reply(
        resp,
        conversion_target=conversion_target,
        conversion_reason=conversion_reason,
    )

    needs_handoff = _should_offer_handoff(
        resp,
        faq_hit_id=_faq_hit_id,
        ai_attempted=ai_attempted,
        mode=mode,
        is_priv=is_priv,
    )
    if needs_handoff:
        conversion_target = "none"
        conversion_reason = "unresolved_handoff"
        resp = _align_conversion_reply(
            resp or "",
            conversion_target=conversion_target,
            conversion_reason=conversion_reason,
        )
        if "@moryfansbot" not in str(resp or "").lower():
            prefix = str(resp or "").strip()
            if prefix and prefix[-1] not in "。！？!?～~\n":
                prefix += "。"
            resp = f"{prefix}这个我不乱说，直接问 @Moryfansbot。"

    if resp is None:
        resp = _final_ai_reply_fallback(mode, is_priv=is_priv)
        try:
            from modules.auto_tasks import report_fault
            report_fault("AI引擎故障", f"mode={mode}，AI重试耗尽，已发送降级兜底", "🚨" if mode != "normal" else "⚠️",
                         f"用户消息: {msg[:80]}")
        except Exception as notify_err:
            logger.error(f"故障通知发送失败: {notify_err}")

    if resp:
        handoff_markup = _build_sales_reply_markup(
            is_priv=is_priv,
            needs_handoff=needs_handoff,
            conversion_target=conversion_target,
        )
        if isinstance(resp, dict):
            tool_result = _handle_tool_calls(resp, bot, m, CONFIG, db)
            if tool_result:
                resp = tool_result
            else:
                resp = resp.get("content") or ""

        if isinstance(resp, str) and resp:
            from modules.content import draw_tarot, get_fortune
            if mode == "tarot":
                resp = draw_tarot(uname) + "\n\n" + resp
            if fortune_bonus:
                resp += f"\n\n🎴 今日签：{get_fortune()}"

            # [TRAE SOLO CN v5.24.0 阶段3-A] 记录 assistant 回复到记忆缓冲
            try:
                from core.memory_summarizer import record_message
                record_message(uid, "assistant", resp)
            except Exception as e:
                # 【v5.31.2 修复】记忆缓冲写入失败会导致长上下文记忆退化，必须 warning
                logger.warning(f"记录 assistant 回复到记忆缓冲失败 uid={uid}: {e}")

        delay = _calc_humanized_delay(resp, is_priv, conv_count, CONFIG)

        should_split = (
            is_priv
            and len(resp) > 60
            and random.randint(1, 100) <= 30
            and conv_count < 3
        )
        hour_now = datetime.now(_CST).hour
        if is_priv and 0 <= hour_now < 5 and len(resp) > 60 and random.randint(1, 100) <= 50:
            should_split = True

        if should_split:
            parts = _split_for_private(resp)
            if len(parts) == 2:
                _delayed_reply(bot, chat_id, m, parts[0], delay, mory_bot, is_priv)
                part2_delay = delay + random.uniform(2.0, 5.0)
                _delayed_reply(
                    bot,
                    chat_id,
                    m,
                    parts[1],
                    part2_delay,
                    mory_bot,
                    is_priv,
                    reply_markup=handoff_markup,
                )
            else:
                _delayed_reply(
                    bot,
                    chat_id,
                    m,
                    resp,
                    delay,
                    mory_bot,
                    is_priv,
                    reply_markup=handoff_markup,
                )
        else:
            _delayed_reply(
                bot,
                chat_id,
                m,
                resp,
                delay,
                mory_bot,
                is_priv,
                reply_markup=handoff_markup,
            )

        if is_priv:
            try:
                admin_id = CONFIG.get("ADMIN_ID", 0)
                if admin_id and uid != admin_id:
                    if CONFIG.get('RELAY_MODE_ENABLED', False):
                        from core.handlers.relay_handler import forward_ai_reply_to_admin
                        forward_ai_reply_to_admin(bot, db, CONFIG, uid, uname, resp, chat_id, source_type='private')
                    else:
                        msg_display = msg[:200] + "..." if len(msg) > 200 else msg
                        resp_display = resp[:500] + "..." if len(resp) > 500 else resp
                        safe_msg = msg_display.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                        safe_resp = resp_display.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                        bot.send_message(admin_id,
                            f"📩 私聊通知\n"
                            f"👤 {format_user_mention(uid, uname)}\n"
                            f"💬 你：{safe_msg}\n"
                            f"🤖 Mory回复：{safe_resp}",
                            parse_mode="HTML")
            except Exception as e:
                logger.warning(f"私聊转发通知失败 uid={uid}：{e}")

        # 群聊 AI 回复转发给管理员（中继模式开启时）
        if is_group and CONFIG.get('RELAY_MODE_ENABLED', False):
            try:
                from core.handlers.relay_handler import forward_ai_reply_to_admin
                group_name = m.chat.title or ""
                forward_ai_reply_to_admin(bot, db, CONFIG, uid, uname, resp, chat_id, source_type='group', group_name=group_name)
            except Exception as e:
                logger.debug(f"群聊AI回复转发失败（静默）：{e}")

        if mode == "convert":
            db.log_conversion_event(uid, "consulted")

        if growth_ctx:
            try:
                from core.growth_optimizer import record_growth_reply
                record_growth_reply(db, dctx, growth_ctx, mode, msg, resp, round_num=conv_count)
            except Exception as e:
                logger.debug(f"增长优化埋点失败 uid={uid}: {e}")

        if notify_admin_reason:
            _notify_admin_for_deep_conversation(dctx, mode, conv_count, notify_admin_reason)

        logger.info(f"💬 回复 uid={uid}  mode={mode}  len={len(resp)}  conv={conv_count}")

        # [v5.15.0] FAQ追踪：更新AI回复摘要+FAQ命中ID
        try:
            if _faq_qid and isinstance(resp, str) and resp:
                summary = resp[:100]
                if needs_handoff:
                    summary = f"[UNRESOLVED] {summary}"[:200]
                db.update_question_reply(_faq_qid, summary, faq_hit_id=_faq_hit_id)
                logger.debug(f"📋 FAQ追踪：更新回复摘要 id={_faq_qid} faq_hit={_faq_hit_id}")
        except Exception as _faq_err:
            logger.error(f"📋 FAQ追踪更新回复失败（不影响AI回复）：{_faq_err}")
    else:
        logger.warning(f"⚠️ AI未能生成回复 uid={uid}")
    clear_logging_context()


def _build_convert_hint(
    db,
    uid,
    conv_count,
    *,
    conversion_target: str = "preview",
    conversion_reason: str = "",
) -> tuple:
    """成交话术只描述本轮目标，随机性留给人设措辞而不是跳步。"""
    notify_admin_reason = ""
    consult_count = db.get_user_consult_count(uid)

    if conversion_reason == "recent_order_cta_suppressed":
        stage_hint = (
            "\n【转化-继续聊】：近期已给过下单入口。只承接当前细节和口味，"
            "不要重复任何入口、链接或按钮，也不要像客服催单。"
        )
    elif conversion_reason in {"user_opt_out", "custom_information_only"}:
        stage_hint = (
            "\n【转化-不推进】：按用户当前问题正常回答；概念咨询只解释，拒绝则停止推销。"
            "本轮不得出现预览、下单、订阅或人工承诺。"
        )
    elif conversion_target == "subscribe":
        stage_hint = random.choice((
            "\n【转化-自助】：先接住用户刚说的具体需求，再自然带一次 @MorychannelBot；只说可查看当前可选内容和档位并按提示自助完成，不承诺未确认的定制能力、价格或交付。",
            "\n【转化-自助】：语气保持清冷、自然，回应当前话题后只给一个 @MorychannelBot 入口；不要再发预览，不要催促，也不要编造表单或服务承诺。",
            "\n【转化-自助】：用户已明确要继续。用一两句人话承接，再轻带 @MorychannelBot 查看当前选项；不写客服流程，不同时出现其他入口。",
        ))
    elif conversion_target == "preview":
        stage_hint = random.choice((
            "\n【转化-先预览】：先回答价格、内容或权益问题，再自然带一次 @moryselect 让用户自己看预览；不要直接催下单。",
            "\n【转化-先预览】：用户仍在了解阶段。保持人设正常接话，只给 @moryselect 这一个入口，让他看完再判断。",
            "\n【转化-先预览】：先解决当前疑问，再轻带 @moryselect；不出现 @MorychannelBot，不制造稀缺感或压力。",
        ))
    else:
        stage_hint = "\n【转化-仅回答】：当前没有可执行成交目标，只回答用户正在问的内容，不塞入口。"

    if consult_count >= 3:
        notify_admin_reason = "convert_stuck"

    return stage_hint, notify_admin_reason


def _build_emotional_hint(conv_count) -> tuple:
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 4:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【情感-深度-A】：用户聊了好几轮，情绪复杂。先温柔接住，不虚构已经转达或承诺谁会来回复；确实需要真人时再给联系 Mory 的真实入口。"
        elif _variants == 2:
            stage_hint = "\n【情感-深度-B】：多轮对话需要真人支持。语气软一点，先听对方说完；只建议可联系 Mory，不说“我已转达”或“她一定会回复”。"
        else:
            stage_hint = "\n【情感-深度-C】：用户情绪低落，先共情并问清最需要什么；需要人工时给真实联系入口，不表演转交流程，不许诺结果。"
        notify_admin_reason = "emotional_deep"
    elif conv_count >= 2:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【情感-引导-A】：用户情绪有点低落。先共情，再围绕他刚说的内容回应；不急着转人工，也不转成销售话题。"
        else:
            stage_hint = "\n【情感-引导-B】：氛围走心时保持温柔和克制，继续听对方说；只有对方明确需要真人帮助时再给联系入口。"

    return stage_hint, notify_admin_reason


def _build_normal_hint(conv_count, *, proactive_preview: bool = False) -> tuple:
    """多轮闲聊优先延续当前话题；只有已决策的低频轮次才推进预览。"""
    notify_admin_reason = "chat_deep" if conv_count >= 6 else ""
    if proactive_preview:
        stage_hint = random.choice((
            "\n【闲聊-低频推进】：先回应当前话题，再像分享一个顺手入口一样轻带 @moryselect；只去预览，不催下单。",
            "\n【闲聊-低频推进】：保持刚才的语气和话题连贯，结尾自然提一次 @moryselect 可以先看看；不要突然变客服。",
            "\n【闲聊-低频推进】：承接当前内容后轻轻把话题连到预览，只有 @moryselect 一个入口，不夸大、不施压。",
        ))
    elif conv_count >= 2:
        stage_hint = (
            "\n【闲聊-连续承接】：继续回答对方刚才的话，沿用最近上下文和人设语气；"
            "不要因为聊天轮数增加就突然销售、收网或另起一个无关话题。"
        )
    else:
        stage_hint = ""
    return stage_hint, notify_admin_reason


def _notify_admin_for_deep_conversation(dctx: DispatchContext, mode: str, conv_count: int, reason: str):
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname

    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            _safe_msg = msg.replace("<", "&lt;").replace(">", "&gt;")[:150]
            if reason == "convert_stuck":
                consult_count = db.get_user_consult_count(uid)
                _label = "🔥 用户多次咨询未下单"
                _detail = f"📊 已咨询{consult_count}次\n💡 建议人工介入"
            elif reason == "emotional_deep":
                _label = "💙 用户情感求助多轮"
                _detail = f"📊 已聊{conv_count}轮\n💡 建议Mory亲自关心"
            elif reason == "chat_deep":
                _label = "💬 用户闲聊多轮未转化"
                _detail = f"📊 已聊{conv_count}轮\n💡 建议Mory主动互动"
            else:
                _label = "📌 用户需要关注"
                _detail = f"📊 mode={mode} conv={conv_count}"
            bot.send_message(admin_id,
                f"{_label}\n"
                f"👤 {format_user_mention(uid, uname)}\n"
                f"💬 消息：{_safe_msg}\n"
                f"{_detail}",
                parse_mode="HTML")
    except Exception as e:
        logger.warning(f"管理员通知失败 uid={uid} reason={reason}：{e}")
