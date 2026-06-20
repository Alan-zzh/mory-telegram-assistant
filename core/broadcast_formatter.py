# -*- coding: utf-8 -*-
"""
播报排版工具 v5.0 - 统一富文本卡片。

统一排版结构（所有播报类型共用）：
<b><i>emoji 标题</i></b>

<i>角标</i>

正文（自然段落，不整段斜体）

<blockquote expandable><i>折叠补充（自然转化引导）</i></blockquote>

设计原则：
1. 简洁清晰，不过度装饰
2. 充分利用 Telegram HTML 格式化
3. 移动端友好，一屏看完
4. 话术自然，不生硬，不明显往转化靠
5. 折叠区放转化引导，不破坏正文阅读体验
"""

import html
import re


# ── 时段样式映射 ─────────────────────────────────────────────────────────────
PERIOD_STYLES = {
    "morning":   {"emoji": "☀️", "greeting": "早"},
    "afternoon": {"emoji": "🍃", "greeting": "午安"},
    "evening":   {"emoji": "🌆", "greeting": "晚上好"},
    "night":     {"emoji": "🌙", "greeting": "晚安"},
}


# ── HTML 检测与转义 ─────────────────────────────────────────────────────────
_HTML_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|tg-spoiler|code|pre|"
    r"blockquote|a|tg-emoji|tg-map|tg-copy|tg-expand|tg-s|tg-mention|tg-person)\b",
    re.I,
)


def looks_like_html(text: str) -> bool:
    """粗略判断文本是否已经是 HTML 富文本。"""
    if not text:
        return False
    return bool(_HTML_TAG_RE.search(text))


def escape_html_text(text: str) -> str:
    """转义普通文本，避免插入 HTML 卡片时破版。"""
    return html.escape((text or "").strip(), quote=False)


def normalize_text(text: str) -> str:
    """把多余空行和首尾空白收一收。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.split("\n")]
    cleaned = []
    last_blank = False
    for line in lines:
        if not line:
            if not last_blank:
                cleaned.append("")
            last_blank = True
            continue
        cleaned.append(line)
        last_blank = False
    return "\n".join(cleaned).strip()


# ── 辅助函数 ─────────────────────────────────────────────────────────────────
def add_emphasis(text: str, keywords: list[str] = None) -> str:
    """给关键词加 <b> 强调。"""
    if not keywords or not text:
        return text
    result = escape_html_text(text)
    for kw in keywords:
        if kw in result:
            result = result.replace(kw, f"<b>{kw}</b>")
    return result


def add_spoiler_hint(text: str) -> str:
    """给私密内容加 <tg-spoiler> 剧透标签。"""
    if not text:
        return text
    safe = escape_html_text(text)
    return f"<tg-spoiler>{safe}</tg-spoiler>"


# ── 统一富文本卡片构建器（v5.0）──────────────────────────────────────────────
def build_card_html(
    title: str,
    body: str,
    footer: str = "",
    badge: str = "",
    emoji: str = "📢",
) -> str:
    """
    统一富文本卡片构建器。所有播报类型共用此函数。

    排版结构：
    <b><i>emoji 标题</i></b>
    <空行>
    <i>角标</i>
    <空行>
    正文内容
    <空行>
    <blockquote expandable><i>折叠补充</i></blockquote>

    参数：
        title: 标题文字（如 "早"、"午后碎碎念"）
        body: 正文（纯文本，自动转义）
        footer: 折叠补充内容（纯文本，自动转义）
        badge: 角标（如 "Mory来报到啦"）
        emoji: 标题前 emoji
    """
    safe_title = escape_html_text(title)
    head = f"<b><i>{emoji} {safe_title}</i></b>"

    badge_line = ""
    if badge:
        safe_badge = escape_html_text(badge)
        badge_line = f"<i>{safe_badge}</i>"

    safe_body = escape_html_text(normalize_text(body))

    footer_html = ""
    if footer:
        safe_footer = escape_html_text(footer)
        footer_html = f"<blockquote expandable><i>{safe_footer}</i></blockquote>"

    parts = [head]
    if badge_line:
        parts.append("")
        parts.append(badge_line)
    parts.append("")
    parts.append(safe_body)
    if footer_html:
        parts.append("")
        parts.append(footer_html)

    return "\n".join(parts)


# ── 问候卡片 ─────────────────────────────────────────────────────────────────
def build_greeting_html(
    period: str,
    body: str,
    footer: str = "",
    user_profile: dict = None,
) -> str:
    """
    问候卡片（早安/午安/晚安）。

    根据时段自动选择 emoji。
    正文不整段斜体，保持可读性。
    折叠区放自然转化引导。
    """
    style = PERIOD_STYLES.get(period, {})
    emoji = style.get("emoji", "📢")
    greeting = style.get("greeting", "你好")

    # 用户画像微调
    if user_profile:
        tags = user_profile.get("tags", [])
        level = user_profile.get("level", 0)
        interests = user_profile.get("interests", [])
        if "vip" in tags or level >= 5:
            emoji = "✨"
        if "tarot" in interests and period in ("evening", "night"):
            emoji = ""
        elif "treehole" in interests:
            emoji = "🌳"

    return build_card_html(
        title=greeting,
        body=body,
        footer=footer,
        badge="Mory来报到啦",
        emoji=emoji,
    )


# ── 定点播报卡片 ─────────────────────────────────────────────────────────────
def build_broadcast_html(
    title: str,
    body: str,
    footer: str = "",
    badge: str = "",
    period: str = "",
    user_profile: dict = None,
) -> str:
    """定点播报卡片。"""
    emoji = "📢"
    if period:
        style = PERIOD_STYLES.get(period, {})
        emoji = style.get("emoji", "📢")

    if user_profile:
        tags = user_profile.get("tags", [])
        level = user_profile.get("level", 0)
        interests = user_profile.get("interests", [])
        if "vip" in tags or level >= 5:
            emoji = "✨"
        if "tarot" in interests and period in ("evening", "night"):
            emoji = "🔮"
        elif "treehole" in interests:
            emoji = ""

    return build_card_html(
        title=title,
        body=body,
        footer=footer,
        badge=badge,
        emoji=emoji,
    )


# ── 新闻播报卡片 ─────────────────────────────────────────────────────────────
def build_news_html(
    time_desc: str,
    news_content: str,
) -> str:
    """
    新闻播报卡片。

    排版结构：
    <b><i>emoji 时段新闻</i></b>
    <空行>
    📌 新闻1
    📌 新闻2
    ...
    <blockquote expandable><i>观察行</i></blockquote>
    <空行>
    ─ ─ ─ ─  ─ ─ ─ ─ ─
    <b><i>自然引导</i></b>
    """
    period_emojis = {
        "早间": "",
        "午间": "️",
        "晚间": "🌙",
    }
    emoji = period_emojis.get(time_desc, "📰")

    title = f"<b><i>{emoji} {time_desc}新闻</i></b>"

    safe_body = escape_html_text(normalize_text(news_content))

    # 按行号识别：前5行新闻 + 第6行观察
    body_lines = safe_body.split("\n")
    formatted_lines = []
    news_count = 0
    for line in body_lines:
        line = line.strip()
        if not line:
            formatted_lines.append("")
            continue
        news_count += 1
        if news_count <= 5:
            formatted_lines.append(f"📌 {line}")
        elif news_count == 6:
            formatted_lines.append(
                f"<blockquote expandable><i>{line}</i></blockquote>"
            )

    formatted_body = "\n".join(formatted_lines)

    # 底部自然引导（不用分隔线，用折叠区）
    footer = "<i>想看更多？来 @MorychannelBot 找我聊～</i>"

    parts = [title, "", formatted_body, "", footer]
    return "\n".join(parts)


# ── 旧版兼容（保留，避免其他模块引用报错）────────────────────────────────────
def build_rich_broadcast_html(**kwargs) -> str:
    """兼容旧接口，转发到 build_broadcast_html。"""
    return build_broadcast_html(
        title=kwargs.get("title", ""),
        body=kwargs.get("body", ""),
        footer=kwargs.get("footer", ""),
        badge=kwargs.get("badge", ""),
        period=kwargs.get("period", ""),
        user_profile=kwargs.get("user_profile"),
    )


def build_rich_greeting_html(
    period: str, body: str, footer: str = "", **kwargs
) -> str:
    """兼容旧接口，转发到 build_greeting_html。"""
    return build_greeting_html(
        period=period,
        body=body,
        footer=footer,
        user_profile=kwargs.get("user_profile"),
    )


def build_rich_news_html(time_desc: str, news_content: str, **kwargs) -> str:
    """兼容旧接口，转发到 build_news_html。"""
    return build_news_html(time_desc=time_desc, news_content=news_content)
