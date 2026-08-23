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

# 免责尾注：娱乐与传统文化的双重定性表述（措辞刻意避开历史上被测试
# 禁用的旧免责句式："不替代现实判断" / "传统民俗参考" / "不作确定性断言"）。
DISCLAIMER_NOTE = "内容仅供娱乐与传统文化参考，不构成决策依据"

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
    "祭祀": "拜祭纪念",
    "开光": "开光安放",
    "拆卸": "拆旧改造",
    "起基": "动土奠基",
    "上梁": "上梁安装",
    "栽种": "种植花木",
    "纳畜": "添置宠物",
    "赴任": "上任履新",
    "纳采": "提亲定亲",
    "订盟": "订婚定约",
    "理发": "理发做发型",
    "整手足甲": "修剪手足甲",
    "扫舍宇": "大扫除",
    "经络": "买车交车",
    "出货财": "发货出货",
    "余事勿取": "其余诸事不宜",
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

# 78 牌库策展规范见 docs/technical/tarot-minor-arcana-curation-guide.md；
# 首位关键词被 insight「今日主轴」引用，扩池时禁止重排首位。
_TAROT_CARDS = (
    ("0", "愚者", "风", ("启程", "自由", "可能性", "好奇", "轻装"), ("冒进", "分心", "准备不足", "鲁莽", "心散")),
    ("I", "魔术师", "风", ("行动", "资源", "表达", "专注", "巧思"), ("分散", "失焦", "承诺过满", "拖延", "夸大")),
    ("II", "女祭司", "水", ("直觉", "观察", "信息", "沉淀", "洞察"), ("迟疑", "封闭", "信息不全", "隐瞒", "疏离")),
    ("III", "皇后", "土", ("生长", "照顾", "创造", "丰盈", "包容"), ("消耗", "依赖", "节奏失衡", "耗竭", "越界")),
    ("IV", "皇帝", "火", ("秩序", "边界", "执行", "担当", "稳健"), ("僵化", "控制", "压力过重", "固执", "专断")),
    ("V", "教皇", "土", ("传统", "学习", "方法", "传承", "请教"), ("教条", "盲从", "需要验证", "照本宣科", "疏于思考")),
    ("VI", "恋人", "风", ("选择", "关系", "共识", "契合", "真心"), ("摇摆", "失衡", "价值冲突", "试探", "回避承诺")),
    ("VII", "战车", "水", ("方向", "推进", "专注", "自律", "冲刺"), ("拉扯", "急进", "方向偏移", "分神", "硬撑")),
    ("VIII", "力量", "火", ("勇气", "耐心", "分寸", "温柔坚定", "驯服冲动"), ("逞强", "内耗", "耐心不足", "气馁", "情绪上头")),
    ("IX", "隐士", "土", ("复盘", "筛选", "沉淀", "深思", "充电"), ("封闭", "拖延", "过度独处", "孤立感", "避世")),
    ("X", "命运之轮", "火", ("变化", "周期", "机会", "转机", "顺势"), ("反复", "失控", "时机未稳", "被动等待", "抗拒变化")),
    ("XI", "正义", "风", ("事实", "规则", "平衡", "公正", "权衡"), ("偏见", "失衡", "依据不足", "推诿", "双标")),
    ("XII", "倒吊人", "水", ("换位", "暂停", "新视角", "沉淀", "甘愿"), ("停滞", "牺牲过度", "迟迟不动", "白费力气", "消极等")),
    ("XIII", "死神", "水", ("结束", "转化", "清理", "告别", "新生"), ("抗拒", "拖延告别", "旧事反复", "藕断丝连", "原地踏步")),
    ("XIV", "节制", "火", ("协调", "适量", "磨合", "调和", "耐心"), ("过量", "急躁", "配合失衡", "顾此失彼", "内耗")),
    ("XV", "恶魔", "土", ("欲望", "束缚", "执念", "诱惑", "沉迷"), ("松绑", "看清代价", "重新选择", "挣脱", "清醒")),
    ("XVI", "高塔", "火", ("突变", "真相", "重建", "打破幻象", "释放"), ("余震", "回避变化", "基础不稳", "惊魂未定", "讳疾忌医")),
    ("XVII", "星星", "风", ("希望", "修复", "愿景", "疗愈", "灵感"), ("失望", "分心", "目标模糊", "灰心", "理想褪色")),
    ("XVIII", "月亮", "水", ("潜意识", "想象", "迷雾", "敏感", "梦境"), ("核实", "看清", "减少猜测", "拨云见日", "澄清误会")),
    ("XIX", "太阳", "火", ("清晰", "活力", "公开", "明朗", "坦荡"), ("过热", "自满", "忽略细节", "虚火", "乐极生悲")),
    ("XX", "审判", "火", ("回顾", "回应", "更新", "觉醒", "总结"), ("迟疑", "自我怀疑", "旧账未清", "逃避结论", "错过召唤")),
    ("XXI", "世界", "土", ("完成", "整合", "新阶段", "达成", "里程碑"), ("收尾未尽", "循环未合", "仍需补足", "差一口气", "拖尾")),
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

# 三张牌阵框架：默认框架保栏目身份认知；备选框架仅在
# MYSTIC_BROADCAST_CONFIG.tarot_spread_rotation_enabled 开启时，
# 由独立随机流（_spread_rng）按 <20% 概率启用，默认框架占比 ≥80%。
# 各框架的角色名、动作池、句式互相独立，避免跨框架角色错配。
_TAROT_SPREAD_STYLES = {
    "default": {
        "roles": ("主牌", "助力", "提醒"),
        "actions": _TAROT_ACTIONS,
        # 兼容既有文案测试：默认框架句式保留「牌阵从」开篇骨架
        "templates": (
            "牌阵从「{lead}」展开，可用的助力落在「{support}」，需要留意的是「{watch}」。{action}",
            "今天的牌面先看「{lead}」，牌阵从「{support}」接上助力，提醒位上是「{watch}」。{action}",
            "「{lead}」打头，牌阵从它一路铺开，帮你看清「{support}」与「{watch}」的取舍。{action}",
            "牌阵从「{lead}」起势，「{support}」负责补位，「{watch}」负责敲警钟。{action}",
            "顺着牌阵从「{lead}」往下看：助力在「{support}」，要留意的是「{watch}」。{action}",
        ),
    },
    "situation": {
        "roles": ("情境", "行动", "结果"),
        "actions": (
            "情境位看的是土壤，行动位才是你能握住的部分，结果位只给方向感。",
            "适合先接受现状，再挑一个成本最小的动作试水。",
            "结果位不是终点判决，只是当前路径的自然延伸；换打法，结局就换。",
            "如果行动位与情境位明显冲突，说明现在需要的是调整而非硬闯。",
            "今天更适合小步快跑，把大决定拆成几个可验证的小动作。",
            "三张牌连成一句话读：因为什么、做什么、会到哪里。",
            "行动位是整个牌阵的支点，其余两张都在为它提供语境。",
            "若结果位不如预期，先回看行动位是否偏离了情境给出的条件。",
            "牌阵提醒：方向感比速度重要，落点可以微调，路径要自己走。",
            "把牌面当沙盘推演，真动手前仍以现实条件为准。",
        ),
        "templates": (
            "眼下的「{lead}」是底色，「{support}」给出可走的路，指向的落点是「{watch}」。{action}",
            "先把「{lead}」看清楚，行动位落在「{support}」，照这个走法，结果偏向「{watch}」。{action}",
            "「{lead}」描述处境，「{support}」是建议的动作，「{watch}」是它通向的方向。{action}",
            "处境在「{lead}」，能做的是「{support}」，这样走下去大概率停在「{watch}」。{action}",
            "从「{lead}」出发，经「{support}」这一步，画面最后落在「{watch}」。{action}",
        ),
    },
    "status": {
        "roles": ("现状", "挑战", "指引"),
        "actions": (
            "现状位描述位置，挑战位指出阻力，指引位只负责给一个可行的小动作。",
            "挑战不是否定，它只是把最容易绊倒的地方提前标了出来。",
            "指引位通常很小，小到容易忽略；今天就从那件小事做起。",
            "如果挑战位与指引位指向同一处，说明解法已经摆在台面上了。",
            "适合先稳住现状位的部分再谈突破；地基没稳之前，不急着加盖。",
            "三张牌串起来看：身在何处、卡在哪里、往哪挪一步。",
            "今天的节奏是防守反击：守住该守的，再按指引位出手。",
            "挑战位的压力是暂时的，指引位的动作是可以立刻开始的。",
            "不必一次解决所有问题，指引位那一件事做好就算达标。",
            "牌阵给的是观察角度，落地与否还是看你手里的实际筹码。",
        ),
        "templates": (
            "现状停在「{lead}」，真正的挑战是「{support}」，指引让你先做「{watch}」。{action}",
            "「{lead}」是底子，「{support}」是要迈过去的坎，「{watch}」指了条明路。{action}",
            "现在的局面是「{lead}」，拦路的是「{support}」，不妨按「{watch}」调整。{action}",
            "你站在「{lead}」，挑战藏在「{support}」，出路写着「{watch}」。{action}",
            "「{lead}」暂时不动的，动的是「{support}」，破局点在「{watch}」。{action}",
        ),
    },
}

_DEFAULT_SPREAD_KEY = "default"
_ALTERNATE_SPREAD_KEYS = ("situation", "status")

# 六十四卦「经典一句」：卦辞白话 + 大象传行为映射（公共领域文本的策展白话）。
# 策展口径：通行本原文为底、白话克制中性、险难卦不鸡汤化（坎就是险）、
# 与 insight 一行句式对齐；键为卦名（与 _HEXAGRAMS[1] 对应）。
_HEXAGRAM_CLASSICS = {
    "乾": ("开创势头正盛，主动权在自己手里", "自强不息，把节奏握在手中"),
    "坤": ("顺势承载比带头冲锋更有利", "厚德载物，先接住再施展"),
    "屯": ("起步千头万绪，先盘整再出发", "理出头绪，胜过急着上路"),
    "蒙": ("缺的是方法，虚心求教就有答案", "行动果断，学习认真"),
    "需": ("条件已备，等待本身也是推进", "养足精神，时机到自然能走"),
    "讼": ("争执宜早收，拖久两败俱伤", "开局就把规则讲清楚"),
    "师": ("成事需要靠谱的人牵头", "容得下人，才带得动队伍"),
    "比": ("亲近与结盟带来顺利", "选好同行的人"),
    "小畜": ("积累未满，火候还差一点", "继续蓄力，别急着摊牌"),
    "履": ("行事谨慎，险处也能走稳", "分清场合与分寸"),
    "泰": ("通达顺畅，沟通皆有效", "趁势打通该通的关系"),
    "否": ("暂时闭塞，不宜强推", "收敛锋芒，保存实力"),
    "同人": ("志同道合者相助，事可成", "先找对人，再做成事"),
    "大有": ("丰盛之时，名与实都旺", "拥有越多，越要行得正"),
    "谦": ("谦逊者善始善终", "留有余地，受益的是自己"),
    "豫": ("准备充分，可以调动资源", "顺时而动，也别忘绸缪"),
    "随": ("跟随对的节奏，顺势无咎", "该休息休息，该跟随时跟随"),
    "蛊": ("积弊待整，动手即是转机", "整顿旧局，正是立信之时"),
    "临": ("居于上位，宽厚得人心", "好光景也要有忧患意识"),
    "观": ("多观察少妄动，看清再走", "站高一层，看全局"),
    "噬嗑": ("障碍需要果断清除", "规则分明，事情才顺"),
    "贲": ("修饰得当，锦上添花", "外在得体，内在务实"),
    "剥": ("消退期宜守，不宜进", "巩固根基，静待复苏"),
    "复": ("回归正轨，一步比一步稳", "休整蓄力，来日方长"),
    "无妄": ("守正则吉，妄动招灾", "循着本分行事"),
    "大畜": ("厚积已足，可外出成事", "多学前人的经验"),
    "颐": ("自食其力，慎言节欲", "管住嘴，养住身"),
    "大过": ("非常时期，需要非常担当", "顶住压力才有转机"),
    "坎": ("险中有路，心定则能过", "保持操守，稳步涉险"),
    "离": ("依附光明，柔顺则吉", "借势而亮，持续发光"),
    "咸": ("真诚感应，关系水到渠成", "放空自己，才能接住他人"),
    "恒": ("持久之道，贵在坚持", "方向不变，日拱一卒"),
    "遁": ("退避不是败，是保全", "拉开距离，守住底线"),
    "大壮": ("力量正盛，仍需守规矩", "越有力，越要克制"),
    "晋": ("处于上升期，表现会被看见", "把自己照亮，机会自来"),
    "明夷": ("光藏于暗，守志待时", "低调行事，内心清明"),
    "家人": ("内部有序，内外安宁", "说话实在，做事有恒"),
    "睽": ("分歧时期，求同存异", "大事缓办，小事可为"),
    "蹇": ("路遇险阻，宜绕行修己", "先反省自身，再找出路"),
    "解": ("困境缓解，宜宽不宜紧", "放下小过节，轻装上阵"),
    "损": ("有所舍，才有所得", "减掉多余，留住要紧"),
    "益": ("增益之时，行动有利", "向好的学，往对的路走"),
    "夬": ("决断时刻，光明正大", "当断则断，不留暗账"),
    "姤": ("意外相遇，警惕为上", "新苗头看清了再靠近"),
    "萃": ("聚拢人心，共谋其事", "相聚之时，防患未然"),
    "升": ("步步上升，积小成大", "顺着节奏，一级级上"),
    "困": ("受限不失志，熬过即安", "境遇困住人，困不住心"),
    "井": ("根本不变，滋养常在", "养清自己的井，惠人惠己"),
    "革": ("变革须待信任成熟", "时机对了再改，改就改透"),
    "鼎": ("更新成器，格局初定", "摆正位置，扛起使命"),
    "震": ("震动来袭，省身则安", "惊而不乱，借势自省"),
    "艮": ("该停则停，界限即护栏", "守好自己的位置"),
    "渐": ("循序渐进，事缓则圆", "慢慢来，反而快"),
    "归妹": ("位置未正，慎始慎终", "看清局限，别勉强前行"),
    "丰": ("鼎盛之时，大公则明", "趁正午的阳光办事"),
    "旅": ("旅途之中，谦谨为安", "身在异地，凡事从简从慎"),
    "巽": ("以柔渗透，反复申明", "温和坚持，一样成事"),
    "兑": ("交流喜悦，彼此成就", "和同好切磋，越聊越明"),
    "涣": ("涣散之际，重聚人心", "找到凝聚点，把人拢起来"),
    "节": ("节制有度，过苛不必", "规矩要有，别捆死自己"),
    "中孚": ("诚信立身，难事亦解", "以诚待人，留有余地"),
    "小过": ("小事可为，大事宜缓", "宁恭俭有余，不张扬越线"),
    "既济": ("完成之后，最防松懈", "越顺，越要回头看"),
    "未济": ("未完待续，从容续行", "辨清形势，下一步才稳"),
}

# 十二值神浅释（名称与 cnlunar 库内拼写一致，如「金贵」）；
# 传统民俗说法的克制转述，不构成任何现实建议。
_DUTY_GOD_NOTES = {
    "青龙": "黄道 · 得势之时，宜主动推进",
    "明堂": "黄道 · 宜公开办事、见人议事",
    "天刑": "黑道 · 易有摩擦，凡事务必留凭据",
    "朱雀": "黑道 · 防口舌争执，话到嘴边缓三分",
    "金贵": "黄道 · 传统视为财星，宜打理财务",
    "天德": "黄道 · 传统认为贵人运旺，宜求助",
    "白虎": "黑道 · 传统提醒谨慎，重大安排多核一遍",
    "玉堂": "黄道 · 宜文书、学习与安顿",
    "天牢": "黑道 · 进展易受阻，先处理简单事项",
    "玄武": "黑道 · 防暗耗与糊涂账，细核对",
    "司命": "黄道 · 昼间顺利，夜间不宜决大事",
    "勾陈": "黑道 · 旧事易缠身，理清再动",
}

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
    "今天有没有一件事，其实做到八成就已经够了？",
    "如果明天的你只记得今天的一件事，你希望是哪件？",
    "此刻更该相信的是冷静的判断，还是时间给的答案？",
    "有没有一件小事，值得从明天开始固定做下去？",
    "最近让你反复琢磨的那件事，卡点究竟在哪一层？",
    "如果把顾虑写下来，它们还剩几条经得起推敲？",
    "今天有没有哪个瞬间，其实比你以为的更重要？",
    "眼下这一步，是在解决问题，还是在回避问题？",
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

# 私聊占卜敏感分流：仅在「已命中占卜意图」的请求内部做窄关键词匹配，
# 绝不独立扫描全量私聊（避免宽匹配吞掉正常聊天、中断消息分发主链）。
# 词表刻意收窄到具体表述，正常的工作/感情类占卜请求不受影响。
_SENSITIVE_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "医疗健康",
        ("癌症", "绝症", "肿瘤", "病能不能治", "能活多久", "治得好吗", "手术顺利吗"),
    ),
    (
        "法律纠纷",
        ("官司", "诉讼", "牢狱之灾", "判几年", "能打赢吗", "会不会坐牢"),
    ),
    (
        "金融投资",
        ("股票", "买哪支", "炒币", "期货", "该不该投", "彩票号码", "加杠杆", "梭哈哪个"),
    ),
)

# 敏感承接文案（草稿）：中性、不评判、不给占卜答案、不携带任何 @ 入口；
# 属敏感话题承接文案，正式启用前须经管理员确认。
_SENSITIVE_HOLD_TEXT = (
    "{domain}这类问题，占卜给不了答案，也不该由它来给——"
    "这更值得听专业人士的意见。想轻松抽张牌、看看黄历，随时再来找我。"
)


def _match_sensitive_domain(text: str) -> str | None:
    """对已命中占卜意图的文本做敏感域窄匹配，命中返回领域名。"""
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return None
    for domain, keywords in _SENSITIVE_TOPIC_RULES:
        if any(keyword in compact for keyword in keywords):
            return domain
    return None


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


def _spread_rng(date_key: str, period: str) -> random.Random:
    """牌阵框架独立随机流：与牌面/点评流完全隔离。

    框架选择若挂在牌面流上会多消费随机数、移动整条牌面序列，
    破坏「按日期稳定起牌」的产品合同；此流只决定用哪套框架。
    """
    raw = f"{date_key}|{period}|tarot|mory-spread-v1".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(seed)


def _resolve_tarot_spread_key(rotation_enabled: bool, spread_random: random.Random) -> str:
    """默认框架占比 ≥80%；仅在轮换开启时由独立流选备选框架。"""
    if not rotation_enabled:
        return _DEFAULT_SPREAD_KEY
    if spread_random.random() < 0.8:
        return _DEFAULT_SPREAD_KEY
    return spread_random.choice(_ALTERNATE_SPREAD_KEYS)


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


def _format_lucky_hours(hours: list[tuple[str, int, str]]) -> str:
    """把时辰吉凶压缩成「吉时参考」一行：卯时05-07 · 午时11-13。

    时辰吉凶依传统时辰位表（与值神体系相互独立）；子时跨午夜，
    写作 23-01 以免误读。无吉时返回空串。
    """
    lucky = [(name, start) for name, start, luck in hours if luck == "吉"]
    if not lucky:
        return ""
    parts = []
    for name, start in lucky:
        end = (start + 2) % 24
        parts.append(f"{name}时{start:02d}-{end:02d}")
    return " · ".join(parts)


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
            "动土、出行在传统里属「大动作」，今天被标了「忌」；理解为节奏提示即可，手续照办、安全照查。",
            "忌项里有动土与出行，不代表今天不能出门；只是传统更建议把远行和开工这类事多想一层再定。",
            "今天的宜忌对出行、动土偏保守。要动工的话，把合同、天气和人员这三件事先过一遍再说。",
            "黄历的「忌」更像老辈人的叮嘱：动土出行这类大事，今天适合只做准备，不动手。",
        ))
    elif "出行" in good or any("动土" in item for item in good):
        insight = ins.choice((
            "出行或动土出现在「宜」项，更适合推进已经准备充分的安排；临时起意的事仍以现实条件为准。",
            "今天传统宜忌对行动类事项较友好，适合把准备充分的计划往前推一步。",
            "动土、出行都在宜项里，传统视角算友好；动工前把人员和材料核对齐，顺势推进即可。",
            "宜项里出现出行或动土，适合把拖着的安排拿出来过一遍；真正动手前还是看现实条件。",
            "出行、动土落在宜项，是个顺手的信号：已经规划好的行程和工程，可以按表推进了。",
            "传统视角今天利行动。出行记得看天气路况，动土开工则把安全交底做在前面。",
            "宜项见出行与动土，属于「可以动起来」的日子；把第一步安排在今天，后面会顺一些。",
            "今天宜出行也宜开工，但「宜」不等于免检——该有的审批、防护和保险一样都不能省。",
        ))
    elif any(item in good for item in ("嫁娶", "开业开市", "签约交易")):
        insight = ins.choice((
            "今天宜项里有嫁娶、开业或签约这类「定日子」的事。传统认为这类安排适合挑日子，具体还要结合行程与现实准备。",
            "若有婚约、开业或合同需要敲定时点，今天的宜项给了个温和的信号；把流程细节核清楚，日子自然水到渠成。",
            "嫁娶、开业、签约这类大事落在宜项，传统上算个好兆头；细节仍要逐项确认，别只图日子好看。",
            "今天宜项偏向「定事」：嫁娶、开业、签约都可以往前推；关键条款和流程，还是白纸黑字最稳。",
            "宜项里的嫁娶、开业、签约都是「落笔为定」的事，今天签下的约定，更要逐条读清楚再签字。",
            "传统择日里，今天是利于「定终身、开新张」的日子；仪式感可以有，预算和条款也要量力而行。",
            "婚约、开业、签约若已在日程上，今天的宜项算加分项；剩下的交给清单：材料、证照、见证人。",
            "宜定事的日子适合推进嫁娶开业签约这类安排，但也别临时加戏——按原计划走就是最好的吉时。",
        ))
    else:
        insight = ins.choice((
            "今天更适合按既定节奏推进，不必为了“求吉”临时打乱成熟安排。",
            "黄历给的是传统择日视角，真正落地仍要把天气、交通、合同与个人状态一起考虑。",
            "今天的宜忌没有特别突出的项，按原计划走就好；想微调节奏，先从最顺手的事开始。",
            "宜忌平平的一天，传统没什么特别叮嘱；把手头的事做扎实，比挑日子更要紧。",
            "没有特别宜忌的一天，反而自由：日程怎么排，取决于你自己最想先完成哪件。",
            "传统视角今天无大风大浪，适合处理日常琐事；把积压的小事清一清，比等好日子更实际。",
            "宜忌平常的日子有个好处——做什么都不算错，重点是别什么都想做。",
            "今天黄历没什么戏剧性，按部就班就是最优解；留点余量给意外，也留点心情给自己。",
        ))

    directions = _extract_lucky_directions(lunar)
    hours = _extract_almanac_hours(lunar)
    duty_note = _DUTY_GOD_NOTES.get(str(duty_god), "")
    lucky_hours_text = _format_lucky_hours(hours)
    day_value_lines = [
        ("冲煞", lunar.chineseZodiacClash),
        ("值日", f"{officer}日 · {duty_god} · {road}"),
        ("星宿", lunar.get_the28Stars()),
        ("吉神方位", " · ".join(lucky_directions[:3])),
    ]
    if duty_note:
        day_value_lines.append(("值神浅释", duty_note))
    if lucky_hours_text:
        # 时辰吉凶依传统时辰位表，与值神体系相互独立；子时跨午夜已写作 23-01
        day_value_lines.append(("吉时参考", lucky_hours_text))
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
                "lines": day_value_lines,
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
        "hours": hours,
        "wealth_direction": directions.get("wealth", ""),
        "joy_direction": directions.get("joy", ""),
        "source": "cnlunar-0.2.4",
    }


def _build_tarot(
    now: datetime,
    rng: random.Random,
    ins_rng: random.Random | None = None,
    spread_key: str = _DEFAULT_SPREAD_KEY,
) -> dict[str, Any]:
    # 点评优先走独立随机流；私聊路径未传时回落牌面流（行为不变）
    ins = ins_rng if ins_rng is not None else rng
    style = _TAROT_SPREAD_STYLES.get(spread_key, _TAROT_SPREAD_STYLES[_DEFAULT_SPREAD_KEY])
    cards = rng.sample(list(_TAROT_CARDS), 3)
    roles = style["roles"]
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
    # insight 句式按框架独立：同日稳定、跨日变化（由 _insight_rng 保证）；
    # 牌面抽取仍走牌面流，扩池不会打乱抽牌的日期稳定序列。
    # 默认框架句式保留「牌阵从」开篇骨架（兼容既有文案测试）。
    action = ins.choice(style["actions"])
    template = ins.choice(style["templates"])
    lead, support, watch = readings
    insight = template.format(lead=lead, support=support, watch=watch, action=action)
    return {
        "mode": "tarot",
        "emoji": "🔮",
        "title": "午间 · 三张塔罗",
        "kicker": "主牌 / 助力 / 提醒" if spread_key == _DEFAULT_SPREAD_KEY else " / ".join(roles),
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
    classic = _HEXAGRAM_CLASSICS.get(
        primary[1], ("卦象平实，按部就班即可", "守好本分，稳字当头")
    )
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
                    ("经典一句", f"{classic[0]}→{classic[1]}"),
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
    mystic_cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    rotation_enabled = bool(
        mystic_cfg.get("tarot_spread_rotation_enabled", False)
    ) if isinstance(mystic_cfg, dict) else False
    if mode == "almanac":
        payload = _build_almanac(current, rng, ins_rng)
    elif mode == "tarot":
        spread_key = _resolve_tarot_spread_key(rotation_enabled, _spread_rng(date_key, period))
        payload = _build_tarot(current, rng, ins_rng, spread_key=spread_key)
    else:
        payload = _build_iching(current, rng, ins_rng)
    payload.update({
        "period": period,
        "date": date_key,
    })
    if isinstance(mystic_cfg, dict) and bool(mystic_cfg.get("disclaimer_note_enabled", False)):
        payload["note"] = DISCLAIMER_NOTE
    return payload


def build_private_mystic_reply(
    text: str,
    user_id: int,
    now: datetime | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """生成私聊本地占卜回复；不调用 LLM，不产生模型 Token。

    config 提供且 MYSTIC_BROADCAST_CONFIG.disclaimer_note_enabled 开启时，
    回复末尾追加与栏目一致的免责尾注（双路径同覆盖）。
    """
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
    mystic_cfg = {}
    if isinstance(config, dict):
        raw_cfg = config.get("MYSTIC_BROADCAST_CONFIG", {})
        if isinstance(raw_cfg, dict):
            mystic_cfg = raw_cfg
    disclaimer_enabled = bool(mystic_cfg.get("disclaimer_note_enabled", False))
    # 敏感分流：先命中占卜意图（上方 resolve），再在占卜分支内查敏感词；
    # 命中则用中性承接替换本次占卜输出，不影响其他消息分发。
    if bool(mystic_cfg.get("private_sensitive_guard_enabled", False)):
        domain = _match_sensitive_domain(text)
        if domain:
            return {
                "mode": "sensitive_hold",
                "topic": _private_theme_key(text, mode),
                "text": _SENSITIVE_HOLD_TEXT.format(domain=domain),
                "source": "sensitive-guard-v1",
                "token_usage": 0,
            }
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
    if disclaimer_enabled:
        lines.append("")
        lines.append(DISCLAIMER_NOTE)
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
