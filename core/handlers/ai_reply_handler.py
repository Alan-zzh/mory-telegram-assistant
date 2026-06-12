from __future__ import annotations

import time
import random
import concurrent.futures
from datetime import datetime
from typing import TYPE_CHECKING

from core.logging_util import get_logger, clear_logging_context
from core.helpers import format_user_mention

if TYPE_CHECKING:
    from core.message_dispatcher import DispatchContext

logger = get_logger("ai_reply_handler")

_append_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="append")


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
                    _conv_tracker[uid] = {"count": 1, "last_time": now_ts}
                else:
                    _conv_tracker[uid]["count"] += 1
                    _conv_tracker[uid]["last_time"] = now_ts
            else:
                _conv_tracker[uid] = {"count": 1, "last_time": now_ts}
            conv_count = _conv_tracker[uid]["count"]

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

    user_profile = None
    try:
        user_profile = db.users.get_user_profile(uid)
    except Exception:
        pass

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

    if resp is None:
        resp = ai.ask(msg, mode=mode, tools=use_tools, is_priv=is_priv, stage_hint=stage_hint, user_profile=user_profile)

    if resp is None:
        try:
            from modules.auto_tasks import report_fault
            report_fault("AI引擎故障", f"mode={mode}，用户消息无法回复", "🚨" if mode != "normal" else "⚠️",
                         f"用户消息: {msg[:80]}")
        except Exception as notify_err:
            logger.error(f"故障通知发送失败: {notify_err}")

    if resp:
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
        hour_now = datetime.now().hour
        if is_priv and 0 <= hour_now < 5 and len(resp) > 60 and random.randint(1, 100) <= 50:
            should_split = True

        if should_split:
            parts = _split_for_private(resp)
            if len(parts) == 2:
                _delayed_reply(bot, chat_id, m, parts[0], delay, mory_bot, is_priv)
                part2_delay = delay + random.uniform(2.0, 5.0)
                _delayed_reply(bot, chat_id, m, parts[1], part2_delay, mory_bot, is_priv)
            else:
                _delayed_reply(bot, chat_id, m, resp, delay, mory_bot, is_priv)
        else:
            _delayed_reply(bot, chat_id, m, resp, delay, mory_bot, is_priv)

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

        if notify_admin_reason:
            _notify_admin_for_deep_conversation(dctx, mode, conv_count, notify_admin_reason)

        logger.info(f"💬 回复 uid={uid}  mode={mode}  len={len(resp)}  conv={conv_count}")

        # [v5.15.0] FAQ追踪：更新AI回复摘要+FAQ命中ID
        try:
            if _faq_qid and isinstance(resp, str) and resp:
                db.update_question_reply(_faq_qid, resp[:100], faq_hit_id=_faq_hit_id)
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
            stage_hint = "\n【转化-首次-A】：用户第一次问消费类问题。直接告诉：自助下单找 @MorychannelBot 按提示操作即可，简洁说明档位。语气温柔但不撩人，重点是给出明确操作路径。"
        elif _variants == 2:
            stage_hint = "\n【转化-首次-B】：用户首次咨询消费类。引导自助：找 @MorychannelBot 就能下单，操作很简单。语气亲切自然，像朋友推荐一样，别太正式。"
        else:
            stage_hint = "\n【转化-首次-C】：用户刚问消费类问题。直接给路径：@MorychannelBot 是自助下单机器人，按提示选就行。简短明了，别啰嗦，让用户知道怎么操作。"
    elif consult_count == 2:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【转化-二次-A】：用户再次询问，有兴趣但犹豫。用撩人话术引导下单，给预览诱饵：@moryselect 有初步预览，每周更新海量资源。可以撩一下但核心还是引导下单。"
        elif _variants == 2:
            stage_hint = "\n【转化-二次-B】：用户又来问了，说明心动了。换个角度撩：先给甜头 @moryselect 看看预览，再引导 @MorychannelBot 下单。语气带点小暧昧，让用户觉得不买亏了。"
        else:
            stage_hint = "\n【转化-二次-C】：用户第二次咨询，还在观望。用好奇心驱动：'好多人在 @moryselect 那边都看过了，你也可以先看看～'，然后自然引导 @MorychannelBot 下单。别催，要勾。"
    else:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【转化-多次-A】：用户问了3次以上还没下单，需要人工介入。告诉用户：'我帮你转达Mory，等我这的回复谢谢。'语气温柔真诚，让用户感到被重视。"
        elif _variants == 2:
            stage_hint = "\n【转化-多次-B】：用户反复咨询但没下单，可能需要Mory亲自来。说：'我帮你跟Mory说一声，她看到会来找你的，稍等哦～'让用户觉得有人在为他操心。"
        else:
            stage_hint = "\n【转化-多次-C】：多次咨询未转化，转人工。说：'你的问题我帮你转给Mory了，她会亲自回复你的，等我消息～'语气诚恳，给用户安全感。"
        notify_admin_reason = "convert_stuck"

    return stage_hint, notify_admin_reason


def _build_emotional_hint(conv_count) -> tuple:
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 4:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【情感-深度-A】：用户聊了好几轮，情绪复杂。安慰完后说：'我帮你跟Mory说一声吧，她看到会来找你的～'让用户知道有人在背后关心ta。"
        elif _variants == 2:
            stage_hint = "\n【情感-深度-B】：多轮对话了，用户可能需要真人支持。安慰后温柔说：'要不要我帮你转达给Mory？她人超好的，会帮你的～'给用户一个出口，不硬推。"
        else:
            stage_hint = "\n【情感-深度-C】：聊了挺久了，用户情绪需要更多关注。说：'我帮你通知Mory吧，等她回复你，她一定会的～'语气温暖坚定，让用户有依靠感。"
        notify_admin_reason = "emotional_deep"
    elif conv_count >= 2:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【情感-引导-A】：用户情绪需要持续关注。安慰完后轻描淡写：'其实Mory人也很nice的，有啥想说的也可以跟她说～'。自然带出，不硬推。"
        else:
            stage_hint = "\n【情感-引导-B】：聊了两轮了，用户可能需要更多支持。安慰后顺带提：'Mory平时也在线的，有啥事找她也行～'。像不经意提到一个朋友，不刻意。"

    return stage_hint, notify_admin_reason


def _build_normal_hint(conv_count) -> tuple:
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 6:
        _variants = random.choice([1, 2, 3])
        if _variants == 1:
            stage_hint = "\n【闲聊-收网-A】：聊了很多轮了，自然收尾。说：'我帮你跟Mory说一声，让她来看看你～'，或者'跟你聊天好开心～@MorychannelBot 那边还有更多好玩的哦'。二选一。"
        elif _variants == 2:
            stage_hint = "\n【闲聊-收网-B】：聊了好久，该收了。自然说：'下次再聊～对了，@moryselect 每周都有新内容，你可以看看'，或者'我帮你转达给Mory，让她来找你玩～'。选一个。"
        else:
            stage_hint = "\n【闲聊-收网-C】：多轮闲聊，温和引导。'好啦今天先这样～想看更多的话 @MorychannelBot 那边解锁就行'，或者'我帮你通知Mory，让她来陪你～'。自然过渡。"
        notify_admin_reason = "chat_deep"
    elif conv_count >= 5:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【闲聊-深度-A】：聊了5轮以上，关系升温了。自然暗示：'跟你聊天好开心～@MorychannelBot 那边可以直接解锁更多内容哦'。"
        else:
            stage_hint = "\n【闲聊-深度-B】：聊了好几轮，气氛不错。不经意提：'你要是喜欢这里，@moryselect 有超多好东西，每周更新～'。"
    elif conv_count >= 3:
        _variants = random.choice([1, 2])
        if _variants == 1:
            stage_hint = "\n【闲聊-升温-A】：聊了好几轮，气氛不错。不经意提：'对了，你知道 @moryselect 吗？那边有超多好东西，每周都更新～'。自然植入，不硬推。"
        else:
            stage_hint = "\n【闲聊-升温-B】：聊了几轮，可以轻推一下。随口说：'群里还有 @MorychannelBot 可以解锁更多内容哦～'。像推荐一个好玩的地方，不刻意。"

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
