"""
tasks/support/message_templates.py - 消息文案资源池

集中管理 auto_tasks.py 中散落的话术池，避免巨型文件混合文案与逻辑。
"""

import random
from typing import List


class MessageTemplates:
    """集中管理各类定时任务的文案池。"""

    GREETING_STYLE_BAN: List[str] = [
        "多源汇总",
        "TrendRadar",
        "脑子刚才短路",
        "刚才走神",
        "网络有点卡",
        "刚刚没反应过来",
        "喝口水缓一缓",
        "慢慢来",
        "别把自己逼太紧",
        "今天会顺一点",
        "身心",
        "归位",
        "允许自己",
        "外界期待",
        "安静地存在",
        "蓝光",
        "多线程",
        "线程",
        "弹窗",
        "通知",
        "静音",
        "任务",
        "窗口",
        "待办",
        "效率",
        "开机",
        "工作流",
        "优先级",
        "编程",
        "代码",
        "模型",
    ]

    # 早安/午安/晚安播报尾语池（[v5.32] 重构：从硬塞转化引导改为场景化温柔收尾）
    # 用户反馈"再加的东西特别尬" → 移除所有"私聊我""来找我""戳我"等生硬营销话术
    MORNING_SUFFIXES: List[str] = [
        "\n\n早上好，今天按自己的节奏来。",
        "\n\n新一天开始了，有想聊的直接在群里说。",
        "\n\n早安，先处理眼前最重要的一件事。",
        "\n\n今天也不用赶，稳稳开始就好。",
    ]

    AFTERNOON_SUFFIXES: List[str] = [
        "\n\n下午好，剩下的事一件一件来。",
        "\n\n午安，有空就在群里聊两句。",
        "\n\n下午继续，按自己的节奏推进。",
        "\n\n今天过半了，先顾好当前这一件事。",
    ]

    EVENING_SUFFIXES: List[str] = [
        "\n\n晚上好，今天辛苦了。",
        "\n\n晚安，剩下的事明天再处理。",
        "\n\n准备休息的话，就先把今天放下。",
        "\n\n晚上有想聊的，也可以直接在群里说。",
    ]

    # 叫醒服务备用文案池
    WAKEUP_FALLBACKS: List[str] = [
        "到你设定的叫醒时间了，该起床了。",
        "叫醒提醒到了，醒来后慢慢开始今天。",
        "现在是你设定的起床时间，别忘了关闹钟。",
        "该起床了，这是你之前设置的叫醒提醒。",
    ]

    # 非活跃用户关心：中性、无销售、无关系施压。
    REACTIVATE_FALLBACKS: List[str] = [
        "最近还好吗？有空回群里打个招呼就行，不急。",
        "好久没见你冒泡了，希望你最近一切顺利。",
        "路过问候一下。忙你的就好，有空再回来聊。",
        "最近怎么样？不用特意回复，照顾好自己就行。",
    ]

    # 购物车召回只允许发送一次温和预览提醒；三组保留是为了兼容旧 stage。
    CART_RECOVERY_STAGE_1: List[str] = [
        "刚才想了解的内容，可以先去 @moryselect 看预览。没写清楚的再问我呀，不急。",
    ]

    # 旧 stage 1/2 不再改变口径，避免虚假福利、稀缺和多阶段骚扰。
    CART_RECOVERY_STAGE_2: List[str] = [
        "刚才想了解的内容，可以先去 @moryselect 看预览。没写清楚的再问我呀，不急。",
    ]

    # 旧 stage 2 同样只给预览，不制造情感负担。
    CART_RECOVERY_STAGE_3: List[str] = [
        "刚才想了解的内容，可以先去 @moryselect 看预览。没写清楚的再问我呀，不急。",
    ]

    # 旧版通用备用文案（保留兼容）
    CART_RECOVERY_FALLBACKS: List[str] = [
        "刚才想了解的内容，可以先去 @moryselect 看预览。没写清楚的再问我呀，不急。",
    ]

    # 挽回阶段 → 文案池映射
    CART_RECOVERY_POOLS = {
        0: CART_RECOVERY_STAGE_1,
        1: CART_RECOVERY_STAGE_2,
        2: CART_RECOVERY_STAGE_3,
    }

    # 塔罗互动仅在群内承接话题，不虚构隐藏内容、不导私聊。
    TAROT_HOOKS: List[str] = [
        "你更在意这张牌里的哪一句？可以直接在群里聊。",
        "这只是轻松互动，哪部分有共鸣就说哪部分。",
        "如果你愿意，可以在群里说说你最近最关心的事。",
    ]

    # 非事实互动前缀：不再声称掌握 Mory 的私生活或秘密。
    LEAK_PREFIXES: List[str] = [
        "来个不涉及真实隐私的轻互动：\n\n",
        "今天换个轻松话题：\n\n",
        "群里做个小选择题：\n\n",
    ]
    WEEKLY_INTERACTION_QUESTIONS: List[str] = [
        "今天用一个词形容心情，你会选什么？",
        "最近循环最多的一首歌是什么？",
        "如果今天能多出一小时，你会拿来做什么？",
        "这周有什么小事让你觉得还不错？",
    ]

    # 问候话术池：AI 失败时也不虚构天气/行程，不使用咖啡、阳光等固定场景。
    GREETING_FALLBACK_POOL = {
        "morning": [
            "早上好。今天想聊什么，直接在群里说就行。",
            "早安。新一天开始了，大家按自己的节奏来。",
            "早。大家路过群里就打个招呼，随便聊点什么都行。",
            "早上好。新朋友和老朋友都可以直接参与群里话题。",
        ],
        "afternoon": [
            "下午好。今天过得怎么样，可以直接在群里聊。",
            "午安。大家有想分享的，就在群里说两句。",
            "下午了。大家顺利或不顺利，都可以正常聊聊。",
            "午安。大家路过就冒个泡，不用特意组织话题。",
        ],
        "evening": [
            "晚上好。今天过得怎么样，可以在群里聊聊。",
            "到晚上了。大家白天没空说的话，现在说也不迟。",
            "晚安前大家路过群里，想分享什么都可以。",
            "晚上好。大家今天有没有一件值得记住的小事？",
        ],
    }

    # AI 主体已包含功能引导时的关键词检测
    SUFFIX_TRIGGER_KEYWORDS: List[str] = ["私聊", "找我", "戳我", "误封", "有问题", "来找我", "找我私"]

    @classmethod
    def get_dynamic_suffix(cls, time_period: str) -> str:
        """根据时段获取随机播报尾语。"""
        if time_period == "morning":
            return random.choice(cls.MORNING_SUFFIXES)
        elif time_period == "afternoon":
            return random.choice(cls.AFTERNOON_SUFFIXES)
        elif time_period == "evening":
            return random.choice(cls.EVENING_SUFFIXES)
        return random.choice(cls.MORNING_SUFFIXES + cls.AFTERNOON_SUFFIXES + cls.EVENING_SUFFIXES)

    @classmethod
    def needs_suffix(cls, msg: str) -> bool:
        """判断 AI 生成的播报是否已包含功能引导，需要补 suffix 则返回 True。"""
        return not any(kw in msg for kw in cls.SUFFIX_TRIGGER_KEYWORDS)

    @classmethod
    def get_fallback_greeting(cls, period: str) -> str:
        """从话术池随机选择问候语。"""
        pool = cls.GREETING_FALLBACK_POOL.get(period, [])
        if pool:
            return random.choice(pool)
        return "你好"

    @classmethod
    def is_usable_greeting(cls, period: str, text) -> bool:
        """拦住引擎异常、内部字样和已确认僵硬套路，失败时使用可信话术池。"""
        if not isinstance(text, str):
            return False
        value = text.strip()
        min_length = 25 if period == "night" else 30
        if not min_length <= len(value) <= 120:
            return False
        return not any(marker in value for marker in cls.GREETING_STYLE_BAN)

    @classmethod
    def get_wakeup_fallback(cls) -> str:
        return random.choice(cls.WAKEUP_FALLBACKS)

    @classmethod
    def get_reactivate_fallback(cls) -> str:
        return random.choice(cls.REACTIVATE_FALLBACKS)

    @classmethod
    def get_cart_recovery_text(cls, stage: int) -> str:
        """根据挽回阶段获取文案。"""
        pool = cls.CART_RECOVERY_POOLS.get(stage, cls.CART_RECOVERY_FALLBACKS)
        return random.choice(pool)

    @classmethod
    def get_tarot_hook(cls) -> str:
        return random.choice(cls.TAROT_HOOKS)

    @classmethod
    def get_leak_prefix(cls) -> str:
        return random.choice(cls.LEAK_PREFIXES)

    @classmethod
    def get_weekly_interaction_question(cls) -> str:
        return random.choice(cls.WEEKLY_INTERACTION_QUESTIONS)
