from __future__ import annotations

import time
import random
import concurrent.futures
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

_append_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="append")


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
    """构建同一行的“联系 Mory / 自助下单”双按钮。"""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("联系 Mory", url="https://t.me/Moryfansbot"),
        InlineKeyboardButton("自助下单", url="https://t.me/MorychannelBot"),
    )
    return markup


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


def _direct_access_reply(is_priv: bool = False) -> str:
    if is_priv:
        return (
            "给你入口啦，别再兜圈。\n"
            "预览：https://t.me/moryselect\n"
            "自助下单：https://t.me/MorychannelBot"
        )
    return (
        "入口给你，自己去看就行。\n"
        "预览群 @moryselect\n"
        "自助下单 @MorychannelBot"
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

    if mode == "convert":
        stage_hint, notify_admin_reason = _build_convert_hint(db, uid, conv_count)
    elif mode in ("treehole", "dream"):
        stage_hint, notify_admin_reason = _build_emotional_hint(conv_count)
    elif mode == "normal":
        stage_hint, notify_admin_reason = _build_normal_hint(conv_count)

    # [TRAE SOLO CN] v5.19.0 意图路由联动：根据 dctx.intent 增强 stage_hint
    _intent = getattr(dctx, "intent", None) or {}
    _intent_label = _intent.get("intent", "chat")
    if _intent.get("source", "disabled") != "disabled":
        if _intent_label == "flirt":
            stage_hint += "\n【意图-调戏】：用户在调戏/撩你。保持清冷傲娇人设，可以适当回撩但不主动，留悬念。"
        elif _intent_label == "purchase_intent":
            stage_hint += "\n【意图-购买】：用户有明确购买意向。自然引导 @MorychannelBot 自助下单，别催。"
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

    if resp is None and mode == "convert" and _is_direct_access_request(msg):
        resp = _direct_access_reply(is_priv=is_priv)
        logger.info(f"🔗 直接入口回复 uid={uid} mode={mode}")

    ai_attempted = False
    if resp is None:
        ai_attempted = True
        resp = ai.ask(msg, mode=mode, tools=use_tools, is_priv=is_priv, stage_hint=stage_hint, user_profile=user_profile)

    needs_handoff = _should_offer_handoff(
        resp,
        faq_hit_id=_faq_hit_id,
        ai_attempted=ai_attempted,
        mode=mode,
        is_priv=is_priv,
    )
    if needs_handoff and not resp:
        resp = "这个我不乱说。你可以直接问 Mory，或者去自助下单看看。"

    if resp is None:
        resp = _final_ai_reply_fallback(mode, is_priv=is_priv)
        try:
            from modules.auto_tasks import report_fault
            report_fault("AI引擎故障", f"mode={mode}，AI重试耗尽，已发送降级兜底", "🚨" if mode != "normal" else "⚠️",
                         f"用户消息: {msg[:80]}")
        except Exception as notify_err:
            logger.error(f"故障通知发送失败: {notify_err}")

    if resp:
        handoff_markup = _build_unresolved_handoff_markup() if needs_handoff else None
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

        if is_group and mode == "normal" and conv_count >= 2:
            append_text = _append_conv_response(dctx, conv_count)
            if append_text:
                resp += append_text

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


def _build_convert_hint(db, uid, conv_count) -> tuple:
    stage_hint = ""
    notify_admin_reason = ""
    consult_count = db.get_user_consult_count(uid)

    if consult_count <= 1:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【转化-首次-A】：用户第一次问消费类问题。直接告诉他：找 @MorychannelBot，自己看。别啰嗦，带点小傲娇就行。"
        elif _variants == 2:
            stage_hint = "\n【转化-首次-B】：用户第一次问。给路径：@MorychannelBot 自助下单，按提示来。语气温柔带点撩，别太生硬。"
        else:
            stage_hint = "\n【转化-首次-C】：第一次问消费的事。简洁说：@MorychannelBot 下单，很简单。像随口说的，不是客服回答问题。"
    elif consult_count == 2:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【转化-二次-A】：又来问了？带点绿茶的小暧昧：你这么好奇呀…@MorychannelBot 那边都有啦，自己去看嘛～"
        elif _variants == 2:
            stage_hint = "\n【转化-二次-B】：还在问？说明心动了嘛。故意吊一下胃口：群里不方便说啦，@MorychannelBot 那边有你想看的，嗯？"
        else:
            stage_hint = "\n【转化-二次-C】：问两遍了哦...用撒娇带点小抱怨的语气：哎呀你怎么这么磨叽～去 @MorychannelBot 看一眼不就知道了嘛。"
    else:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【转化-多次-A】：你问题好多哦。行吧，我帮你问Mory，你等着。语气温柔带点无奈。"
        elif _variants == 2:
            stage_hint = "\n【转化-多次-B】：好吧好吧，我帮你跟她说一声，你别催啦。像哄小孩一样，但别太假。"
        else:
            stage_hint = "\n【转化-多次-C】：真能问...我转达一下，你等我消息嘛。带点小嫌弃但还是会帮忙的感觉。"
        notify_admin_reason = "convert_stuck"

    return stage_hint, notify_admin_reason


def _build_emotional_hint(conv_count) -> tuple:
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 4:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【情感-深度-A】：用户聊了好几轮，情绪复杂。温柔安慰完，带点心疼的语气：你这样我都心疼了…要不我帮你跟Mory说一声？她看到会来找你的。"
        elif _variants == 2:
            stage_hint = "\n【情感-深度-B】：多轮对话了，用户需要真人支持。软下来：别难过啦好不好？Mory人超nice的，要不我帮你转达给她？她会帮你的。"
        else:
            stage_hint = "\n【情感-深度-C】：聊了挺久了，用户情绪低落。用绿茶式的关心：你这样我都不知道怎么说了…等下我帮你告诉Mory好不好？她一定会回你的。"
        notify_admin_reason = "emotional_deep"
    elif conv_count >= 2:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【情感-引导-A】：用户情绪有点down。安慰完轻描淡写：其实Mory人真的超好的，你有啥想不开的也可以找她说说的。自然带出，不硬推。"
        else:
            stage_hint = "\n【情感-引导-B】：聊了两轮了，氛围挺走心。顺带一提：对了Mory平时也在的，你要是想找人说话，找她也行呀。像不经意提一个朋友。"

    return stage_hint, notify_admin_reason


def _build_normal_hint(conv_count) -> tuple:
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 6:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【闲聊-收网-A】：聊了很多轮了，该自然收尾了。带点不舍：跟你聊天好开心呀…对了@MorychannelBot 那边还有好多好玩的，你不去看看嘛？"
        elif _variants == 2:
            stage_hint = "\n【闲聊-收网-B】：聊了好久了，别硬聊下去。用撒娇收尾：哎呀不跟你说了啦，再说我都不想干活了～想看更多去 @MorychannelBot 自己解锁哦。"
        else:
            stage_hint = "\n【闲聊-收网-C】：多轮闲聊，温和引导。自然收：好啦今天先这样嘛，你要是想看点别的…@MorychannelBot 那边都有。像随口提一句。"
        notify_admin_reason = "chat_deep"
    elif conv_count >= 5:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【闲聊-深度-A】：聊了5轮以上，关系升温了。带点小暧昧：跟你聊天还挺有意思的…对了@MorychannelBot 那边还有更多有意思的哦？"
        else:
            stage_hint = "\n【闲聊-深度-B】：聊了好几轮，气氛不错。不经意说：你要是喜欢跟我聊的话…@MorychannelBot 那边还有群里不发的东西呢，你懂的。"
    elif conv_count >= 3:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【闲聊-升温-A】：聊了好几轮，气氛不错。故意神秘一点：对了，有个事一直没跟你说…@MorychannelBot 那边有些群里不发的，你不好奇嘛？"
        else:
            stage_hint = "\n【闲聊-升温-B】：聊了几轮，可以轻推一下。随口说：聊这么久了，要不要看点好东西？@MorychannelBot 那边自己去翻，我不说啦。像推荐小秘密。"

    return stage_hint, notify_admin_reason


def _append_conv_response(dctx: DispatchContext, conv_count: int) -> str:
    ai = dctx.ctx.ai
    seed_h = random.randint(100000, 999999)

    append_mode = None
    append_prompt = ""
    if conv_count >= 5 and random.randint(1, 10) <= 3:
        append_mode = "convert_soft"
        append_prompt = f"用户已和你连续聊了{conv_count}轮，自然收尾引导"
    elif conv_count >= 3 and random.randint(1, 10) <= 3:
        append_mode = "nudge"
        append_prompt = "用户和你聊得不错，不经意间植入暗示"
    elif random.randint(1, 10) <= 6:
        append_mode = "hook"
        append_prompt = "基于刚才的对话，用绿茶风反问结尾让对话继续"

    if append_mode:
        try:
            _append_future = _append_pool.submit(
                lambda: ai.ask(append_prompt, mode=append_mode, seed=seed_h))
            try:
                append_text = _append_future.result(timeout=5)
                if append_text:
                    return f"\n\n{append_text.strip()}"
            except concurrent.futures.TimeoutError:
                logger.info("连续对话追加超时（5秒），跳过")
        except Exception as e:
            logger.warning(f"连续对话追加失败（跳过）：{e}")

    return ""


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
