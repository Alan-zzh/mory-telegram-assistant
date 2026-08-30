# -*- coding: utf-8 -*-
"""
modules/linked_channel_sync.py  ·  关联频道联动模块（置顶取消 + 点赞 + 评论转化）

功能：
  1. 频道发帖 → 机器人自动点赞（set_message_reaction，需频道管理员权限）
  2. 关联频道自动转发到群的消息 → 自动取消置顶（unpin_chat_message，
     因为 Telegram 群设置里"频道消息置顶"开关经常不生效）
  3. 对群内自有频道转发 → 直接回复一条内容相关彩虹屁：
     按原帖文案选择定制私聊或自助订阅，并可配一张已审核营销图片卡；
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
  comment_style:        contextual=按原帖文案选单一入口 / mixed=旧混合随机 / compliment=纯彩虹屁 / convert=纯转化
  comment_media_enabled: 是否用已审核营销图作为评论卡（默认 False）
  comment_timeout_seconds: 群转发等待窗口（秒，默认 15；超时未匹配可选直接回复频道）
  comment_fallback_direct: 超时后是否直接回复频道帖子（默认 False，防重复/扰民）
  max_comments_per_hour: 每小时评论上限（默认 10，防刷屏）
"""

import re
import secrets
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    "comment_style": "contextual",
    "comment_media_enabled": False,
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

# 频道评论营销图只复用项目内已经人工审核的静态卡片，不调用图片模型。
_COMMENT_MEDIA_ROOT = Path(__file__).resolve().parents[1] / "assets" / "preset_media"
_COMMENT_MEDIA_POOL = tuple(f"photo_pool_{index:02d}.png" for index in range(1, 8))
_ORIGINAL_TASTE_MEDIA = "original_taste_menu.png"

_CONTACT_INTENT_RE = re.compile(
    r"(?:定制|訂製|订制|专属|專屬|需求|想法|原味|同款|私聊|联系|聯繫|咨询|諮詢|聊聊)",
    re.I | re.S,
)
_SUBSCRIBE_INTENT_RE = re.compile(
    r"(?:完整版|完整内容|完整內容|解锁|解鎖|订阅|訂閱|开通|開通|下单|下單|"
    r"购买|購買|付费|付費|价格|價格|套餐|档位|檔位|会员|會員|VIP|全享)",
    re.I | re.S,
)
_VIDEO_COPY_RE = re.compile(r"(?:视频|視頻|片段|短片|镜头|鏡頭|预告|預告)", re.I)
_PHOTO_COPY_RE = re.compile(r"(?:照片|图片|圖片|图集|圖集|写真|寫真|这组|這組)", re.I)

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
    return build_contextual_comment(cfg, "")


def resolve_comment_target(source_text: str) -> str:
    """按频道帖子文案选择唯一转化目标；频道本身已是预览，不再回引预览。"""
    text = str(source_text or "").strip()
    if _CONTACT_INTENT_RE.search(text):
        return TARGET_CONTACT
    if _SUBSCRIBE_INTENT_RE.search(text):
        return TARGET_SUBSCRIBE
    # 普通预览帖默认承接到自助订阅；只有明确的沟通/定制语义才导向私聊。
    return TARGET_SUBSCRIBE


def _compliment_subject(source_text: str) -> str:
    text = str(source_text or "")
    if _VIDEO_COPY_RE.search(text):
        return "这段"
    if _PHOTO_COPY_RE.search(text):
        return "这组"
    return "这篇"


def build_contextual_comment(cfg: dict, source_text: str) -> tuple:
    """按配置与原帖文案生成彩虹屁，并保证正文与唯一按钮目标一致。"""
    import random

    style = (cfg.get("comment_style") or "contextual").lower()
    # 纯转发 / 混合随机（默认混合）
    if style == "compliment":
        return random.choice(_COMPLIMENT_POOL), None
    if style == "convert":
        text, label, target = random.choice(_CONVERT_POOL)
        return text, target
    if style == "contextual":
        target = resolve_comment_target(source_text)
        subject = _compliment_subject(source_text)
        if target == TARGET_CONTACT:
            return (
                f"{subject}真的太会了，氛围和细节都很抓人 ✨ "
                "想做同款或有自己的想法，直接把需求发给 Mory 慢慢定制。",
                target,
            )
        return (
            f"{subject}质感太绝了，光预告就让人想继续看 ✨ "
            "想解锁完整版，可以直接查看当前选项并自助订阅。",
            target,
        )
    # mixed：保留旧兼容模式；生产可显式切 contextual，避免纯彩虹屁没有入口。
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
        from core.telegram_send_utils import create_colored_button
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


def _extract_post_text(m) -> str:
    """读取群内频道转发可见文案，文本帖和媒体 caption 都覆盖。"""
    parts = []
    for attr in ("text", "caption"):
        value = str(getattr(m, attr, "") or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts)


def _extract_origin_post_id(m, channel_id: int) -> int:
    """兼容 Telegram 新旧转发字段提取频道原帖 ID。"""
    try:
        origin = getattr(m, "forward_origin", None)
        origin_chat = getattr(origin, "chat", None)
        if origin_chat and int(getattr(origin_chat, "id", 0) or 0) == int(channel_id):
            return int(getattr(origin, "message_id", 0) or 0)
    except (TypeError, ValueError):
        pass
    try:
        return int(getattr(m, "forward_from_message_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _pick_comment_media(cfg: dict, source_text: str) -> Path | None:
    """选择一张已审核营销图；开关关闭或素材缺失时返回 None。"""
    if not bool(cfg.get("comment_media_enabled", False)):
        return None
    text = str(source_text or "")
    if "原味" in text:
        candidate = _COMMENT_MEDIA_ROOT / _ORIGINAL_TASTE_MEDIA
        return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None
    candidates = [
        _COMMENT_MEDIA_ROOT / name
        for name in _COMMENT_MEDIA_POOL
        if (_COMMENT_MEDIA_ROOT / name).is_file()
        and (_COMMENT_MEDIA_ROOT / name).stat().st_size > 0
    ]
    return secrets.choice(candidates) if candidates else None


def _is_missing_reply_target_error(exc: Exception) -> bool:
    """只识别 Telegram 明确返回的回复目标不存在错误。"""
    text = str(exc or "").lower()
    return (
        "message to be replied not found" in text
        or "reply message not found" in text
    )


def _send_comment_reply(
    bot,
    chat_id: int,
    reply_to_message_id: int,
    cfg: dict,
    root_config: dict,
    source_text: str,
    db=None,
):
    """发送一条评论：优先营销图片卡，失败时降级为同文案文本卡。"""
    text, target = build_contextual_comment(cfg, source_text)
    markup = build_comment_button(target, root_config or cfg)
    media_path = _pick_comment_media(cfg, source_text)
    sent = None
    media_sent = False
    reply_target_available = True
    if media_path is not None:
        try:
            from core.telegram_send_utils import send_photo_compat

            sent = send_photo_compat(
                bot,
                chat_id,
                str(media_path),
                caption=text,
                reply_to_message_id=reply_to_message_id,
                reply_markup=markup,
            )
            media_sent = sent is not None
        except Exception as exc:
            if _is_missing_reply_target_error(exc):
                reply_target_available = False
            logger.warning(
                f"营销图片评论发送失败，降级文本: chat={chat_id} "
                f"reply_to={reply_to_message_id}: {exc}"
            )
    if sent is None:
        kwargs = {"reply_markup": markup}
        if reply_target_available and reply_to_message_id:
            kwargs["reply_to_message_id"] = reply_to_message_id
        try:
            sent = bot.send_message(chat_id, text, **kwargs)
        except Exception as exc:
            if not reply_target_available or not _is_missing_reply_target_error(exc):
                raise
            logger.warning(
                f"评论回复目标不存在，改为群内直发: chat={chat_id} "
                f"reply_to={reply_to_message_id}"
            )
            sent = bot.send_message(chat_id, text, reply_markup=markup)
    if sent is None:
        raise RuntimeError("Telegram 未返回评论消息回执")
    _track_sent_message(db, chat_id, sent)
    return sent, target, media_sent


def _register_pending(cfg: dict, channel_id: int, post_msg_id: int, bot=None, root_config=None, db=None):
    """登记待评论帖子，并安排超时兜底线程。"""
    key = (channel_id, post_msg_id)
    with _pending_lock:
        existing = _pending_comments.get(key)
        if existing and existing.get("consumed"):
            # 群自动转发可能先于 channel_post 到达；已直评的帖子不能被后到事件重新打开。
            return False
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
    return True


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
        sent, target, media_sent = _send_comment_reply(
            bot,
            channel_id,
            post_msg_id,
            cfg,
            root_config or {},
            "",
            db=db,
        )
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
                root_config=config, db=db, source_text=_extract_post_text(m),
            )
        else:
            # 生产实测 Telegram 可能只先送达群自动转发、频道事件缺席或后到。
            # 评论直接以可信自有频道转发为真相源，取消对 channel_post pending 的硬依赖。
            _try_direct_forward_comment(
                bot,
                m,
                chat_id,
                message_id,
                channel_id,
                cfg,
                root_config=config,
                db=db,
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

def _try_consumed_post(
    bot,
    chat_id,
    message_id,
    channel_id,
    post_msg_id,
    cfg,
    root_config=None,
    db=None,
    source_text="",
):
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

    try:
        sent, target, media_sent = _send_comment_reply(
            bot,
            chat_id,
            message_id,
            cfg,
            root_config or {},
            source_text,
            db=db,
        )
        logger.info(
            f"💬 关联频道评论已发: chat={chat_id} channel={channel_id} "
            f"post={post_msg_id} target={target} media={media_sent} source=pending"
        )
    except Exception as e:
        logger.warning(f"评论发送失败: chat={chat_id} post={post_msg_id}: {e}")
        _refund_rate()
        # 发送失败恢复待消费，下次转发（如编辑）可再尝试
        with _pending_lock:
            pending = _pending_comments.get((channel_id, post_msg_id))
            if pending:
                pending["consumed"] = False


def _try_direct_forward_comment(
    bot,
    m,
    chat_id,
    message_id,
    channel_id,
    cfg,
    root_config=None,
    db=None,
):
    """无频道 pending 时直接回复群自动转发，修复只取消置顶、不出评论。"""
    if not _check_rate(cfg, channel_id):
        logger.info(f"⏳ 评论限流，跳过直评: chat={chat_id} message={message_id}")
        return False
    source_text = _extract_post_text(m)
    post_msg_id = _extract_origin_post_id(m, channel_id)
    try:
        sent, target, media_sent = _send_comment_reply(
            bot,
            chat_id,
            message_id,
            cfg,
            root_config or {},
            source_text,
            db=db,
        )
        if post_msg_id:
            with _pending_lock:
                _pending_comments[(channel_id, post_msg_id)] = {
                    "ts": time.time(),
                    "consumed": True,
                }
        logger.info(
            f"💬 关联频道评论已发: chat={chat_id} channel={channel_id} "
            f"post={post_msg_id or 0} target={target} media={media_sent} source=group_forward"
        )
        return bool(sent)
    except Exception as e:
        logger.warning(
            f"评论直发失败: chat={chat_id} channel={channel_id} "
            f"message={message_id}: {e}"
        )
        _refund_rate()
        return False
