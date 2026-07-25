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
        "\n\n今天的状态对，节奏就跟着走。",
        "\n\n咖啡配阳光，今天不容易卡壳。",
        "\n\n慢慢来，今天比昨天顺一点就行。",
        "\n\n早安，今天别把自己逼太紧。",
        "\n\n起得来就是好事，慢慢进入节奏。",
        "\n\n今天的咖啡温度刚好，状态也在线。",
        "\n\n窗外天气不错，今天的节奏可以稳一点。",
        "\n\n早安，今天该来的会来，先把手头的理顺。",
    ]

    AFTERNOON_SUFFIXES: List[str] = [
        "\n\n下午容易卡，喝口水缓一缓。",
        "\n\n午后犯困正常，眯十分钟再继续。",
        "\n\n下午的活儿慢慢推，别一上来就硬扛。",
        "\n\n午安，今天的进度比昨天好一点就够了。",
        "\n\n下午的节奏可以慢一拍，不用一直绷着。",
        "\n\n犯困就站起来走走，比硬撑管用。",
        "\n\n午安，今天过半了，剩下的事一件一件来。",
        "\n\n下午的光线正好，状态回来了就好。",
    ]

    EVENING_SUFFIXES: List[str] = [
        "\n\n晚上别再赶了，今天的事今天算完。",
        "\n\n晚安前把明天的事理一两条，明天会顺很多。",
        "\n\n睡前别刷太久手机，眼睛先休息。",
        "\n\n晚安，今天的疲惫放下，明天再开始。",
        "\n\n晚上适合放空，不用一直想着明天的安排。",
        "\n\n晚安，今天的事别带到床上想。",
        "\n\n睡前可以听点轻音乐，比刷视频容易入睡。",
        "\n\n晚安，今天的节奏已经够了，剩下交给明天。",
    ]

    # 叫醒服务备用文案池
    WAKEUP_FALLBACKS: List[str] = [
        "该起了，再不起床今天又要赶了。",
        "醒了没？新的一天，别浪费。",
        "起来了，别赖床，今天还有事。",
        "早，别睡了，起来干活。",
        "起床，太阳都晒半天了。",
        "起来了，咖啡都凉了。",
        "醒醒，今天也要好好过。",
        "该起了，别让我说第二遍。",
    ]

    # 醋意挽回备用文案池
    REACTIVATE_FALLBACKS: List[str] = [
        "你人呢，群里都安静好几天了。",
        "最近怎么没看到你了，群里都没你？",
        "最近挺忙的？好久没见你了。",
        "你是不是把我忘了，群里都没你？",
        "最近不来找我，是有什么事吗？",
        "好久没聊了，最近过得怎么样。",
        "你不在群里说话，我都不知道你在干嘛了。",
        "最近群里都没你，我还以为你把我删了呢。",
    ]

    # 购物车挽回：阶段 0（15分钟，傲娇催促）
    CART_RECOVERY_STAGE_1: List[str] = [
        "哼，刚才话说到一半人就跑了…是不是又去刷别的群了？",
        "你刚才问完就跑，我还没说完呢…回来。",
        "喂，你该不会是在货比三家吧？我感受到了哦。",
        "刚聊到关键你就消失，故意的吧？回来把话说完。",
        "你就这么走了？我白跟你聊那么多了…哼。",
        "问完价格就跑，你是来逗我的吗～回来。",
        "刚才不是说有兴趣吗？怎么转眼人就没了，回来。",
        "你这个人…撩完就跑，再来聊两句嘛。",
    ]

    # 购物车挽回：阶段 1（2小时，利益诱导）
    CART_RECOVERY_STAGE_2: List[str] = [
        "悄悄告诉你，今天找我下单的人，我都给了额外福利…你懂的。",
        "刚才整理了一下，发现还有几张专属优惠没用出去…你想要吗？",
        "有些东西，越早来的人越划算。你懂的～",
        "我刚算了一下，你今天来的话，刚好能赶上这一波…",
        "偷偷跟你说，今天的名额还剩最后几个，过了就没了哦。",
        "我这边有个小惊喜，只给主动来找我的人…你猜是什么？",
        "刚才有人来问，我都没给这个价…你不一样。",
        "今天还有个隐藏福利，就看你来不来了～",
    ]

    # 购物车挽回：阶段 2（24小时，清冷关怀）
    CART_RECOVERY_STAGE_3: List[str] = [
        "一天了，你还没想好呀。没关系，我等你。",
        "昨天的事，如果你改变主意了，我一直都在。",
        "其实你不用急着决定，我只是想确认你还好吗。",
        "不管你最后怎么选，能跟你聊那几句，我已经很开心了。",
        "有些事不用勉强，但如果你想继续聊，我随时在。",
        "上次聊到一半你就走了，我其实有点在意。不过没关系。",
        "如果真的没缘分，那也没关系。只是想说，我还在。",
        "走了的人很多，但回来的人很少。你是哪一种？",
    ]

    # 旧版通用备用文案（保留兼容）
    CART_RECOVERY_FALLBACKS: List[str] = [
        "昨天你问的那个事，还想了解吗？来找我聊。",
        "昨天好像还有话没说完？我在，随时来。",
        "还在犹豫？有些事慢慢聊就清楚了，来找我。",
        "昨天聊到一半你就走了，来继续聊？",
        "你昨天问的那个，我这边还有后续，来聊聊。",
        "有些事群里不方便细说，来私聊我给你讲。",
        "昨天没聊完的，我这边还有你感兴趣的，来看看。",
        "别纠结了，来找我聊聊，说不定有答案。",
    ]

    # 挽回阶段 → 文案池映射
    CART_RECOVERY_POOLS = {
        0: CART_RECOVERY_STAGE_1,
        1: CART_RECOVERY_STAGE_2,
        2: CART_RECOVERY_STAGE_3,
    }

    # 塔罗搭讪转化钩子池
    TAROT_HOOKS: List[str] = [
        "这牌后面还有内容，想知道来找我。",
        "这张牌还有另一层意思，私聊我跟你说。",
        "有些话这里说不完，来私聊我。",
        "今天这牌还有后半段，来找我聊。",
        "你今天的运势还有隐藏内容，来找我看看。",
        "光看这几行不够，后面还有，来找我。",
        "这运势只是冰山一角，来私聊我细说。",
        "今天的好事不止这些，来找我聊聊。",
        "这牌暗示的东西比表面深，来找我聊。",
        "想知道这张牌真正想说啥吗，来找我。",
        "有些缘分得慢慢聊才能懂，来私聊我。",
        "今天运势后面跟着个小惊喜，来找我。",
        "这牌的解读嘛，三言两语说不清，来找我。",
        "有些话得悄悄说才更有味道，来私聊我。",
        "我还有个更详细的版本，来找我看看。",
        "这牌的深层含义，私聊我跟你说。",
        "运势卡片背后还写了句话，来找我聊。",
    ]

    # 背刺泄密前缀池
    LEAK_PREFIXES: List[str] = [
        "Mory不在，偷偷跟你们说：\n\n",
        "嘘——别告诉Mory我说的：\n\n",
        "趁Mory不注意，偷偷爆料：\n\n",
        "你们凑过来，我只说一次：\n\n",
        "偷偷告诉你们一个秘密：\n\n",
        "她让我保密的，但我想跟你们说：\n\n",
        "嘘——这个你们肯定不知道：\n\n",
    ]

    # 问候话术池：AI 失败时也不虚构天气/行程，不使用咖啡、阳光等固定场景。
    GREETING_FALLBACK_POOL = {
        "morning": [
            "早呀，你们醒了就来群里冒个泡。哪怕只说一句，我也想知道今天第一个出现的是谁。",
            "早安。新一天不急着说漂亮话，你们好好在，我就会认真记住每一次出现。",
            "早。看到你们陆续出现，群里才算真的醒了。今天谁先来跟我说句话？",
            "早安呀。老朋友不用客套，新朋友也别躲着，你们愿意来，我就愿意认真听。",
        ],
        "afternoon": [
            "午安呀。忙到现在也该歇口气了，你们在群里冒个泡，我看到就会回。",
            "下午好。突然想问问你们今天过得怎么样，顺利也好、烦也好，都可以在群里说。",
            "午安。你们不说话的时候群里会有点安静，随便来一句也行，我在听。",
            "下午过半啦。今天有什么想分享的就丢群里，开心的不开心的，我都愿意接住。",
        ],
        "evening": [
            "晚上好。今天过得怎么样，不想讲大道理也没关系，来群里说句真的就好。",
            "晚安前来看看你们。开心的可以分享，难受的也不用装没事，我会认真听。",
            "到晚上啦。白天没空说的话，现在丢群里也不迟，老朋友的消息我不会敷衍。",
            "晚上好呀。你们今天有没有一句特别想说的话？别藏着，群里有人愿意接住。",
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
