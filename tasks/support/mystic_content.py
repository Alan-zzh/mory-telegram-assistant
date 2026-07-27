"""风水、塔罗与能量签的确定性内容生成器。

内容按北京时间日期与时段稳定抽取：同一天重试不会换牌，隔天会自然变化。
所有文案只作轻松娱乐，不制造确定性预测，也不携带销售入口。
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any


_CST = timezone(timedelta(hours=8))

MYSTIC_MODES = {"feng_shui", "tarot", "fortune", "random"}
MYSTIC_NOTE = "只当一张轻松小签看，真正的选择还是交给你。"

_PERIOD_DEFAULT_MODES = {
    "morning": "feng_shui",
    "afternoon": "tarot",
    "evening": "fortune",
}

_DIRECTIONS = ["东方", "东南", "南方", "西南", "西方", "西北", "北方", "东北"]
_COLORS = ["雾霾蓝", "米白", "青绿色", "浅金", "灰紫", "暖橙", "墨绿", "银灰"]
_SPACE_ACTIONS = [
    "把桌面最显眼的一小块清空，视线先松下来。",
    "给门口留一点空位，进出时别让杂物挡住脚步。",
    "拉开窗帘透透光，再把手边最乱的一处收好。",
    "换一杯干净的水放在手边，让空间有一点流动感。",
    "把不用的线材和小物收起来，给注意力留点余地。",
    "挪开挡住通道的小东西，今天让行动更利落一点。",
    "给常坐的位置添一点柔和颜色，不必买新东西。",
    "擦干净常看的镜面或屏幕，先把眼前的杂乱降下来。",
]
_FENG_SHUI_INTENTIONS = [
    "宜先完成一件小事，再开启新的安排。",
    "宜少一点催促，多一点清楚的边界。",
    "宜把最重要的东西放在顺手的位置。",
    "宜慢半拍做决定，先看清自己真正想要什么。",
    "宜收尾，不必同时开启太多新的事情。",
    "宜主动表达，但别替别人预设答案。",
    "宜留白，今天不需要把每分钟都塞满。",
    "宜把注意力放回自己能控制的部分。",
]

_TAROT_REFLECTIONS = {
    "愚者": "新的念头正在冒头，先允许好奇心存在，不急着证明它。",
    "魔术师": "你手上的资源比想象中多，关键是先动用最顺手的那一个。",
    "女祭司": "答案未必需要立刻说出口，安静观察也算一种推进。",
    "皇后": "照顾好感受和节奏，柔软并不等于没有力量。",
    "皇帝": "今天适合把边界说清楚，稳定来自可执行的规则。",
    "教皇": "旧经验仍有价值，但也可以问问自己是否还认同它。",
    "恋人": "真正重要的不是选得完美，而是选择与你的价值一致。",
    "战车": "方向明确后就少一点犹豫，把力气放在向前而不是拉扯。",
    "力量": "温和地掌控情绪，比压住情绪更有用。",
    "隐士": "暂时退开一点，可能更容易看见真正的问题。",
    "命运之轮": "变化已经出现，不必急着把它定义成好或坏。",
    "正义": "把事实和感受分开看，答案会更清楚。",
    "倒吊人": "换个角度并不代表妥协，只是给自己多一个选择。",
    "死神": "有些结束是在腾位置，不必勉强维持已经失效的东西。",
    "节制": "今天更适合调和与微调，不需要一次走到极端。",
    "恶魔": "留意那些明知消耗却舍不得放下的习惯。",
    "塔": "原有判断被打乱时，先确认什么仍然真实可靠。",
    "星星": "愿望可以保留，但下一步最好小到今天就能开始。",
    "月亮": "情绪会放大猜测，今晚适合多核实、少脑补。",
    "太阳": "坦率和清晰会让事情简单很多，别把好意藏得太深。",
    "审判": "过去的经验正在提醒你：这次可以做出不同回应。",
    "世界": "一个阶段接近完整，先承认自己的进展再继续赶路。",
}
_TAROT_QUESTIONS = [
    "如果不考虑别人期待，你现在最想保留什么？",
    "这件事里，哪一部分是真实事实，哪一部分只是猜测？",
    "你今天能完成的最小一步是什么？",
    "有什么已经不适合你，却还在勉强维持？",
    "如果允许自己慢一点，答案会不会更清楚？",
    "你真正需要的是结果、确认，还是一个明确边界？",
]
_TAROT_ACTIONS = [
    "写下一句最诚实的答案，不用发给任何人。",
    "先完成一件十分钟内能收尾的小事。",
    "把犹豫拆成两个选项，各写一个代价。",
    "今晚少做一次无根据的猜测，多问一个具体问题。",
    "给自己留二十分钟不被消息打断的时间。",
    "把已经做到的部分记下来，别只盯着还没完成的。",
]

_FORTUNE_THEMES = ["留白", "边界", "专注", "表达", "收尾", "松弛", "选择", "整理"]
_FORTUNE_LINES = [
    "今天不必把所有问题都解决，先让一个答案变清楚。",
    "真正消耗你的可能不是事情本身，而是反复预演。",
    "该说明白的就说明白，含糊不会自动变成体贴。",
    "有些停顿不是退步，是在把力气重新放回自己身上。",
    "能安稳收尾的一天，也比仓促开启很多事更有分量。",
    "不用急着回应所有声音，先听见自己那一句。",
    "把复杂的事缩小一点，今晚只处理最具体的部分。",
    "允许事情暂时没有结论，也是一种清醒。",
]
_EVENING_ACTIONS = [
    "睡前把明天第一件事写下来，然后停止继续安排。",
    "收起一件让你分心的东西，给夜晚留一点安静。",
    "把没说出口的话写成草稿，明天再决定要不要发。",
    "关掉一个不必要的提醒，让注意力真正下线。",
    "整理床边或桌角的一小块地方，今天就到这里。",
    "给今天找一个已经完成的句号，不再追加自责。",
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
        "title": "今日风水小签",
        "sections": [
            ("今日方位", rng.choice(_DIRECTIONS)),
            ("气场色", rng.choice(_COLORS)),
            ("空间动作", rng.choice(_SPACE_ACTIONS)),
            ("今日宜", rng.choice(_FENG_SHUI_INTENTIONS)),
        ],
    }


def _build_tarot(rng: random.Random) -> dict[str, Any]:
    card = rng.choice(list(_TAROT_REFLECTIONS))
    position = rng.choice(["正位", "逆位"])
    return {
        "mode": "tarot",
        "emoji": "🔮",
        "title": "今日塔罗牌",
        "sections": [
            ("今日牌面", f"{card} · {position}"),
            ("牌意", _TAROT_REFLECTIONS[card]),
            ("给你的问题", rng.choice(_TAROT_QUESTIONS)),
            ("今日动作", rng.choice(_TAROT_ACTIONS)),
        ],
    }


def _build_fortune(rng: random.Random) -> dict[str, Any]:
    return {
        "mode": "fortune",
        "emoji": "🌙",
        "title": "晚间能量签",
        "sections": [
            ("今晚主题", rng.choice(_FORTUNE_THEMES)),
            ("签面", rng.choice(_FORTUNE_LINES)),
            ("收尾动作", rng.choice(_EVENING_ACTIONS)),
            ("留一句", "今天已经走到这里，剩下的可以明天再说。"),
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
    """确定性输出门禁：结构完整、无新闻残留、无销售入口。"""
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
