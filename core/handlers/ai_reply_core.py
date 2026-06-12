# -*- coding: utf-8 -*-
"""
AI回复核心子函数 - P10 AI回复的内部处理逻辑

包含：
- 连续对话追踪（内存字典 + 线程安全）
- AI回复处理（FC处理、彩蛋追加、延迟发送）
- 私聊转发管理员
- 统一管理员通知
- 递进引导提示词构建（转化/情感/闲聊）
- 连续对话追加（绿茶风反问）
- 深夜警告生成
- Function Calling 工具定义
"""

import time
import random
import concurrent.futures
from datetime import datetime

from core.logging_util import get_logger
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

    # 连续对话追加：绿茶风反问 + 转化引导
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
    """构建转化类递进引导提示词"""
    stage_hint = ""
    notify_admin_reason = ""
    consult_count = db.get_user_consult_count(uid)

    if consult_count <= 1:
        _v = random.choice([1, 2, 3])
        if _v == 1:
            stage_hint = "\n【转化-首次-A】：用户第一次问消费类问题。直接告诉：自助下单找 @MorychannelBot 按提示操作即可，简洁说明档位。语气温柔但不撩人，重点是给出明确操作路径。"
        elif _v == 2:
            stage_hint = "\n【转化-首次-B】：用户首次咨询消费类。引导自助：找 @MorychannelBot 就能下单，操作很简单。语气亲切自然，像朋友推荐一样，别太正式。"
        else:
            stage_hint = "\n【转化-首次-C】：用户刚问消费类问题。直接给路径：@MorychannelBot 是自助下单机器人，按提示选就行。简短明了，别啰嗦，让用户知道怎么操作。"
    elif consult_count == 2:
        _v = random.choice([1, 2, 3])
        if _v == 1:
            stage_hint = "\n【转化-二次-A】：用户再次询问，有兴趣但犹豫。用撩人话术引导下单，给预览诱饵：@moryselect 有初步预览，每周更新海量资源。可以撩一下但核心还是引导下单。"
        elif _v == 2:
            stage_hint = "\n【转化-二次-B】：用户又来问了，说明心动了。换个角度撩：先给甜头 @moryselect 看看预览，再引导 @MorychannelBot 下单。语气带点小暧昧，让用户觉得不买亏了。"
        else:
            stage_hint = "\n【转化-二次-C】：用户第二次咨询，还在观望。用好奇心驱动：'好多人在 @moryselect 那边都看过了，你也可以先看看～'，然后自然引导 @MorychannelBot 下单。别催，要勾。"
    else:
        _v = random.choice([1, 2, 3])
        if _v == 1:
            stage_hint = "\n【转化-多次-A】：用户问了3次以上还没下单，需要人工介入。告诉用户：'我帮你转达Mory，等我这的回复谢谢。'语气温柔真诚，让用户感到被重视。"
        elif _v == 2:
            stage_hint = "\n【转化-多次-B】：用户反复咨询但没下单，可能需要Mory亲自来。说：'我帮你跟Mory说一声，她看到会来找你的，稍等哦～'让用户觉得有人在为他操心。"
        else:
            stage_hint = "\n【转化-多次-C】：多次咨询未转化，转人工。说：'你的问题我帮你转给Mory了，她会亲自回复你的，等我消息～'语气诚恳，给用户安全感。"
        notify_admin_reason = "convert_stuck"

    return stage_hint, notify_admin_reason


def build_emotional_hint(conv_count) -> tuple:
    """构建情感类递进引导提示词"""
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 4:
        _v = random.choice([1, 2, 3])
        if _v == 1:
            stage_hint = "\n【情感-深度-A】：用户聊了好几轮，情绪复杂。安慰完后说：'我帮你跟Mory说一声吧，她看到会来找你的～'让用户知道有人在背后关心ta。"
        elif _v == 2:
            stage_hint = "\n【情感-深度-B】：多轮对话了，用户可能需要真人支持。安慰后温柔说：'要不要我帮你转达给Mory？她人超好的，会帮你的～'给用户一个出口，不硬推。"
        else:
            stage_hint = "\n【情感-深度-C】：聊了挺久了，用户情绪需要更多关注。说：'我帮你通知Mory吧，等她回复你，她一定会的～'语气温暖坚定，让用户有依靠感。"
        notify_admin_reason = "emotional_deep"
    elif conv_count >= 2:
        _v = random.choice([1, 2])
        if _v == 1:
            stage_hint = "\n【情感-引导-A】：用户情绪需要持续关注。安慰完后轻描淡写：'其实Mory人也很nice的，有啥想说的也可以跟她说～'。自然带出，不硬推。"
        else:
            stage_hint = "\n【情感-引导-B】：聊了两轮了，用户可能需要更多支持。安慰后顺带提：'Mory平时也在线的，有啥事找她也行～'。像不经意提到一个朋友，不刻意。"

    return stage_hint, notify_admin_reason


def build_normal_hint(conv_count) -> tuple:
    """构建闲聊类递进引导提示词"""
    stage_hint = ""
    notify_admin_reason = ""

    if conv_count >= 6:
        _v = random.choice([1, 2, 3])
        if _v == 1:
            stage_hint = "\n【闲聊-收网-A】：聊了很多轮了，自然收尾。说：'我帮你跟Mory说一声，让她来看看你～'，或者'跟你聊天好开心～@MorychannelBot 那边还有更多好玩的哦'。二选一。"
        elif _v == 2:
            stage_hint = "\n【闲聊-收网-B】：聊了好久，该收了。自然说：'下次再聊～对了，@moryselect 每周都有新内容，你可以看看'，或者'我帮你转达给Mory，让她来找你玩～'。选一个。"
        else:
            stage_hint = "\n【闲聊-收网-C】：多轮闲聊，温和引导。'好啦今天先这样～想看更多的话 @MorychannelBot 那边解锁就行'，或者'我帮你通知Mory，让她来陪你～'。自然过渡。"
        notify_admin_reason = "chat_deep"
    elif conv_count >= 5:
        _v = random.choice([1, 2])
        if _v == 1:
            stage_hint = "\n【闲聊-深度-A】：聊了5轮以上，关系升温了。自然暗示：'跟你聊天好开心～@MorychannelBot 那边可以直接解锁更多内容哦'。"
        else:
            stage_hint = "\n【闲聊-深度-B】：聊了好几轮，气氛不错。不经意提：'你要是喜欢这里，@moryselect 有超多好东西，每周更新～'。"
    elif conv_count >= 3:
        _v = random.choice([1, 2])
        if _v == 1:
            stage_hint = "\n【闲聊-升温-A】：聊了好几轮，气氛不错。不经意提：'对了，你知道 @moryselect 吗？那边有超多好东西，每周都更新～'。自然植入，不硬推。"
        else:
            stage_hint = "\n【闲聊-升温-B】：聊了几轮，可以轻推一下。随口说：'群里还有 @MorychannelBot 可以解锁更多内容哦～'。像推荐一个好玩的地方，不刻意。"

    return stage_hint, notify_admin_reason


# ═══════════════════════════════════════════════════════════════════════
#  连续对话追加 + 深夜警告 + Function Calling
# ═══════════════════════════════════════════════════════════════════════

def append_conv_response(ai, conv_count: int) -> str:
    """连续对话追加：绿茶风反问 + 转化引导，返回追加文本"""
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
                append_text = _append_future.result(timeout=25)
                if append_text:
                    return f"\n\n{append_text.strip()}"
            except concurrent.futures.TimeoutError:
                logger.info("连续对话追加超时（5秒），跳过")
        except Exception as e:
            logger.warning(f"连续对话追加失败（跳过）：{e}")

    return ""


def generate_late_night_warning(ai, uname, is_group, uid):
    """生成深夜撩人警告消息（带随机性和人设）"""
    # 40%概率直接使用备用文案
    if random.random() < 0.4:
        return get_late_night_fallback(uname)

    # 60%概率调用AI生成
    try:
        seed = uid + int(time.time()) % 3600
        prompt = (
            f"你是Mory，一个贴心又有点小调皮的小姐姐。\n\n"
            f"现在是凌晨，用户{uname}还在群里发消息不睡觉。\n"
            f"你要用关心但不说教的方式提醒他去睡觉。\n\n"
            f"要求：\n"
            f"1. 20-30字，像闺蜜私聊一样自然\n"
            f"2. 带点小撒娇/小关心\n"
            f"3. 可以暗示：熬夜会变丑/对身体不好/明天没精神\n"
            f"4. 结尾要有emoji（😴💤🌙✨选一个）\n"
            f"5. seed={seed}，每次必须不同\n\n"
            f"禁止：\n"
            f"- 不要说教式语气（如'你应该'、'你必须'）\n"
            f"- 不要出现'老板'这个词（不在回复里使用任何'老板'称谓）\n"
            f"- 控制在30字以内"
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
        f"哎呀{uname}～这么晚还不睡呀？熬夜会掉头发的哦～快去被窝里躲着吧 💤",
        f"诶嘿～{uname}还在活跃呀？月亮都困得打哈欠了，你也快去休息嘛～🌙",
        f"{uname}哥哥～再熬下去明天要变熊猫眼了啦！快去梦里找我玩～😴",
        f"偷偷告诉你哦{uname}～熬夜会变笨的！小Mory可不想明天看到迷糊的你～✨",
        f"呜呼{uname}～深夜不睡觉是在等谁呀？快闭眼休息啦，明天见～💤",
        f"{uname}～你是在偷偷熬夜刷手机吗？小心被小Mory抓包哦～快去睡！😴",
        f"嘿{uname}～夜深啦～星星都困得眨眼了，你也该去被窝里躲着啦～🌙",
        f"{uname}哥哥～再晚下去要错过好运了！快去睡吧，梦里啥都有～✨",
        f"哎呀呀{uname}～这么精神呀？小Mory都打哈欠了，你也快去休息嘛～💤",
        f"{uname}～深夜是皮肤修复的黄金时间哦！快去睡美容觉吧～😴",
    ]
    return random.choice(templates)
