"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/scheduled_broadcast.py  ·  定点播报增强模块                   ║
║                                                                        ║
║  功能：自定义定时播报，支持多个时间点、多种内容类型。                    ║
║
║  配置：                                                                ║
║    SCHEDULED_BROADCASTS: [                                             ║
║        {                                                               ║
║            "id": "custom_broadcast_1",                                 ║
║            "time": "10:00",         // HH:MM                           ║
║            "content": "文本内容",                                        ║
║            "type": "text",          // text/image/voice                ║
║            "frequency": "daily",     // daily/weekly/monthly           ║
║            "enabled": true                                            ║
║        }                                                               ║
║    ]                                                                   ║
║
║  被调用：main.py 定时任务系统                                          ║
══════════════════════════════════════════════════════════════════════════╝
"""

import random
from datetime import datetime, timezone, timedelta
from telebot import types
from core.broadcast_formatter import build_broadcast_html, build_rich_broadcast_html, looks_like_html, normalize_text
from core.telebot_compat import send_checklist_compat, send_message_compat, send_photo_compat, send_poll_compat, send_rich_message_compat
from core.logging_util import get_logger
from core.theme_engine import build_broadcast_context

logger = get_logger("scheduled_broadcast")

_CST = timezone(timedelta(hours=8))


_SOFT_TEMPLATE_VARIANTS = {
    "morning": [
        "今天换了个开场，从天气聊起～",
        "这条从一句反问开始，看看有没有人回～",
        "今天试试先说结论再补场景",
        "用了个新的小习惯：早安前先伸个懒腰",
        "今天想试试更短的句子，看看效果",
        "今天醒来心情还行，说话带点随意",
        "有点没睡醒，语气懒懒的",
        "刚遇到一件顺心的事，整个人都轻松了",
        "今天状态还行，说话带点小自信",
        "有些人已经跨过那个门槛了，里面的世界不太一样",
        "刚整理了一些照片，但有些不太适合发在群里",
        "关于那个门槛的事，私聊说更方便",
        "有些片段只放在至臻那边，群里不太方便发",
    ],
    "afternoon": [
        "午后这条想试试先问个问题",
        "今天午后想换个角度，从一个小细节说起",
        "这条午后提醒加了点生活气息",
        "想看看午后用更随意的语气会怎样",
        "今天午后想试试倒叙，先说结果再说过程",
        "刚喝完咖啡，精神还行",
        "有点犯困，但跟你聊着聊着就清醒了",
        "刚吃完东西，心情还行",
        "突然有点想发呆，不知道为什么",
        "今天有点小福利，但只给主动的人",
        "有些照片只放在那边，想看的来找我",
        "福利这种事，私聊说比较方便",
        "至臻系列刚更新了一些新内容",
    ],
    "evening": [
        "晚间想试试更走心的表达",
        "今天晚间从一个小观察开始",
        "这条晚间播报想加点故事感",
        "晚间想试试先说感受再说场景",
        "今天晚间想用一个悬念收尾",
        "刚听了一首歌，整个人都放松了",
        "今天状态有点高冷，别介意",
        "刚忙完，脑子还有点转",
        "心情像过山车，刚才还开心现在想发呆",
        "今天特别想聊天，谁来都接",
        "全享的用户能看到更多独家内容",
        "刚拍了几张自拍，但有点太私人了",
        "有些自拍只放在私密空间",
        "有些特权只有全享才有，你懂的",
    ],
    "night": [
        "深夜想试试更私密的语气",
        "今天深夜想从一个小小的情绪开始",
        "这条深夜播报想加点氛围感",
        "深夜想试试更慢的节奏",
        "今天深夜想用一个反问结尾",
        "刚喝了杯东西，精神得不行",
        "有点犯困，但跟你聊着聊着就清醒了",
        "刚吃完东西，心情还行",
        "突然有点想发呆，不知道为什么",
        "有些贴身的小物件，每件都是独一无二的",
        "刚录了点视频，但内容有点敏感",
        "有些视频不太适合公开，私聊给你看",
        "如果你想看什么特定的，可以私聊我写剧本",
        "定制的内容只属于你一个人",
    ],
    "default": [
        "今天想试试换个开场方式",
        "这条想加点小变化，看看反应",
        "保留核心，只调整表达方式",
        "今天想试试更口语化的说法",
        "旧瓶装新酒，意思不变，说法微调",
        "刚喝了杯东西，精神还行",
        "有点犯困，但跟你聊着聊着就清醒了",
        "刚吃完东西，心情还行",
        "突然有点想发呆，不知道为什么",
        "有些事私聊说更方便",
        "来 @MorychannelBot 找我聊",
        "主动的人能看到更多",
    ],
}


def _parse_broadcast_time(item: dict):
    """兼容 time=HH:MM 与 hour/minute 两种写法。"""
    time_str = str(item.get("time", "") or "").strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None, None

    hour = item.get("hour")
    minute = item.get("minute")
    try:
        if hour is not None and minute is not None:
            return int(hour), int(minute)
    except (TypeError, ValueError):
        return None, None
    return None, None


def _build_markup(item: dict, config: dict = None):
    """可选的单按钮，适合下单引导或详情跳转。支持彩色按钮。"""
    button_text = str(item.get("button_text", "") or "").strip()
    button_url = str(item.get("button_url", "") or "").strip()
    if not button_text or not button_url:
        return None

    # 尝试使用彩色按钮
    if config and config.get("BUTTON_STYLE_ENABLED", False):
        from core.telebot_compat import create_colored_button
        button_style = item.get("button_style", "primary")
        button_emoji_id = item.get("button_emoji_id")
        button = create_colored_button(
            text=button_text,
            url=button_url,
            style=button_style,
            icon_emoji_id=button_emoji_id,
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(button)
        return markup

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(button_text, url=button_url))
    return markup


def _pick_soft_template_variant(item: dict, config: dict | None = None) -> str:
    """给旧模板加一个轻微变化句，保留原文案骨架。"""
    cfg = config or {}
    if cfg.get("BROADCAST_TEMPLATE_VARIATION_ENABLED", True) is False:
        return ""
    if item.get("template_variant") is False:
        return ""

    period = str(item.get("period", "") or "default").strip() or "default"
    pool = _SOFT_TEMPLATE_VARIANTS.get(period) or _SOFT_TEMPLATE_VARIANTS["default"]
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    seed = f"{item.get('id', '')}|{period}|{today}"
    return random.Random(seed).choice(pool)


def _merge_footer_with_variant(footer: str, variant: str) -> str:
    """把每日小变化放进折叠补充，不破坏原模板正文。"""
    footer = normalize_text(footer)
    variant = normalize_text(variant)
    if not variant or variant in footer:
        return footer
    if not footer:
        return variant
    return f"{footer}\n\n{variant}"


def _render_broadcast_text(item: dict, user_profile: dict = None, config: dict = None):
    """按配置把播报渲染成更适合 Telegram 的 HTML 卡片（富文本升级版 v5.0，含多样性引擎）。"""
    content = normalize_text(item.get("content", ""))
    if not content:
        return "", None

    parse_mode = str(item.get("parse_mode", "") or "").strip() or None
    if parse_mode and parse_mode.upper() != "HTML":
        return content, parse_mode
    if looks_like_html(content):
        return content, "HTML"

    title = str(item.get("title", "") or "").strip() or "群播报"
    footer = str(item.get("footer", "") or "").strip()
    badge = str(item.get("badge", "") or "").strip()
    period = str(item.get("period", "") or "").strip()
    button_text = str(item.get("button_text", "") or "").strip()
    button_url = str(item.get("button_url", "") or "").strip()
    broadcast_id = str(item.get("id", "") or "").strip()

    # 使用多样性引擎构建播报上下文
    theme_enabled = bool((config or {}).get("BROADCAST_THEME_ENABLED", True))
    if theme_enabled and period:
        try:
            ctx = build_broadcast_context(period=period, item_id=broadcast_id)
            # 将黑话暗示和图片暗示融入折叠区
            theme_hints = []
            if ctx.get("slang_hint"):
                theme_hints.append(ctx["slang_hint"])
            if ctx.get("photo_hint"):
                theme_hints.append(ctx["photo_hint"])
            if ctx.get("conversion_hint"):
                theme_hints.append(ctx["conversion_hint"])

            if theme_hints:
                theme_footer = "\n\n".join(theme_hints)
                footer = _merge_footer_with_variant(footer, theme_footer)
            else:
                footer = _merge_footer_with_variant(footer, _pick_soft_template_variant(item, config))
        except Exception as e:
            logger.debug(f"多样性引擎异常（已忽略，回退默认）: {e}")
            footer = _merge_footer_with_variant(footer, _pick_soft_template_variant(item, config))
    else:
        footer = _merge_footer_with_variant(footer, _pick_soft_template_variant(item, config))

    # 使用 v5.0 富文本排版（支持用户画像个性化）
    return build_rich_broadcast_html(
        title=title,
        body=content,
        footer=footer,
        badge=badge,
        period=period,
        button_text=button_text,
        button_url=button_url,
        user_profile=user_profile,
    ), "HTML"


def _send_formatted_text(bot, chat_id, text: str, parse_mode, config: dict, **kwargs):
    """按配置优先发送 Rich Message，失败时回退 HTML。"""
    cfg = config or {}
    format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
    rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))

    if rich_enabled and parse_mode == "HTML" and format_version in ("rich", "auto"):
        try:
            return send_rich_message_compat(bot, chat_id, text, **kwargs)
        except Exception as e:
            logger.warning(f"Rich Message 发送失败，回退 HTML: {e}")

    return send_message_compat(
        bot,
        chat_id,
        text,
        parse_mode=parse_mode,
        **kwargs,
    )


def execute_scheduled_broadcast(bot, chat_id, config: dict, db=None, target_broadcast_id: str = ""):
    """
    执行定点播报
    被 auto_tasks.py 定时任务调用
    """
    broadcasts = config.get("SCHEDULED_BROADCASTS", [])

    # 获取用户画像（如果是私聊播报）
    user_profile = None
    if db and chat_id > 0:  # 私聊
        try:
            user_profile = db.get_user_profile(chat_id)
        except Exception as e:
            logger.debug(f"获取用户画像失败（已忽略）: {e}")

    for bc in broadcasts:
        if not bc.get("enabled", False):
            continue

        broadcast_id = bc.get("id", "")
        if not broadcast_id:
            continue
        if target_broadcast_id and broadcast_id != target_broadcast_id:
            continue

        # 检查今天是否已执行（防重复）
        if db:
            from datetime import datetime, timezone, timedelta
            _CST = timezone(timedelta(hours=8))
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            task_key = f"scheduled_broadcast_{broadcast_id}_{today}"
            if db.is_task_executed_today(task_key):
                logger.debug(f"⏭️ 播报 {broadcast_id} 今日已执行，跳过")
                continue
            if not db.claim_task(task_key):
                logger.debug(f"️ 播报 {broadcast_id} 被其他进程抢占，跳过")
                continue

        # 执行播报
        content_type = bc.get("type", "text")
        content = bc.get("content", "")
        reply_markup = _build_markup(bc, config)
        disable_notification = bool(bc.get("silent", False))
        protect_content = bool(bc.get("protect_content", False))
        disable_preview = bool(bc.get("disable_preview", False))
        allow_paid_broadcast = bool(bc.get("allow_paid_broadcast", False))
        message_effect_id = bc.get("message_effect_id")
        direct_messages_topic_id = bc.get("direct_messages_topic_id")
        suggested_post_parameters = bc.get("suggested_post_parameters")

        if content_type == "rich_message" or bc.get("rich_message"):
            try:
                msg = send_rich_message_compat(
                    bot,
                    chat_id,
                    bc.get("rich_message"),
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    allow_paid_broadcast=allow_paid_broadcast,
                    message_effect_id=message_effect_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                    suggested_post_parameters=suggested_post_parameters,
                )
                logger.info(f"📢 定点播报(Rich Message): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "rich_message")
                    # [v5.23.0 P1-4] 记录归因事件：播报触达
                    _log_broadcast_attribution(db, chat_id, broadcast_id, "rich_message")
            except Exception as e:
                logger.warning(f"定点播报发送失败(Rich Message) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
            continue

        if content_type == "text":
            try:
                text, parse_mode = _render_broadcast_text(bc, user_profile=user_profile, config=config)
                msg = _send_formatted_text(
                    bot,
                    chat_id,
                    text,
                    parse_mode,
                    config,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_preview,
                    link_preview_options={
                        "is_disabled": disable_preview
                    } if disable_preview else None,
                    allow_paid_broadcast=allow_paid_broadcast,
                    message_effect_id=message_effect_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                    suggested_post_parameters=suggested_post_parameters,
                )
                logger.info(f" 定点播报: {broadcast_id}")
                # 追踪消息
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "text")
            except Exception as e:
                logger.warning(f"定点播报发送失败 {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
        elif content_type == "image":
            # content 可以是 file_id 或 URL
            try:
                caption = normalize_text(bc.get("caption", ""))
                caption_mode = None
                if caption:
                    temp_item = dict(bc)
                    temp_item["content"] = caption
                    temp_item["title"] = temp_item.get("title", "图片播报")
                    caption, caption_mode = _render_broadcast_text(temp_item, user_profile=user_profile, config=config)
                msg = send_photo_compat(
                    bot,
                    chat_id,
                    content,
                    caption=caption or None,
                    parse_mode=caption_mode,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_markup=reply_markup,
                    show_caption_above_media=bool(bc.get("show_caption_above_media", False)),
                    allow_paid_broadcast=allow_paid_broadcast,
                    message_effect_id=message_effect_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                )
                logger.info(f"📢 定点播报(图片): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "image")
            except Exception as e:
                logger.warning(f"定点播报发送失败(图片) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
        elif content_type == "voice":
            try:
                msg = bot.send_voice(chat_id, content)
                logger.info(f" 定点播报(语音): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "voice")
            except Exception as e:
                logger.warning(f"定点播报发送失败(语音) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
        elif content_type == "poll":
            try:
                question = str(bc.get("question") or content or "").strip()
                options = bc.get("options", [])
                if isinstance(options, str):
                    options = [item.strip() for item in options.split("|") if item.strip()]
                if not question or len(options) < 2:
                    logger.warning(f"定点播报投票配置无效 {broadcast_id}: question/options缺失")
                    continue
                msg = send_poll_compat(
                    bot,
                    chat_id,
                    question,
                    options,
                    is_anonymous=bc.get("is_anonymous"),
                    type=bc.get("poll_type") or bc.get("poll_kind"),
                    allows_multiple_answers=bc.get("allows_multiple_answers"),
                    correct_option_id=bc.get("correct_option_id"),
                    correct_option_ids=bc.get("correct_option_ids"),
                    explanation=bc.get("explanation"),
                    explanation_parse_mode=bc.get("explanation_parse_mode"),
                    open_period=bc.get("open_period"),
                    close_date=bc.get("close_date"),
                    is_closed=bc.get("is_closed"),
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_markup=reply_markup,
                    media=bc.get("media"),
                    description=bc.get("description"),
                    description_parse_mode=bc.get("description_parse_mode"),
                    allows_changing_answer=bc.get("allows_changing_answer"),
                    allows_revoting=bc.get("allows_revoting"),
                    country_codes=bc.get("country_codes"),
                    members_only=bc.get("members_only"),
                    shuffle_options=bc.get("shuffle_options"),
                    hide_results_until_closes=bc.get("hide_results_until_closes"),
                    allow_adding_options=bc.get("allow_adding_options"),
                    allow_paid_broadcast=allow_paid_broadcast,
                    message_effect_id=message_effect_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                    suggested_post_parameters=suggested_post_parameters,
                )
                logger.info(f"📊 定点播报(投票): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "poll")
            except Exception as e:
                logger.warning(f"定点播报发送失败(投票) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
        elif content_type == "checklist":
            try:
                business_connection_id = (
                    bc.get("business_connection_id")
                    or config.get("TELEGRAM_BUSINESS_CONNECTION_ID")
                    or ""
                )
                checklist = bc.get("checklist")
                if not checklist:
                    title = str(bc.get("title") or content or "Mory清单").strip()
                    tasks = bc.get("tasks", [])
                    if isinstance(tasks, str):
                        tasks = [item.strip() for item in tasks.split("|") if item.strip()]
                    checklist = {
                        "title": title,
                        "tasks": [
                            {"id": idx + 1, "text": task}
                            for idx, task in enumerate(tasks)
                        ],
                    }
                if not business_connection_id:
                    logger.warning(f"定点清单跳过 {broadcast_id}: TELEGRAM_BUSINESS_CONNECTION_ID 未配置")
                    continue
                if not checklist.get("tasks"):
                    logger.warning(f"定点清单配置无效 {broadcast_id}: tasks缺失")
                    continue
                msg = send_checklist_compat(
                    bot,
                    business_connection_id,
                    chat_id,
                    checklist,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_markup=reply_markup,
                    message_effect_id=message_effect_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                )
                logger.info(f"📋 定点播报(清单): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "checklist")
            except Exception as e:
                logger.warning(f"定点播报发送失败(清单) {broadcast_id}: {e}")
                if db:
                    try:
                        db.release_task(task_key)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
def get_broadcast_schedule(config: dict):
    """获取播报时间表（用于定时任务注册）"""
    broadcasts = config.get("SCHEDULED_BROADCASTS", [])
    schedule = []

    for bc in broadcasts:
        if not bc.get("enabled", False):
            continue

        hour, minute = _parse_broadcast_time(bc)
        if hour is None or minute is None:
            continue

        frequency = bc.get("frequency", "daily")

        schedule.append({
            "id": bc.get("id", ""),
            "hour": hour,
            "minute": minute,
            "frequency": frequency,
            "day_of_week": bc.get("day_of_week", None),  # 0-6, 周一=0
            "day_of_month": bc.get("day_of_month", None),  # 1-31
        })

    return schedule


def _log_broadcast_attribution(db, chat_id: int, broadcast_id: str, content_type: str = "text"):
    """【v5.23.0 P1-4】记录播报归因事件

    将播报触达事件写入 conversion_events 表，source=broadcast，
    campaign_id 格式为 {broadcast_id}_{YYYYMMDD}，便于后续归因分析。

    注意：此函数不抛异常，失败只记日志（不影响播报主流程）。
    """
    try:
        from datetime import datetime
        campaign_id = f"{broadcast_id}_{datetime.now().strftime('%Y%m%d')}"
        # 群播报无法确定具体 uid，用 chat_id 的负数作为占位（群 chat_id 本身就是负数）
        # 真正的归因在用户私聊点击 Bot 时通过 /start?start=track_bc_xxx 完成
        placeholder_uid = abs(chat_id)  # 用群ID正数作为占位，避免与真实uid冲突
        # 直接写 conversion_events 表（touched 事件表示播报触达）
        db.conn.execute(
            "INSERT INTO conversion_events(uid, event, ts, mode, source, campaign_id) "
            "VALUES (?, 'touched', ?, ?, 'broadcast', ?)",
            (placeholder_uid, int(__import__('time').time()), content_type, campaign_id)
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"播报归因记录失败（非致命）: {e}")
