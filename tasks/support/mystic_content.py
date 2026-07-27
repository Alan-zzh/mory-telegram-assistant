"""风水、塔罗与能量签的确定性内容生成器。

内容按北京时间日期与时段稳定抽取：同一天重试不会换牌，隔天会自然变化。
所有文案按群公共栏目口吻输出，只作轻松娱乐，不制造确定性预测，
不对群友作心理判断，也不携带销售入口。
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any


_CST = timezone(timedelta(hours=8))

MYSTIC_MODES = {"feng_shui", "tarot", "fortune", "random"}
MYSTIC_NOTE = "每日随机参考，仅供娱乐，祝大家顺顺利利。"

_PERIOD_DEFAULT_MODES = {
    "morning": "feng_shui",
    "afternoon": "tarot",
    "evening": "fortune",
}

_DIRECTIONS = ["东方", "东南", "南方", "西南", "西方", "西北", "北方", "东北"]
_COLORS = ["雾霾蓝", "米白", "青绿色", "浅金", "灰紫", "暖橙", "墨绿", "银灰"]
_FENG_SHUI_YI = [
    "开窗通风、保持入口整洁",
    "清理桌面、先做已有安排",
    "补充光线、整理常用区域",
    "让通道保持顺畅、减少杂物堆放",
    "先收尾，再开启新事项",
    "调整座位周边、保持视线清爽",
]
_FENG_SHUI_JI = [
    "门口和通道堆放杂物",
    "一早频繁挪动大件",
    "同时开启太多新安排",
    "光线昏暗、桌面过度拥挤",
    "临时反复改变顺序",
    "把常用物品放得太远",
]

_TAROT_CARDS = {
    "魔术师": ("行动、资源、沟通", "推进已有计划、整合现有资源", "摊子铺得太大、承诺过满"),
    "女祭司": ("观察、信息、耐心", "核对信息、留出观察时间", "凭第一印象仓促判断"),
    "皇后": ("生长、照顾、审美", "改善环境、推进创作", "只顾速度、忽略体验"),
    "皇帝": ("秩序、边界、执行", "明确规则、整理优先级", "安排过满、要求过硬"),
    "恋人": ("选择、协作、共识", "沟通分工、确认共同目标", "一味迎合、含糊表态"),
    "战车": ("方向、推进、专注", "集中处理主线事项", "多线拉扯、频繁改方向"),
    "力量": ("稳定、耐心、分寸", "稳步处理、保持节奏", "硬碰硬、急于见结果"),
    "隐士": ("复盘、筛选、沉淀", "整理资料、减少干扰", "封闭信息、拖延沟通"),
    "命运之轮": ("变化、机会、调整", "顺势调整、保留弹性", "把临时变化当成定局"),
    "正义": ("事实、规则、平衡", "核对细节、按规则推进", "只凭印象、忽略依据"),
    "节制": ("协调、适量、磨合", "微调方案、协调节奏", "一次改动过多"),
    "太阳": ("清晰、活力、公开", "直接沟通、推进合作", "信息藏得太深"),
}

_FORTUNE_THEMES = ["留白", "边界", "专注", "表达", "收尾", "松弛", "选择", "整理"]
_EVENING_YI = [
    "收尾、整理、早点休息",
    "核对明日安排、减少临时事项",
    "放下屏幕、给房间通风",
    "整理桌角、准备明日用品",
    "完成一件小事后及时停下",
    "简单散步、降低夜间节奏",
]
_EVENING_JI = [
    "临睡前开启复杂任务",
    "反复刷新消息、打乱休息",
    "一次安排太多明日事项",
    "把未完成事项全部留到深夜",
    "临时做重要决定",
    "继续堆积桌面和床边杂物",
]
_TOMORROW_PREP = [
    "写下明早第一件事即可",
    "把常用物品放到顺手位置",
    "确认一次闹钟和出门时间",
    "准备好水杯与随身物品",
    "清出一小块可用桌面",
    "列出一项最优先安排",
]

_FORBIDDEN_VISIBLE_MARKERS = (
    "新闻",
    "热搜",
    "据报道",
    "最新消息",
    "http://",
    "https://",
    "@moryselect",
    "@morychannelbot",
    "下单",
    "购买",
    "订阅",
    "私聊",
    "给你的",
    "交给你",
    "自己",
    "内心",
    "情绪",
    "真正的选择",
    "自责",
)


def _stable_rng(date_key: str, period: str, mode: str) -> random.Random:
    raw = f"{date_key}|{period}|{mode}|mory-mystic-v1".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(seed)


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(_CST)
    if now.tzinfo is None:
        return now.replace(tzinfo=_CST)
    return now.astimezone(_CST)


def resolve_mystic_mode(config: dict[str, Any], period: str, now: datetime | None = None) -> str:
    """解析时段栏目；random 也按日期稳定抽取。"""
    cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    default_mode = _PERIOD_DEFAULT_MODES.get(period, "fortune")
    mode = str(cfg.get(f"{period}_mode", default_mode) or default_mode).strip().lower()
    if mode not in MYSTIC_MODES:
        mode = default_mode
    if mode == "random":
        date_key = _normalize_now(now).strftime("%Y-%m-%d")
        mode = _stable_rng(date_key, period, "random").choice(["feng_shui", "tarot", "fortune"])
    return mode


def _build_feng_shui(rng: random.Random) -> dict[str, Any]:
    return {
        "mode": "feng_shui",
        "emoji": "🧭",
        "title": "今日风水播报",
        "sections": [
            ("今日宜", rng.choice(_FENG_SHUI_YI)),
            ("今日忌", rng.choice(_FENG_SHUI_JI)),
            ("参考方位", rng.choice(_DIRECTIONS)),
            ("参考色", rng.choice(_COLORS)),
        ],
    }


def _build_tarot(rng: random.Random) -> dict[str, Any]:
    card = rng.choice(list(_TAROT_CARDS))
    position = rng.choice(["正位", "逆位"])
    keywords, suitable, avoid = _TAROT_CARDS[card]
    return {
        "mode": "tarot",
        "emoji": "🔮",
        "title": "今日塔罗播报",
        "sections": [
            ("今日牌面", f"{card} · {position}"),
            ("关键词", keywords),
            ("适合", suitable),
            ("避免", avoid),
        ],
    }


def _build_fortune(rng: random.Random) -> dict[str, Any]:
    return {
        "mode": "fortune",
        "emoji": "🌙",
        "title": "晚间宜忌播报",
        "sections": [
            ("今晚主题", rng.choice(_FORTUNE_THEMES)),
            ("适合", rng.choice(_EVENING_YI)),
            ("避免", rng.choice(_EVENING_JI)),
            ("明日准备", rng.choice(_TOMORROW_PREP)),
        ],
    }


def build_mystic_broadcast(
    config: dict[str, Any],
    period: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """生成一个可直接交给排版器的栏目 payload。"""
    current = _normalize_now(now)
    date_key = current.strftime("%Y-%m-%d")
    mode = resolve_mystic_mode(config, period, current)
    rng = _stable_rng(date_key, period, mode)
    if mode == "feng_shui":
        payload = _build_feng_shui(rng)
    elif mode == "tarot":
        payload = _build_tarot(rng)
    else:
        payload = _build_fortune(rng)
    payload.update({
        "period": period,
        "date": date_key,
        "note": MYSTIC_NOTE,
    })
    return payload


def is_usable_mystic_broadcast(payload: object) -> bool:
    """确定性输出门禁：群公共口吻、结构完整、无新闻与销售入口。"""
    if not isinstance(payload, dict):
        return False
    if payload.get("mode") not in {"feng_shui", "tarot", "fortune"}:
        return False
    if payload.get("note") != MYSTIC_NOTE:
        return False
    sections = payload.get("sections")
    if not isinstance(sections, list) or len(sections) != 4:
        return False
    visible = " ".join(
        [str(payload.get("title", ""))]
        + [f"{label} {value}" for label, value in sections]
        + [str(payload.get("note", ""))]
    ).lower()
    return not any(marker in visible for marker in _FORBIDDEN_VISIBLE_MARKERS)
