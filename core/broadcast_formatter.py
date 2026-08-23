# -*- coding: utf-8 -*-
"""
播报排版工具 v5.32 - 统一富文本卡片 + Rich Message 块级标签。

两套排版路径（[v5.32] 新增 Rich Message 路径）：

路径 1：HTML parse_mode（旧版，所有客户端可用）
  统一结构：
    <b><i>emoji 标题</i></b>
    <i>角标</i>
    正文
    <blockquote expandable>折叠补充</blockquote>
  标签限制：仅内联标签 + blockquote，不支持 <h1>/<ul>/<table> 等块级标签。

路径 2：Rich Message（[v5.32] 新增，Bot API 10.1+）
  统一结构：
    <h2>emoji 标题</h2>
    <p><i>角标</i></p>
    <p>正文段落1</p>
    <p>正文段落2</p>
    <details><summary>更多</summary>...footer...</details>
  支持块级标签：<h1>-<h6>/<p>/<ul>/<ol>/<li>/<table>/<tr>/<td>/<th>/
              <details>/<summary>/<hr>/<blockquote>/<pullquote>/<footer>
  旧客户端降级为纯文本，新客户端展示富文本。

设计原则：
1. 简洁清晰，不过度装饰
2. 充分利用 Telegram 原生格式化能力
3. 移动端友好，一屏看完
4. 话术自然，不生硬，不硬塞营销引导
5. 折叠区放补充信息，不破坏正文阅读体验
"""

import html
import re


# ── 时段样式映射 ─────────────────────────────────────────────────────────────
PERIOD_STYLES = {
    "morning":   {"emoji": "☀️", "greeting": "早"},
    "afternoon": {"emoji": "🍵", "greeting": "午安"},
    # 傍晚档标题与图片卡一致用"暮安"，晚安留给 night 档
    "evening":   {"emoji": "🌆", "greeting": "暮安"},
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


# ── 统一富文本卡片构建器（v5.38.15）────────────────────────────────────────────
def build_card_html(
    title: str,
    body: str,
    footer: str = "",
    badge: str = "",
    emoji: str = "📢",
    closing: str = "",
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
    💬 结尾引导语（可选）
    <空行>
    <blockquote expandable>折叠补充</blockquote>

    参数：
        title: 标题文字（如 "早"、"午后碎碎念"）
        body: 正文（纯文本，自动转义）
        footer: 折叠补充内容（纯文本，自动转义）
        badge: 角标（如 "Mory来报到啦"）
        emoji: 标题前 emoji
        closing: 正文结尾自然引导语（与按钮配套）
    """
    safe_title = escape_html_text(title)
    head = f"<b><i>{emoji} {safe_title}</i></b>"

    badge_line = ""
    if badge:
        safe_badge = escape_html_text(badge)
        badge_line = f"<i>{safe_badge}</i>"

    safe_body = escape_html_text(normalize_text(body))

    parts = [head]
    if badge_line:
        parts.append("")
        parts.append(badge_line)
    parts.append("")
    parts.append(safe_body)

    if closing:
        safe_closing = escape_html_text(closing)
        parts.append("")
        parts.append(f"💬 {safe_closing}")

    if footer:
        safe_footer = escape_html_text(footer)
        parts.append("")
        parts.append(f"<blockquote expandable>{safe_footer}</blockquote>")

    return "\n".join(parts)


# ── 告警/通知卡片 ────────────────────────────────────────────────────────────
_ALERT_LEVEL_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "danger": "🚫",
    "success": "✅",
}

# 卡片署名代表当前发送消息的机器人身份；自助订阅入口由独立按钮承载。
BROADCAST_SENDER_HANDLE = "@MoryMateBot"


def build_alert_card_html(
    title: str,
    body: str,
    level: str = "info",
    footer: str = "",
) -> str:
    """
    告警/通知卡片构建器（v5.31.6 新增）。

    用于管理员通知、系统告警等场景，与播报卡片 build_card_html 区分。
    排版结构：
    <b>emoji 标题</b>
    <空行>
    正文内容（支持 HTML，调用方需自行转义）
    <空行>
    <blockquote>附注</blockquote>

    参数：
        title: 标题文字（纯文本，自动转义）
        body: 正文（支持 HTML，调用方需自行转义外部内容）
        level: 告警级别 info/warning/danger/success，决定 emoji
        footer: 附注内容（纯文本，自动转义）
    """
    safe_title = escape_html_text(title)
    emoji = _ALERT_LEVEL_EMOJI.get(level, "ℹ️")
    head = f"<b>{emoji} {safe_title}</b>"

    footer_html = ""
    if footer:
        safe_footer = escape_html_text(footer)
        footer_html = f"<blockquote>{safe_footer}</blockquote>"

    parts = [head, "", body]
    if footer_html:
        parts.extend(["", footer_html])

    return "\n".join(parts)


# ── 问候卡片 ─────────────────────────────────────────────────────────────────
def build_greeting_html(
    period: str,
    body: str,
    footer: str = "",
    badge: str = "",
    user_profile: dict = None,
    closing: str = "",
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
            emoji = "🔮"
        elif "treehole" in interests:
            emoji = "🌳"

    return build_card_html(
        title=greeting,
        body=body,
        footer=footer,
        badge=badge,
        emoji=emoji,
        closing=closing,
    )


# ── 定点播报卡片 ─────────────────────────────────────────────────────────────
def build_broadcast_html(
    title: str,
    body: str,
    footer: str = "",
    badge: str = "",
    period: str = "",
    user_profile: dict = None,
    closing: str = "",
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
            emoji = "🌳"

    return build_card_html(
        title=title,
        body=body,
        footer=footer,
        badge=badge,
        emoji=emoji,
        closing=closing,
    )


# ── 旧版兼容（保留，历史版本引用报错）────────────────────────────────────
def build_rich_broadcast_html(**kwargs) -> str:
    """兼容旧接口，转发到 build_broadcast_html。"""
    return build_broadcast_html(
        title=kwargs.get("title", ""),
        body=kwargs.get("body", ""),
        footer=kwargs.get("footer", ""),
        badge=kwargs.get("badge", ""),
        period=kwargs.get("period", ""),
        user_profile=kwargs.get("user_profile"),
        closing=kwargs.get("closing", ""),
    )


def build_rich_greeting_html(
    period: str, body: str, footer: str = "", **kwargs
) -> str:
    """兼容旧接口，转发到 build_greeting_html。"""
    return build_greeting_html(
        period=period,
        body=body,
        footer=footer,
        badge=kwargs.get("badge", ""),
        user_profile=kwargs.get("user_profile"),
        closing=kwargs.get("closing", ""),
    )


# ════════════════════════════════════════════════════════════════════════════
# [v5.32] Rich Message 构建器（Bot API 10.1+，块级标签）
# 与上面 HTML parse_mode 构建器并存。当 RICH_MESSAGE_ENABLED=true 且
# BROADCAST_FORMAT_VERSION ∈ {"rich","auto"} 时，scheduled_broadcast /
# greeting_task / news_task 优先调用以下函数，配合 send_rich_message_compat
# 发送。旧客户端自动降级为纯文本，新客户端展示富文本。
#
# Rich Message 限制（官方）：
# - 嵌套 ≤16 层
# - 块数 ≤500
# - 表格列数 ≤20
# - <td> 仅内联格式
# - <blockquote> 不能嵌套
# - <table> 内不能嵌套 <table>
# ════════════════════════════════════════════════════════════════════════════

def _rich_split_paragraphs(text: str) -> list[str]:
    """把正文按空行切成段落，每段 <p>。</p> 包裹。"""
    safe = escape_html_text(normalize_text(text))
    if not safe:
        return []
    paragraphs = [p.strip() for p in safe.split("\n\n") if p.strip()]
    return paragraphs


def build_rich_card_message(
    title: str,
    body: str,
    footer: str = "",
    badge: str = "",
    emoji: str = "📢",
    closing: str = "",
) -> str:
    """[v5.38.15] Rich Message 通用卡片（块级标签）。

    排版结构：
        <h2>emoji 标题</h2>
        <p><i>角标</i></p>
        <p>正文段落1</p>
        <p>正文段落2</p>
        <p>💬 结尾引导语（可选）</p>
        <hr>
        <footer>@MoryMateBot</footer>
        <details><summary>更多</summary>...footer...</details>

    返回 HTML 字符串，调用方用 send_rich_message_compat(bot, chat_id, html) 发送。
    """
    safe_title = escape_html_text(title)
    parts = [f"<h2>{emoji} {safe_title}</h2>"]

    if badge:
        safe_badge = escape_html_text(badge)
        parts.append(f"<p><i>{safe_badge}</i></p>")

    for para in _rich_split_paragraphs(body):
        parts.append(f"<p>{para}</p>")

    if closing:
        safe_closing = escape_html_text(closing)
        parts.append(f"<p>💬 {safe_closing}</p>")

    parts.append("<hr>")
    parts.append(f"<footer>{BROADCAST_SENDER_HANDLE}</footer>")

    if footer:
        safe_footer = escape_html_text(footer)
        parts.append(
            f"<details><summary>更多</summary><p>{safe_footer}</p></details>"
        )

    return "\n".join(parts)


def build_rich_greeting_card_message(
    period: str,
    body: str,
    footer: str = "",
    badge: str = "",
    user_profile: dict = None,
    closing: str = "",
) -> str:
    """[v5.38.15] Rich Message 问候卡片（早/午/晚安）。"""
    style = PERIOD_STYLES.get(period, {})
    emoji = style.get("emoji", "📢")
    greeting = style.get("greeting", "你好")

    if user_profile:
        tags = user_profile.get("tags", [])
        level = user_profile.get("level", 0)
        interests = user_profile.get("interests", [])
        if "vip" in tags or level >= 5:
            emoji = "✨"
        if "tarot" in interests and period in ("evening", "night"):
            emoji = "🔮"
        elif "treehole" in interests:
            emoji = "🌳"

    return build_rich_card_message(
        title=greeting,
        body=body,
        footer=footer,
        badge=badge,
        emoji=emoji,
        closing=closing,
    )


def build_rich_broadcast_card_message(
    title: str,
    body: str,
    footer: str = "",
    badge: str = "",
    period: str = "",
    user_profile: dict = None,
    closing: str = "",
) -> str:
    """[v5.38.15] Rich Message 定点播报卡片。"""
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
            emoji = "🌳"

    return build_rich_card_message(
        title=title,
        body=body,
        footer=footer,
        badge=badge,
        emoji=emoji,
        closing=closing,
    )


def build_mystic_html(payload: dict) -> str:
    """[v5.38.15] 传统文化栏目的 Telegram HTML 降级卡片。"""
    # 标题统一 <b><i> 风格，与 build_card_html 一致
    parts = [
        f"<b><i>{escape_html_text(payload.get('emoji', '🔮'))} "
        f"{escape_html_text(payload.get('title', '今日栏目'))}</i></b>",
    ]
    kicker = str(payload.get("kicker", "") or "")
    if kicker:
        parts.append(f"<i>{escape_html_text(kicker)}</i>")
    meta = str(payload.get("meta", "") or "")
    if meta:
        parts.extend(["", f"<blockquote>{escape_html_text(meta)}</blockquote>"])
    for block in payload.get("blocks", []):
        parts.extend(["", f"<b>{escape_html_text(block.get('heading', ''))}</b>"])
        parts.extend(
            f"<b>{escape_html_text(label)}</b>　{escape_html_text(value)}"
            for label, value in block.get("lines", [])
        )
    insight = str(payload.get("insight", "") or "")
    if insight:
        parts.extend(["", f"<blockquote>{escape_html_text(insight)}</blockquote>"])
    cta = payload.get("cta")
    closing = cta.get("closing") if isinstance(cta, dict) else ""
    if closing:
        parts.extend(["", f"💬 {escape_html_text(closing)}"])
    note = str(payload.get("note", "") or "")
    if note:
        parts.extend(["", f"<i>{escape_html_text(note)}</i>"])
    parts.extend(["", f"<i>{BROADCAST_SENDER_HANDLE}</i>"])
    return "\n".join(parts)


def build_rich_mystic_card_message(payload: dict) -> str:
    """[v5.38.15] 三时段传统文化栏目的分区 Rich Message 卡片。"""
    parts = [
        f"<h2>{escape_html_text(payload.get('emoji', '🔮'))} "
        f"{escape_html_text(payload.get('title', '今日栏目'))}</h2>",
    ]
    kicker = str(payload.get("kicker", "") or "")
    if kicker:
        parts.append(f"<p><i>{escape_html_text(kicker)}</i></p>")
    meta = str(payload.get("meta", "") or "")
    if meta:
        parts.append(f"<blockquote>{escape_html_text(meta)}</blockquote>")
    for block in payload.get("blocks", []):
        parts.append(f"<h3>{escape_html_text(block.get('heading', ''))}</h3>")
        parts.extend(
            f"<p><b>{escape_html_text(label)}</b>　{escape_html_text(value)}</p>"
            for label, value in block.get("lines", [])
        )
    insight = str(payload.get("insight", "") or "")
    if insight:
        parts.append(f"<blockquote>{escape_html_text(insight)}</blockquote>")
    cta = payload.get("cta")
    closing = cta.get("closing") if isinstance(cta, dict) else ""
    if closing:
        parts.append(f"<p>💬 {escape_html_text(closing)}</p>")
    note = str(payload.get("note", "") or "")
    if note:
        # 免责尾注用小字段落而非 h3 区块，保持 blocks 数与 <h3> 数一致
        parts.append(f"<p><i>{escape_html_text(note)}</i></p>")
    parts.extend(["<hr>", f"<footer>{BROADCAST_SENDER_HANDLE}</footer>"])
    return "\n".join(parts)


def build_rich_alert_card_message(
    title: str,
    body: str,
    level: str = "info",
    footer: str = "",
) -> str:
    """[v5.32] Rich Message 告警卡片（管理员通知用）。

    排版结构：
        <h3>emoji 标题</h3>
        <p>正文（支持 HTML，调用方需自行转义外部内容）</p>
        <blockquote>附注</blockquote>
    """
    safe_title = escape_html_text(title)
    emoji = _ALERT_LEVEL_EMOJI.get(level, "ℹ️")
    parts = [f"<h3>{emoji} {safe_title}</h3>"]

    if body:
        # body 已是 HTML（调用方负责转义），直接放 <p>
        parts.append(f"<p>{body}</p>")

    if footer:
        safe_footer = escape_html_text(footer)
        parts.append(f"<blockquote>{safe_footer}</blockquote>")

    return "\n".join(parts)
