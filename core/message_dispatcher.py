"""
core/message_dispatcher.py  ·  消息分发器

从 main.py 提取的消息分发逻辑，负责：
- 内存状态变量（连续对话追踪、视奸雷达冷却）
- 辅助工具函数（延迟回复、分段发送、深夜警告等）
- DispatchContext 数据类
- 核心分发函数（P0-P10优先级分发，拆分为子函数）

消息分发优先级：
  P0  新人入群欢迎 → P1 黑名单 → P2 积分 → P3 敏感词 → P4 反刷屏
  → P5 机器人过滤 → P6 管理员指令 → P7 价格雷达 → P8 彩蛋
  → P9 画像标签 → P10 AI回复
"""

import os, time, random, traceback, threading, uuid
import re
from datetime import datetime, timezone, timedelta
from threading import Lock
from dataclasses import dataclass, field
from typing import Any

from core.helpers import can_delete_message, format_user_mention
from core.bot_initializer import BotContext
from core.i18n import set_user_language, _
from core.logging_util import get_logger, set_logging_context, clear_logging_context
from core.tracing import is_tracing_enabled
from core.handlers.command_handlers import (
    _handle_welcome_fed_commands, _handle_admin_feature_commands,
    _handle_feature_keywords, _handle_group_admin_commands,
    _handle_module_commands, _handle_extended_commands,
)
from core.handlers.ai_reply_handler import (
    _dispatch_p10_ai, _build_convert_hint, _build_emotional_hint,
    _build_normal_hint, _notify_admin_for_deep_conversation,
)

logger = get_logger("message_dispatcher")


def _strip_direct_bot_mention(text: str, bot_username: str) -> tuple[str, bool]:
    """移除群聊里对当前 Bot 的精确 @，并返回是否真实点名。

    Telegram username 不区分大小写；边界必须精确，避免把
    ``@MoryBot_backup`` 之类的其他账号误判为当前 Bot。
    """
    username = str(bot_username or "").strip().lstrip("@")
    raw = str(text or "")
    if not username:
        return raw, False
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_])@{re.escape(username)}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    cleaned, count = pattern.subn(" ", raw)
    return " ".join(cleaned.split()).strip(), count > 0


def _is_group_verification_number(text: str) -> bool:
    """群内纯数字视为新人验证流量，不参与聊天统计、画像或 AI。"""
    compact = "".join(str(text or "").split())
    return bool(compact) and compact.isdecimal()


# 【v5.31.2 修复】VPS 运行在 UTC，时段/日期相关逻辑必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))

# ── 连续对话追踪（内存字典 + 线程安全）────────────────────────────
# key=uid, value={"count": int, "last_time": float}
# 用于：绿茶风反问（保持对话）+ 连续对话后的转化引导植入
_conv_tracker = {}
_conv_lock = Lock()  # 防止多线程并发修改字典导致RuntimeError
_CONV_TIMEOUT = 300  # 5分钟无对话则计数清零
_conv_last_cleanup = 0  # 上次清理时间戳
_MAX_CONV_ENTRIES = 1000  # 最大条目数限制

# ── 视奸雷达冷却机制（内存字典 + 线程安全）────────────────────────
# 防止同一用户频繁触发导致管理员被刷屏
_radar_cooldown = {}  # key=uid, value=上次触发时间戳
_radar_lock = Lock()  # 防止多线程并发修改字典导致RuntimeError
_RADAR_COOLDOWN = 3600  # 1小时冷却时间
_radar_last_cleanup = 0  # 上次清理时间戳

# ═══════════════════════════════════════════════════════════════════════
#  辅助工具函数
# ═══════════════════════════════════════════════════════════════════════

def _extract_uid(text, m=None):
    """从文本中提取用户ID，支持纯数字和@username格式"""
    text = text.strip()
    # 纯数字
    if text.isdigit():
        return int(text)
    # @username → 尝试从回复消息中获取
    if text.startswith("@") and m and m.reply_to_message:
        return m.reply_to_message.from_user.id
    # 回复消息的用户
    if m and m.reply_to_message:
        return m.reply_to_message.from_user.id
    return None


def _cleanup_conv_tracker():
    """清理超时的对话追踪条目（每10分钟执行一次，线程安全）"""
    global _conv_last_cleanup
    now = time.time()
    if now - _conv_last_cleanup < 600:
        return
    _conv_last_cleanup = now
    with _conv_lock:
        expired = [uid for uid, v in _conv_tracker.items() if now - v["last_time"] > _CONV_TIMEOUT]
        for uid in expired:
            del _conv_tracker[uid]
        # 超出上限时淘汰最老的条目
        if len(_conv_tracker) > _MAX_CONV_ENTRIES:
            sorted_uids = sorted(_conv_tracker.items(), key=lambda x: x[1]["last_time"])
            for uid, _ in sorted_uids[:len(_conv_tracker) - _MAX_CONV_ENTRIES]:
                del _conv_tracker[uid]


def _cleanup_radar_cooldown():
    """定期清理过期的视奸雷达冷却记录"""
    global _radar_last_cleanup
    now = time.time()
    if now - _radar_last_cleanup < 3600:  # 每小时清理一次
        return
    _radar_last_cleanup = now
    with _radar_lock:
        expired = [uid for uid, ts in _radar_cooldown.items() if now - ts > _RADAR_COOLDOWN]
        for uid in expired:
            del _radar_cooldown[uid]


def _calc_humanized_delay(text: str, is_priv: bool, conv_count: int = 0, config: dict = None) -> float:
    """计算拟人化回复延迟（秒），让Bot不再秒回

    规则：
    - 根据回复长度分级：短/中/长
    - 私聊比群聊稍慢（更亲密更慢节奏）
    - 深夜(0-5点)额外加2-4秒（"困了打字慢"）
    - 连续对话第3轮起延迟递减（"聊嗨了回复变快"）
    - ±30%随机抖动避免机械感
    """
    cfg_speed = "human"  # 默认值
    if config:
        cfg_speed = config.get("REPLY_SPEED", "human")

    speed_presets = {
        "fast":   (0.5, 2.0),
        "normal": (2.0, 5.0),
        "slow":   (5.0, 12.0),
        "human":  None,
    }
    preset = speed_presets.get(cfg_speed, None)
    if preset and cfg_speed != "human":
        lo, hi = preset
        return round(random.uniform(lo, hi), 1)

    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cn_chars <= 20:
        base = random.uniform(2.0, 4.5)
    elif cn_chars <= 60:
        base = random.uniform(3.0, 7.0)
    else:
        base = random.uniform(5.0, 10.0)

    if is_priv:
        base *= 1.2

    hour = datetime.now(_CST).hour
    if 0 <= hour < 5:
        base += random.uniform(2.0, 4.0)

    if conv_count >= 3:
        reduction = min(conv_count * 0.4, 2.5)
        base = max(1.0, base - reduction)

    jitter = base * random.uniform(-0.3, 0.3)
    base += jitter

    return round(max(0.5, min(15.0, base)), 1)


def _delayed_reply(
    bot,
    chat_id,
    reply_to_msg,
    text,
    delay_seconds,
    mory_bot,
    is_priv=False,
    reply_markup=None,
):
    """非阻塞延迟发送回复，期间持续typing状态

    用threading.Timer实现延迟，不阻塞线程池。
    后台线程每5秒续一次typing状态直到消息发出。
    群聊消息发送后自动添加反馈按钮。
    """
    def _do_send():
        try:
            send_kwargs = {"reply_markup": reply_markup} if reply_markup is not None else {}
            sent = mory_bot.reply_and_track(reply_to_msg, text, **send_kwargs)
            if sent and not is_priv and reply_markup is None:
                try:
                    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                    fb_markup = InlineKeyboardMarkup()
                    fb_markup.row(
                        InlineKeyboardButton("👍", callback_data=f"fb_like_{sent.message_id}"),
                        InlineKeyboardButton("👎", callback_data=f"fb_dislike_{sent.message_id}"),
                    )
                    bot.edit_message_reply_markup(chat_id=sent.chat.id, message_id=sent.message_id, reply_markup=fb_markup)
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.warning(f"延迟发送失败: {e}")

    bot.send_chat_action(chat_id, "typing")

    timer = threading.Timer(delay_seconds, _do_send)
    timer.daemon = True
    timer.start()

    if delay_seconds > 4:
        def _keep_typing():
            remaining = delay_seconds
            while remaining > 0:
                sleep_time = min(5.0, remaining)
                time.sleep(sleep_time)
                remaining -= sleep_time
                if remaining > 0:
                    try:
                        bot.send_chat_action(chat_id, "typing")
                    except Exception:
                        break
        t = threading.Thread(target=_keep_typing, daemon=True)
        t.start()


def _split_for_private(text: str) -> list[str]:
    """将长回复拆分为两段，用于私聊分段发送

    拆分规则：在自然语句边界（。！？…~）处拆分
    第一段占总长度40-60%
    """
    if len(text) < 60:
        return [text]

    split_chars = ['。', '！', '？', '…', '~', '～', '！', '？']
    mid = int(len(text) * random.uniform(0.4, 0.6))

    best_pos = -1
    for i in range(mid, min(mid + 20, len(text))):
        if text[i] in split_chars:
            best_pos = i + 1
            break

    if best_pos == -1:
        for i in range(max(mid - 20, 0), mid):
            if text[i] in split_chars:
                best_pos = i + 1
                break

    if best_pos <= 0 or best_pos >= len(text):
        return [text]

    part1 = text[:best_pos].rstrip()
    part2 = text[best_pos:].lstrip()

    if not part1 or not part2:
        return [text]

    if not part1.endswith(('…', '~', '～', '—')):
        part1 += '…'

    return [part1, part2]


def _generate_late_night_warning(ai, uname, is_group, uid):
    """生成深夜撩人警告消息（带随机性和人设）

    策略：60%调用AI生成（带随机seed），40%使用备用文案库
    这样既保证多样性，又避免每次都要等AI响应
    """
    # 40%概率直接使用备用文案（快速响应）
    if random.random() < 0.4:
        return _get_late_night_fallback(uname)

    # 60%概率调用AI生成（带随机seed保证每次不同）
    try:
        seed = uid + int(time.time()) % 3600  # 每小时一个seed区间
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
            return ai_reply.strip()[:100]  # 截断保护
    except Exception as e:
        logger.debug(f"AI生成深夜回复失败，使用备用文案：{e}")

    # AI失败时fallback
    return _get_late_night_fallback(uname)


def _get_late_night_fallback(uname):
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


# ═══════════════════════════════════════════════════════════════════════
#  Function Calling 工具定义
# ═══════════════════════════════════════════════════════════════════════

def _get_function_tools():
    """返回 AI 可用工具。

    ReplyContract v1 禁止模型绕过统一阶段判定主动发价格表或私聊推销，
    因此普通回复不再暴露销售类 Function Calling 工具。
    """
    return []


def get_function_tools():
    """返回AI可用的工具列表（OpenAI function calling格式）【公开导出】"""
    return _get_function_tools()


def _is_admin_uid(config: dict, uid: int) -> bool:
    """判断用户是否为管理员。"""
    admin_ids = set((config or {}).get("ADMIN_IDS", []) or [])
    admin_id = (config or {}).get("ADMIN_ID", 0)
    if admin_id:
        admin_ids.add(admin_id)
    return uid in admin_ids


def _handle_tool_calls(message: dict, bot, m, config: dict, db) -> str | None:
    """处理AI的函数调用，执行对应操作，返回AI生成的文字回复。
    如果AI同时生成了文字+函数调用，文字回复会被附加到工具执行结果后面。
    """
    tool_calls = message.get("tool_calls", [])
    text_content = message.get("content", "")

    if not tool_calls:
        return text_content or None

    tool_outputs = []
    for tc in tool_calls:
        func = tc.get("function", {})
        func_name = func.get("name", "")

        try:
            import json as _json
            args = {}
            if func.get("arguments"):
                try:
                    args = _json.loads(func["arguments"])
                except Exception:
                    args = {}

            if func_name in {"send_price_list", "send_private_guide"}:
                # 兼容旧模型/缓存返回的工具调用，但绝不执行外部发送动作。
                logger.warning(
                    "🔧 已拦截废弃销售工具 %s uid=%s",
                    func_name,
                    m.from_user.id,
                )
            else:
                logger.warning(f"🔧 未知工具: {func_name}")
        except Exception as e:
            logger.error(f"🔧 工具执行失败 {func_name}: {e}")

    # 返回AI原始文字回复 + 工具执行结果提示
    if tool_outputs:
        return (text_content + "\n" + "\n".join(tool_outputs)) if text_content else "\n".join(tool_outputs)
    return text_content or None


def _exec_send_price_list(bot, m, config: dict, args: dict) -> str:
    """废弃兼容入口：不发送价格表或私聊，只返回安全的预览目标。"""
    return "想先了解的话可以去 @moryselect 看预览，没写清楚的再问我呀。"


def _exec_send_private_guide(bot, m, config: dict, args: dict) -> str:
    """废弃兼容入口：不主动私聊用户，只返回安全的预览目标。"""
    return "想先了解的话可以去 @moryselect 看预览，没写清楚的再问我呀。"


# ═══════════════════════════════════════════════════════════════════════
#  DispatchContext 数据类
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DispatchContext:
    """消息分发上下文，封装单次分发的共享状态"""
    ctx: BotContext       # 核心上下文
    msg: Any = None       # 原始消息对象
    uid: int = 0          # 用户ID
    uname: str = ""       # 用户名
    chat_id: int = 0      # 聊天ID
    is_priv: bool = False # 是否私聊
    is_group: bool = False # 是否群聊
    text: str = ""        # 消息文本
    proactive_eligible: bool = False  # 是否符合主动消息条件
    intent: dict = field(default_factory=lambda: {"intent": "chat", "source": "disabled"})  # [TRAE SOLO CN] v5.19.0 意图路由结果
    _analysis: dict = field(default_factory=dict)  # 中间分析结果
    conversation_history: list = field(default_factory=list)  # 同一用户/聊天最近几轮真实对话
    contextual_purchase: bool = False  # 当前短句是否承接上一轮购买/定制意图
    bot_mentioned: bool = False  # 群聊文本是否精确 @ 当前 Bot
    # [TRAE SOLO CN v5.24.0 阶段2-D] 多 Bot 共享上下文（跨 Bot 画像 + 漏斗状态）
    shared_profile: dict = field(default_factory=dict)        # 跨 Bot 用户画像（来自 shared_db）
    shared_funnel_state: str = ""                             # 跨 Bot 漏斗状态（touched/interested/carted/converted/unknown）


# ═══════════════════════════════════════════════════════════════════════
#  核心分发函数
# ═══════════════════════════════════════════════════════════════════════

def master_handler(m, ctx: BotContext):
    """全域消息主分发器入口"""
    try:
        dispatch(m, ctx)
    except Exception as e:
        logger.error(f"❌ 主分发器异常：{e}\n{traceback.format_exc()}")
        # 全局故障通知：任何未捕获异常都通知管理员
        try:
            from modules.auto_tasks import _notify_admin_system_failure
            _notify_admin_system_failure(ctx.resource_manager, "主分发器未捕获异常", f"{e}\n{traceback.format_exc()[:200]}", "🚨")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
def dispatch(m, ctx: BotContext):
    """消息分发核心逻辑（优先级严格控制）"""
    try:
        do_dispatch(m, ctx)
    except Exception as e:
        # [v5.25.0 阶段1-B] WriteQueue 背压降级：核心写入队列满时返回友好文案
        if "WriteQueueFullError" in type(e).__name__:
            clear_logging_context()
            logger.warning(f"⚠️ WriteQueue 背压降级：{e}")
            try:
                uid = getattr(m, "from_user", None)
                uid = uid.id if uid else 0
                chat_id = getattr(m, "chat", None)
                chat_id = chat_id.id if chat_id else 0
                if uid and chat_id:
                    # 人设内降级文案（傲娇风格）
                    ctx.bot.send_message(
                        chat_id,
                        "Mory 脑子现在有点乱，等本姑娘三秒钟再试嘛~ 💭",
                        reply_to_message_id=getattr(m, "message_id", None),
                    )
            except Exception as send_err:
                logger.debug(f"降级文案发送失败: {send_err}")
            return
        clear_logging_context()
        logger.error(f"❌ 分发器内部异常：{e}\n{traceback.format_exc()}")
        try:
            from modules.auto_tasks import _notify_admin_system_failure
            _notify_admin_system_failure(ctx.resource_manager, "分发器内部异常", f"{e}\n{traceback.format_exc()[:200]}", "🚨")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
def do_dispatch(m, ctx: BotContext):
    """消息分发核心逻辑（优先级严格控制）

    依次调用各优先级子函数，任一子函数返回True表示消息已处理完毕
    """
    # ── 分布式追踪：消息分发全链路 Span ──
    _tracing_enabled = is_tracing_enabled()
    if _tracing_enabled:
        from core.tracing import get_tracer
        _tracer = get_tracer("message_dispatcher")
        _dispatch_span = _tracer.start_span(
            "message.dispatch",
            attributes={
                "messaging.chat.type": m.chat.type or "unknown",
                "messaging.chat.id": m.chat.id,
                "messaging.user.id": m.from_user.id,
                "messaging.user.name": (m.from_user.first_name or "?")[:50],
                "messaging.text.length": len(m.text or ""),
            }
        )
    else:
        _dispatch_span = None

    try:
        _do_dispatch_inner(m, ctx, _dispatch_span)
    finally:
        if _dispatch_span:
            _dispatch_span.end()


def _do_dispatch_inner(m, ctx: BotContext, span=None):
    """消息分发内部逻辑（与 do_dispatch 分离以支持追踪）"""
    # ── 配置热重载检查 ──
    from core.bot_initializer import _check_config_hot_reload
    _check_config_hot_reload(ctx.config)

    # ── DEBUG 全量消息入口日志 ──
    _dbg_msg = (m.text or "")[:50]
    _dbg_uname = (m.from_user.first_name or "?")[:20]
    _dbg_chat_type = m.chat.type or "?"
    _dbg_chat_id = str(m.chat.id)
    _dbg_uid = str(m.from_user.id)
    logger.info(f"[MSG_IN] uid={_dbg_uid} name={_dbg_uname} chat={_dbg_chat_id}({_dbg_chat_type}) type={_dbg_chat_type} text='{_dbg_msg}'")

    # ── 基本信息提取 ──
    msg_text  = m.text or ""
    uid       = m.from_user.id
    uname     = m.from_user.first_name or "神秘人"
    chat_id   = m.chat.id
    is_priv   = m.chat.type == "private"
    is_group  = m.chat.type in ("group", "supergroup")

    # ── i18n: 根据用户 language_code 设置当前会话语言 ──
    # Telegram 用户的 language_code 属性（如 "zh-hans", "en"）会被自动规范化
    # 后续调用 _("key") 时会使用用户偏好的语言返回翻译
    try:
        set_user_language(m.from_user)
    except Exception as e:
        logger.debug(f"设置用户语言失败: {e}")

    # 设置日志上下文（request_id 贯穿同一次请求的失败链，便于跨线程/跨进程串联诊断）
    request_id = uuid.uuid4().hex[:12]
    set_logging_context(uid=uid, chat_id=chat_id, msg_id=m.message_id, uname=uname, request_id=request_id)

    # [v5.24.0 阶段3-C] 多 Bot 路由检查：群组消息按 bot_group_routing 表决定是否响应
    # 默认关闭（BOT_ROUTING_ENABLED=False 时 should_handle 直接返回 True，向后兼容）
    # 仅对群组消息生效，私聊不受路由控制
    if is_group:
        try:
            from core.bot_routing import should_handle
            if not should_handle(ctx.bot_id, chat_id, "group_chat"):
                logger.debug(f"[ROUTING] bot={ctx.bot_id} 不处理 chat={chat_id} 的 group_chat 模块，静默退出")
                clear_logging_context()
                return
        except Exception as e:
            logger.debug(f"路由检查异常 bot={ctx.bot_id} chat={chat_id}: {e}")

    # 新人算术验证答案优先交给验证码模块；无活动会话的纯数字也静默忽略。
    # 必须位于历史、last_active、画像、快照、积分和 AI 之前，避免污染真实聊天数据。
    if is_group and _is_group_verification_number(msg_text):
        try:
            from modules.verification import check_verification_answer
            check_verification_answer(ctx.bot, m, ctx.config)
        except Exception as e:
            logger.warning(
                "群验证数字处理异常 uid=%s chat=%s: %s",
                uid,
                chat_id,
                e,
            )
        clear_logging_context()
        return

    # 构建分发上下文
    dctx = DispatchContext(
        ctx=ctx,
        msg=m,
        uid=uid,
        uname=uname,
        chat_id=chat_id,
        is_priv=is_priv,
        is_group=is_group,
        text=msg_text,
    )

    # 群聊点名既要强制响应，也不能把 ``@BotUsername`` 当成用户问题交给
    # 意图路由和模型。原文仍由快照/安全链保存，业务处理只使用清洗后的正文。
    if is_group:
        cleaned_text, bot_mentioned = _strip_direct_bot_mention(
            msg_text, ctx.bot_username
        )
        if bot_mentioned:
            dctx.bot_mentioned = True
            dctx.text = cleaned_text

    # 当前轮进入意图路由和 AI 前，先读取同一用户、同一聊天的最近真实对话。
    # 不能只把历史写进摘要缓冲却不给本轮判断/模型使用。
    try:
        from core.growth_optimizer import (
            is_contextual_purchase_intent,
            load_recent_conversation,
        )
        dctx.conversation_history = load_recent_conversation(
            ctx.db, uid, chat_id, limit=3, max_age_seconds=1800
        )
        dctx.contextual_purchase = is_contextual_purchase_intent(
            msg_text, dctx.conversation_history
        )
    except Exception as e:
        logger.debug(f"近期对话上下文加载失败 uid={uid} chat={chat_id}: {e}")

    # [TRAE SOLO CN v5.24.0 阶段2-D] 多 Bot 共享上下文读取
    # 从 shared_db 读取跨 Bot 画像 + 漏斗状态，注入 dctx 供后续 P9/P10 使用
    # 主 Bot 读取自身 DB（等价本地查询），media Bot 读取主 Bot DB（跨 Bot 感知）
    # 失败静默降级，不影响主流程
    try:
        from core.shared_db import get_shared_profile, get_shared_conversion_state
        dctx.shared_profile = get_shared_profile(uid)
        dctx.shared_funnel_state = get_shared_conversion_state(uid)
        if dctx.shared_profile or dctx.shared_funnel_state != "unknown":
            logger.debug(f"[SHARED_CTX] uid={uid} profile_tags={dctx.shared_profile.get('tags', [])} funnel={dctx.shared_funnel_state}")
    except Exception as e:
        logger.debug(f"共享上下文读取失败 uid={uid}: {e}")

    # [TRAE SOLO CN v5.12.3 修复：在所有优先级判断之前更新 last_active
    # 确保无论后续哪个优先级拦截终止分发，last_active 都会被更新
    # 这是 ACTIVE_USERS_7D=0 的根因修复：之前如果 P1 黑名单/P3 敏感词等拦截，
    # P2 积分处理不会执行，last_active 就不会被更新
    try:
        db = ctx.db
        db.update_last_active(uid)
    except Exception as e:
        logger.debug(f"update_last_active 失败 uid={uid}: {e}")

    # 群聊首次精确 @ 的欢迎链必须是确定性零 TOKEN 路径。先只读判断是否已欢迎，
    # 未欢迎时仍记录消息，但跳过可能触发 LLM 的异步记忆摘要；安全/广告门禁照常执行。
    skip_memory_summary = False
    if is_group and dctx.bot_mentioned:
        try:
            skip_memory_summary = not db.has_onboarding_delivery(
                uid=uid,
                chat_id=chat_id,
                surface="group_mention",
            )
        except Exception as e:
            # 状态未知时按首次候选处理，宁可少做一次摘要，也不能让欢迎链暗耗 TOKEN。
            skip_memory_summary = True
            logger.warning(f"首次@状态预检失败，跳过记忆摘要 uid={uid} chat={chat_id}: {e}")

    # [TRAE SOLO CN v5.24.0 阶段3-A] 混合记忆：记录 user 消息 + 检查触发
    # 每条 user 消息都入缓冲；非首次欢迎消息达到 15 轮阈值时才允许异步摘要。
    try:
        from core.memory_summarizer import record_message, check_and_trigger
        record_message(uid, "user", msg_text)
        if not skip_memory_summary:
            check_and_trigger(uid, db)
    except Exception as e:
        logger.debug(f"记忆触发检查失败 uid={uid}: {e}")

    # [TRAE SOLO CN v5.24.0 阶段3-B] 新用户冷启动：首条消息生成种子画像摘要
    # 零成本（不调 LLM，纯规则分析），幂等（已有 memory_summary 则跳过），失败静默降级
    try:
        from core.memory_summarizer import seed_initial_memory
        seed_initial_memory(uid, msg_text, db)
    except Exception as e:
        logger.debug(f"种子画像冷启动失败 uid={uid}: {e}")

    # [TRAE SOLO CN] v5.19.0 新增：非侵入式画像采集（默认关闭）
    # 挂在 last_active 之后，所有 P 之前，确保每条消息都被采集
    if ctx.config.get("USER_PROFILE_ENABLED", False):
        try:
            profile_learner = getattr(ctx, "profile_learner", None)
            if profile_learner:
                profile_learner.learn_from_message(uid, msg_text, chat_id, int(time.time()))
        except Exception as e:
            logger.debug(f"画像采集异常 uid={uid}: {e}")

    # [TRAE SOLO CN] v5.15.3 新增：消息追踪快照（AGENTS.md 教训 #17 落实）
    # 之前 P1 拦截只 return True 静默吞消息，导致 18:36 教白嫖消息 msg_id 不可知，历史消息无法追溯删除
    # 现在每条进入分发流程的消息都入 message_snapshots 表，永久保留
    # 未来封禁/追溯扫描/批量删除都能直接查到 msg_id
    if is_group and dctx.msg and getattr(dctx.msg, "message_id", None):
        try:
            db.snapshot_message(
                chat_id=chat_id,
                msg_id=dctx.msg.message_id,
                user_id=uid,
                text=msg_text,
                ts=int(time.time())
            )
        except Exception as e:
            logger.debug(f"snapshot_message 失败: uid={uid} mid={getattr(dctx.msg, 'message_id', '?')}: {e}")

    # ── P0-：转发即删除（私聊中转发群消息到 Bot，自动删除原消息）──
    if _dispatch_forward_delete(dctx):
        return

    # ── P0.1：关联频道转发联动（取消自动置顶 + 评论转化），命中即停止后续分发 ──
    try:
        if dctx.is_group and dctx.msg and getattr(dctx.msg, "sender_chat", None):
            from modules.linked_channel_sync import handle_group_forward
            if handle_group_forward(ctx.bot, dctx.msg, ctx.config, db=ctx.db):
                clear_logging_context()
                return
    except Exception as e:
        logger.debug(f"P0.1 关联频道联动处理异常（静默）: {e}")

    # ── P0：新人入群 ──
    if _dispatch_p0_member(dctx):
        return

    # [Bug-02 修复] /unban 早路由：必须在 P1 黑名单拦截之前处理
    # 被误封禁的用户发 /unban 时，P1 黑名单拦截会先返回 True 吞掉解封指令，
    # 导致用户无法自助解封。这里强制在 P1 之前拦截 /unban/解封 等指令。
    # 注意：用 strip() 容忍前导空格，避免 " /unban" 被漏判
    _stripped = msg_text.strip() if msg_text else ""
    if _stripped.startswith(("/unban", "/解封", "解封 ", "解除封禁")) or _stripped == "解封":
        try:
            from modules.ad_enforcement import handle_unban_command
            handle_unban_command(ctx.bot, m, ctx.config, ctx.db,
                                 ad_detector=getattr(ctx, "ad_detector", None))
            logger.info(f"🔓 [Bug-02 早路由] /unban 已在 P1 前处理 uid={uid} chat={chat_id}")
            clear_logging_context()
            return
        except Exception as unban_err:
            logger.warning(f"🔓 [Bug-02 早路由] /unban 处理异常，回退到 P5.6: {unban_err}")
            # 异常时不 return，让 P5.6 兜底处理

    # ── P1-P3：安全处理（黑名单/敏感词/夜间模式）──
    if _dispatch_p1_p3_security(dctx):
        return

    # ── P3.5：广告检测（必须在积分和反刷屏之前执行，避免广告用户被5分钟禁言而非永久封禁）──
    if _dispatch_p3_5_ad_detection(dctx):
        return

    # ── P3.55：群聊首次精确 @ 欢迎（确定性本地模板，必须早于意图路由/AI）──
    if _dispatch_first_group_mention_onboarding(dctx):
        return

    # ── P3.6：意图路由（v5.19.0 新增，分类后写入 dctx.intent 供 P10 使用）──
    _dispatch_p3_6_intent_routing(dctx)

    # ── P2：积分处理（广告检测之后，避免广告消息获得积分）──
    if _dispatch_p2_points(dctx):
        return

    # ── P4：反刷屏 ──
    if _dispatch_p4_flood(dctx):
        return

    # ── P5-P9：命令和功能处理 ──
    if _dispatch_p5_p9_commands(dctx):
        return

    # ── P10：AI回复 ──
    _dispatch_p10_ai(dctx)


def _dispatch_first_group_mention_onboarding(dctx: DispatchContext) -> bool:
    """每个用户在每个群首次精确 @ 时发送与私聊 /start 完全同款欢迎卡。

    该路由位于意图分类和 P10 之前，运行时只访问 SQLite、本地 JPEG、Pillow
    与 Telegram Bot API，不存在 AI/LLM 调用，因此模型 Token 固定为 0。
    """
    if not dctx.is_group or not dctx.bot_mentioned:
        return False

    db = dctx.ctx.db
    surface = "group_mention"
    try:
        if db.has_onboarding_delivery(dctx.uid, dctx.chat_id, surface):
            return False
        if not db.claim_onboarding_delivery(dctx.uid, dctx.chat_id, surface):
            # 同一用户的并发更新已有一个发送者，当前消息必须停止，避免双卡。
            logger.info(
                "群聊首次@已有并发发送 uid=%s chat=%s",
                dctx.uid,
                dctx.chat_id,
            )
            clear_logging_context()
            return True
    except Exception as e:
        # 首次状态未知时不能冒险进入可能消耗 Token 的普通 AI 链。
        logger.error(
            "群聊首次@状态读取失败，已阻断AI uid=%s chat=%s reason=%s",
            dctx.uid,
            dctx.chat_id,
            e,
        )
        clear_logging_context()
        return True

    try:
        from core.start_welcome_card import send_start_welcome

        delivery = send_start_welcome(
            dctx.ctx.bot,
            dctx.msg,
            dctx.ctx.config,
            mory_bot=dctx.ctx.mory_bot,
        )
        if not db.complete_onboarding_delivery(dctx.uid, dctx.chat_id, surface):
            raise RuntimeError("欢迎卡已送达但首次状态未能持久化")
        logger.info(
            "🖼️ 群聊首次@欢迎卡已发送 uid=%s asset=%s degraded=%s",
            dctx.uid,
            delivery.asset_name,
            delivery.degraded_to_text,
        )
    except Exception as e:
        try:
            db.release_onboarding_delivery(dctx.uid, dctx.chat_id, surface)
        except Exception as release_error:
            logger.error(
                "群聊首次@释放失败 uid=%s chat=%s reason=%s",
                dctx.uid,
                dctx.chat_id,
                release_error,
            )
        logger.error(
            "群聊首次@欢迎卡未完成 uid=%s chat=%s reason=%s",
            dctx.uid,
            dctx.chat_id,
            e,
        )
    clear_logging_context()
    return True


# ═══════════════════════════════════════════════════════════════════════
#  P0：新人入群处理
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_forward_delete(dctx: DispatchContext) -> bool:
    """P0-：转发即删除。仅管理员私聊转发群消息时可删原消息。
    触发条件：
    - 私聊消息 + 管理员（ADMIN_ID / ADMIN_IDS）
    - 消息有 forward_from_chat（从群组转发而来）
    - 消息有 forward_from_message_id（原消息 msg_id）
    - 原消息发送时间在 48 小时内（Telegram API 限制）
    """
    m = dctx.msg
    ctx = dctx.ctx
    bot = ctx.bot
    CONFIG = ctx.config

    # 仅处理私聊中的转发消息
    if not dctx.is_priv:
        return False
    if not hasattr(m, "forward_from_chat") or not m.forward_from_chat:
        return False
    if not hasattr(m, "forward_from_message_id") or not m.forward_from_message_id:
        return False

    # 安全红线：非管理员不得触发群消息删除
    if not _is_admin_uid(CONFIG, dctx.uid):
        logger.warning(
            f"[转发即删除] 拒绝非管理员 uid={dctx.uid} chat={getattr(m.forward_from_chat, 'id', 0)}"
        )
        try:
            bot.reply_to(m, "❌ 仅管理员可通过转发删除群消息")
        except Exception as e:
            logger.debug(f"reply_to 非管理员拒绝提示失败: {e}")
        clear_logging_context()
        return True

    original_chat_id = m.forward_from_chat.id
    original_msg_id = m.forward_from_message_id

    try:
        bot.delete_message(original_chat_id, original_msg_id)
        logger.info(f"[转发即删除] 成功删除 chat={original_chat_id} msg_id={original_msg_id}")
        # 回复用户告知删除成功
        try:
            bot.reply_to(m, "✅ 已从群中删除该消息")
        except Exception as e:
            logger.debug(f"reply_to 删除成功提示失败: {e}")
        clear_logging_context()
        return True
    except Exception as e:
        logger.warning(f"[转发即删除] 删除失败 chat={original_chat_id} msg_id={original_msg_id}: {e}")
        # 失败时告知用户原因
        try:
            bot.reply_to(m, "❌ 删除失败（消息可能已超过48小时或 Bot 权限不足）")
        except Exception as reply_err:
            logger.debug(f"reply_to 删除失败提示失败: {reply_err}")
        # 不阻断消息继续处理（交给后续 relay 等）
        return False


def _dispatch_p0_member(dctx: DispatchContext) -> bool:
    """P0 新人入群 + 验证码 + 远程连接"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot

    # P0：新人入群
    if m.content_type == "new_chat_members":
        _handle_new_chat_members(bot, m, CONFIG, db, ctx)
        clear_logging_context()
        return True

    # P0.45：私聊黑名单优先拦截，避免进入中继、远程连接或 AI 回复。
    if dctx.is_priv and not _is_admin_uid(CONFIG, dctx.uid):
        try:
            if db.is_blacklisted(dctx.uid):
                logger.info(f"🚫 [P0] 黑名单私聊拦截: uid={dctx.uid} name={dctx.uname} text='{dctx.text[:30]}'")
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"私聊黑名单检查失败 uid={dctx.uid}: {e}")

    # P0.5：验证码回答检查
    if dctx.is_group:
        from modules.verification import check_verification_answer
        if check_verification_answer(bot, m, CONFIG):
            clear_logging_context()
            return True

    # P0.6：设置面板数值修改会话
    from modules.settings_panel import has_pending_session, apply_pending_value
    if has_pending_session(dctx.chat_id, dctx.uid):
        if apply_pending_value(bot, dctx.chat_id, dctx.uid, dctx.text, CONFIG):
            clear_logging_context()
            return True

    # P0.7：私聊远程连接转发
    if dctx.is_priv:
        try:
            from modules.remote_connect import get_connected_chat, handle_remote_message
            connected_chat = get_connected_chat(db, dctx.uid)
            if connected_chat:
                handle_remote_message(bot, m, CONFIG, db)
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P0.75：中继模式 - 管理员回复中继消息 + 用户消息即时转发
    if CONFIG.get('RELAY_MODE_ENABLED', False) and dctx.is_priv:
        try:
            from core.handlers.relay_handler import handle_admin_reply, handle_user_to_admin
            # 管理员回复中继消息
            if handle_admin_reply(bot, db, CONFIG, m):
                clear_logging_context()
                return True
            # 用户私聊消息即时转发给管理员（不等AI回复，管理员可立即回复）
            if dctx.text and not _is_admin_uid(CONFIG, dctx.uid):
                handle_user_to_admin(bot, db, CONFIG, dctx.uid, dctx.uname, dctx.text, dctx.chat_id, source_type='private')
        except Exception as e:
            logger.debug(f"P0.75中继处理异常（静默）：{e}")

    return False


def _handle_new_chat_members(bot, m, config, db, ctx: BotContext):
    """P0 新人入群处理链路（整合多模块）：
    0. 反突袭检测 → 1. 联邦封禁检查 → 2. emoji面具检查 → 3. 验证码/欢迎消息
    """
    chat_id = m.chat.id

    # 步骤0：反突袭检测
    try:
        from modules.anti_raid import check_raid
        check_raid(bot, m, config, db)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    for user in m.new_chat_members:
        user_id = user.id
        user_display = (user.first_name or "") + (user.last_name or "")

        # 步骤0.5：CAS/SpamWatch检查
        try:
            from modules.spam_watch import check_user_spam
            if check_user_spam(bot, user.id, config):
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    uid=user.id,
                    uname=user_display,
                    reason="CAS/SpamWatch广告黑名单",
                    notify_admin=True,
                )
                logger.info(f"🚫 CAS黑名单永久禁言: uid={user.id}")
                continue
        except Exception as e:
            logger.debug(f"CAS检查异常: {e}")

        # 步骤1：联邦封禁拦截
        from modules.federation import execute_fban_on_join
        if execute_fban_on_join(bot, m, config, db, user, user_display):
            logger.warning(f"🚫 联邦封禁拦截新人: {user_display}")
            continue

        # 步骤1.5：邀请记录
        try:
            from modules.invite import record_invite
            if hasattr(m, 'from_user') and m.from_user and m.from_user.id != user_id:
                record_invite(db, m.from_user.id, user_id, chat_id, config, bot)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        # 步骤2：emoji面具检测
        from modules.emoji_mask_detector import check_emoji_mask_in_username
        emoji_hit, emoji_reason = check_emoji_mask_in_username(user_display, config)
        if emoji_hit:
            logger.warning(f"🎭 emoji面具拦截新人: {user_display}")
            from modules.ad_enforcement import enforce_ad_user
            enforce_ad_user(
                bot=bot,
                db=db,
                config=config,
                chat_id=chat_id,
                uid=user_id,
                uname=user_display,
                reason=emoji_reason or "入群用户名emoji面具广告",
                notify_admin=True,
            )
            continue

        # 步骤2.5：资料层广告检测（名字 + BIO + Premium emoji状态）
        try:
            # 【v5.38.22】检测前置豁免：白名单/群管理员在资料检测前直接跳过（零处置）
            from core.handlers.member_handlers import _is_member_ad_exempt
            if _is_member_ad_exempt(bot, config, chat_id, user_id):
                logger.info(
                    f"👥 [入群资料检测] 豁免白名单/群管理员，跳过检测: uid={user_id} display={user_display}"
                )
                continue
            user_bio = ""
            chat_info = None
            try:
                chat_info = bot.get_chat(user_id)
                user_bio = (getattr(chat_info, "bio", "") or "")[:500]
            except Exception as e:
                logger.debug(f"入群拉取用户bio失败 uid={user_id}: {e}")

            from modules.ad_profile_signals import detect_profile_ad_signal
            profile_result = detect_profile_ad_signal(
                bot, user, user_bio, config, chat_info=chat_info
            )
            if profile_result.get("is_ad"):
                logger.warning(
                    f"🚫 [入群资料检测] 拦截广告新人: {user_display}({user_id}) "
                    f"原因={profile_result.get('reason', '')[:120]}"
                )
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    uid=user_id,
                    uname=user_display,
                    reason=f"入群资料检测: {profile_result.get('reason', '')[:200]} BIO:{user_bio[:120]}",
                    notify_admin=True,
                )
                continue

            ad_detector = getattr(ctx, "ad_detector", None) if ctx else None
            if ad_detector:
                ad_result = ad_detector.detect(
                    username=user_display,
                    msg="",
                    user_id=user_id,
                    bot=bot,
                    bio=user_bio,
                    chat_id=chat_id,
                )
                score = ad_result.get("score", 0) + int(profile_result.get("score", 0) or 0)
                is_ad = ad_result.get("is_ad", False)
                action = ad_result.get("action", "none")
                reason = ad_result.get("reason", "")
                if is_ad and action == "ban":
                    logger.warning(
                        f"🚫 [入群即检测] 拦截广告新人: {user_display}({user_id}) "
                        f"评分={score} 动作={action} 原因={reason[:100]}"
                    )
                    from modules.ad_enforcement import enforce_ad_user
                    enforce_ad_user(
                        bot=bot,
                        db=db,
                        config=config,
                        chat_id=chat_id,
                        uid=user_id,
                        uname=user_display,
                        reason=f"入群即检测: {reason[:200]} BIO:{user_bio[:120]}",
                        notify_admin=True,
                    )
                    continue
                if score >= 2:
                    logger.info(
                        f"⚠️ [入群即检测] 可疑新人: {user_display}({user_id}) "
                        f"评分={score} 原因={(reason or profile_result.get('reason', ''))[:100]}"
                    )
                    try:
                        ad_detector.track_suspicious_user(
                            user_id,
                            0,
                            chat_id,
                            f"[入群即检测] {(reason or profile_result.get('reason', ''))[:80]}",
                            score,
                        )
                    except Exception as e:
                        logger.debug(f"追踪可疑用户失败: {e}")
        except Exception as e:
            logger.error(f"入群广告资料检测异常 uid={user_id}: {e}")

        # 步骤3：启动验证码
        from modules.verification import start_verification, check_verification_answer
        from modules.welcome_customization import send_welcome_message
        from modules.group_mgr import handle_new_members
        from modules.force_subscribe import check_force_subscribe

        ver_config = config.get("VERIFICATION_CONFIG", {})
        if ver_config.get("enable", False):
            try:
                from telebot.types import ChatPermissions
                bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            question, keyboard = start_verification(bot, chat_id, user_id, user_display, config)
            try:
                if keyboard:
                    bot.send_message(chat_id, question, reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, question)
            except Exception as e:
                logger.error(f"发送验证码失败: {e}")
                try:
                    bot.restrict_chat_member(
                        chat_id, user_id,
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                        ),
                    )
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
        else:
            keyword_manager = getattr(ctx, 'keyword_manager', None) if ctx else None
            handle_new_members(bot, m, config, db, keyword_manager)

        # 步骤4：发送定制欢迎消息
        try:
            send_welcome_message(bot, m, config, db)
        except Exception as e:
            logger.debug(f"发送定制欢迎消息失败: {e}")

        # 强制订阅检查
        try:
            check_force_subscribe(bot, m, config, db)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
# ═══════════════════════════════════════════════════════════════════════
#  P1-P3：安全处理（黑名单/敏感词/广告检测）
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p1_p3_security(dctx: DispatchContext) -> bool:
    """P1 黑名单 → P3 敏感词 → P3.5 广告检测"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_group = dctx.is_group

    # P1：黑名单用户 → 永久禁言 + 删除消息 + 同步黑名单 + 写日志
    # [Codex] 2026-06-12 策略纠正：广告/黑名单链路不踢人，留群但彻底禁言
    if db.is_blacklisted(uid):
        if not is_group:
            logger.info(f"🚫 [P1] 黑名单非群聊拦截: uid={uid} name={uname} chat={chat_id} text='{msg[:30]}'")
            clear_logging_context()
            return True
        from modules.ad_enforcement import enforce_ad_user
        enforce_ad_user(
            bot=bot,
            db=db,
            config=CONFIG,
            chat_id=chat_id,
            uid=uid,
            uname=uname,
            reason=f"黑名单拦截:{uname}",
            message=m,
            current_msg_id=getattr(m, "message_id", 0),
            notify_admin=False,
        )
        logger.info(f"🚫 [P1] 黑名单拦截: uid={uid} name={uname} chat={chat_id} mid={m.message_id} text='{msg[:30]}'")
        clear_logging_context()
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P3.6：意图路由（v5.19.0 新增）
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p3_6_intent_routing(dctx: DispatchContext) -> bool:
    """[TRAE SOLO CN] v5.19.0 P3.6 意图路由：分类后写入 dctx.intent，供 P10 stage_hint 使用。

    默认关闭（INTENT_ROUTING_ENABLED=false），关闭时 dctx.intent 保持默认值。
    高置信度投诉意图 → 直接通知管理员，不进 P10 AI。
    """
    ctx = dctx.ctx
    if not ctx.config.get("INTENT_ROUTING_ENABLED", False):
        return False
    try:
        intent_router = getattr(ctx, "intent_router", None)
        if not intent_router:
            return False
        dctx.intent = intent_router.classify(
            dctx.text,
            conversation_history=getattr(dctx, "conversation_history", []),
        )
        # 高置信度投诉 → 转人工通知
        if (dctx.intent.get("intent") == "complaint"
                and dctx.intent.get("confidence", 0.0) > 0.6
                and dctx.intent.get("source") in ("rule", "llm")):
            try:
                from modules.auto_tasks import _notify_admin_system_failure
                _notify_admin_system_failure(
                    ctx.resource_manager, "用户投诉预警",
                    f"uid={dctx.uid} name={dctx.uname} chat={dctx.chat_id}\n意图={dctx.intent}\n内容={dctx.text[:200]}",
                    "⚠️"
                )
            except Exception as e:
                logger.debug(f"投诉通知失败: {e}")
            # 投诉不拦截，继续走 P10 AI 回复
        logger.debug(f"意图路由 uid={dctx.uid} intent={dctx.intent}")
    except Exception as e:
        logger.debug(f"意图路由异常 uid={dctx.uid}: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════
#  P2：积分处理
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p2_points(dctx: DispatchContext) -> bool:
    """P2 积分/活跃度更新 + 消息缓存 + AFK + 安全检测"""
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

    # P2：更新用户活跃度 / 群ID / 积分
    from modules.points_enhanced import check_level_up
    _points_rules = CONFIG.get("POINTS_RULES", {})
    _speech_pts = _points_rules.get("speech", 1)
    _daily_limit = _points_rules.get("daily_limit", 50)
    if is_group and _daily_limit > 0:
        _today_speech_pts = db.get_today_speech_points(uid)
        if _today_speech_pts >= _daily_limit:
            _speech_pts = 0
    _level_result = db.upsert_user_with_points(uid, uname, "private" if is_priv else "group", pts=_speech_pts)
    if _speech_pts > 0:
        # [Trae CN v5.12.0] 传 db 给 check_level_up 用于入库 broadcast_tracking（孤儿播报30S删）
        check_level_up(bot, chat_id, uid, uname, _level_result, CONFIG, db=db)
    if is_group:
        gid = CONFIG.get("GROUP_ID", 0)
        if gid == 0:
            CONFIG["GROUP_ID"] = chat_id
            ctx.save_config()

    # P2.2：消息缓存（反撤回）
    try:
        from modules.antidelete import cache_message
        if m.text or m.caption:
            content = m.text or m.caption or ""
            cache_message(chat_id, m.message_id, uid, m.from_user.first_name or "", content[:500], m.content_type)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # P2.5：AFK自动解除
    if is_group:
        try:
            from modules.afk import check_afk_on_message, check_afk_mention
            check_afk_on_message(bot, m, CONFIG, db)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        # P2.6：检查@提及/回复的用户是否AFK
        try:
            from modules.afk import check_afk_mention
            entities = m.entities or []
            for ent in entities:
                if ent.type == "text_mention" and ent.user:
                    check_afk_mention(bot, m, CONFIG, db, ent.user.id)
                elif ent.type == "mention":
                    mention_text = m.text[ent.offset:ent.offset + ent.length]
                    try:
                        username = mention_text.lstrip("@")
                        chat_member = bot.get_chat_member(chat_id, username)
                        if chat_member and chat_member.user:
                            check_afk_mention(bot, m, CONFIG, db, chat_member.user.id)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        # 检查回复的用户是否AFK
        if m.reply_to_message and m.reply_to_message.from_user and not m.reply_to_message.from_user.is_bot:
            try:
                from modules.afk import check_afk_mention
                check_afk_mention(bot, m, CONFIG, db, m.reply_to_message.from_user.id)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
    # P3：黑名单词过滤
    if is_group:
        from modules.group_mgr import check_banned_words
        from modules.blocklist_modes import apply_blocklist_action
        if check_banned_words(bot, m, CONFIG, db):
            try:
                apply_blocklist_action(bot, m, CONFIG, db, chat_id, uid)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            clear_logging_context()
            return True

    # P3.2：夜间模式拦截
    if is_group:
        from modules.night_mode import should_mute_for_night_mode
        if should_mute_for_night_mode(bot, m, CONFIG):
            if can_delete_message(CONFIG):
                try:
                    bot.delete_message(chat_id, m.message_id)
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
            logger.info(f"🌙 夜间模式拦截: uid={uid} msg={msg[:30]}")
            clear_logging_context()
            return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P3.5：广告检测（独立于积分系统，优先于反刷屏执行）
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p3_5_ad_detection(dctx: DispatchContext) -> bool:
    """P3.5 智能广告检测（零TOKEN消耗）- 独立执行，优先于反刷屏
    
    此函数独立于P2积分系统，确保广告检测在反刷屏之前执行。
    避免广告用户被5分钟临时禁言而非永久封禁。
    """
    if not dctx.is_group:
        return False

    msg = dctx.text
    if not msg:
        return False

    # 跳过 Bot 命令，避免误封 /start@Bot 等正常指令
    if msg.startswith("/"):
        return False

    # ── 分布式追踪：广告检测 Span ──
    if is_tracing_enabled():
        from core.tracing import get_tracer
        _tracer = get_tracer("ad_detection")
        with _tracer.start_as_current_span(
            "ad_detection.check",
            attributes={
                "messaging.user.id": dctx.uid,
                "messaging.chat.id": dctx.chat_id,
                "messaging.text.length": len(msg),
            }
        ) as span:
            from core.handlers.security_handlers import check_ad_detection
            result = check_ad_detection(dctx)
            span.set_attribute("ad_detection.result", "blocked" if result else "passed")
            if result:
                clear_logging_context()
            return result
    else:
        from core.handlers.security_handlers import check_ad_detection
        if check_ad_detection(dctx):
            clear_logging_context()
            return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P4：反刷屏
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p4_flood(dctx: DispatchContext) -> bool:
    """P4 反刷屏 + 锁群/慢速模式/服务消息清理/发言统计"""
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

    if not is_group:
        return False

    # 反刷屏检测
    from modules.group_mgr import check_spam
    from modules.antiflood import check_antiflood, handle_flood_user
    from modules.approvals import is_approved
    from modules.anti_channel import check_anti_channel
    from modules.nsfw_detect import check_nsfw_image
    from modules.message_locks import check_message_lock
    from modules.slow_mode import check_slow_mode
    from modules.clean_service import check_clean_service
    from modules.speech_stats import increment_speech_count
    from modules.daily_quest import get_quest_progress, check_quest_completion

    if not is_priv:
        try:
            if check_antiflood(bot, m, CONFIG, db):
                if not is_approved(db, chat_id, uid):
                    handle_flood_user(bot, m, CONFIG, db)
                    clear_logging_context()
                    return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # 反频道转发检测
    if not is_priv:
        try:
            if check_anti_channel(bot, m, CONFIG, db):
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # NSFW图片检测
    if not is_priv and (m.photo or (m.document and m.document.mime_type and m.document.mime_type.startswith("image/"))):
        try:
            if check_nsfw_image(bot, m, CONFIG, db):
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P4：反刷机制
    if check_spam(bot, m, CONFIG, db):
        clear_logging_context()
        return True

    # P4.5：锁群/消息类型限制检测
    if not is_priv:
        try:
            admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
            admin_id = CONFIG.get("ADMIN_ID", 0)
            if admin_id:
                admin_ids.add(admin_id)
            if uid not in admin_ids and not is_approved(db, chat_id, uid) and check_message_lock(bot, m, CONFIG, db):
                if can_delete_message(CONFIG):
                    try:
                        bot.delete_message(chat_id, m.message_id)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                else:
                    logger.info(f"[消息锁] 消息删除已禁用，跳过删除消息")
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P4.6：慢速模式检测
    if not is_priv:
        try:
            admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
            admin_id = CONFIG.get("ADMIN_ID", 0)
            if admin_id:
                admin_ids.add(admin_id)
            if uid not in admin_ids and check_slow_mode(bot, m, CONFIG, db):
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P4.7：服务消息自动清理
    if not is_priv:
        try:
            if check_clean_service(bot, m, CONFIG, db):
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P3.8：发言统计计数
    try:
        increment_speech_count(db, uid, chat_id)
        try:
            progress = get_quest_progress(db, uid, "speech5", CONFIG)
            if progress >= 5:
                check_quest_completion(db, uid, "speech5", CONFIG, bot, chat_id, uname)
            progress = get_quest_progress(db, uid, "speech10", CONFIG)
            if progress >= 10:
                check_quest_completion(db, uid, "speech10", CONFIG, bot, chat_id, uname)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════
#  P5-P9：命令和功能处理
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p5_p9_commands(dctx: DispatchContext) -> bool:
    """P5 机器人过滤 → P6 管理员指令 → P7 价格雷达 → P8 彩蛋 → P9 画像"""
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

    # P5：过滤野生机器人
    if any(b.lower() in uname.lower() for b in CONFIG.get("IGNORE_BOTS", [])):
        clear_logging_context()
        return True

    # P5.5：命令禁用检查
    if is_group and msg and msg.startswith("/"):
        try:
            from modules.cmd_control import is_command_disabled
            cmd_parts = msg.split()[0].lstrip("/").split("@")[0].lower()
            if is_command_disabled(db, chat_id, cmd_parts):
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")

    # P5.6：误封解封必须在私聊/群聊都早处理，避免被后续私聊反馈或群功能路由吞掉。
    if msg and (
        msg.startswith("/unban")
        or msg.startswith("/解封")
        or msg.startswith("解封 ")
        or msg == "解封"
        or msg.startswith("解除封禁")
    ):
        from modules.ad_enforcement import handle_unban_command
        handle_unban_command(bot, m, CONFIG, db, ad_detector=getattr(ctx, "ad_detector", None))
        clear_logging_context()
        return True

    # P6：管理员专属指令
    from modules.admin_cmds import handle_admin
    from modules.natural_cmd import handle_natural_admin
    admin_result = handle_admin(bot, mory_bot, m, CONFIG, db, ai, ctx.save_config)
    if admin_result:
        logger.info(f"👑 管理员指令执行成功 uid={uid} msg={msg[:30]}")
        clear_logging_context()
        return True

    # P6.3：自然语言配置
    try:
        admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            admin_ids.add(admin_id)
        is_admin_user = uid in admin_ids
        if handle_natural_admin(bot, m, CONFIG, ctx.save_config, mory_bot=mory_bot, is_admin=is_admin_user, ad_detector=ctx.ad_detector):
            logger.info(f"🗣️ 自然语言配置已处理 uid={uid} msg={msg[:30]}")
            clear_logging_context()
            return True
    except Exception as e:
        logger.error(f"🗣️ 自然语言配置处理异常: {e}")

    # P6.4：欢迎定制/联邦封禁指令
    if msg.startswith("/") and is_group:
        if _handle_welcome_fed_commands(dctx):
            return True

    # P6.5：自定义命令检测
    if is_group and msg and msg.startswith("/"):
        try:
            from modules.custom_commands import check_custom_command
            if check_custom_command(bot, m, CONFIG, db):
                logger.info(f"🔧 自定义命令触发 uid={uid} msg={msg[:30]}")
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"自定义命令检测异常: {e}")

    # 转化状态前置：关键词早路由也需遵守 opt_out / 近期 CTA 抑制
    try:
        from core.growth_optimizer import (
            get_conversion_state,
            persist_conversion_decision,
            resolve_conversion_target,
        )
        conversion_state = get_conversion_state(db, uid, chat_id)
        conversion_target, conversion_reason = resolve_conversion_target(
            msg,
            getattr(dctx, "conversation_history", []),
            mode="normal",
            state=conversion_state,
        )
        dctx.conversion_state = conversion_state
        dctx.conversion_target = conversion_target
        dctx.conversion_reason = conversion_reason
        persist_conversion_decision(db, uid, chat_id, conversion_target, conversion_reason)
    except Exception as e:
        logger.debug("预处理转化状态失败 uid=%s: %s", uid, e)

    # P6.6：关键词触发回复（ADMIN_IDS 全量管理员；opt_out 时跳过销售类关键词）
    if msg:
        try:
            is_admin = _is_admin_uid(CONFIG, uid)
            conversion_state = getattr(dctx, "conversion_state", None) or {}
            if conversion_state.get("opt_out") and not is_admin:
                logger.debug("🔑 转化 opt_out，跳过关键词销售路由 uid=%s", uid)
            elif ctx.keyword_trigger.handle_message(
                msg,
                chat_id,
                m,
                bot,
                is_admin=is_admin,
                conversation_history=getattr(dctx, "conversation_history", []),
            ):
                logger.info(f"🔑 关键词触发回复成功 uid={uid} msg={msg[:30]}")
                clear_logging_context()
                return True
        except Exception as e:
            logger.error(f"🔑 关键词触发检测异常: {e}")

    # P6.6：管理员专属新功能指令
    if is_group and msg:
        if _handle_admin_feature_commands(dctx):
            return True

    # P7：视奸雷达（v5.14.0 扩展：使用扩展的 convert 关键词 + 标志位供 P7.5 消费）
    _cleanup_radar_cooldown()
    from modules.group_mgr import _is_convert_message
    from core.growth_optimizer import is_direct_custom_order_request
    keyword_manager = getattr(dctx.ctx, 'keyword_manager', None)
    is_direct_custom_order = is_direct_custom_order_request(msg)
    if (
        is_group
        and msg
        and _is_convert_message(msg, keyword_manager)
        and not is_direct_custom_order
    ):
        now_radar = time.time()
        with _radar_lock:
            last_trigger = _radar_cooldown.get(uid, 0)
            should_notify = now_radar - last_trigger > _RADAR_COOLDOWN
            if should_notify:
                _radar_cooldown[uid] = now_radar

        if should_notify:
            try:
                bot.send_message(
                    CONFIG["ADMIN_ID"],
                    f"👀 视奸雷达\n👤 {format_user_mention(uid, uname)} 提到了费用相关词\n💡 该用户可能对付费服务有兴趣",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"视奸雷达通知失败：{e}")

        # 留资打捞不受冷却限制
        db.set_cart(uid)
        db.log_conversion_event(uid, "touched")

        # [v5.14.0] 设置搭讪标志位，供 P7.5 主动搭讪层消费
        dctx.proactive_eligible = True

    # P8：固定彩蛋响应
    from modules.content import handle_easter_eggs
    if handle_easter_eggs(mory_bot, m, CONFIG, db):
        clear_logging_context()
        return True

    # P8.5：新功能关键词触发
    if is_group and msg:
        if _handle_feature_keywords(dctx):
            return True

    # P8.8：成就自动检测
    if is_group and uid and random.randint(1, 20) == 1:
        try:
            from modules.achievement import check_achievements_for_user
            check_achievements_for_user(bot, chat_id, db, uid, CONFIG)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P8.85：猜数字回复检测
    if is_group:
        try:
            from modules.games import handle_guess_reply
            if handle_guess_reply(bot, m, CONFIG, db):
                clear_logging_context()
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # P9：用户画像标签提取
    from modules.group_mgr import detect_keywords
    analysis = detect_keywords(msg, CONFIG, keyword_manager)
    if getattr(dctx, "contextual_purchase", False):
        analysis["mode"] = "convert"
        analysis["is_cart"] = True
        if not analysis.get("keyword_tag"):
            analysis["keyword_tag"] = "付费意向-上下文承接"
    if analysis["keyword_tag"]:
        db.add_keyword(uid, analysis["keyword_tag"])
    if analysis["is_cart"]:
        db.set_cart(uid)
        db.log_conversion_event(uid, "interested")

    # P9.3：天气/城市共情（命中后停止，避免与 P10 AI 双回复）
    if analysis.get("weather_empathy") and is_group:
        mory_bot.reply_and_track(m, analysis["weather_empathy"])
        clear_logging_context()
        return True

    # P9.5：黑话/行话自动科普（命中后停止，避免与 P10 AI 双回复）
    if analysis.get("slang_reply") and is_group:
        if random.randint(1, 20) == 1:
            mory_bot.reply_and_track(m, analysis["slang_reply"])
            clear_logging_context()
            return True

    # P9.7：用户反馈/找Mory
    if analysis.get("mode") in ("feedback", "contact_mory"):
        if _handle_feedback(dctx, analysis):
            return True

    # 保存analysis给P10用
    dctx._analysis = analysis

    # ── P7.5 [v5.14.0]：商业问题主动搭讪 ──
    # 必须在 P5-P9 内部调用（而非 do_dispatch），否则 P8/P9 return True 会跳过搭讪
    if getattr(dctx, "proactive_eligible", False):
        if _dispatch_p7_5_proactive_engage(dctx):
            return True

    return False

def _send_feedback_admin_notification(dctx: DispatchContext, analysis: dict, *, unban_failure: bool = False) -> bool:
    """只在 Telegram 真正接受通知时返回 True，供用户回复如实说明状态。"""
    admin_id = dctx.ctx.config.get("ADMIN_ID", 0)
    if not admin_id:
        return False
    try:
        kind = "用户自助解封失败" if unban_failure else "用户反馈通知"
        action = "请手动解封" if unban_failure else "请查看并按需处理"
        dctx.ctx.bot.send_message(
            admin_id,
            f"📢 {kind}\n"
            f"👤 {format_user_mention(dctx.uid, dctx.uname)}\n"
            f"💬 消息：{dctx.text[:150]}\n"
            f"🏷 类型：{'用户遇到问题' if analysis['mode'] == 'feedback' else '用户想找Mory'}\n"
            f"💡 {action}",
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        logger.warning("反馈通知发送失败 uid=%s: %s", dctx.uid, e)
        return False


def _handle_feedback(dctx: DispatchContext, analysis: dict) -> bool:
    """P9.7 用户反馈/找Mory（安抚回复 + 通知管理员）"""
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

    if is_group:
        notified = _send_feedback_admin_notification(dctx, analysis)
        feedback_reply = (
            f"{uname}收到啦，方便的话私聊我把情况说清楚。已提交给管理员查看。"
            if notified else
            f"{uname}收到啦，方便的话私聊我把情况说清楚；我先把情况记下来了。"
        )
        mory_bot.reply_and_track(m, feedback_reply)
    else:
        # 用户自述只能创建审核请求，不能作为清黑名单/恢复权限的证据。
        # 真正解封继续复用 handle_unban_command / ad_unban 回调的管理员鉴权链。
        if "解封" in msg or "解禁" in msg or "被封" in msg or "封了" in msg or "禁言" in msg:
            notified = _send_feedback_admin_notification(dctx, analysis, unban_failure=True)
            feedback_reply = (
                "收到，你的解封申请已提交给管理员审核；审核前不会改动封禁状态。"
                if notified else
                "收到，我先记录你的解封申请；目前不能确认通知是否送达，封禁状态没有改动。"
            )
        else:
            notified = _send_feedback_admin_notification(dctx, analysis)
            feedback_reply = (
                "收到，已提交给管理员查看。"
                if notified else
                "收到，我先把情况记下来了；目前不能确认通知是否送达。"
            )
        mory_bot.reply_and_track(m, feedback_reply)

    clear_logging_context()
    return True


# ═══════════════════════════════════════════════════════════════════════
#  P7.5 [v5.14.0]：商业问题主动搭讪
# ═══════════════════════════════════════════════════════════════════════

def _dispatch_p7_5_proactive_engage(dctx: DispatchContext) -> bool:
    """P7.5 商业问题主动搭讪（在 P5-P9 后、P10 AI 前）

    触发条件：
    - 仅群聊（is_group=True）
    - P7 视奸雷达已设 proactive_eligible=True
    - PROACTIVE_ENGAGE_CONFIG.enabled=True（默认关闭）
    - 用户不在冷却期内
    - 非管理员

    行为：
    - 调用 ctx.proactive_engage.should_engage() 判断
    - 满足条件时调用 ctx.proactive_engage.engage() 执行搭讪
    - 成功搭讪后 return True 拦截 P10 AI（避免重复回复）
    """
    if not dctx.is_group:
        return False

    if not getattr(dctx, "proactive_eligible", False):
        return False

    # 检查 ProactiveEngage 是否已注入
    if not dctx.ctx.proactive_engage:
        return False

    try:
        # 管理员豁免
        CONFIG = dctx.ctx.config
        admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            admin_ids.add(admin_id)
        is_admin_user = dctx.uid in admin_ids

        # only_in_group_id 检查
        engage_cfg = CONFIG.get("PROACTIVE_ENGAGE_CONFIG", {})
        if engage_cfg.get("only_in_group_id", True):
            target_group = CONFIG.get("GROUP_ID", 0)
            if target_group and dctx.chat_id != target_group:
                return False

        # 明确购买/订阅必须进入 P10 统一成交链：那里会结合真实历史、
        # 生成当前人设正文并挂唯一自助下单按钮。P7.5 只保留了解阶段搭讪，
        # 否则旧旁路会在模型超时或发送失败时截断真正的成交回复。
        from core.growth_optimizer import (
            get_conversion_state,
            resolve_conversion_target,
        )
        conversion_state = get_conversion_state(
            dctx.ctx.db,
            dctx.uid,
            dctx.chat_id,
        )
        conversion_target, _ = resolve_conversion_target(
            dctx.text,
            getattr(dctx, "conversation_history", []),
            mode="convert",
            state=conversion_state,
        )
        if conversion_target == "subscribe":
            return False

        should, matched_kw = dctx.ctx.proactive_engage.should_engage(
            uid=dctx.uid,
            msg=dctx.text,
            is_admin=is_admin_user,
        )
        if not should:
            return False

        # 执行搭讪
        engaged = dctx.ctx.proactive_engage.engage(
            uid=dctx.uid,
            uname=dctx.uname,
            chat_id=dctx.chat_id,
            msg=dctx.text,
            matched_keyword=matched_kw,
            m=dctx.msg,
        )
        if not engaged:
            logger.warning(
                "🔔 P7.5 搭讪未实际发送，继续交给 P10 uid=%s",
                dctx.uid,
            )
            return False
        clear_logging_context()
        return True

    except Exception as e:
        logger.warning(f"🔔 P7.5 主动搭讪异常（已静默）: {e}")
        return False
