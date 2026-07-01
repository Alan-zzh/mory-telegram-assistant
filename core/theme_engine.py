# -*- coding: utf-8 -*-
"""
播报多样性引擎 v1.0 - 去重 + 主题轮换 + 黑话软植入。

核心能力：
1. 基于日期/时段/星期的种子随机，确保同一天同一时段内容一致
2. 主题池轮换（天气/生活/情感/故事/提问），避免同质化
3. 语气池轮换（清新/慵懒/温暖/神秘），匹配时段情绪
4. 黑话软植入（门槛/至臻/全享/原味/定制），不直白营销
5. 图片关键词暗示（照片/福利/自拍/视频/看图），制造好奇

设计原则：
- 像朋友随口提到，不像推销
- 话说一半留一半，让对方自己脑补
- 禁止"想看更多？""要不要试试？"这种硬广句式
"""

import hashlib
from datetime import datetime, timezone, timedelta

_CST = timezone(timedelta(hours=8))


# ── 主题池（按星期轮换）─────────────────────────────────────────────────────
THEME_POOL = {
    "morning": [
        {"theme": "weather", "desc": "从天气聊起", "keywords": ["阳光", "温度", "风"]},
        {"theme": "life", "desc": "生活碎片", "keywords": ["早餐", "通勤", "日常"]},
        {"theme": "question", "desc": "反问开场", "keywords": ["今天", "计划", "期待"]},
        {"theme": "mood", "desc": "心情分享", "keywords": ["醒来", "状态", "感觉"]},
        {"theme": "story", "desc": "小故事", "keywords": ["刚才", "遇到", "想到"]},
    ],
    "afternoon": [
        {"theme": "detail", "desc": "小细节", "keywords": ["窗台", "咖啡", "光线"]},
        {"theme": "lazy", "desc": "慵懒午后", "keywords": ["犯困", "发呆", "休息"]},
        {"theme": "curious", "desc": "制造好奇", "keywords": ["刚才", "发现", "有趣"]},
        {"theme": "life", "desc": "生活观察", "keywords": ["午饭", "同事", "闲聊"]},
        {"theme": "question", "desc": "提问互动", "keywords": ["你们", "下午", "在忙"]},
    ],
    "evening": [
        {"theme": "story", "desc": "故事感", "keywords": ["今天", "发生", "想起"]},
        {"theme": "emotion", "desc": "走心表达", "keywords": ["辛苦", "感受", "心情"]},
        {"theme": "memory", "desc": "回忆杀", "keywords": ["以前", "记得", "那时候"]},
        {"theme": "observation", "desc": "小观察", "keywords": ["窗外", "天色", "安静"]},
        {"theme": "mood", "desc": "情绪分享", "keywords": ["放松", "疲惫", "满足"]},
    ],
    "night": [
        {"theme": "private", "desc": "私密语气", "keywords": ["被子", "安静", "只有"]},
        {"theme": "atmosphere", "desc": "氛围感", "keywords": ["夜", "灯光", "影子"]},
        {"theme": "emotion", "desc": "深夜情绪", "keywords": ["想你", "睡不着", "心事"]},
        {"theme": "hint", "desc": "暗示引导", "keywords": ["有些", "不太适合", "私聊"]},
        {"theme": "mystery", "desc": "神秘感", "keywords": ["秘密", "隐藏", "专属"]},
    ],
}


# ── 语气池（按时段匹配）─────────────────────────────────────────────────────
TONE_POOL = {
    "morning": {
        "fresh": "清新、期待、轻盈",
        "lazy": "懒懒的、没睡醒、随意",
        "confident": "小自信、状态好、积极",
    },
    "afternoon": {
        "casual": "随意、放松、不强求",
        "curious": "好奇、探索、想聊聊",
        "sleepy": "犯困、慵懒、软软的",
    },
    "evening": {
        "warm": "温暖、走心、共鸣",
        "story": "故事感、沉浸、画面",
        "cool": "高冷、距离、神秘",
    },
    "night": {
        "intimate": "私密、亲近、悄悄话",
        "mysterious": "神秘、暗示、留白",
        "seductive": "诱惑、氛围、画面感",
    },
}


# ── 黑话软植入模板（不直白说价格/购买）─────────────────────────────────────
SLANG_TEMPLATES = {
    "门槛": [
        "有些人已经进来了。",
        "那个坎，过了就知道。",
        "想知道私聊。",
    ],
    "至臻": [
        "那边东西多一点。",
        "完整版在那边。",
        "有些这边不放。",
    ],
    "全享": [
        "年费档什么都有。",
        "全享那边更全。",
        "一次到位的选这个。",
    ],
    "原味": [
        "有些东西...不好说。",
        "穿过的，私聊。",
        "贴身的，懂的都懂。",
    ],
    "定制": [
        "单独的，私聊。",
        "定制只给你一个人。",
        "想拍什么私聊说。",
    ],
}


# ── 图片关键词暗示模板 ──────────────────────────────────────────────────────
PHOTO_HINT_TEMPLATES = {
    "照片": [
        "有些照片这边不放。",
        "刚拍了点东西。",
        "照片在那边。",
    ],
    "福利": [
        "今天有更新。",
        "新的，私聊。",
        "有些东西只发给主动的人。",
    ],
    "自拍": [
        "拍了几张。",
        "新自拍在那边。",
        "有些不适合发群里。",
    ],
    "视频": [
        "录了点东西。",
        "视频这边不发。",
        "想看私聊。",
    ],
    "看图": [
        "图在那边。",
        "想看图来找我。",
        "图不发群里。",
    ],
}


# ── 转化引导模板（底部折叠区/按钮）─────────────────────────────────────────
CONVERSION_TEMPLATES = [
    "有些事私聊说更方便。",
    "来 @MorychannelBot 找我聊。",
    "那边有更多内容。",
    "主动的人先看到。",
    "群里不方便说。",
    "有事私聊。",
    "找我。",
    "那边自己看。",
    "想知道私聊。",
    "来了就知道。",
]


def _get_seed(date: datetime, period: str, item_id: str = "") -> str:
    """生成确定性种子，同一天同一时段内容一致。"""
    date_str = date.strftime("%Y-%m-%d")
    raw = f"{item_id}|{period}|{date_str}"
    return hashlib.md5(raw.encode()).hexdigest()


def _seeded_random(seed: str):
    """基于种子的伪随机数生成器。"""
    import random
    seed_int = int(seed[:8], 16)
    return random.Random(seed_int)


def get_daily_theme(period: str, date: datetime = None, item_id: str = "") -> dict:
    """
    获取当天的主题。

    返回：{"theme": "weather", "desc": "从天气聊起", "keywords": ["阳光", "温度", "风"]}
    """
    if date is None:
        date = datetime.now(_CST)

    seed = _get_seed(date, period, item_id)
    rng = _seeded_random(seed)

    pool = THEME_POOL.get(period, THEME_POOL["morning"])
    return rng.choice(pool)


def get_daily_tone(period: str, date: datetime = None, item_id: str = "") -> dict:
    """
    获取当天的语气。

    返回：{"fresh": "清新、期待、轻盈"}
    """
    if date is None:
        date = datetime.now(_CST)

    seed = _get_seed(date, period, item_id)
    rng = _seeded_random(seed)

    pool = TONE_POOL.get(period, TONE_POOL["morning"])
    tone_keys = list(pool.keys())
    tone_key = rng.choice(tone_keys)
    return {tone_key: pool[tone_key]}


def get_slang_hint(slang_key: str, date: datetime = None, item_id: str = "") -> str:
    """
    获取黑话软植入句子。

    slang_key: 门槛/至臻/全享/原味/定制
    """
    if date is None:
        date = datetime.now(_CST)

    if slang_key not in SLANG_TEMPLATES:
        return ""

    seed = _get_seed(date, "slang", item_id + slang_key)
    rng = _seeded_random(seed)

    templates = SLANG_TEMPLATES[slang_key]
    return rng.choice(templates)


def get_photo_hint(photo_keyword: str, date: datetime = None, item_id: str = "") -> str:
    """
    获取图片关键词暗示句子。

    photo_keyword: 照片/福利/自拍/视频/看图
    """
    if date is None:
        date = datetime.now(_CST)

    if photo_keyword not in PHOTO_HINT_TEMPLATES:
        return ""

    seed = _get_seed(date, "photo", item_id + photo_keyword)
    rng = _seeded_random(seed)

    templates = PHOTO_HINT_TEMPLATES[photo_keyword]
    return rng.choice(templates)


def get_conversion_hint(date: datetime = None, item_id: str = "") -> str:
    """获取转化引导句子（用于底部折叠区）。"""
    if date is None:
        date = datetime.now(_CST)

    seed = _get_seed(date, "conversion", item_id)
    rng = _seeded_random(seed)

    return rng.choice(CONVERSION_TEMPLATES)


def build_broadcast_context(period: str, date: datetime = None, item_id: str = "") -> dict:
    """
    构建播报上下文（主题+语气+黑话+图片暗示+转化引导）。

    返回：
    {
        "theme": {...},
        "tone": {...},
        "slang_hint": "...",
        "photo_hint": "...",
        "conversion_hint": "...",
    }
    """
    if date is None:
        date = datetime.now(_CST)

    theme = get_daily_theme(period, date, item_id)
    tone = get_daily_tone(period, date, item_id)

    slang_keys = list(SLANG_TEMPLATES.keys())
    photo_keys = list(PHOTO_HINT_TEMPLATES.keys())

    seed = _get_seed(date, period, item_id)
    rng = _seeded_random(seed)

    if period in ("morning", "afternoon"):
        slang_key = rng.choice(["门槛", "至臻"])
        photo_key = rng.choice(["照片", "福利"])
    else:
        slang_key = rng.choice(["全享", "原味", "定制"])
        photo_key = rng.choice(["自拍", "视频", "看图"])

    return {
        "theme": theme,
        "tone": tone,
        "slang_hint": get_slang_hint(slang_key, date, item_id),
        "photo_hint": get_photo_hint(photo_key, date, item_id),
        "conversion_hint": get_conversion_hint(date, item_id),
    }
