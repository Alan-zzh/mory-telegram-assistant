"""三时段传统文化栏目的确定性内容引擎。

早间使用 cnlunar 计算真实农历与黄历字段；午间使用策展后的大阿卡纳
三张牌阵；晚间按六十四卦与动爻生成本卦、之卦。日期相同的重试保持
一致，跨日自然变化。所有内容只作传统文化与娱乐参考。
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any


_CST = timezone(timedelta(hours=8))

MYSTIC_MODES = {"almanac", "tarot", "iching"}
MYSTIC_MODE_BY_PERIOD = {
    "morning": "almanac",
    "afternoon": "tarot",
    "evening": "iching",
}

_FORBIDDEN_VISIBLE_MARKERS = (
    "新闻",
    "热搜",
    "据报道",
    "最新消息",
    "http://",
    "https://",
    "@moryselect",
    "@morychannelbot",
    "@moryfansbot",
)

_HOUR_NAMES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
_HOUR_STARTS = [23, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21]

_THING_ALIASES = {
    "结婚姻": "嫁娶",
    "宴会": "聚会宴请",
    "修造": "动土装修",
    "营建": "动土营建",
    "修宫室": "动土修造",
    "修仓库": "修缮仓储",
    "开市": "开业开市",
    "纳财": "纳财收款",
    "立券交易": "签约交易",
    "求医疗病": "求医问诊",
    "移徙": "搬迁",
    "进人口": "迎接新成员",
}
_THING_PRIORITY = (
    "出行",
    "动土装修",
    "动土营建",
    "搬迁",
    "入宅",
    "嫁娶",
    "开业开市",
    "签约交易",
    "纳财收款",
    "安床",
    "求医问诊",
    "祈福",
    "聚会宴请",
)

_TAROT_CARDS = (
    ("0", "愚者", "风", ("启程", "自由", "可能性"), ("冒进", "分心", "准备不足")),
    ("I", "魔术师", "风", ("行动", "资源", "表达"), ("分散", "失焦", "承诺过满")),
    ("II", "女祭司", "水", ("直觉", "观察", "信息"), ("迟疑", "封闭", "信息不全")),
    ("III", "皇后", "土", ("生长", "照顾", "创造"), ("消耗", "依赖", "节奏失衡")),
    ("IV", "皇帝", "火", ("秩序", "边界", "执行"), ("僵化", "控制", "压力过重")),
    ("V", "教皇", "土", ("传统", "学习", "方法"), ("教条", "盲从", "需要验证")),
    ("VI", "恋人", "风", ("选择", "关系", "共识"), ("摇摆", "失衡", "价值冲突")),
    ("VII", "战车", "水", ("方向", "推进", "专注"), ("拉扯", "急进", "方向偏移")),
    ("VIII", "力量", "火", ("勇气", "耐心", "分寸"), ("逞强", "内耗", "耐心不足")),
    ("IX", "隐士", "土", ("复盘", "筛选", "沉淀"), ("封闭", "拖延", "过度独处")),
    ("X", "命运之轮", "火", ("变化", "周期", "机会"), ("反复", "失控", "时机未稳")),
    ("XI", "正义", "风", ("事实", "规则", "平衡"), ("偏见", "失衡", "依据不足")),
    ("XII", "倒吊人", "水", ("换位", "暂停", "新视角"), ("停滞", "牺牲过度", "迟迟不动")),
    ("XIII", "死神", "水", ("结束", "转化", "清理"), ("抗拒", "拖延告别", "旧事反复")),
    ("XIV", "节制", "火", ("协调", "适量", "磨合"), ("过量", "急躁", "配合失衡")),
    ("XV", "恶魔", "土", ("欲望", "束缚", "执念"), ("松绑", "看清代价", "重新选择")),
    ("XVI", "高塔", "火", ("突变", "真相", "重建"), ("余震", "回避变化", "基础不稳")),
    ("XVII", "星星", "风", ("希望", "修复", "愿景"), ("失望", "分心", "目标模糊")),
    ("XVIII", "月亮", "水", ("潜意识", "想象", "迷雾"), ("核实", "看清", "减少猜测")),
    ("XIX", "太阳", "火", ("清晰", "活力", "公开"), ("过热", "自满", "忽略细节")),
    ("XX", "审判", "火", ("回顾", "回应", "更新"), ("迟疑", "自我怀疑", "旧账未清")),
    ("XXI", "世界", "土", ("完成", "整合", "新阶段"), ("收尾未尽", "循环未合", "仍需补足")),
)

_TAROT_ACTIONS = (
    "主牌先看方向，助力牌看可用资源，提醒牌只负责指出盲区。",
    "适合先处理已经有基础的事，再决定要不要开启新线。",
    "今天的牌阵更重视信息核对；直觉可以听，结论要慢一点下。",
    "先写下最在意的一个问题，再看三张牌分别提醒了什么。",
    "若三张牌的信息互相拉扯，先看主牌，再用提醒牌做风险检查。",
    "牌面只是参考坐标，真要动手前，还是先把现实条件摆清楚。",
    "今天的节奏更适合稳步推进，不必为了赶进度把提醒项略过。",
    "把三张牌当成一次梳理：方向、资源、盲区各归各位再行动。",
    "提醒牌不是否定，只是把容易忽略的地方先摆在台面上。",
    "牌阵给的是观察角度，落地与否还是看你手里的实际筹码。",
)

_TRIGRAM_LINES = {
    "乾": (1, 1, 1),
    "兑": (1, 1, 0),
    "离": (1, 0, 1),
    "震": (1, 0, 0),
    "巽": (0, 1, 1),
    "坎": (0, 1, 0),
    "艮": (0, 0, 1),
    "坤": (0, 0, 0),
}

# 序号、卦名、全名、观察关键词、上卦、下卦（文辞为公共领域传统名称）。
_HEXAGRAMS = (
    (1, "乾", "乾为天", "开创与自强", "乾", "乾"),
    (2, "坤", "坤为地", "承载与顺势", "坤", "坤"),
    (3, "屯", "水雷屯", "起步维艰", "坎", "震"),
    (4, "蒙", "山水蒙", "启蒙与求知", "艮", "坎"),
    (5, "需", "水天需", "等待时机", "坎", "乾"),
    (6, "讼", "天水讼", "分歧与规则", "乾", "坎"),
    (7, "师", "地水师", "组织与纪律", "坤", "坎"),
    (8, "比", "水地比", "亲近与协作", "坎", "坤"),
    (9, "小畜", "风天小畜", "积累与蓄势", "巽", "乾"),
    (10, "履", "天泽履", "谨慎前行", "乾", "兑"),
    (11, "泰", "地天泰", "通达与交流", "坤", "乾"),
    (12, "否", "天地否", "闭塞与调整", "乾", "坤"),
    (13, "同人", "天火同人", "同道与合作", "乾", "离"),
    (14, "大有", "火天大有", "丰盛与责任", "离", "乾"),
    (15, "谦", "地山谦", "谦逊与留余", "坤", "艮"),
    (16, "豫", "雷地豫", "准备与愉悦", "震", "坤"),
    (17, "随", "泽雷随", "顺应与跟随", "兑", "震"),
    (18, "蛊", "山风蛊", "整顿与修复", "艮", "巽"),
    (19, "临", "地泽临", "接近与带领", "坤", "兑"),
    (20, "观", "风地观", "观察与示范", "巽", "坤"),
    (21, "噬嗑", "火雷噬嗑", "决断与清障", "离", "震"),
    (22, "贲", "山火贲", "修饰与本质", "艮", "离"),
    (23, "剥", "山地剥", "剥落与止损", "艮", "坤"),
    (24, "复", "地雷复", "回归与复苏", "坤", "震"),
    (25, "无妄", "天雷无妄", "真诚与守正", "乾", "震"),
    (26, "大畜", "山天大畜", "蓄力与学习", "艮", "乾"),
    (27, "颐", "山雷颐", "滋养与言语", "艮", "震"),
    (28, "大过", "泽风大过", "承压与非常", "兑", "巽"),
    (29, "坎", "坎为水", "险阻与韧性", "坎", "坎"),
    (30, "离", "离为火", "清明与依附", "离", "离"),
    (31, "咸", "泽山咸", "感应与互动", "兑", "艮"),
    (32, "恒", "雷风恒", "持续与常道", "震", "巽"),
    (33, "遁", "天山遁", "退让与保存", "乾", "艮"),
    (34, "大壮", "雷天大壮", "力量与克制", "震", "乾"),
    (35, "晋", "火地晋", "前进与显现", "离", "坤"),
    (36, "明夷", "地火明夷", "藏光与保护", "坤", "离"),
    (37, "家人", "风火家人", "秩序与分工", "巽", "离"),
    (38, "睽", "火泽睽", "差异与求同", "离", "兑"),
    (39, "蹇", "水山蹇", "困难与绕行", "坎", "艮"),
    (40, "解", "雷水解", "释放与化解", "震", "坎"),
    (41, "损", "山泽损", "取舍与节制", "艮", "兑"),
    (42, "益", "风雷益", "增益与分享", "巽", "震"),
    (43, "夬", "泽天夬", "决断与公开", "兑", "乾"),
    (44, "姤", "天风姤", "相遇与警觉", "乾", "巽"),
    (45, "萃", "泽地萃", "汇聚与共识", "兑", "坤"),
    (46, "升", "地风升", "渐进与成长", "坤", "巽"),
    (47, "困", "泽水困", "受限与守志", "兑", "坎"),
    (48, "井", "水风井", "资源与更新", "坎", "巽"),
    (49, "革", "泽火革", "变革与时机", "兑", "离"),
    (50, "鼎", "火风鼎", "更新与成器", "离", "巽"),
    (51, "震", "震为雷", "震动与行动", "震", "震"),
    (52, "艮", "艮为山", "停止与界限", "艮", "艮"),
    (53, "渐", "风山渐", "循序与积累", "巽", "艮"),
    (54, "归妹", "雷泽归妹", "关系与位置", "震", "兑"),
    (55, "丰", "雷火丰", "丰盛与高峰", "震", "离"),
    (56, "旅", "火山旅", "旅途与适应", "离", "艮"),
    (57, "巽", "巽为风", "渗透与柔顺", "巽", "巽"),
    (58, "兑", "兑为泽", "交流与喜悦", "兑", "兑"),
    (59, "涣", "风水涣", "疏散与重聚", "巽", "坎"),
    (60, "节", "水泽节", "节度与边界", "坎", "兑"),
    (61, "中孚", "风泽中孚", "诚信与感通", "巽", "兑"),
    (62, "小过", "雷山小过", "小步与谨慎", "震", "艮"),
    (63, "既济", "水火既济", "完成与防松", "坎", "离"),
    (64, "未济", "火水未济", "未完与续行", "离", "坎"),
)

_ICHING_QUESTIONS = (
    "眼下最需要先稳定的，是方向、关系，还是节奏？",
    "如果只改变一个环节，哪一处最可能带动后续变化？",
    "这件事应当继续推进，还是先补足条件再动？",
    "当前看到的是结果，还是过程中的一次转折？",
    "哪些是可以主动调整的，哪些更适合顺势观察？",
    "今晚最值得先放下的，是哪一个没必要的负担？",
    "若把期待降一格，第一步会不会更好走？",
    "现在缺的是信息，还是下决心的时机？",
)

_PRIVATE_COMMAND_MODES = {
    "/fengshui": "almanac",
    "/风水": "almanac",
    "/tarot": "tarot",
    "/塔罗": "tarot",
    "/iching": "iching",
    "/易经": "iching",
    "/算卦": "iching",
}
_PRIVATE_MODE_KEYWORDS = {
    "tarot": ("塔罗", "抽牌"),
    "iching": ("算卦", "起卦", "卜卦", "易经", "卦象"),
    "almanac": ("风水", "方位", "财位"),
}
_PRIVATE_REQUEST_MARKERS = (
    "帮我",
    "给我",
    "替我",
    "想",
    "要",
    "来一个",
    "来一",
    "看看",
    "看一下",
    "算一下",
    "测一下",
    "抽一下",
    "抽个",
    "抽一",
    "起一",
    "问一",
)


def _stable_rng(date_key: str, period: str, mode: str) -> random.Random:
    raw = f"{date_key}|{period}|{mode}|mory-mystic-v3".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(seed)


def _insight_rng(date_key: str, period: str, mode: str) -> random.Random:
    """点评文案独立随机源：与牌面/卦象流完全隔离。

    扩容文案池或调整句式不会影响牌面的日期稳定序列（卡面声明了
    按日期稳定起卦）；同一天点评仍保持一致，跨日自然轮换。
    """
    raw = f"{date_key}|{period}|{mode}|mory-insight-v1".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(seed)


def resolve_private_mystic_mode(text: str) -> str | None:
    """只识别明确的私聊占卜请求，普通话题讨论继续走正常聊天。"""
    raw = str(text or "").strip().lower()
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None
    command = raw.split(None, 1)[0].split("@", 1)[0].rstrip("：:?!？")
    if command in _PRIVATE_COMMAND_MODES:
        return _PRIVATE_COMMAND_MODES[command]

    for mode, keywords in _PRIVATE_MODE_KEYWORDS.items():
        matched = next((keyword for keyword in keywords if keyword in compact), "")
        if not matched:
            continue
        if compact in keywords or len(compact) <= len(matched) + 2:
            return mode
        if any(marker in compact for marker in _PRIVATE_REQUEST_MARKERS):
            return mode
    return None


def _private_theme_key(text: str, mode: str) -> str:
    """抽取主题，让同一用户同日同主题稳定，不同主题可重新起盘。"""
    value = re.sub(r"[/@_\-\s，。！？?、：:]", "", str(text or "").lower())
    for keyword in _PRIVATE_MODE_KEYWORDS.get(mode, ()):
        value = value.replace(keyword, "")
    for marker in _PRIVATE_REQUEST_MARKERS:
        value = value.replace(marker, "")
    value = value.replace("我", "").replace("的", "").replace("一下", "")
    return value[:32] or "daily"


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(_CST)
    if now.tzinfo is None:
        return now.replace(tzinfo=_CST)
    return now.astimezone(_CST)


def _extract_almanac_hours(lunar: Any) -> list[tuple[str, int, str]]:
    """从 cnlunar 提取今日十二时辰吉凶，返回 [(名称, 起始时, 吉凶), ...]。"""
    try:
        lucky_list = lunar.get_twohourLuckyList()
    except Exception:
        lucky_list = []
    if not lucky_list:
        return []
    # cnlunar 返回 13 项（子…亥 + 下一个子），取前 12 项对应十二时辰
    lucky_list = lucky_list[:12]
    return [
        (name, start, str(luck))
        for name, start, luck in zip(_HOUR_NAMES, _HOUR_STARTS, lucky_list)
    ]


def _extract_lucky_directions(lunar: Any) -> dict[str, str]:
    """从 cnlunar 吉神方位中提取财神、喜神方位。"""
    result: dict[str, str] = {}
    try:
        directions = lunar.get_luckyGodsDirection()
    except Exception:
        directions = []
    for item in directions:
        text = str(item or "")
        for key, cfg_key in (("财神", "wealth"), ("喜神", "joy")):
            if text.startswith(key):
                result[cfg_key] = text.replace(key, "").strip() or text
    return result


def resolve_mystic_mode(config: dict[str, Any], period: str, now: datetime | None = None) -> str:
    """三时段产品身份固定，避免三个时间段再次变成同一种栏目。"""
    _ = config, now
    return MYSTIC_MODE_BY_PERIOD.get(period, "iching")


def _modernize_things(values: Any, limit: int = 6) -> list[str]:
    normalized = []
    for value in values if isinstance(values, (list, tuple)) else []:
        item = _THING_ALIASES.get(str(value), str(value))
        if item and item not in normalized:
            normalized.append(item)
    ordered = [item for item in _THING_PRIORITY if item in normalized]
    ordered.extend(item for item in normalized if item not in ordered)
    return ordered[:limit] or ["日常安排"]


def _format_next_term(lunar: Any) -> str:
    month, day = lunar.nextSolarTermDate
    return f"{lunar.nextSolarTerm} · {month}月{day}日"


def _build_almanac(now: datetime, rng: random.Random, ins_rng: random.Random | None = None) -> dict[str, Any]:
    # 点评优先走独立随机流；私聊路径未传时回落牌面流（行为不变）
    ins = ins_rng if ins_rng is not None else rng
    try:
        import cnlunar
    except ImportError as exc:
        raise RuntimeError("cnlunar_not_installed") from exc

    lunar = cnlunar.Lunar(now.replace(tzinfo=None), godType="8char")
    good = _modernize_things(lunar.goodThing)
    bad = _modernize_things(lunar.badThing)
    officer, duty_god, road = lunar.get_today12DayOfficer()
    lucky_directions = lunar.get_luckyGodsDirection()
    solar_term = (
        f"今日交节 · {lunar.todaySolarTerms}"
        if lunar.todaySolarTerms != "无"
        else f"下一节气 · {_format_next_term(lunar)}"
    )

    if "出行" in bad or any("动土" in item for item in bad):
        insight = ins.choice((
            "今天的黄历把出行或动土放在「忌」项。日常通勤照常，重大安排更适合把天气、工期和现实条件再核一遍。",
            "若今天正好有远行或开工计划，传统宜忌偏保守；动土这类动工的事不用紧张，把必要的安全检查做足就好。",
            "动土和出行今天落在忌项，传统视角偏保守；真要推进，把备选方案和天气路况先确认一遍更稳。",
            "黄历把动土、出行标了「忌」，当作一次提醒就好：流程照走，关键环节多留一点余量。",
        ))
    elif "出行" in good or any("动土" in item for item in good):
        insight = ins.choice((
            "出行或动土出现在「宜」项，更适合推进已经准备充分的安排；临时起意的事仍以现实条件为准。",
            "今天传统宜忌对行动类事项较友好，适合把准备充分的计划往前推一步。",
            "动土、出行都在宜项里，传统视角算友好；动工前把人员和材料核对齐，顺势推进即可。",
            "宜项里出现出行或动土，适合把拖着的安排拿出来过一遍；真正动手前还是看现实条件。",
        ))
    elif any(item in good for item in ("嫁娶", "开业开市", "签约交易")):
        insight = ins.choice((
            "今天宜项里有嫁娶、开业或签约这类「定日子」的事。传统认为这类安排适合挑日子，具体还要结合行程与现实准备。",
            "若有婚约、开业或合同需要敲定时点，今天的宜项给了个温和的信号；把流程细节核清楚，日子自然水到渠成。",
            "嫁娶、开业、签约这类大事落在宜项，传统上算个好兆头；细节仍要逐项确认，别只图日子好看。",
            "今天宜项偏向「定事」：嫁娶、开业、签约都可以往前推；关键条款和流程，还是白纸黑字最稳。",
        ))
    else:
        insight = ins.choice((
            "今天更适合按既定节奏推进，不必为了“求吉”临时打乱成熟安排。",
            "黄历给的是传统择日视角，真正落地仍要把天气、交通、合同与个人状态一起考虑。",
            "今天的宜忌没有特别突出的项，按原计划走就好；想微调节奏，先从最顺手的事开始。",
            "宜忌平平的一天，传统没什么特别叮嘱；把手头的事做扎实，比挑日子更要紧。",
        ))

    directions = _extract_lucky_directions(lunar)
    return {
        "mode": "almanac",
        "emoji": "📜",
        "title": "早间 · 今日黄历",
        "kicker": "农历 / 宜忌 / 节气",
        "meta": (
            f"{now:%Y年%m月%d日} {lunar.weekDayCn}｜"
            f"农历{lunar.year8Char}年 {lunar.lunarMonthCn}{lunar.lunarDayCn}｜"
            f"{lunar.day8Char}日 {lunar.twohour8Char}时"
        ),
        "blocks": [
            {
                "heading": "📌 今日宜忌",
                "lines": [
                    ("宜", " · ".join(good)),
                    ("忌", " · ".join(bad)),
                ],
            },
            {
                "heading": "🧭 日值参考",
                "lines": [
                    ("冲煞", lunar.chineseZodiacClash),
                    ("值日", f"{officer}日 · {duty_god} · {road}"),
                    ("星宿", lunar.get_the28Stars()),
                    ("吉神方位", " · ".join(lucky_directions[:3])),
                ],
            },
            {
                "heading": "🌿 节气提醒",
                "lines": [
                    ("节气", solar_term),
                    ("彭祖百忌", lunar.get_pengTaboo(long=4, delimit="；")),
                ],
            },
        ],
        "insight": insight,
        "hours": _extract_almanac_hours(lunar),
        "wealth_direction": directions.get("wealth", ""),
        "joy_direction": directions.get("joy", ""),
        "source": "cnlunar-0.2.4",
    }


def _build_tarot(now: datetime, rng: random.Random, ins_rng: random.Random | None = None) -> dict[str, Any]:
    # 点评优先走独立随机流；私聊路径未传时回落牌面流（行为不变）
    ins = ins_rng if ins_rng is not None else rng
    cards = rng.sample(list(_TAROT_CARDS), 3)
    roles = ("主牌", "助力", "提醒")
    rows = []
    readings = []
    elements = []
    for role, card in zip(roles, cards):
        number, name, element, upright, reversed_words = card
        reversed_position = bool(rng.getrandbits(1))
        position = "逆位" if reversed_position else "正位"
        words = reversed_words if reversed_position else upright
        rows.append((role, f"{number} · {name} · {position}｜{' / '.join(words)}"))
        readings.append(words[0])
        elements.append(element)
    dominant = max(set(elements), key=elements.count)
    # insight 句式多样化：_insight_rng 保证同日稳定、跨日变化；牌面抽取仍走牌面流，
    # 扩池不会打乱抽牌的日期稳定序列。各句式均保留「牌阵从」开篇骨架（兼容既有文案测试）
    action = ins.choice(_TAROT_ACTIONS)
    lead, support, watch = readings
    insight = ins.choice((
        f"牌阵从「{lead}」展开，可用的助力落在「{support}」，需要留意的是「{watch}」。{action}",
        f"今天的牌面先看「{lead}」，牌阵从「{support}」接上助力，提醒位上是「{watch}」。{action}",
        f"「{lead}」打头，牌阵从它一路铺开，帮你看清「{support}」与「{watch}」的取舍。{action}",
        f"牌阵从「{lead}」起势，「{support}」负责补位，「{watch}」负责敲警钟。{action}",
        f"顺着牌阵从「{lead}」往下看：助力在「{support}」，要留意的是「{watch}」。{action}",
    ))
    return {
        "mode": "tarot",
        "emoji": "🔮",
        "title": "午间 · 三张塔罗",
        "kicker": "主牌 / 助力 / 提醒",
        "meta": f"{now:%Y年%m月%d日}｜三张无重复大阿卡纳｜每日一次",
        "blocks": [
            {"heading": "🎴 今日牌阵", "lines": rows},
            {
                "heading": "✨ 能量观察",
                "lines": [
                    ("主导元素", dominant),
                    ("今日主轴", f"{readings[0]} → {readings[1]} → {readings[2]}"),
                ],
            },
        ],
        "insight": insight,
        "source": "curated-major-arcana-v1",
    }


def _hexagram_pattern(item: tuple[Any, ...]) -> tuple[int, ...]:
    return _TRIGRAM_LINES[item[5]] + _TRIGRAM_LINES[item[4]]


_HEXAGRAM_BY_PATTERN = {_hexagram_pattern(item): item for item in _HEXAGRAMS}


def _line_label(line_no: int, yang: bool) -> str:
    numeral = "九" if yang else "六"
    if line_no == 1:
        return f"初{numeral}"
    if line_no == 6:
        return f"上{numeral}"
    return f"{numeral}{'二三四五'[line_no - 2]}"


def _build_iching(now: datetime, rng: random.Random, ins_rng: random.Random | None = None) -> dict[str, Any]:
    # 点评优先走独立随机流；私聊路径未传时回落牌面流（行为不变）
    ins = ins_rng if ins_rng is not None else rng
    primary = rng.choice(_HEXAGRAMS)
    lines = list(_hexagram_pattern(primary))
    moving_line = rng.randint(1, 6)
    original_yang = bool(lines[moving_line - 1])
    lines[moving_line - 1] = 0 if original_yang else 1
    changed = _HEXAGRAM_BY_PATTERN[tuple(lines)]
    primary_symbol = chr(0x4DC0 + primary[0] - 1)
    changed_symbol = chr(0x4DC0 + changed[0] - 1)
    line_label = _line_label(moving_line, original_yang)
    question = ins.choice(_ICHING_QUESTIONS)
    # insight 句式多样化：同日稳定、跨日变化（由 _insight_rng 保证）；
    # 各句式均保留「本卦看」开篇骨架（兼容既有文案测试），差异化在后续引导语
    insight = ins.choice((
        f"本卦看「{primary[3]}」，变化落在{line_label}；之卦转向「{changed[3]}」。先看清变化从哪一层开始，再决定今天最值得推动的一步。",
        f"本卦看「{primary[3]}」，{line_label}一动，卦象转向「{changed[3]}」。别急着追着变化走，先看自己被哪一层牵动。",
        f"本卦看「{primary[3]}」，再到之卦「{changed[3]}」，中间会动的是{line_label}。变化不算大，但它提醒你今天最该稳住的地方。",
        f"本卦看「{primary[3]}」，{line_label}先动，之卦落在「{changed[3]}」。先认清哪一层在变，再谈下一步怎么走。",
        f"本卦看「{primary[3]}」，之卦指向「{changed[3]}」，枢纽就在{line_label}。变化不急着定论，先把最在意的部分稳住。",
    ))
    return {
        "mode": "iching",
        "emoji": "☯️",
        "title": "晚间 · 易经一卦",
        "kicker": "本卦 / 动爻 / 之卦",
        "meta": f"{now:%Y年%m月%d日 %H:%M}｜按北京时间日期稳定起卦",
        "blocks": [
            {
                "heading": "☯️ 今晚卦象",
                "lines": [
                    ("本卦", f"{primary_symbol} 第{primary[0]}卦 · {primary[2]}"),
                    ("上下卦", f"上{primary[4]} · 下{primary[5]}"),
                    ("动爻", f"{line_label} · 第{moving_line}爻变"),
                    ("之卦", f"{changed_symbol} 第{changed[0]}卦 · {changed[2]}"),
                ],
            },
            {
                "heading": "🪶 卦意观察",
                "lines": [
                    ("本卦主旨", primary[3]),
                    ("变化方向", changed[3]),
                    ("今晚一问", question),
                ],
            },
        ],
        "insight": insight,
        "source": "king-wen-64-v1",
    }


def build_mystic_broadcast(
    config: dict[str, Any],
    period: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """生成一张可直接交给富文本排版器的栏目 payload。

    CTA 由统一组件 core.broadcast_cta.get_broadcast_cta 在发送层生成并回填
    （见 tasks/broadcast/mystic_broadcast_task.py），此处不再维护第二套 CTA。
    """
    current = _normalize_now(now)
    date_key = current.strftime("%Y-%m-%d")
    mode = resolve_mystic_mode(config, period, current)
    rng = _stable_rng(date_key, period, mode)
    # 点评文案走独立随机流：扩池不扰动牌面的日期稳定序列
    ins_rng = _insight_rng(date_key, period, mode)
    if mode == "almanac":
        payload = _build_almanac(current, rng, ins_rng)
    elif mode == "tarot":
        payload = _build_tarot(current, rng, ins_rng)
    else:
        payload = _build_iching(current, rng, ins_rng)
    payload.update({
        "period": period,
        "date": date_key,
    })
    return payload


def build_private_mystic_reply(
    text: str,
    user_id: int,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """生成私聊本地占卜回复；不调用 LLM，不产生模型 Token。"""
    mode = resolve_private_mystic_mode(text)
    if mode is None or not int(user_id or 0):
        return None
    current = _normalize_now(now)
    theme = _private_theme_key(text, mode)
    rng = _stable_rng(
        current.strftime("%Y-%m-%d"),
        f"private-{int(user_id)}-{theme}",
        mode,
    )
    if mode == "almanac":
        payload = _build_almanac(current, rng)
        first = dict(payload["blocks"][0]["lines"])
        second = dict(payload["blocks"][1]["lines"])
        lines = [
            "🧭 你的今日风水参考",
            payload["meta"],
            "",
            f"宜　{first['宜']}",
            f"忌　{first['忌']}",
            f"冲煞　{second['冲煞']}",
            f"吉神方位　{second['吉神方位']}",
            "",
            payload["insight"],
            "想看具体空间，直接发我：所在城市、房间朝向、主要用途和最想调整的问题。",
        ]
    elif mode == "tarot":
        payload = _build_tarot(current, rng)
        card_lines = [
            f"{label}　{value}"
            for label, value in payload["blocks"][0]["lines"]
        ]
        lines = [
            "🔮 你的三张牌阵",
            *card_lines,
            "",
            payload["insight"],
        ]
    else:
        payload = _build_iching(current, rng)
        hexagram_lines = [
            f"{label}　{value}"
            for label, value in payload["blocks"][0]["lines"]
        ]
        lines = [
            "☯️ 为你起一卦",
            *hexagram_lines,
            "",
            payload["insight"],
        ]
    return {
        "mode": mode,
        "topic": theme,
        "text": "\n".join(lines),
        "source": payload["source"],
        "token_usage": 0,
    }


def is_usable_mystic_broadcast(payload: object) -> bool:
    """结构、来源、内容与单 CTA 门禁。"""
    if not isinstance(payload, dict):
        return False
    mode = payload.get("mode")
    if mode not in MYSTIC_MODES or not payload.get("title") or not payload.get("meta"):
        return False
    if mode == "almanac" and payload.get("source") != "cnlunar-0.2.4":
        return False
    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or len(blocks) < 2:
        return False
    for block in blocks:
        if not isinstance(block, dict) or not block.get("heading"):
            return False
        lines = block.get("lines")
        if not isinstance(lines, list) or not lines:
            return False
    cta = payload.get("cta")
    if cta is not None:
        # CTA 由统一组件生成：target 合法且 label 非空即可（URL 由统一池保证）
        if not isinstance(cta, dict) or cta.get("target") not in (
            "none", "preview", "subscribe", "contact",
        ):
            return False
        if cta.get("label") is None:
            return False
    visible = " ".join([
        str(payload.get("title", "")),
        str(payload.get("meta", "")),
        str(payload.get("insight", "")),
        str(payload.get("note", "")),
        *[
            f"{label} {value}"
            for block in blocks
            for label, value in block.get("lines", [])
        ],
    ]).lower()
    return not any(marker in visible for marker in _FORBIDDEN_VISIBLE_MARKERS)
