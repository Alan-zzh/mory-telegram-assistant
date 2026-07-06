# -*- coding: utf-8 -*-
"""
AI回复处理器 - P7/P8/P9/P10 优先级AI相关处理

包含：
- P7 视奸雷达（价格关键词通知管理员）
- P8 固定彩蛋响应
- P8.8 成就自动检测
- P8.85 猜数字回复检测
- P9 用户画像标签提取
- P9.3 天气/城市共情
- P9.5 黑话/行话自动科普
- P9.7 用户反馈/找Mory
- P10 AI回复主逻辑（入口函数）

P10内部子函数见 ai_reply_core.py：
- 连续对话追踪、递进引导、深夜警告、FC工具等
"""

import random

from core.logging_util import get_logger, clear_logging_context
from core.helpers import format_user_mention

logger = get_logger("ai_handlers")


def _final_ai_reply_fallback(mode: str, is_priv: bool = False) -> str:
    """处理AI失败时给用户的兜底回复（旧版兼容）。

    [Bug-01 修复] 兜底文案统一走 ai_engine.get_fallback_text()，
    与 ai_engine._final_fallback_reply / ai_reply_handler._final_ai_reply_fallback 保持一致。
    """
    from core.ai_engine import get_fallback_text
    return get_fallback_text(mode, is_priv=is_priv)

# ═══════════════════════════════════════════════════════════════════════
#  P8：固定彩蛋 + P8.8 成就检测 + P8.85 猜数字
# ═══════════════════════════════════════════════════════════════════════

def handle_easter_eggs(dctx) -> bool:
    """P8 固定彩蛋响应

    返回 True 表示彩蛋已触发
    """
    from modules.content import handle_easter_eggs

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    mory_bot = dctx.ctx.mory_bot

    if handle_easter_eggs(mory_bot, m, CONFIG, db):
        clear_logging_context()
        return True
    return False


def check_achievements(dctx) -> bool:
    """P8.8 成就自动检测（群聊中5%概率检查）

    注意：此函数始终返回 False（不终止分发），仅做成就检查
    """
    if not dctx.is_group or not dctx.uid:
        return False

    if random.randint(1, 20) != 1:  # 5%概率
        return False

    from modules.achievement import check_achievements_for_user

    bot = dctx.ctx.bot
    db = dctx.ctx.db
    CONFIG = dctx.ctx.config
    uid = dctx.uid
    chat_id = dctx.chat_id

    try:
        check_achievements_for_user(bot, chat_id, db, uid, CONFIG)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return False


def check_guess_reply(dctx) -> bool:
    """P8.85 猜数字回复检测

    返回 True 表示猜数字回复已处理
    """
    if not dctx.is_group:
        return False

    from modules.games import handle_guess_reply

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    try:
        if handle_guess_reply(bot, m, CONFIG, db):
            clear_logging_context()
            return True
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════
#  P9：用户画像 + 共情 + 科普 + 反馈
# ═══════════════════════════════════════════════════════════════════════

def extract_user_profile(dctx) -> dict:
    """P9 用户画像标签提取

    返回 analysis 字典，供后续 P10 使用
    同时执行 P9.3 天气共情、P9.5 黑话科普
    """
    from modules.group_mgr import detect_keywords

    msg = dctx.text
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    mory_bot = dctx.ctx.mory_bot
    m = dctx.msg
    uid = dctx.uid
    is_group = dctx.is_group

    analysis = detect_keywords(msg, CONFIG)

    # 画像标签写入
    if analysis["keyword_tag"]:
        db.add_keyword(uid, analysis["keyword_tag"])
    if analysis["is_cart"]:
        db.set_cart(uid)
        db.log_conversion_event(uid, "interested")

    # P9.3：天气/城市共情
    if analysis.get("weather_empathy") and is_group:
        mory_bot.reply_and_track(m, analysis["weather_empathy"])

    # P9.5：黑话/行话自动科普（5%概率触发防刷屏）
    if analysis.get("slang_reply") and is_group:
        if random.randint(1, 20) == 1:
            mory_bot.reply_and_track(m, analysis["slang_reply"])

    return analysis


def handle_feedback(dctx, analysis: dict) -> bool:
    """P9.7 用户反馈/找Mory（安抚回复 + 通知管理员）

    返回 True 表示反馈已处理，应终止分发
    """
    if analysis.get("mode") not in ("feedback", "contact_mory"):
        return False

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    mory_bot = dctx.ctx.mory_bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_priv = dctx.is_priv
    is_group = dctx.is_group

    if is_group:
        # 群聊：安抚 + 引导私聊
        feedback_reply = random.choice([
            f"{uname}收到啦～你私聊我，我帮你处理哦～",
            f"{uname}好的～来私聊我吧，这边不太方便说～",
            f"嗯嗯～直接私聊我就行，我帮你转达Mory～",
        ])
        mory_bot.reply_and_track(m, feedback_reply)
        # 通知管理员
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            try:
                bot.send_message(admin_id,
                    f"📢 用户反馈通知\n"
                    f"👤 {format_user_mention(uid, uname)}\n"
                    f"💬 消息：{msg[:150]}\n"
                    f"🏷 类型：{'用户遇到问题' if analysis['mode'] == 'feedback' else '用户想找Mory'}\n"
                    f"💡 已引导私聊处理",
                    parse_mode="HTML")
            except Exception as e:
                logger.warning(f"反馈通知发送失败：{e}")
    else:
        # 私聊：尝试自助解封
        if _handle_private_feedback(dctx, analysis):
            pass  # 已处理
        else:
            # 私聊普通反馈（非解封）
            feedback_reply = random.choice([
                "收到啦～我已经记下来了，Mory会尽快来处理的！有事随时私聊我哦～",
                "好的好的～我帮你转达给Mory，她看到就会来处理～以后有事直接找我就行！",
                "嗯嗯～已经通知Mory了，别着急哦～有任何问题都可以私聊我～",
            ])
            mory_bot.reply_and_track(m, feedback_reply)

    clear_logging_context()
    return True


def _handle_private_feedback(dctx, analysis: dict) -> bool:
    """私聊反馈处理（含自助解封逻辑），返回 True 表示已处理"""
    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    mory_bot = dctx.ctx.mory_bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname

    if not ("解封" in msg or "解禁" in msg or "被封" in msg or "封了" in msg or "禁言" in msg):
        return False

    gid = CONFIG.get("GROUP_ID", 0)
    unban_success = False
    tracking_cleared = False
    if gid:
        try:
            from modules.ad_enforcement import restore_ad_user
            result = restore_ad_user(
                bot=bot,
                db=db,
                config=CONFIG,
                chat_id=gid,
                uid=uid,
                actor_id=uid,
                ad_detector=getattr(dctx.ctx, "ad_detector", None),
            )
            unban_success = result.get("code") == 200
            tracking_cleared = bool(result.get("data", {}).get("tracking_cleared"))
            logger.info(f"✅ 私聊自助解封成功: {uname}({uid})")
        except Exception as e:
            logger.warning(f"私聊自助解封失败: {e}")

    if unban_success:
        blame = random.choice([
            "这次是系统误判，真的不好意思。",
            "刚才的封禁不该发生，已经帮你处理好了。",
            "抱歉让你受影响了，我已经把封禁状态撤掉了。",
        ])
        tracking_note = "可疑追踪记录也一起清掉了。" if tracking_cleared else "没有发现额外的可疑追踪记录。"
        feedback_reply = f"已经帮你解封了。{blame}现在可以回群里正常发言，{tracking_note}"
    else:
        blame = random.choice([
            "我这边没能自动恢复。",
            "自动解封没有成功。",
            "这次需要管理员手动看一下。",
        ])
        feedback_reply = f"{blame}我已经通知管理员，请稍等一下。"
        # 通知管理员解封失败
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            try:
                bot.send_message(admin_id,
                    f"🚨 用户自助解封失败\n"
                    f"👤 {format_user_mention(uid, uname)}\n"
                    f"💬 消息：{msg[:150]}\n"
                    f"💡 请手动解封",
                    parse_mode="HTML")
            except Exception as e:
                logger.debug(f"操作异常: {e}")
    mory_bot.reply_and_track(m, feedback_reply)
    return True


# ═══════════════════════════════════════════════════════════════════════
#  FAQ自动回复匹配（AI调用前拦截）
# ═══════════════════════════════════════════════════════════════════════

def _try_faq_match(db, CONFIG, ai, msg: str, mode: str, analysis: dict) -> tuple:
    """FAQ自动回复匹配

    在AI调用前检查用户消息是否匹配FAQ条目。
    匹配成功则返回 (回复文本, faq_id)，未匹配返回 (None, 0)。
    任何异常均静默返回 (None, 0)，绝不阻塞正常AI回复流程。
    """
    try:
        # 检查FAQ自动回复开关
        if not CONFIG.get("FAQ_AUTO_REPLY_ENABLED", False):
            return None, 0

        # 提取意图信息用于匹配
        intent = analysis.get("keyword_tag", "") if analysis else ""

        # 调用数据库搜索FAQ
        faq_entry = db.search_faq(msg, mode, intent)
        if not faq_entry:
            return None, 0

        faq_id = faq_entry.get("id", 0)
        answer_template = faq_entry.get("answer_template", "")
        ai_polish = faq_entry.get("ai_polish", False)

        if not answer_template:
            return None, 0

        # 记录命中次数
        try:
            db.increment_faq_hit(faq_id)
        except Exception as e:
            logger.debug(f"FAQ命中计数更新失败(非致命): {e}")

        # AI润色模式：用Mory人设风格润色FAQ模板回复
        if ai_polish:
            try:
                polished = ai.ask(
                    f"请用Mory的人设风格润色以下回复，保持核心意思不变但更自然：{answer_template}",
                    mode="normal",
                    seed=hash(msg) % 999999
                )
                if polished and len(polished.strip()) > 5:
                    return polished.strip(), faq_id
            except Exception as e:
                logger.debug(f"FAQ AI润色失败(使用原文): {e}")

        # 直接使用模板回复
        return answer_template, faq_id

    except Exception as e:
        # FAQ匹配任何异常均静默，绝不阻塞正常AI流程
        logger.debug(f"FAQ匹配异常(静默跳过): {e}")
        return None, 0


# ═══════════════════════════════════════════════════════════════════════
#  P10：AI回复主逻辑（入口函数）【DEPRECATED 旧版，新版见 ai_reply_handler.py】
# ═══════════════════════════════════════════════════════════════════════

def handle_ai_reply(dctx, analysis: dict = None):
    """⚠️ DEPRECATED 旧版P10入口，已被 ai_reply_handler._dispatch_p10_ai 替代。
    保留仅为兼容，新代码请勿调用。

    包含：人格模式选择、Function Calling、连续对话追踪、
    递进引导、拟人化延迟、私聊分段发送、深夜警告等

    内部子函数见 ai_reply_core.py
    """
    from core.handlers.ai_reply_core import (
        track_conversation, build_convert_hint, build_emotional_hint,
        build_normal_hint, process_ai_response, generate_late_night_warning,
        get_function_tools
    )

    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    mory_bot = ctx.mory_bot
    ai = ctx.ai
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_priv = dctx.is_priv
    is_group = dctx.is_group

    # 获取analysis
    if analysis is None:
        analysis = extract_user_profile(dctx)

    mode = analysis["mode"]
    is_at = f"@{ctx.bot_username}" in msg
    is_reply = m.reply_to_message and m.reply_to_message.from_user.id == ctx.bot_id

    # 5%概率给普通消息附加运势签
    fortune_bonus = False
    if mode == "normal" and random.randint(1, 100) <= 5:
        fortune_bonus = True

    should_reply = (
        is_priv
        or is_at
        or is_reply
        or mode != "normal"
        or random.randint(1, 100) <= CONFIG.get("REPLY_CHANCE", 10)
    )

    if not should_reply:
        clear_logging_context()
        return

    # 生物钟警告（凌晨0-5点）
    from modules.content import is_late_night
    if is_late_night() and is_group:
        late_night_text = generate_late_night_warning(ai, uname, is_group, uid)
        mory_bot.reply_and_track(m, late_night_text)
        clear_logging_context()
        return

    # 连续对话追踪（仅群聊 @/回复 机器人时计数）
    conv_count = track_conversation(uid, is_group, is_at, is_reply, mode)

    # 拟人化延迟：发送typing状态
    bot.send_chat_action(chat_id, "typing")

    # Function Calling 触发逻辑
    use_tools = None
    if is_group and mode == "normal":
        use_tools = get_function_tools()

    # 递进引导逻辑
    stage_hint = ""
    notify_admin_reason = ""

    if mode == "convert":
        stage_hint, notify_admin_reason = build_convert_hint(db, uid, conv_count)
    elif mode in ("treehole", "dream"):
        stage_hint, notify_admin_reason = build_emotional_hint(conv_count)
    elif mode == "normal":
        stage_hint, notify_admin_reason = build_normal_hint(conv_count)

    # FAQ自动回复匹配（AI调用前拦截，节省API费用）
    faq_resp, faq_id = _try_faq_match(db, CONFIG, ai, msg, mode, analysis)
    if faq_resp is not None:
        # FAQ命中，使用FAQ回复（已含AI润色），跳过AI调用
        resp = faq_resp
        logger.info(f"📋 FAQ自动回复命中 uid={uid} mode={mode} faq_id={faq_id}")
    else:
        # FAQ未命中，走正常AI回复流程
        seed = random.randint(1, 999999)
        resp = ai.ask(msg, mode=mode, tools=use_tools, is_priv=is_priv, stage_hint=stage_hint, user_profile=analysis, seed=seed)

    if resp is None:
        resp = _final_ai_reply_fallback(mode, is_priv=is_priv)
        try:
            from modules.auto_tasks import report_fault
            report_fault("AI引擎故障", f"mode={mode}，AI重试耗尽，已发送降级兜底", "🚨" if mode != "normal" else "⚠️",
                         f"用户消息: {msg[:80]}")
        except Exception as notify_err:
            logger.error(f"故障通知发送失败: {notify_err}")

    if resp:
        process_ai_response(dctx, resp, mode, conv_count, fortune_bonus, notify_admin_reason, analysis)
    else:
        logger.warning(f"⚠️ AI未能生成回复 uid={uid}")

    clear_logging_context()
