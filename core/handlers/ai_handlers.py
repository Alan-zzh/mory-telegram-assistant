# -*- coding: utf-8 -*-
"""
AI回复处理器 - P7/P8/P9 优先级AI相关处理

包含：
- P7 视奸雷达（价格关键词通知管理员）
- P8 固定彩蛋响应
- P8.8 成就自动检测
- P8.85 猜数字回复检测
- P9 用户画像标签提取
- P9.3 天气/城市共情
- P9.5 黑话/行话自动科普
- P9.7 用户反馈/找Mory
- FAQ 匹配（供 ai_reply_handler 调用）

P10 AI 回复主链唯一入口：core/handlers/ai_reply_handler.py。
（旧版 P10 入口 handle_ai_reply 与 ai_reply_core.py 已作为死代码移除。）
"""

import random

from core.logging_util import get_logger, clear_logging_context
from core.helpers import format_user_mention

logger = get_logger("ai_handlers")


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
        # 群聊反馈同样以真实通知结果为准，不先承诺、不强导私聊。
        admin_notified = False
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            try:
                bot.send_message(admin_id,
                    f"📢 用户反馈通知\n"
                    f"👤 {format_user_mention(uid, uname)}\n"
                    f"💬 消息：{msg[:150]}\n"
                    f"🏷 类型：{'用户遇到问题' if analysis['mode'] == 'feedback' else '用户想找Mory'}",
                    parse_mode="HTML")
                admin_notified = True
            except Exception as e:
                logger.warning(f"反馈通知发送失败：{e}")
        feedback_reply = (
            f"{uname}，收到，已经提交给管理员；具体处理结果以实际回复为准。"
            if admin_notified
            else f"{uname}，收到，我先记录下来了；目前不能确认通知是否送达。"
        )
        mory_bot.reply_and_track(m, feedback_reply)
    else:
        if _handle_private_feedback(dctx, analysis):
            pass  # 解封申请已进入管理员审核，不修改封禁状态
        else:
            # 私聊普通反馈：只有真实通知成功才能说“已提交”，不承诺处理时效。
            admin_notified = False
            admin_id = CONFIG.get("ADMIN_ID", 0)
            if admin_id:
                try:
                    bot.send_message(
                        admin_id,
                        f"📢 用户反馈通知\n"
                        f"👤 {format_user_mention(uid, uname)}\n"
                        f"💬 消息：{msg[:150]}\n"
                        f"🏷 类型：{'用户遇到问题' if analysis['mode'] == 'feedback' else '用户想找Mory'}",
                        parse_mode="HTML",
                    )
                    admin_notified = True
                except Exception as e:
                    logger.warning(f"反馈通知发送失败：{e}")
            feedback_reply = (
                "收到，已经提交给管理员了；具体处理结果以实际回复为准。"
                if admin_notified
                else "收到，我先把问题记录下来了；目前不能确认人工处理时间。"
            )
            mory_bot.reply_and_track(m, feedback_reply)

    clear_logging_context()
    return True


def _handle_private_feedback(dctx, analysis: dict) -> bool:
    """把私聊解封自述转为管理员审核请求，不直接修改治理状态。"""
    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    mory_bot = dctx.ctx.mory_bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname

    if not ("解封" in msg or "解禁" in msg or "被封" in msg or "封了" in msg or "禁言" in msg):
        return False

    admin_notified = False
    admin_id = CONFIG.get("ADMIN_ID", 0)
    if admin_id:
        try:
            bot.send_message(
                admin_id,
                f"🚨 用户申请解封审核\n"
                f"👤 {format_user_mention(uid, uname)}\n"
                f"💬 消息：{msg[:150]}\n"
                f"💡 请核对广告证据后再决定是否解封",
                parse_mode="HTML",
            )
            admin_notified = True
        except Exception as e:
            logger.warning(f"解封审核通知发送失败: {e}")
    feedback_reply = (
        "收到，你的解封申请已提交给管理员审核；审核前不会改动封禁状态。"
        if admin_notified
        else "收到，我先记录你的解封申请；目前不能确认通知是否送达，封禁状态没有改动。"
    )
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
        faq_result = db.search_faq(msg, mode, intent)
        if not faq_result:
            return None, 0
        # QuestionRepo.search_faq() 返回按优先级排序的候选列表；
        # 兼容旧测试桩或第三方 Repo 直接返回单条字典。
        faq_entry = faq_result[0] if isinstance(faq_result, (list, tuple)) else faq_result
        if not isinstance(faq_entry, dict):
            logger.warning(f"FAQ搜索返回类型异常: {type(faq_entry).__name__}")
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
