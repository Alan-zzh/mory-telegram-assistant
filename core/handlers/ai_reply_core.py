# -*- coding: utf-8 -*-
"""
⚠️ DEPRECATED 废弃文件
AI回复核心子函数 - 旧版P10实现，已被 ai_reply_handler.py 完全替代。
本文件仅保留给旧版ai_handlers.handle_ai_reply引用，新代码禁止导入。
所有新功能请在 ai_reply_handler.py 中实现。

原包含：
- 连续对话追踪（内存字典 + 线程安全）
- AI回复处理（FC处理、彩蛋追加、延迟发送）
- 私聊转发管理员
- 统一管理员通知
- 递进引导提示词构建（转化/情感/闲聊）
- 连续对话追加（清冷反问）
- 深夜警告生成
- Function Calling 工具定义
"""

import time
import random
import concurrent.futures
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

# 【v5.31.2 修复】VPS 运行在 UTC，时段/日期相关逻辑必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))
from core.helpers import format_user_mention

logger = get_logger("ai_reply_core")

# ── 连续对话追踪变量（从message_dispatcher统一导入，避免重复定义）──
# 注意：_conv_tracker(字典)和_conv_lock(Lock)是可变对象，导入后可直接修改
# _CONV_TIMEOUT和_MAX_CONV_ENTRIES只读，导入后可直接使用
# _cleanup_conv_tracker直接委托给message_dispatcher的版本
from core.message_dispatcher import (
    _conv_tracker,
    _conv_lock,
    _CONV_TIMEOUT,
    _MAX_CONV_ENTRIES,
    _cleanup_conv_tracker as _md_cleanup_conv_tracker,
    get_function_tools,
)

# ── 追加线程池 ──
_append_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="append")


# ═══════════════════════════════════════════════════════════════════════
#  连续对话追踪（变量统一由message_dispatcher管理）
# ═══════════════════════════════════════════════════════════════════════

def track_conversation(uid, is_group, is_at, is_reply, mode) -> int:
    """连续对话追踪（仅群聊 @/回复 机器人时计数），返回当前轮次"""
    conv_count = 0
    if is_group and (is_at or is_reply) and mode == "normal":
        now_ts = time.time()
        cleanup_conv_tracker()
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
    return conv_count


def cleanup_conv_tracker():
    """清理超时的对话追踪条目（直接委托给message_dispatcher）"""
    _md_cleanup_conv_tracker()


# ═══════════════════════════════════════════════════════════════════════
#  P10：AI回复处理
# ═══════════════════════════════════════════════════════════════════════

def process_ai_response(dctx, resp, mode, conv_count, fortune_bonus, notify_admin_reason, analysis):
    """处理AI回复：FC处理、彩蛋追加、连续对话追加、延迟发送、通知"""
    from core.message_dispatcher import _handle_tool_calls, _calc_humanized_delay, _delayed_reply, _split_for_private

    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    mory_bot = ctx.mory_bot
    m = dctx.msg
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_priv = dctx.is_priv
    is_group = dctx.is_group

    # Function Calling处理
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
        # 运势签追加
        if fortune_bonus:
            resp += f"\n\n🎴 今日签：{get_fortune()}"

    # 连续对话追加：清冷反问 + 转化引导
    if is_group and mode == "normal" and conv_count >= 2:
        append_text = append_conv_response(ctx.ai, conv_count)
        if append_text:
            resp += append_text

    # 拟人化延迟发送 + 私聊分段发送
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
            _delayed_reply(bot, chat_id, m, parts[1], part2_delay, mory_bot, is_priv)
        else:
            _delayed_reply(bot, chat_id, m, resp, delay, mory_bot, is_priv)
    else:
        _delayed_reply(bot, chat_id, m, resp, delay, mory_bot, is_priv)

    # 私聊消息转发给管理员
    if is_priv:
        forward_private_to_admin(dctx, resp)

    # 群聊 AI 回复转发给管理员（中继模式开启时）
    if is_group and CONFIG.get('RELAY_MODE_ENABLED', False):
        try:
            from core.handlers.relay_handler import forward_ai_reply_to_admin
            group_name = m.chat.title or ""
            forward_ai_reply_to_admin(bot, db, CONFIG, uid, uname, resp, chat_id, source_type='group', group_name=group_name)
        except Exception as e:
            logger.debug(f"群聊AI回复转发失败（静默）：{e}")

    # 更新转化漏斗
    if mode == "convert":
        db.log_conversion_event(uid, "consulted")

    # 统一管理员通知
    if notify_admin_reason:
        notify_admin_for_deep_conversation(dctx, mode, conv_count, notify_admin_reason)

    logger.info(f"💬 回复 uid={uid}  mode={mode}  len={len(resp)}  conv={conv_count}")


def forward_private_to_admin(dctx, resp):
    """私聊消息转发给管理员"""
    bot = dctx.ctx.bot
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id

    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id and uid != admin_id:
            # 中继模式：使用 relay_handler 转发（含 relay_sessions 记录）
            if CONFIG.get('RELAY_MODE_ENABLED', False):
                from core.handlers.relay_handler import forward_ai_reply_to_admin
                forward_ai_reply_to_admin(bot, db, CONFIG, uid, uname, resp, chat_id, source_type='private')
            else:
                # 原有逻辑：简单转发
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


def notify_admin_for_deep_conversation(dctx, mode, conv_count, reason):
    """统一管理员通知：所有模式多轮搞不定都通知"""
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


# ═══════════════════════════════════════════════════════════════════════
#  递进引导提示词构建
# ═══════════════════════════════════════════════════════════════════════

def build_convert_hint(db, uid, conv_count) -> tuple:
    """构建兼容旧入口的统一转化提示词。

    旧入口没有传入已解析的 conversion_target，因此这里只给模型明确的
    ReplyContract v1 判定规则，禁止按咨询次数硬推或切换成交目标。
    """
    consult_count = db.get_user_consult_count(uid)
    stage_hint = (
        "\n【统一成交规则】：先自然回答当前问题。价格、内容、权益、套餐或"
        "了解阶段只给 @moryselect 预览；只有明确购买、下单、订阅或确认"
        "看过预览才给 @MorychannelBot 自助入口。每轮最多一个目标，"
        "不发完整价格表，不主动私聊，不承诺未核实商品、定制、福利、价格或交付。"
    )
    notify_admin_reason = "convert_stuck" if consult_count >= 3 else ""
    return stage_hint, notify_admin_reason


def build_emotional_hint(conv_count) -> tuple:
    """构建情感类递进引导提示词"""
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 4:
        _v = random.choice([1, 2, 3])
        if _v == 1:
            stage_hint = "\n【情感-深度-A】：......嗯。这种事别跟我说。"
        elif _v == 2:
            stage_hint = "\n【情感-深度-B】：想听安慰去找她，我不会。"
        else:
            stage_hint = "\n【情感-深度-C】：你跟我说这些没用。找Mory去。"
        notify_admin_reason = "emotional_deep"
    elif conv_count >= 2:
        _v = random.choice([1, 2])
        if _v == 1:
            stage_hint = "\n【情感-引导-A】：对了，Mory比我会安慰人。"
        else:
            stage_hint = "\n【情感-引导-B】：这种事找她说比较好。"

    return stage_hint, notify_admin_reason


def build_normal_hint(conv_count) -> tuple:
    """构建兼容旧入口的普通聊天提示词；轮数不再触发销售 CTA。"""
    stage_hint = (
        "\n【普通聊天】：只承接当前话题，保持简短自然，不因聊天轮数添加"
        "预览、下单、私聊或任何销售入口。"
    )
    notify_admin_reason = "chat_deep" if conv_count >= 6 else ""
    return stage_hint, notify_admin_reason


# ═══════════════════════════════════════════════════════════════════════
#  连续对话追加 + 深夜警告 + Function Calling
# ═══════════════════════════════════════════════════════════════════════

def append_conv_response(ai, conv_count: int) -> str:
    """连续对话只追加自然承接，不根据轮数植入销售引导。"""
    seed_h = random.randint(100000, 999999)

    append_mode = None
    append_prompt = ""
    if random.randint(1, 10) <= 6:
        append_mode = "hook"
        append_prompt = (
            "用一句自然的追问或简短承接收尾，让对方愿意继续聊；"
            "不要添加预览、下单、私聊或销售入口。"
        )

    if append_mode:
        try:
            _append_future = _append_pool.submit(
                lambda: ai.ask(append_prompt, mode=append_mode, seed=seed_h))
            try:
                append_text = _append_future.result(timeout=25)
                if append_text:
                    return f"\n\n{append_text.strip()}"
            except concurrent.futures.TimeoutError:
                logger.info("连续对话追加超时（25秒），跳过")
        except Exception as e:
            logger.warning(f"连续对话追加失败（跳过）：{e}")

    return ""


def generate_late_night_warning(ai, uname, is_group, uid):
    """生成深夜警告消息（带随机性和人设）"""
    # 40%概率直接使用备用文案
    if random.random() < 0.4:
        return get_late_night_fallback(uname)

    # 60%概率调用AI生成
    try:
        seed = uid + int(time.time()) % 3600
        prompt = (
            f"你是Mory，一个嘴硬心软的Mory。\n\n"
            f"现在是凌晨，用户{uname}还在群里发消息不睡觉。\n"
            f"你要用关心但不说教的方式提醒他去睡觉。\n\n"
            f"要求：\n"
            f"1. 20字以内，清冷短句\n"
            f"2. 嘴硬地关心，不撒娇\n"
            f"3. 可以暗示：熬夜会变丑/对身体不好/明天没精神\n"
            f"4. 结尾可以有一个emoji（😴💤🌙选一个）\n"
            f"5. seed={seed}，每次必须不同\n\n"
            f"禁止：\n"
            f"- 不要说教式语气（如'你应该'、'你必须'）\n"
            f"- 不要称呼用户'哥哥'，不要用'嘛''啦''～'\n"
            f"- 不要出现'老板'这个词（不在回复里使用任何'老板'称谓）\n"
            f"- 控制在20字以内"
        )
        ai_reply = ai.ask(prompt, mode="normal")
        if ai_reply and len(ai_reply) > 5:
            return ai_reply.strip()[:100]
    except Exception as e:
        logger.debug(f"AI生成深夜回复失败，使用备用文案：{e}")

    return get_late_night_fallback(uname)


def get_late_night_fallback(uname):
    """备用深夜文案库（高度随机化）"""
    templates = [
        "还没睡？🌙",
        "熬夜会变丑。😴",
        "再不睡明天起不来。💤",
        "早点休息。",
        "几点了还在这。🌙",
        "还不睡？",
        "夜猫子。😴",
        "去睡。",
        "别熬了。💤",
        "明天没精神别怪我。🌙",
    ]
    return random.choice(templates)
