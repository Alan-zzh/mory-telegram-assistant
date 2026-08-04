# -*- coding: utf-8 -*-
"""统一播报 CTA 组件。

把图片卡上的视觉 CTA、真实 Inline Keyboard 按钮、Mini App 入口、
文案池全部收敛到一个地方，确保：
- 图片上印的文案与真实按钮文案一致（image_label 由 label 经 strip_visual_emoji 派生）
- 同一场景每轮只出现单一入口
- 新闻等纯资讯类型不夹带转化入口
- 支持彩色按钮与 Mini App 入口（默认关闭）
"""

from __future__ import annotations

import hashlib
import random
from typing import Dict, List, Optional, Tuple


# ── 目标入口常量 ──
TARGET_PREVIEW = "preview"
TARGET_SUBSCRIBE = "subscribe"
TARGET_CONTACT = "contact"
TARGET_MINI_APP = "mini_app"
TARGET_NONE = "none"

_DEFAULT_URLS = {
    TARGET_PREVIEW: "https://t.me/moryselect",
    TARGET_SUBSCRIBE: "https://t.me/MorychannelBot",
    TARGET_CONTACT: "https://t.me/Moryfansbot",
}

# ── 各场景 CTA 文案池 ──
# 元组格式：(label, image_label, closing)
# label: 真实按钮文案（可含 emoji）
# image_label: 图片卡上印的文案（建议无 emoji）
# closing: 正文结尾自然引导语（可选，放在按钮前）
_CTA_POOLS: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = {
    "mystic_almanac": {
        TARGET_CONTACT: [
            ("🧭 找 Mory 看日子", "找 Mory 看日子", "黄历上的宜忌、冲煞只是日常参考，具体择日或有具体事情想选日子，适合找 Mory 单独看。"),
            ("🧭 想算个人方位？找 Mory", "想算个人方位？找 Mory", "空间风水、择日办事这类具体问题，适合把信息准备齐后找 Mory 单独看。"),
            ("🧭 个人择日咨询", "个人择日咨询", "有具体日子或行程想确认，可以带着问题找 Mory 单独看。"),
        ],
        TARGET_PREVIEW: [
            ("🎁 看预览与福利", "看预览与福利", "想先看看内容和群内福利，下面有预览入口，合不合适看完再说。"),
            ("🎁 先看一眼群内福利", "先看一眼群内福利", "不确定要不要订，可以先去预览里看看实际内容和氛围。"),
            ("🎁 预览入口", "预览入口", "想了解的都在预览里，看完再决定要不要继续聊。"),
        ],
        TARGET_SUBSCRIBE: [
            ("🛒 自助订阅", "自助订阅", "已经了解过、想继续的话，下面可以查看当前选项并自助订阅。"),
            ("🛒 开通每日推送", "开通每日推送", "看完预览觉得合适的话，可以直接从这里查看可选项。"),
            ("🛒 查看当前选项", "查看当前选项", "如果已经看过预览，可以直接查看当前有哪些选项。"),
        ],
    },
    "mystic_tarot": {
        TARGET_CONTACT: [
            ("🔮 找 Mory 单独抽牌", "找 Mory 单独抽牌", "想看自己的专属牌阵，先想好一个具体问题，再找 Mory 单独抽牌。"),
            ("🔮 想抽个人牌阵？找 Mory", "想抽个人牌阵？找 Mory", "个人塔罗更适合带着具体问题来抽，把问题想清楚后找 Mory 单独聊。"),
            ("🔮 个人塔罗咨询", "个人塔罗咨询", "有想抽的牌阵或问题，可以直接找 Mory 单独聊。"),
        ],
        TARGET_PREVIEW: [
            ("🎁 看预览与福利", "看预览与福利", "想先看看内容和群内福利，下面有预览入口，合不合适看完再说。"),
            ("🎁 先看一眼群内福利", "先看一眼群内福利", "不确定要不要订，可以先去预览里看看实际内容和氛围。"),
            ("🎁 预览入口", "预览入口", "想了解的都在预览里，看完再决定要不要继续聊。"),
        ],
        TARGET_SUBSCRIBE: [
            ("🛒 自助订阅", "自助订阅", "已经了解过、想继续的话，下面可以查看当前选项并自助订阅。"),
            ("🛒 开通每日推送", "开通每日推送", "看完预览觉得合适的话，可以直接从这里查看可选项。"),
            ("🛒 查看当前选项", "查看当前选项", "如果已经看过预览，可以直接查看当前有哪些选项。"),
        ],
    },
    "mystic_iching": {
        TARGET_CONTACT: [
            # ☯️ 注意：strip_visual_emoji 会把 FE0F 变体选择符去掉，保留 ☯ 本体；img_label 需与派生结果一致
            ("☯️ 找 Mory 问一卦", "☯ 找 Mory 问一卦", "想问自己的具体主题，可以先把问题压成一句话，再找 Mory 单独起卦。"),
            ("☯️ 想起个人卦象？找 Mory", "☯ 想起个人卦象？找 Mory", "易经问事越具体越准，先把问题整理成一句话，再找 Mory 单独起卦。"),
            ("☯️ 个人易经咨询", "☯ 个人易经咨询", "有具体的问题想卜一卦，可以直接找 Mory 单独聊。"),
        ],
        TARGET_PREVIEW: [
            ("🎁 看预览与福利", "看预览与福利", "想先看看内容和群内福利，下面有预览入口，合不合适看完再说。"),
            ("🎁 先看一眼群内福利", "先看一眼群内福利", "不确定要不要订，可以先去预览里看看实际内容和氛围。"),
            ("🎁 预览入口", "预览入口", "想了解的都在预览里，看完再决定要不要继续聊。"),
        ],
        TARGET_SUBSCRIBE: [
            ("🛒 自助订阅", "自助订阅", "已经了解过、想继续的话，下面可以查看当前选项并自助订阅。"),
            ("🛒 开通每日推送", "开通每日推送", "看完预览觉得合适的话，可以直接从这里查看可选项。"),
            ("🛒 查看当前选项", "查看当前选项", "如果已经看过预览，可以直接查看当前有哪些选项。"),
        ],
    },
    "greeting": {
        TARGET_PREVIEW: [
            ("👀 看看预览", "看看预览", "路过也可以先看看预览，合不合适看完再说。"),
            ("👀 先去看看内容", "先去看看内容", "想先了解内容的话，下面有入口。"),
            ("👀 了解一下", "了解一下", "想多了解一点的话，可以点进去看看。"),
        ],
    },
    # greeting_afternoon / greeting_night 按 period 精确匹配（period 由调用方传）
    # _resolve_pool_name 会先查精确匹配，找不到再回退 "greeting" 通用池
    "greeting_afternoon": {
        TARGET_PREVIEW: [
            ("👀 歇一分钟 · 看看预览", "歇一分钟 · 看看预览", "下午忙累了，歇一分钟看看预览，合不合适再说。"),
            ("👀 顺便看看内容", "顺便看看内容", "正好路过，顺便看看内容？下面有入口。"),
            ("👀 下午好 · 先看一眼预览", "下午好 · 先看一眼预览", "下午时间还长，先看一眼预览也不着急。"),
        ],
    },
    "greeting_night": {
        TARGET_PREVIEW: [
            ("👀 今晚先到这 · 看看预览", "今晚先到这 · 看看预览", "今天先到这，想看的话预览里都有，看完早点休息。"),
            ("👀 睡前看看预览", "睡前看看预览", "睡不着的时候，可以点进去看看预览里的内容。"),
            ("👀 晚安 · 明天再见", "晚安 · 明天再见", "看完早点睡，明天还有新的内容。"),
        ],
    },
    "scheduled": {
        TARGET_PREVIEW: [
            ("👀 看看预览", "看看预览", "路过也可以先看看预览，合不合适看完再说。"),
            ("👀 先去看看内容", "先去看看内容", "想先了解内容的话，下面有入口。"),
            ("👀 了解一下", "了解一下", "想多了解一点的话，可以点进去看看。"),
        ],
    },
    "scheduled_afternoon": {
        TARGET_PREVIEW: [
            ("👀 下午时段 · 精选预览", "下午时段 · 精选预览", "下午固定播报，可以顺便看看下午的精选预览。"),
            ("👀 了解今天的内容", "了解今天的内容", "想了解今天还有什么内容，可以点进去看预览。"),
        ],
    },
    "scheduled_night": {
        TARGET_PREVIEW: [
            ("👀 晚间播报 · 看看预览", "晚间播报 · 看看预览", "晚间播报结束，想看更多内容可以去预览看看。"),
            ("👀 回顾今天的内容", "回顾今天的内容", "想回顾今天还有什么，可以点头像看预览。"),
        ],
    },
    "news": {
        # 新闻属于纯资讯，不夹带入口
    },
}

_STYLE_MAP = {
    TARGET_PREVIEW: "primary",
    TARGET_SUBSCRIBE: "success",
    TARGET_CONTACT: "primary",
    TARGET_MINI_APP: "success",
}


def _resolve_pool_name(scene: str, mode: str = "", period: str = "") -> str:
    """根据场景定位文案池。

    优先级：
    1. mystic + mode → mystic_{mode}
    2. (greeting|scheduled) + period ∈ {afternoon,night} → {scene}_{period}（精确匹配）
    3. 回退到通用 {scene} 池
    """
    if scene == "mystic" and mode:
        return f"mystic_{mode}"
    if scene in ("greeting", "scheduled") and period in ("afternoon", "night"):
        precise = f"{scene}_{period}"
        if precise in _CTA_POOLS:
            return precise
    return scene


def _stable_seed(*parts) -> int:
    """确定性种子，用于同一天的 CTA 选择保持一致。

    用 md5 而非内置 hash()，消除跨进程 PYTHONHASHSEED 漂移，
    保证同参数在任何进程/重启后种子一致（与 modules/scheduled_broadcast.py 模式一致）。
    """
    h = "|".join(str(p) for p in parts)
    return int(hashlib.md5(h.encode("utf-8")).hexdigest()[:8], 16)


def _choose_target(
    scene: str,
    period: str,
    config: dict,
    user_profile: dict,
    rng: random.Random,
) -> str:
    """按场景和配置选择一个转化目标。"""
    cfg = config or {}

    # 新闻、问候早晨/晚上 无入口
    if scene == "news":
        return TARGET_NONE
    if scene == "greeting" and period not in ("afternoon", "night"):
        return TARGET_NONE
    # 定点低频播报只会先到预览，不直接给订阅/私聊入口
    if scene == "scheduled":
        return TARGET_PREVIEW

    # 玄学栏目根据 cta_enabled 决定；未开启则不展示
    if scene == "mystic":
        mystic_cfg = cfg.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(cfg, dict) else {}
        if not bool(mystic_cfg.get("cta_enabled", False)):
            return TARGET_NONE

    # 可用的目标按顺序轮转，让不同时段/日期分布更均匀
    available = [TARGET_PREVIEW, TARGET_CONTACT, TARGET_SUBSCRIBE]
    if bool(cfg.get("MINI_APP_ENABLED", False)):
        available.append(TARGET_MINI_APP)

    # 用户画像：VIP 或高等级用户更常看到订阅入口
    if user_profile:
        tags = user_profile.get("tags", []) or []
        level = user_profile.get("level", 0) or 0
        if "vip" in tags or level >= 5:
            # 增加 subscribe 权重：放两次
            available.append(TARGET_SUBSCRIBE)

    # 确定性轮转：用日期+场景决定
    return rng.choice(available)


def _get_url(target: str, config: dict) -> str:
    """获取目标 URL，支持配置覆盖。"""
    cfg = config or {}
    if target == TARGET_MINI_APP:
        return cfg.get("MINI_APP_URL", _DEFAULT_URLS.get(TARGET_PREVIEW, ""))
    return _DEFAULT_URLS.get(target, "")


def _personalize_label(label: str, image_label: str, closing: str, user_profile: dict) -> Tuple[str, str, str]:
    """根据用户画像微调文案，保持温和不冒犯。"""
    if not user_profile:
        return label, image_label, closing
    tags = user_profile.get("tags", []) or []
    level = user_profile.get("level", 0) or 0
    if "vip" in tags or level >= 5:
        # VIP 用户用更直接的表达
        if "看看预览" in label:
            label = label.replace("看看预览", "查看精选预览")
            # 注意：image_label 后续会由 label 重新派生，这里只同步改 label 即可
    return label, image_label, closing


def validate_cta_consistency(label: str, image_label: str) -> Tuple[bool, str]:
    """校验 CTA 文案一致性：strip emoji 后 label 应与 image_label 等价或 image_label 是 label 的子集。

    返回：(是否通过, 原因说明)。此函数用于测试/调试，不拦截生产流程。
    """
    from core.broadcast_image_card import strip_visual_emoji

    derived = strip_visual_emoji(label)
    if not derived and not image_label:
        return True, "both empty"
    # 派生值需要和显式提供的 image_label 相等，或 image_label 完全包含在派生值中
    if derived == image_label:
        return True, "exact match"
    if image_label and image_label in derived:
        return True, "image_label is substring of derived label"
    if derived and derived in image_label:
        return True, "derived label is substring of image_label"
    return False, f"mismatch: label={label!r} -> derived={derived!r} vs image_label={image_label!r}"


def _derive_image_label(label: str, fallback_image_label: str = "") -> str:
    """由按钮文案派生图片卡文案：优先 strip emoji，失败时用池子中的 fallback。

    强绑定核心：图片上印的字永远从真实按钮文案派生，而不是两处独立硬编码。
    """
    from core.broadcast_image_card import strip_visual_emoji

    derived = strip_visual_emoji(label)
    if derived:
        return derived
    # 极端场景：label 全是 emoji → 用池子中预写的纯文字兜底
    return strip_visual_emoji(fallback_image_label)


def get_broadcast_cta(
    scene: str,
    period: str = "",
    mode: str = "",
    config: dict = None,
    user_profile: dict = None,
    rng: random.Random = None,
) -> dict:
    """生成统一 CTA 对象。

    返回字段：
        target: 目标类型（preview/subscribe/contact/mini_app/none）
        label: 真实按钮文案（可含 emoji）
        image_label: 图片卡上印的文案（由 label 经 strip_visual_emoji 派生，保证强绑定）
        url: 跳转链接
        mini_app: Mini App 配置 dict（仅 target=mini_app 时）
        style: 彩色按钮样式
        closing: 正文结尾引导语（可选）
    """
    cfg = config or {}
    pool_name = _resolve_pool_name(scene, mode=mode, period=period)
    pool = _CTA_POOLS.get(pool_name, {})

    if rng is None:
        rng = random.Random(_stable_seed(scene, period, mode))

    target = _choose_target(scene, period, cfg, user_profile, rng)
    if target == TARGET_NONE or not pool:
        return {
            "target": TARGET_NONE,
            "label": "",
            "image_label": "",
            "url": "",
            "mini_app": None,
            "style": "default",
            "closing": "",
        }

    choices = pool.get(target, [])
    if not choices:
        # 如果该目标没有文案，回退到 preview
        choices = pool.get(TARGET_PREVIEW, [])
        target = TARGET_PREVIEW
    if not choices:
        return {
            "target": TARGET_NONE,
            "label": "",
            "image_label": "",
            "url": "",
            "mini_app": None,
            "style": "default",
            "closing": "",
        }

    choice = rng.choice(choices)
    label, pool_image_label, closing = choice
    label, _, closing = _personalize_label(label, pool_image_label, closing, user_profile)

    # 强绑定：image_label 由 label 派生，而非独立池子字段（池子里的字段仅作极端情况兜底）
    image_label = _derive_image_label(label, pool_image_label)

    url = _get_url(target, cfg)
    mini_app = None
    if target == TARGET_MINI_APP:
        mini_app = {
            "url": url,
            "short_name": cfg.get("MINI_APP_SHORT_NAME", "Mory"),
        }

    return {
        "target": target,
        "label": label,
        "image_label": image_label,
        "url": url,
        "mini_app": mini_app,
        "style": _STYLE_MAP.get(target, "default"),
        "closing": closing,
    }


def build_cta_markup(cta: dict, config: dict = None):
    """把 CTA 对象转成 telebot.types.InlineKeyboardMarkup。

    当 target == none 或缺少必要字段时返回 None。
    """
    if not isinstance(cta, dict):
        return None
    target = cta.get("target", TARGET_NONE)
    if target == TARGET_NONE:
        return None

    label = cta.get("label") or cta.get("image_label")
    url = cta.get("url", "")
    mini_app = cta.get("mini_app")
    if not label:
        return None

    cfg = config or {}
    button_style_enabled = bool(cfg.get("BUTTON_STYLE_ENABLED", False))

    from telebot import types
    markup = types.InlineKeyboardMarkup(row_width=1)

    if target == TARGET_MINI_APP and mini_app and mini_app.get("url"):
        # Mini App 入口按钮
        try:
            button = types.InlineKeyboardButton(
                text=label,
                web_app=types.WebAppInfo(url=mini_app["url"]),
            )
        except Exception:
            # 旧版本 SDK 没有 web_app，回退 URL 按钮
            button = types.InlineKeyboardButton(text=label, url=url or mini_app["url"])
        markup.add(button)
        return markup

    if button_style_enabled:
        from core.telebot_compat import create_colored_button
        style = cta.get("style", "default")
        button = create_colored_button(text=label, url=url, style=style)
    else:
        button = types.InlineKeyboardButton(text=label, url=url)

    markup.add(button)
    return markup


def build_broadcast_image_cta(
    scene: str,
    period: str = "",
    mode: str = "",
    config: dict = None,
    user_profile: dict = None,
    rng: random.Random = None,
) -> str:
    """只返回图片卡上印的文案（去 emoji，纯视觉）。"""
    cta = get_broadcast_cta(
        scene=scene,
        period=period,
        mode=mode,
        config=config,
        user_profile=user_profile,
        rng=rng,
    )
    from core.broadcast_image_card import strip_visual_emoji
    return strip_visual_emoji(cta.get("image_label", ""))


def is_broadcast_image_enabled(config: dict, section: dict) -> bool:
    """图片卡总闸与分类型分闸的统一判断（全局总闸 AND 类型分闸）。

    section 为各播报类型的配置 dict（需含 image_card_enabled 字段），
    例如 MYSTIC_BROADCAST_CONFIG / GREETING_CONFIG / NEWS_BROADCAST_CONFIG
    / 定点播报单条配置；全局总闸关闭时任何类型都不出图。
    """
    cfg = config or {}
    if not bool(cfg.get("BROADCAST_IMAGE_CARD_ENABLED", False)):
        return False
    section = section or {}
    return bool(section.get("image_card_enabled", False))
