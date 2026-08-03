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

import os
import random
from datetime import datetime, timezone, timedelta
from telebot import types
from core.broadcast_cta import build_cta_markup, get_broadcast_cta
from core.broadcast_formatter import (
    build_broadcast_html,
    build_rich_broadcast_html,
    build_rich_broadcast_card_message,
    looks_like_html,
    normalize_text,
)
from core.broadcast_image_card import build_broadcast_image_card
from core.broadcast_image_payload import build_scheduled_image_payload
from core.telebot_compat import send_checklist_compat, send_message_compat, send_photo_compat, send_poll_compat, send_rich_message_compat
from core.logging_util import get_logger
from core.theme_engine import build_broadcast_context

logger = get_logger("scheduled_broadcast")

_CST = timezone(timedelta(hours=8))

_AI_FALLBACK_MARKERS = (
    "脑子刚才短路",
    "刚才走神",
    "网络有点卡",
    "刚刚没反应过来",
    "暂时没法稳定接上模型",
    "喝口水缓一缓",
    "慢慢来",
    "别把自己逼太紧",
    "今天会顺一点",
    "身心",
    "归位",
    "允许自己",
    "外界期待",
    "安静地存在",
    "蓝光",
)

# 定点播报属于主动触达，不能因为旧配置或模型临场发挥而回到“真人生活
# 日记”或双重成交入口。这里是所有 modular 定点播报实际发送前的唯一门禁。
_UNVERIFIED_LIFE_MARKERS = (
    "咖啡", "沙发", "吹风", "窗外", "刚醒", "刚洗", "洗澡", "头发",
    "早餐", "晚饭", "被窝", "敷面膜", "下午茶", "路灯", "外面天气",
)
_BROADCAST_PRIVATE_MARKERS = (
    "私聊", "找我聊", "来找我", "戳我", "悄悄话", "陪你",
)
_BROADCAST_ORDER_MARKERS = (
    "自助下单", "立即下单", "直接下单", "马上下单", "购买", "定制",
)


def _sanitize_scheduled_broadcast_copy(value: object, fallback: str = "") -> str:
    """确定性清理主动播报中的虚构生活、私聊压力和错误成交入口。"""
    if not isinstance(value, str):
        return fallback

    value = value.replace("@MorychannelBot", "@moryselect")
    value = value.replace("@morychannelbot", "@moryselect")
    value = value.replace("@Moryfansbot", "@moryselect")
    value = value.replace("@moryfansbot", "@moryselect")
    value = value.replace("https://t.me/MorychannelBot", "https://t.me/moryselect")
    value = value.replace("https://t.me/Moryfansbot", "https://t.me/moryselect")

    safe_lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line:
            continue
        if any(marker in line for marker in _UNVERIFIED_LIFE_MARKERS):
            continue
        if any(marker in line for marker in _BROADCAST_PRIVATE_MARKERS):
            continue
        # 成交类播报只允许保留一个“先看预览”的目标，不能保留直接下单或定制承诺。
        if any(marker in line for marker in _BROADCAST_ORDER_MARKERS):
            line = line.replace("自助下单", "先看预览").replace("立即下单", "先看预览")
            line = line.replace("直接下单", "先看预览").replace("马上下单", "先看预览")
            line = line.replace("购买", "了解").replace("定制", "了解")
        if "@moryselect" in lowered or line:
            safe_lines.append(line)

    return "\n".join(safe_lines).strip() or fallback


def _adapt_scheduled_broadcast_item(item: dict) -> dict:
    """返回不污染原配置的主动播报安全副本。"""
    safe = dict(item or {})
    neutral_fallback = "这条提醒先放在这里，大家按自己的节奏来。"
    for key in ("content", "footer", "caption", "rich_message"):
        if key in safe:
            if key == "rich_message" and isinstance(safe.get(key), dict):
                rich_message = dict(safe[key])
                if "text" in rich_message:
                    if isinstance(rich_message["text"], str):
                        rich_message["text"] = _sanitize_scheduled_broadcast_copy(rich_message.get("text"), "")
                    elif isinstance(rich_message["text"], dict):
                        text_payload = dict(rich_message["text"])
                        if isinstance(text_payload.get("text"), str):
                            text_payload["text"] = _sanitize_scheduled_broadcast_copy(text_payload["text"], "")
                        rich_message["text"] = text_payload
                safe[key] = rich_message
            else:
                safe[key] = _sanitize_scheduled_broadcast_copy(safe.get(key), neutral_fallback if key == "content" else "")

    # 定点播报的可点击入口只允许是预览；无按钮的普通提醒保持无按钮。
    if safe.get("button_text") or safe.get("button_url"):
        safe["button_text"] = "👀 看看预览"
        safe["button_url"] = "https://t.me/moryselect"
    return safe


def _is_usable_ai_copy(content) -> bool:
    """防止模型降级提示被当成正式播报正文。"""
    if not isinstance(content, str):
        return False
    text = content.strip()
    return (
        20 <= len(text) <= 180
        and not any(marker in text for marker in _AI_FALLBACK_MARKERS)
        and text == _sanitize_scheduled_broadcast_copy(text)
    )


def _extract_send_error(e: Exception) -> tuple:
    """从发送异常中提取类型、状态码和摘要，用于结构化日志。"""
    exc_type = type(e).__name__
    status_code = None
    # pyTelegramBotAPI 的 ApiException 通常有 error_code
    if hasattr(e, "error_code"):
        try:
            status_code = int(e.error_code)
        except Exception:
            status_code = None
    err_summary = str(e)[:200]
    return exc_type, status_code, err_summary


def _release_failed_broadcast(db, task_key: str, failure: Exception) -> None:
    """发送终态失败时尽力释放防重锁，并把原始失败上浮给调度器。"""
    if db and task_key:
        try:
            db.release_task(task_key)
        except Exception as release_err:
            logger.error(f"release_task 失败 task_key={task_key}: {release_err}")
    raise failure


def _looks_like_local_path(s: str) -> bool:
    """粗略判断字符串是否像本地文件路径（而非 Telegram file_id）。"""
    if not s:
        return False
    lowered = s.lower()
    has_separator = ("/" in s) or ("\\" in s) or (os.path.sep in s)
    has_image_ext = lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
    return has_separator or has_image_ext


# v5.38.10 已彻底移除模板变体内容，避免误开启后复发尴尬句。
# 保留变量名以兼容现有 import / 引用，字典清空为 {}。
_SOFT_TEMPLATE_VARIANTS = {}


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


def _build_markup(item: dict, config: dict = None, cta: dict = None):
    """可选的单按钮，适合下单引导或详情跳转。支持彩色按钮与 Mini App。"""
    button_text = str(item.get("button_text", "") or "").strip()
    button_url = str(item.get("button_url", "") or "").strip()

    # 用户未配置按钮时，使用统一 CTA 文案池（保证与图片卡一致）
    if not button_text or not button_url:
        if cta is None:
            cta = get_broadcast_cta(
                scene="scheduled",
                period=str(item.get("period", "") or ""),
                config=config,
            )
        return build_cta_markup(cta, config=config)

    # 用户已配置按钮：兼容旧版彩色按钮参数
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
    """v5.38.10 已彻底移除模板变体内容，始终返回空串，避免复发尴尬句。"""
    return ""


def _merge_footer_with_variant(footer: str, variant: str) -> str:
    """把每日小变化放进折叠补充，不破坏原模板正文。"""
    footer = normalize_text(footer)
    variant = normalize_text(variant)
    if not variant or variant in footer:
        return footer
    if not footer:
        return variant
    return f"{footer}\n\n{variant}"


def _render_broadcast_text(item: dict, user_profile: dict = None, config: dict = None, cta: dict = None):
    """[v5.38.15] 按配置把播报渲染成 HTML 卡片，同时返回 Rich Message 版本。

    返回三元组 (html_text, parse_mode, rich_html)：
    - html_text：HTML parse_mode 路径用（旧客户端兼容）
    - parse_mode：通常为 "HTML"
    - rich_html：Rich Message 路径用（块级标签），调用方按需取用
    """
    content = normalize_text(item.get("content", ""))
    if not content:
        return "", None, ""

    parse_mode = str(item.get("parse_mode", "") or "").strip() or None
    if parse_mode and parse_mode.upper() != "HTML":
        return content, parse_mode, ""
    if looks_like_html(content):
        # 已是 HTML 富文本，不二次包裹，Rich 路径也用同一份
        return content, "HTML", ""

    title = str(item.get("title", "") or "").strip() or "群播报"
    footer = str(item.get("footer", "") or "").strip()
    badge = str(item.get("badge", "") or "").strip()
    period = str(item.get("period", "") or "").strip()
    button_text = str(item.get("button_text", "") or "").strip()
    button_url = str(item.get("button_url", "") or "").strip()
    broadcast_id = str(item.get("id", "") or "").strip()
    # [v5.38.15] 用户自定义按钮时，不使用自动 CTA 的 closing，避免话术 mismatch
    has_custom_button = bool(button_text and button_url)
    closing = ""
    if not has_custom_button and isinstance(cta, dict):
        closing = cta.get("closing", "")

    # 使用多样性引擎构建播报上下文（[v5.32] 已移除 slang/photo/conversion hint，
    # theme/tone 仍可用作 AI prompt 上下文，但此处不再拼接到 footer）
    theme_enabled = bool((config or {}).get("BROADCAST_THEME_ENABLED", True))
    soft_variant = _pick_soft_template_variant(item, config)
    footer = _merge_footer_with_variant(footer, soft_variant)

    if theme_enabled and period:
        try:
            # 仅触发上下文构建（确定性种子，用于 AI 后续生成参考）
            # hint 已为空串，不再拼接到 footer，避免硬塞话术
            build_broadcast_context(period=period, item_id=broadcast_id)
        except Exception as e:
            logger.debug(f"多样性引擎异常（已忽略，回退默认）: {e}")

    # 旧版 HTML parse_mode 卡片（所有客户端可用）
    html_text = build_rich_broadcast_html(
        title=title,
        body=content,
        footer=footer,
        badge=badge,
        period=period,
        button_text=button_text,
        button_url=button_url,
        user_profile=user_profile,
        closing=closing,
    )

    # [v5.32] 新版 Rich Message 卡片（块级标签，Bot API 10.1+）
    rich_html = build_rich_broadcast_card_message(
        title=title,
        body=content,
        footer=footer,
        badge=badge,
        period=period,
        user_profile=user_profile,
        closing=closing,
    )

    return html_text, "HTML", rich_html


def _send_formatted_text(bot, chat_id, text: str, parse_mode, config: dict, rich_html: str = "", **kwargs):
    """[v5.32] 按配置优先发送 Rich Message，失败时回退 HTML。

    新增 rich_html 参数：当 RICH_MESSAGE_ENABLED=true 且 BROADCAST_FORMAT_VERSION
    ∈ {"rich","auto"} 时优先用 rich_html 发送 sendRichMessage，失败回退到 text +
    parse_mode=HTML 路径。rich_html 为空时直接走旧路径。
    """
    cfg = config or {}
    format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
    # 【v5.31.6 修复 Bug B】send_rich_message_compat 已修正为传入 InputRichMessage 对象
    # {"html": "..."}（而非 List[Dict]），400 "object expected as rich message" 已解决。
    # 恢复从 config 读取开关，默认 False（铁律 #8 新功能默认关闭）。
    rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))

    if rich_enabled and rich_html and format_version in ("rich", "auto"):
        try:
            return send_rich_message_compat(bot, chat_id, rich_html, **kwargs)
        except Exception as e:
            logger.warning(f"Rich Message 发送失败，回退 HTML: {e}")

    return send_message_compat(
        bot,
        chat_id,
        text,
        parse_mode=parse_mode,
        **kwargs,
    )


def _try_ai_generate(bc: dict, ai_engine, broadcast_id: str) -> str:
    """[v5.32] 尝试用 AI 动态生成播报内容。失败返回空串，调用方用静态 content 兜底。

    仅当 bc.ai_generate=true 且 ai_engine 可用时调用。
    使用 period 作为 mode（morning/afternoon/evening/night），seed 按日期+id 确定性 int。
    """
    if not ai_engine or not bc.get("ai_generate"):
        return ""

    period = str(bc.get("period", "") or "").strip()
    ai_msg_map = {
        "morning": "早安",
        "afternoon": "午安",
        "evening": "晚安",
        "night": "晚安",
    }
    ai_msg = ai_msg_map.get(period)
    if not ai_msg:
        return ""

    try:
        import hashlib
        today = datetime.now(_CST).strftime("%Y%m%d")
        # 确定性 int seed：同一播报同一天生成相同内容，避免重复触发时变来变去
        seed_str = f"broadcast_{broadcast_id}_{today}"
        seed = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:8], 16) % 1000000
        content = ai_engine.ask(ai_msg, mode=period, seed=seed)
        if _is_usable_ai_copy(content):
            return content.strip()
        logger.warning(f"[broadcast] AI 生成内容过短或为空 {broadcast_id}, 回退静态")
        return ""
    except Exception as e:
        logger.warning(f"[broadcast] AI 生成失败 {broadcast_id}, 回退静态 content: {e}")
        return ""


def execute_scheduled_broadcast(bot, chat_id, config: dict, db=None, target_broadcast_id: str = "", ai_engine=None):
    """
    执行定点播报
    被 auto_tasks.py 定时任务调用

    [v5.32] 新增 ai_engine 参数：当 broadcast 配置 ai_generate=true 时，
    调用 AI 动态生成 content，失败自动回退静态 content。
    """
    broadcasts = config.get("SCHEDULED_BROADCASTS", [])

    # 获取用户画像（如果是私聊播报）
    user_profile = None
    if db and chat_id > 0:  # 私聊
        try:
            user_profile = db.get_user_profile(chat_id)
        except Exception as e:
            logger.debug(f"获取用户画像失败（已忽略）: {e}")

    for raw_bc in broadcasts:
        task_key = ""
        bc = _adapt_scheduled_broadcast_item(raw_bc)
        if not bc.get("enabled", False):
            continue

        broadcast_id = bc.get("id", "")
        if not broadcast_id:
            continue
        if target_broadcast_id and broadcast_id != target_broadcast_id:
            continue

        # 检查今天是否已执行（防重复，每群独立 claim）
        if db:
            from datetime import datetime, timezone, timedelta
            _CST = timezone(timedelta(hours=8))
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            task_key = f"scheduled_broadcast_{broadcast_id}_{chat_id}_{today}"
            if db.is_task_executed_today(task_key):
                logger.debug(f"⏭️ 播报 {broadcast_id} 群{chat_id} 今日已执行，跳过")
                continue
            if not db.claim_task(task_key):
                logger.debug(f"️ 播报 {broadcast_id} 群{chat_id} 被其他进程抢占，跳过")
                continue

        # 执行播报
        content_type = bc.get("type", "text")
        content = bc.get("content", "")
        # [v5.32] AI 动态生成 content（仅 text 类型，ai_generate=true 时启用）
        # 失败自动回退静态 content，保证播报不中断
        if content_type == "text" and bc.get("ai_generate"):
            ai_content = _try_ai_generate(bc, ai_engine, broadcast_id)
            if ai_content:
                bc = dict(bc)  # 复制避免污染原配置
                bc["content"] = ai_content
                content = ai_content

        # [v5.38.15] 统一 CTA：文字版 closing、图片卡文案、真实按钮保持一致
        cta = get_broadcast_cta(
            scene="scheduled",
            period=str(bc.get("period", "") or ""),
            config=config,
            user_profile=user_profile,
        )
        reply_markup = _build_markup(bc, config, cta=cta)
        disable_notification = bool(bc.get("silent", False))
        protect_content = bool(bc.get("protect_content", False))
        disable_preview = bool(bc.get("disable_preview", False))
        allow_paid_broadcast = bool(bc.get("allow_paid_broadcast", False))
        message_effect_id = bc.get("message_effect_id")
        direct_messages_topic_id = bc.get("direct_messages_topic_id")
        suggested_post_parameters = bc.get("suggested_post_parameters")

        if content_type == "rich_message" or bc.get("rich_message"):
            logger.info(f"[broadcast] 准备发送 {broadcast_id} 到 chat={chat_id}, type=rich_message")
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
                logger.info(f"[broadcast] 发送成功 {broadcast_id}, chat={chat_id}, msg_id={msg.message_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "rich_message")
                    # [v5.23.0 P1-4] 记录归因事件：播报触达
                    _log_broadcast_attribution(db, chat_id, broadcast_id, "rich_message")
            except Exception as e:
                exc_type, status_code, err_summary = _extract_send_error(e)
                logger.warning(
                    f"[broadcast] 发送失败 {broadcast_id}, chat={chat_id}, type=rich_message, "
                    f"exc={exc_type}, status={status_code}, err={err_summary}"
                )
                _release_failed_broadcast(db, task_key, e)
            continue

        if content_type == "text":
            try:
                # [v5.38.15] 传入 cta，让文字版 closing 与真实按钮一致
                # 注意：用户自定义按钮时，_render_broadcast_text 内部会忽略自动 closing
                text, parse_mode, rich_html = _render_broadcast_text(
                    bc, user_profile=user_profile, config=config, cta=cta
                )

                # [v5.38.15] 图片卡优先（仅 text 类型，且全局/单条均开启）
                global_image_enabled = bool(config.get("BROADCAST_IMAGE_CARD_ENABLED", False))
                item_image_enabled = bool(bc.get("image_card_enabled", False))
                image_sent = False
                if global_image_enabled and item_image_enabled:
                    try:
                        image_payload = build_scheduled_image_payload(bc, user_profile=user_profile)
                        today = datetime.now(_CST).strftime("%Y%m%d")
                        image_path = build_broadcast_image_card(
                            image_payload,
                            cache_key=f"scheduled_{broadcast_id}_{today}",
                            cta_pool="scheduled",
                            min_height=1000,
                            cta_text=cta.get("image_label", ""),
                        )
                        if image_path and os.path.isfile(image_path):
                            logger.info(f"[broadcast] 准备发送 {broadcast_id} 到 chat={chat_id}, type=image_card")
                            msg = send_photo_compat(
                                bot,
                                chat_id,
                                image_path,
                                caption=None,
                                disable_notification=disable_notification,
                                protect_content=protect_content,
                                reply_markup=reply_markup,
                                allow_paid_broadcast=allow_paid_broadcast,
                                message_effect_id=message_effect_id,
                                direct_messages_topic_id=direct_messages_topic_id,
                            )
                            logger.info(f"[broadcast] 发送成功 {broadcast_id}, chat={chat_id}, msg_id={msg.message_id}, type=image_card")
                            if db:
                                db.track_channel_message(chat_id, msg.message_id, "image")
                                _log_broadcast_attribution(db, chat_id, broadcast_id, "image_card")
                            image_sent = True
                    except Exception as img_err:
                        exc_type, status_code, err_summary = _extract_send_error(img_err)
                        logger.warning(
                            f"[broadcast] 图片卡发送失败 {broadcast_id}, chat={chat_id}, "
                            f"exc={exc_type}, status={status_code}, err={err_summary}，回退 text"
                        )

                if image_sent:
                    continue

                logger.info(f"[broadcast] 准备发送 {broadcast_id} 到 chat={chat_id}, type=text")
                msg = _send_formatted_text(
                    bot,
                    chat_id,
                    text,
                    parse_mode,
                    config,
                    rich_html=rich_html,
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
                logger.info(f"[broadcast] 发送成功 {broadcast_id}, chat={chat_id}, msg_id={msg.message_id}")
                # 追踪消息
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "text")
            except Exception as e:
                exc_type, status_code, err_summary = _extract_send_error(e)
                logger.warning(
                    f"[broadcast] 发送失败 {broadcast_id}, chat={chat_id}, type=text, "
                    f"exc={exc_type}, status={status_code}, err={err_summary}"
                )
                _release_failed_broadcast(db, task_key, e)
        elif content_type == "image":
            # content 可以是 file_id 或 URL
            caption = normalize_text(bc.get("caption", ""))
            caption_mode = None
            caption_rich_html = ""
            if caption:
                temp_item = dict(bc)
                temp_item["content"] = caption
                temp_item["title"] = temp_item.get("title", "图片播报")
                caption, caption_mode, caption_rich_html = _render_broadcast_text(temp_item, user_profile=user_profile, config=config)

            is_url = bool(content) and str(content).lower().startswith(("http://", "https://"))
            looks_local = _looks_like_local_path(content)
            is_local_path = looks_local and os.path.isfile(content)
            if content and not is_url and looks_local and not is_local_path:
                logger.warning(f"[broadcast] 图片本地路径不存在 {broadcast_id}: {content}")

            logger.info(f"[broadcast] 准备发送 {broadcast_id} 到 chat={chat_id}, type=image")
            try:
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
                logger.info(f"[broadcast] 发送成功 {broadcast_id}, chat={chat_id}, msg_id={msg.message_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "image")
            except Exception as e:
                exc_type, status_code, err_summary = _extract_send_error(e)
                logger.warning(
                    f"[broadcast] 发送失败 {broadcast_id}, chat={chat_id}, type=image, "
                    f"exc={exc_type}, status={status_code}, err={err_summary}"
                )
                # 失败时尝试用 caption/文案回退到文本播报
                fallback_succeeded = False
                fallback_error = None
                if caption:
                    logger.info(f"[broadcast] 图片发送失败，回退到文本播报 {broadcast_id}, chat={chat_id}")
                    try:
                        fallback_msg = _send_formatted_text(
                            bot,
                            chat_id,
                            caption,
                            caption_mode,
                            config,
                            rich_html=caption_rich_html,
                            disable_notification=disable_notification,
                            protect_content=protect_content,
                            reply_markup=reply_markup,
                            disable_web_page_preview=disable_preview,
                            link_preview_options={"is_disabled": disable_preview} if disable_preview else None,
                            allow_paid_broadcast=allow_paid_broadcast,
                            message_effect_id=message_effect_id,
                            direct_messages_topic_id=direct_messages_topic_id,
                            suggested_post_parameters=suggested_post_parameters,
                        )
                        logger.info(
                            f"[broadcast] 文本回退发送成功 {broadcast_id}, chat={chat_id}, "
                            f"msg_id={fallback_msg.message_id}"
                        )
                        if db:
                            db.track_channel_message(chat_id, fallback_msg.message_id, "text")
                        fallback_succeeded = True
                    except Exception as fallback_err:
                        fallback_error = fallback_err
                        exc_type2, status_code2, err_summary2 = _extract_send_error(fallback_err)
                        logger.warning(
                            f"[broadcast] 文本回退发送失败 {broadcast_id}, chat={chat_id}, "
                            f"exc={exc_type2}, status={status_code2}, err={err_summary2}"
                        )
                if not fallback_succeeded:
                    _release_failed_broadcast(db, task_key, fallback_error or e)
        elif content_type == "voice":
            try:
                msg = bot.send_voice(chat_id, content)
                logger.info(f" 定点播报(语音): {broadcast_id}")
                if db:
                    db.track_channel_message(chat_id, msg.message_id, "voice")
            except Exception as e:
                logger.warning(f"定点播报发送失败(语音) {broadcast_id}: {e}")
                _release_failed_broadcast(db, task_key, e)
        elif content_type == "poll":
            try:
                question = str(bc.get("question") or content or "").strip()
                options = bc.get("options", [])
                if isinstance(options, str):
                    options = [item.strip() for item in options.split("|") if item.strip()]
                if not question or len(options) < 2:
                    raise ValueError(
                        f"定点播报投票配置无效 {broadcast_id}: question/options缺失"
                    )
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
                _release_failed_broadcast(db, task_key, e)
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
                    raise ValueError(
                        f"定点清单配置无效 {broadcast_id}: TELEGRAM_BUSINESS_CONNECTION_ID 未配置"
                    )
                if not checklist.get("tasks"):
                    raise ValueError(f"定点清单配置无效 {broadcast_id}: tasks缺失")
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
                _release_failed_broadcast(db, task_key, e)
        else:
            _release_failed_broadcast(
                db,
                task_key,
                ValueError(f"不支持的定点播报类型 {broadcast_id}: {content_type}"),
            )
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

    【v5.31.2 修复】INSERT 引用 source/campaign_id 字段但 conversion_events
    建表时只有 5 个字段（id/uid/event/ts/mode），需先调用 _ensure_conversion_columns
    加列，否则会抛 OperationalError 被静默吞掉，归因数据悄悄丢失。
    """
    try:
        from datetime import datetime
        from core.growth_optimizer import _ensure_conversion_columns
        # 先确保 source/campaign_id 等扩展列存在（与 growth_optimizer._insert_conversion 一致）
        _ensure_conversion_columns(db.conn)

        campaign_id = f"{broadcast_id}_{datetime.now(_CST).strftime('%Y%m%d')}"
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
