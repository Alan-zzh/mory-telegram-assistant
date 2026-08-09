# -*- coding: utf-8 -*-
"""
modules/linked_channel_sync.py  ·  关联频道联动模块（置顶取消 + 点赞 + 评论转化）

功能：
  1. 频道发帖 → 机器人自动点赞（set_message_reaction，需频道管理员权限）
  2. 关联频道自动转发到群的消息 → 自动取消置顶（unpin_chat_message，
     因为 Telegram 群设置里"频道消息置顶"开关经常不生效）
  3. 对频道新帖 → 在群内对应转发消息下回复一条随机评论：
     彩虹屁（无入口）/ 带转化评论（引导定制 / 解锁完整版 / 联系双向机器人），
     每帖至多一条、每按钮正文一致、不引导看预览（频道本身即预览群发）。

  触发点：
    - 频道新帖：core/handlers/media_handlers.py on_channel_post
    - 群内关联转发（sender_chat 为频道）：message_dispatcher 早拦截 + media_handlers
  默认关闭；通过 LINKED_CHANNEL_SYNC_CONFIG 开启后按窗口限流，绝不刷屏。

配置（config.json 顶层键 LINKED_CHANNEL_SYNC_CONFIG）：
  enabled:              总开关（默认 False）
  unpin_auto_forward:   是否取消自动置顶（默认 True）
  auto_like_enabled:    频道发帖自动点赞（默认 True）
  like_emoji:           点赞表情（默认 👍）
  auto_comment_enabled: 是否自动评论（默认 True）
  comment_style:        mixed=彩虹屁与转化混合随机 / compliment=纯彩虹屁 / convert=纯转化
  comment_timeout_seconds: 群转发等待窗口（秒，默认 15；超时未匹配可选直接回复频道）
  comment_fallback_direct: 超时后是否直接回复频道帖子（默认 False，防重复/扰民）
  max_comments_per_hour: 每小时评论上限（默认 10，防刷屏）
"""

import threading
import time
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("linked_channel_sync")

# 北京时区
_CST = timezone(timedelta(hours=8))

_DEFAULT_CONFIG = {
    "enabled": False,
    "unpin_auto_forward": True,
    "auto_like_enabled": True,
    "like_emoji": "👍",
    "auto_comment_enabled": True,
    "comment_style": "mixed",
    "comment_timeout_seconds": 15,
    "comment_fallback_direct": False,
    "max_comments_per_hour": 10,
}

# 转化按钮目标（单一真相源同 core/broadcast_cta，避免两处 URL 漂移）
from core.broadcast_cta import TARGET_CONTACT, TARGET_SUBSCRIBE, _DEFAULT_URLS

# ── 评论文案池 ──
# compliment: 纯彩虹屁（无按钮）
_COMPLIMENT_POOL = [
    "这组也太顶了，先赞为敬 ✨",
    "呜呜这氛围感谁懂啊，收藏了 📌",
    "今天的头种草在线，看一眼就出不去了",
    "这也太会了，光预告就让人上头 🍿",
    "是谁的品味这么好，原来是你们呀 😍",
    "刚点开就被美到了，蹲一个后续～",
]

# convert: 转化评论（text, 按钮文案, 按钮目标类型）
_CONVERT_POOL = [
    (
        "想要专属这种风格的，可以来找 Mory 说需求慢慢定制哦～",
        "🧭 找我定制",
        TARGET_CONTACT,
    ),
    (
        "预告只是开胃菜，解锁完整版之后才是重头戏～",
        "🛒 解锁完整版",
        TARGET_SUBSCRIBE,
    ),
    (
        "想看得更全、有问题的话，随时来双向找 Mory 聊～",
        "💬 联系 Mory",
        TARGET_CONTACT,
    ),
]

# ── 待回复评论队列 ──
# key=(channel_id, post_msg_id) → {ts, consumed}；评论成功即消费，防重复
_pending_comments = {}
_pending_lock = threading.Lock()

# 已处理过的群转发 (chat_id, msg_id) → ts，防止重复取消置顶/评论
_recent_handled = {}
_handled_lock = threading.Lock()

# 每小时评论计数：hour_key("YYYY-MM-DD-HH") → count
_rate_counts = {}
_rate_lock = threading.Lock()

_HANDLED_TTL = 30  # 秒
_MAX_PENDING = 200


def _as_int(value, default: int) -> int:
    """安全转 int，脏值回退默认。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    """安全转 float，脏值回退默认。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_config(config: dict) -> dict:
    """读取模块配置，未知/缺失字段回退默认值。"""
    raw = config or {}
    section = raw.get("LINKED_CHANNEL_SYNC_CONFIG", {})
    if not isinstance(section, dict):
        section = {}
    cfg = dict(_DEFAULT_CONFIG)
    cfg.update({k: v for k, v in section.items() if k in _DEFAULT_CONFIG})
    return cfg


def _target_channel_ids(config: dict) -> set:
    """从 CHANNEL_IDS 提取目标频道 id（兼容 dict 与 int 两种条目）。"""
    ids = set()
    for ch in (config or {}).get("CHANNEL_IDS", []) or []:
        if isinstance(ch, dict):
            cid = ch.get("id", 0)
        else:
            cid = ch
        try:
            ids.add(int(cid))
        except (TypeError, ValueError):
            continue
    return ids


def get_trusted_forward_channel_id(m, config: dict) -> int:
    """返回群内自有频道自动转发的频道 ID；非自有频道返回 0。

    CHANNEL_IDS 是自有频道白名单的唯一真相源。只有 sender_chat 明确属于该
    白名单时才可信，不能只凭 Telegram 的系统发送者或 forward_origin 放行。
    """
    chat = getattr(m, "chat", None)
    if not chat or getattr(chat, "type", "") not in ("group", "supergroup"):
        return 0
    sender_chat = getattr(m, "sender_chat", None)
    if not sender_chat or getattr(sender_chat, "type", "") != "channel":
        return 0
    try:
        channel_id = int(getattr(sender_chat, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return channel_id if channel_id in _target_channel_ids(config) else 0


def _prune_stale():
    """清理过期待处理项与限流计数（幂等，幂等失败不影响主流程）。"""
    now = time.time()
    with _pending_lock:
        stale = [k for k, v in _pending_comments.items() if now - v["ts"] > 600]
        for k in stale:
            _pending_comments.pop(k, None)
    with _handled_lock:
        stale_h = [k for k, v in _recent_handled.items() if now - v > _HANDLED_TTL * 2]
        for k in stale_h:
            _recent_handled.pop(k, None)
    with _rate_lock:
        hour_key = datetime.now(_CST).strftime("%Y-%m-%d-%H")
        for k in [k for k in _rate_counts if k != hour_key]:
            _rate_counts.pop(k, None)


def _check_rate(cfg: dict, channel_id: int = 0) -> bool:
    """评论限流：原子预占名额，超过每小时上限返回 False（点赞不受限）。

    预占后若发送失败须调用 _refund_rate() 退回，避免 TOCTOU 突发超限。
    """
    hour_key = datetime.now(_CST).strftime("%Y-%m-%d-%H")
    limit = _as_int(cfg.get("max_comments_per_hour"), _DEFAULT_CONFIG["max_comments_per_hour"])
    with _rate_lock:
        current = _rate_counts.get(hour_key, 0)
        if current >= limit:
            return False
        _rate_counts[hour_key] = current + 1
        return True


def _record_rate():
    """兼容旧调用：预占已在 _check_rate 完成，此处为空操作。"""
    return


def _refund_rate():
    """发送失败时退回预占名额。"""
    hour_key = datetime.now(_CST).strftime("%Y-%m-%d-%H")
    with _rate_lock:
        current = _rate_counts.get(hour_key, 0)
        if current > 0:
            _rate_counts[hour_key] = current - 1


def _mark_handled(chat_id: int, message_id: int) -> bool:
    """标记群消息已处理；返回 False 表示此前已处理过。"""
    key = (chat_id, message_id)
    now = time.time()
    with _handled_lock:
        if _recent_handled.get(key, 0) > now - _HANDLED_TTL:
            return False
        _recent_handled[key] = now
    return True


def build_comment(cfg: dict) -> tuple:
    """按配置生成评论正文与按钮目标。

    返回 (text, target) 或 (text, None)：target 为 contact/subscribe/preview/none。
    """
    import random

    style = (cfg.get("comment_style") or "mixed").lower()
    # 纯转发 / 混合随机（默认混合）
    if style == "compliment":
        return random.choice(_COMPLIMENT_POOL), None
    if style == "convert":
        text, label, target = random.choice(_CONVERT_POOL)
        return text, target
    # mixed：彩虹与大纯转化随机，彩虹概率压低（转化是主线，否则没有转化效果）
    if random.random() < 0.35:
        return random.choice(_COMPLIMENT_POOL), None
    text, label, target = random.choice(_CONVERT_POOL)
    return text, target


def build_comment_button(target: str, config: dict):
    """按 target 生成单按钮 InlineKeyboardMarkup（无按钮时返回 None）。"""
    if not target:
        return None
    try:
        from telebot import types
        from core.telebot_compat import create_colored_button
        url = _DEFAULT_URLS.get(target, "")
        if not url:
            return None
        label_pool = {TARGET_CONTACT: "💬 联系 Mory", TARGET_SUBSCRIBE: "🛒 解锁完整版"}
        label = label_pool.get(target, "了解更多")
        markup = types.InlineKeyboardMarkup(row_width=1)
        button_style_enabled = bool((config or {}).get("BUTTON_STYLE_ENABLED", False))
        if button_style_enabled:
            style = "primary" if target == TARGET_CONTACT else "success"
            button = create_colored_button(text=label, url=url, style=style)
        else:
            button = types.InlineKeyboardButton(text=label, url=url)
        markup.add(button)
        return markup
    except Exception as e:
        logger.debug(f"评论按钮构建失败（降级纯文本）: {e}")
        return None


def _register_pending(cfg: dict, channel_id: int, post_msg_id: int, bot=None, root_config=None, db=None):
    """登记待评论帖子，并安排超时兜底线程。"""
    key = (channel_id, post_msg_id)
    with _pending_lock:
        if len(_pending_comments) > _MAX_PENDING:
            try:
                oldest = min(_pending_comments, key=lambda k: _pending_comments[k]["ts"])
                _pending_comments.pop(oldest, None)
            except Exception as e:
                logger.debug(f"pending 淘汰失败（非致命）: {e}")
        _pending_comments[key] = {"ts": time.time(), "consumed": False}

    timeout = _as_float(cfg.get("comment_timeout_seconds"), _DEFAULT_CONFIG["comment_timeout_seconds"])
    if timeout > 0 and cfg.get("comment_fallback_direct") and bot is not None:
        timer = threading.Timer(
            timeout,
            _timeout_fallback,
            args=(bot, channel_id, post_msg_id, cfg, root_config or {}, db),
        )
        timer.daemon = True
        timer.start()


def _track_sent_message(db, chat_id: int, sent) -> None:
    """评论消息写入追踪，供 burn_orphan 回收。"""
    try:
        mid = getattr(sent, "message_id", None)
        if not mid or db is None:
            return
        if hasattr(db, "track_bot_message"):
            db.track_bot_message(int(chat_id), int(mid))
    except Exception as e:
        logger.debug(f"评论追踪写入失败 chat={chat_id}: {e}")


def _timeout_fallback(bot, channel_id: int, post_msg_id: int, cfg: dict, root_config=None, db=None):
    """超时未收到群转发：可选直接回复频道帖子（默认关闭）。"""
    try:
        if not bot:
            return
        _prune_stale()
        with _pending_lock:
            pending = _pending_comments.get((channel_id, post_msg_id))
            if not pending or pending["consumed"]:
                return
            pending["consumed"] = True
        if not _check_rate(cfg, channel_id):
            with _pending_lock:
                pending = _pending_comments.get((channel_id, post_msg_id))
                if pending:
                    pending["consumed"] = False
            return
        text, target = build_comment(cfg)
        # 按钮样式读根配置，业务参数读模块 cfg
        markup = build_comment_button(target, root_config or cfg)
        sent = bot.send_message(channel_id, text, reply_to_message_id=post_msg_id, reply_markup=markup)
        _track_sent_message(db, channel_id, sent)
        logger.info(f"📝 频道直评（兜底）: channel={channel_id} msg={post_msg_id} style={cfg.get('comment_style')}")
    except Exception as e:
        logger.debug(f"频道直评兜底失败: channel={channel_id} msg={post_msg_id}: {e}")
        _refund_rate()
        with _pending_lock:
            pending = _pending_comments.get((channel_id, post_msg_id))
            if pending:
                pending["consumed"] = False


def handle_channel_post(bot, m, config: dict, db=None) -> bool:
    """频道新帖联动：点赞 + 登记评论（返回 True 表示已处理）。"""
    cfg = _load_config(config)
    if not cfg.get("enabled"):
        return False

    channel_ids = _target_channel_ids(config)
    cid = getattr(getattr(m, "chat", None), "id", 0) or 0
    if cid not in channel_ids:
        return False
    msg_id = getattr(m, "message_id", 0) or 0

    if cfg.get("auto_like_enabled") and msg_id:
        try:
            from telebot import types
            emoji = (cfg.get("like_emoji") or "👍")[:8] or "👍"
            bot.set_message_reaction(
                cid, msg_id,
                reaction=[types.ReactionTypeEmoji(emoji=emoji)],
            )
            logger.info(f"👍 频道帖已点赞: channel={cid} msg={msg_id} emoji={emoji}")
        except Exception as e:
            logger.debug(f"频道点赞失败（无需管理员权限或旧 API）: channel={cid} msg={msg_id}: {e}")

    if cfg.get("auto_comment_enabled") and msg_id:
        _prune_stale()
        # 限流在真正发送时预占；登记阶段只记 pending
        _register_pending(cfg, cid, msg_id, bot=bot, root_config=config, db=db)

    return True


def handle_group_forward(bot, m, config: dict, db=None) -> bool:
    """处理群内收到的关联频道自动转发消息：
    取消自动置顶 + 匹配并回复评论（每条帖子最多一条）。"""
    cfg = _load_config(config)
    channel_id = get_trusted_forward_channel_id(m, config)
    if not channel_id:
        return False

    # 自有频道转发永远在这里终止后续用户消息管线，避免被广告检测、反频道
    # 或 AI 当作普通群成员消息。关闭联动时只保留消息，不执行点赞/取消置顶/评论。
    if not cfg.get("enabled"):
        return True

    chat = m.chat
    chat_id = chat.id
    message_id = getattr(m, "message_id", 0) or 0

    # 防止媒体 handler 与主分发器双路重复执行
    if not _mark_handled(chat_id, message_id):
        return True

    # 1) 取消自动置顶（个别群设置里"频道消息置顶"关不掉，这里强制取消）
    if cfg.get("unpin_auto_forward"):
        try:
            bot.unpin_chat_message(chat_id, message_id=message_id)
            logger.info(f"📌 取消关联频道置顶: chat={chat_id} channel={channel_id} msg={message_id}")
        except Exception as e:
            logger.debug(f"取消置顶失败（消息未置顶或权限不足）: chat={chat_id} msg={message_id}: {e}")

    # 2) 匹配待回复评论（优先 forward_origin 精确匹配，否则取该频道最近一条未消费的帖子）
    if cfg.get("auto_comment_enabled"):
        post_msg_id = _match_pending_post(m, channel_id, cfg)
        if post_msg_id is not None:
            _try_consumed_post(
                bot, chat_id, message_id, channel_id, post_msg_id, cfg,
                root_config=config, db=db,
            )

    return True


def _match_pending_post(m, channel_id: int, cfg: dict) -> int | None:
    """定位待评论的帖子：先精确（forward_origin），再按时间窗取最近未消费帖。"""
    # forward_origin: 类型 channel 时可拿到 chat.id + message_id
    origin_msg = 0
    try:
        origin = getattr(m, "forward_origin", None)
        if origin and getattr(origin, "chat", None):
            if getattr(origin.chat, "id", 0) == channel_id:
                origin_msg = getattr(origin, "message_id", 0) or 0
    except Exception:
        origin_msg = 0

    with _pending_lock:
        if origin_msg:
            pending = _pending_comments.get((channel_id, origin_msg))
            if pending and not pending["consumed"]:
                return origin_msg
        # 时间窗兜底：该频道最近 60 秒内未消费的帖子
        window = time.time() - 60
        candidates = [
            key[1]
            for key, v in _pending_comments.items()
            if key[0] == channel_id and not v["consumed"] and v.get("ts", 0) >= window
        ]
        if not candidates:
            return None
        # 帖子到达顺序即发送顺序，取最早未消费的，避免多帖并发时错位
        best = min(
            candidates,
            key=lambda mid: _pending_comments[(channel_id, mid)].get("ts", 0),
        )
        # 校验时间窗与回复超时：旧帖子（超过超时窗口多倍）不回复，防错位
        if time.time() - _pending_comments[(channel_id, best)].get("ts", 0) > _as_float(cfg.get("comment_timeout_seconds"), _DEFAULT_CONFIG["comment_timeout_seconds"]) * 3:
            return None
        return best

def _try_consumed_post(bot, chat_id, message_id, channel_id, post_msg_id, cfg, root_config=None, db=None):
    """消费并发送评论（防重复）。"""
    with _pending_lock:
        pending = _pending_comments.get((channel_id, post_msg_id))
        if not pending or pending["consumed"]:
            return
        pending["consumed"] = True

    if not _check_rate(cfg, channel_id):
        with _pending_lock:
            pending = _pending_comments.get((channel_id, post_msg_id))
            if pending:
                pending["consumed"] = False
        logger.info(f"⏳ 评论限流，跳过发送: chat={chat_id} post={post_msg_id}")
        return

    text, target = build_comment(cfg)
    markup = build_comment_button(target, root_config or cfg)
    try:
        sent = bot.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            reply_markup=markup,
        )
        _track_sent_message(db, chat_id, sent)
        logger.info(f"💬 关联频道评论已发: chat={chat_id} channel={channel_id} post={post_msg_id} target={target}")
    except Exception as e:
        logger.warning(f"评论发送失败: chat={chat_id} post={post_msg_id}: {e}")
        _refund_rate()
        # 发送失败恢复待消费，下次转发（如编辑）可再尝试
        with _pending_lock:
            pending = _pending_comments.get((channel_id, post_msg_id))
            if pending:
                pending["consumed"] = False
