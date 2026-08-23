# -*- coding: utf-8 -*-
"""
播报主题词池（v5.41.0 自 theme_engine.py 改名：本模块只提供 THEME_POOL /
TONE_POOL 两组 prompt 词池与轮换逻辑，不承载引擎调度）。

重构说明（用户反馈"再加的东西特别尬"、"记流水账一样没有实际"）：
- 移除 SLANG_TEMPLATES / PHOTO_HINT_TEMPLATES / CONVERSION_TEMPLATES
  这三类硬塞话术（"有些人已经进来了"/"想看私聊"/"来了就知道"等）
  与正文割裂、价值低、像生硬营销，是用户吐槽的"尬"内容源头。
- 保留 THEME_POOL / TONE_POOL：仅作为 AI 生成时的 prompt 上下文，
  让 AI 知道"今天聊天气/生活/情感"，避免 AI 自由发挥跑偏。
- build_broadcast_context 不再返回 slang_hint / photo_hint / conversion_hint，
  下游 scheduled_broadcast.py 的 .get() 检查会自动跳过，无破坏性变更。

核心能力：
1. 基于日期/时段/星期的种子随机，确保同一天同一时段内容一致
2. 主题池轮换（天气/生活/情感/故事/提问），避免同质化
3. 语气池轮换（清新/慵懒/温暖/神秘），匹配时段情绪
"""

import hashlib
from datetime import datetime, timezone, timedelta

_CST = timezone(timedelta(hours=8))


# ── 主题池（按星期轮换，仅用于 AI prompt 上下文）─────────────────────────────
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


# ── 语气池（按时段匹配，仅用于 AI prompt 上下文）─────────────────────────────
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


# [v5.32] 已移除：SLANG_TEMPLATES / PHOTO_HINT_TEMPLATES / CONVERSION_TEMPLATES
# 这些模板硬塞"想知道私聊"/"有些照片这边不放"/"来了就知道"等话术到 footer，
# 与正文割裂、像生硬营销，是用户反馈"再加的东西特别尬"的源头。
# 对应的 getter 函数 get_slang_hint / get_photo_hint / get_conversion_hint 也一并移除。


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
    """[v5.32] 已弃用，始终返回空串。保留函数签名避免调用方报错。"""
    return ""


def get_photo_hint(photo_keyword: str, date: datetime = None, item_id: str = "") -> str:
    """[v5.32] 已弃用，始终返回空串。保留函数签名避免调用方报错。"""
    return ""


def get_conversion_hint(date: datetime = None, item_id: str = "") -> str:
    """[v5.32] 已弃用，始终返回空串。保留函数签名避免调用方报错。"""
    return ""


def build_broadcast_context(period: str, date: datetime = None, item_id: str = "") -> dict:
    """
    构建播报上下文（仅主题+语气，[v5.32] 移除 slang/photo/conversion hint）。

    返回：
    {
        "theme": {"theme": "weather", "desc": "...", "keywords": [...]},
        "tone": {"fresh": "清新、期待、轻盈"},
        # 以下字段保留键但值为空串，确保下游 .get() 检查不报错
        "slang_hint": "",
        "photo_hint": "",
        "conversion_hint": "",
    }
    """
    if date is None:
        date = datetime.now(_CST)

    theme = get_daily_theme(period, date, item_id)
    tone = get_daily_tone(period, date, item_id)

    return {
        "theme": theme,
        "tone": tone,
        "slang_hint": "",
        "photo_hint": "",
        "conversion_hint": "",
    }
