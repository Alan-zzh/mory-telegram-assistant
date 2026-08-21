# -*- coding: utf-8 -*-
"""
[Puzan-OS v5.32] 营销话术正则库

聚焦于"营销话术模板+引流话术+诱导话术"三类组合特征。
与 ad_patterns_encoded.py 的 MONEY_PATTERNS 互补：
- MONEY_PATTERNS：纯赚钱承诺（日入/月入/稳赚）
- 本文件：营销组合话术（0投资+动动手指+新手小白也能等）

设计原则：
1. 单字不是广告，组合才是（避免误伤正常讨论）
2. 与现有 MONEY_PATTERNS 不重复
3. 命中权重 2-3，配合其他维度评分触发封禁
"""

# ── 营销话术模板（组合特征）──
# 0投资/零投资 + 营销承诺
MARKETING_TEMPLATE_PATTERNS = [
    # 0/零投资 + 收益承诺
    r"[0零\u96f6]\u6295\u8d44[\s\S]{0,8}[\u8d5a\u6536\u5165\u5229\u7684\u7a33]",
    r"[0零\u96f6]\u95e8\u69db[\s\S]{0,8}[\u8d5a\u6536\u5165\u5229\u7684\u7a33]",
    r"[0零\u96f6]\u6210\u672c[\s\S]{0,8}[\u8d5a\u6536\u5165\u5229\u7684\u7a33]",
    # 动动手指/手机操作 + 赚钱
    r"\u52a8\u52a8\u624b\u6307[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u624b\u673a\u64cd\u4f5c[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u624b\u673a\u5c31\u80fd[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    # 轻轻松松 + 收益
    r"\u8f7b\u8f7b\u677e\u677e[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u8f7b\u677e[\s\S]{0,5}[\u8d5a\u6536\u5165\u94b1]",
    # 睡后收入/躺赚（独立强信号）
    r"\u7761\u540e\u6536\u5165",
    r"\u8eba\u8d5a[\s\S]{0,5}[\u4e0d\u7528\u52a8\u624b\u673a]",
    # 稳定收益/保本保息
    r"\u7a33\u5b9a\u6536\u76ca[\s\S]{0,5}[\u9879\u76ee\u5e73\u53f0]",
    r"\u4fdd\u672c\u4fdd\u606f",
    r"\u7a33\u8d5a\u4e0d\u8d54",
    # 副业/兼职 + 高收入
    r"\u526f\u4e1a[\s\S]{0,8}[\u6536\u5165\u8d5a\u94b1][0-9\u5343\u767e\u4e07wWkK]+",
    r"\u517c\u804c[\s\S]{0,8}[\u6536\u5165\u8d5a\u94b1][0-9\u5343\u767e\u4e07wWkK]+",
    # 新手小白也能
    r"\u65b0\u624b\u5c0f\u767d\u4e5f\u80fd[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u5c0f\u767d\u4e5f\u80fd[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u96f6\u57fa\u7840[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    # 导师带/老师带 + 赚钱
    r"\u5bfc\u5e08\u5e26[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u8001\u5e08\u5e26[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    r"\u4e00\u5bf9\u4e00\u6307\u5bfc[\s\S]{0,8}[\u8d5a\u6536\u5165\u94b1]",
    # 回本/稳赚不赔 + 项目
    r"\u56de\u672c[\s\S]{0,5}[\u5feb\u7a33\u4fdd\u8bc1]",
    r"\u7a33\u8d5a\u4e0d\u8d54[\s\S]{0,5}[\u9879\u76ee\u5e73\u53f0]",
]

# ── 引流话术（联系方式诱导）──
MARKETING_CONTACT_PATTERNS = [
    # V/微信谐音 + 数字
    r"[Vv\u5fae\u5a01][\s\:\uff1a\u52a0]{1,3}[a-zA-Z0-9_]{6,}",
    r"\u5fae\u4fe1[\s\:\uff1a\u52a0]{1,3}[a-zA-Z0-9_]{6,}",
    r"\u52a0\u6211[\s\S]{0,3}[Vv\u5fae\u5a01]",
    r"\u52a0\u6211\u5fae\u4fe1",
    r"\u79c1\u6211[\s\S]{0,3}[Vv\u5fae\u5a01\u8054\u7cfb]",
    # QQ群/Telegram群引流
    r"\u626b\u7801\u8fdb\u7fa4",
    r"\u626b\u7801\u52a0\u6211",
    r"\u626b\u7801[\s\S]{0,5}[\u7801\u7fa4\u5165\u52a0]",
    # 主页/简介引流（与 PROFILE_HINT_PATTERNS 部分重叠，但更具体）
    r"\u70b9\u6211\u4e3b\u9875[\s\S]{0,5}[\u770b\u67e5\u770b\u89c1]",
    r"\u770b\u6211\u4e3b\u9875[\s\S]{0,5}[\u8be6\u60c5\u4e86\u89e3\u770b]",
    r"\u770b\u7b80\u4ecb[\s\S]{0,5}[\u8be6\u60c5\u4e86\u89e3\u770b]",
    # 联系方式+客服
    r"\u8054\u7cfb\u5ba2\u670d",
    r"\u5bfb\u627e\u5ba2\u670d",
    r"\u5b98\u65b9\u5ba2\u670d",
    r"\u54a8\u8be2\u5ba2\u670d",
    # 私聊+具体引导
    r"\u79c1\u804a[\s\S]{0,3}(?:\u8be6\u60c5|\u4e86\u89e3|\u62a5\u540d)",
    r"\u79c1\u4fe1[\s\S]{0,3}(?:\u8be6\u60c5|\u4e86\u89e3|\u62a5\u540d)",
    r"\u6ef4\u6ef4\u6211[\s\S]{0,3}(?:\u8be6\u60c5|\u4e86\u89e3|\u62a5\u540d)",
]

# ── 诱导话术（紧迫感+利益诱导）──
MARKETING_URGENCY_PATTERNS = [
    # 限时+名额
    r"\u9650\u65f6[\s\S]{0,5}\u540d\u989d",
    r"\u9650\u65f6[\s\S]{0,5}\u62a2\u8d2d",
    r"\u4ec5\u9650[\s\S]{0,5}[\u540d\u989d\u4eba\u540d]",
    r"\u6700\u540e[\s\S]{0,5}\u540d\u989d",
    r"\u6700\u540e[\s\S]{0,5}\u673a\u4f1a",
    # 错过+后悔（已有部分在 MONEY_PATTERNS，此处更具体组合）
    r"\u9519\u8fc7[\s\S]{0,5}\u540e\u6094",
    r"\u4e0d\u62a5\u540d[\s\S]{0,5}\u540e\u6094",
    # 名额有限+免费
    r"\u540d\u989d\u6709\u9650[\s\S]{0,5}\u514d\u8d39",
    r"\u514d\u8d39\u9001[\s\S]{0,5}\u540d\u989d",
    # 立即/马上 + 行动
    r"\u7acb\u5373\u62a5\u540d[\s\S]{0,5}[\u540d\u989d\u6709\u9650]",
    r"\u9a6c\u4e0a\u62a5\u540d[\s\S]{0,5}[\u540d\u989d\u6709\u9650]",
    # 拉人头+奖励
    r"\u62c9\u4eba\u8fdb\u7fa4[\s\S]{0,5}[\u5956\u52b1\u7ea2\u5305\u91d1\u5e01]",
    r"\u9080\u8bf7\u597d\u53cb[\s\S]{0,5}[\u5956\u52b1\u7ea2\u5305\u91d1\u5e01]",
    r"\u63a8\u5e7f\u8d5a\u94b1",
    r"\u5206\u4eab\u8d5a\u94b1",
]

# ── 项目/平台诱导（投资类陷阱）──
MARKETING_PROJECT_PATTERNS = [
    # 平台+保底/收益
    r"\u5e73\u53f0[\s\S]{0,5}\u4fdd\u5e95",
    r"\u5e73\u53f0[\s\S]{0,5}\u6536\u76ca",
    r"\u5e73\u53f0[\s\S]{0,5}\u7a33\u5b9a",
    r"\u5e73\u53f0[\s\S]{0,5}\u56de\u672c",
    # 项目+保本+保收益
    r"\u9879\u76ee[\s\S]{0,5}\u4fdd\u672c[\s\S]{0,5}\u6536\u76ca",
    r"\u9879\u76ee[\s\S]{0,5}\u7a33\u5b9a[\s\S]{0,5}\u6536\u76ca",
    # 任务+佣金
    r"\u505a\u4efb\u52a1[\s\S]{0,5}\u4f63\u91d1",
    r"\u4efb\u52a1\u5957\u73b0",
    r"\u9886\u4efb\u52a1[\s\S]{0,5}\u4f63\u91d1",
    # 注册+返现
    r"\u6ce8\u518c[\s\S]{0,5}\u8fd4\u73b0",
    r"\u6ce8\u518c[\s\S]{0,5}\u9001[\s\S]{0,3}[\u7ea2\u5305\u5956\u91d1]",
    # 试玩+赚钱
    r"\u8bd5\u73a9[\s\S]{0,5}\u8d5a\u94b1",
    r"\u4f53\u9a8c[\s\S]{0,5}\u8d5a\u94b1",
    # 拼团/众筹+收益
    r"\u62fc\u56e2[\s\S]{0,5}\u6536\u76ca",
    r"\u4f17\u7b79[\s\S]{0,5}\u6536\u76ca",
]

# ── 营销话术汇总（按权重分组）──
MARKETING_PATTERN_GROUPS = {
    "marketing_template": {
        "label": "营销话术模板",
        "weight": 2,
        "patterns": MARKETING_TEMPLATE_PATTERNS,
    },
    "marketing_contact": {
        "label": "引流联系方式",
        "weight": 3,
        "patterns": MARKETING_CONTACT_PATTERNS,
    },
    "marketing_urgency": {
        "label": "紧迫诱导话术",
        "weight": 2,
        "patterns": MARKETING_URGENCY_PATTERNS,
    },
    "marketing_project": {
        "label": "项目平台诱导",
        "weight": 3,
        "patterns": MARKETING_PROJECT_PATTERNS,
    },
}

# 全部营销话术模式（用于快速扫描）
ALL_MARKETING_PATTERNS = (
    MARKETING_TEMPLATE_PATTERNS +
    MARKETING_CONTACT_PATTERNS +
    MARKETING_URGENCY_PATTERNS +
    MARKETING_PROJECT_PATTERNS
)


def get_marketing_patterns() -> list:
    """返回所有营销话术正则（扁平列表）。"""
    return ALL_MARKETING_PATTERNS


def get_marketing_groups() -> dict:
    """返回营销话术分组（带权重）。"""
    return MARKETING_PATTERN_GROUPS
