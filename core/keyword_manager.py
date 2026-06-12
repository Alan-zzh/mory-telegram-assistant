"""
core/keyword_manager.py  ·  统一关键词与静态数据管理器

功能：
  1. 从 config.json 加载关键词类数据（广告检测、自动禁言、商业转化等）
  2. 从 data/*.json 加载静态内容数据（塔罗牌、运势签、勋章等）
  3. 提供统一的数据访问接口，消除各模块硬编码
  4. 支持 reload() 热重载，无需重启即可更新关键词

数据存储策略：
  - 关键词类 → config.json（已有 AUTO_MUTE_NAMES / BANNED_WORDS / HATE_KEYWORDS，
    新增 AD_KEYWORDS / CONVERT_KEYWORDS）
  - 静态内容类 → data/*.json（独立文件，便于编辑和版本管理）
  - 所有数据内存缓存，读取零开销

依赖：config dict, data/ 目录
被调用：bot_initializer → KeywordManager(config, db)
"""

import json
import os
import threading
from core.logging_util import get_logger

logger = get_logger("keyword_manager")

# 项目根目录
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")


class KeywordManager:
    """统一的关键词与静态数据管理器"""

    def __init__(self, config: dict, db=None):
        self._config = config
        self._db = db
        self._cache = {}
        self._lock = threading.Lock()
        self._load_all_data()

    # ─────────────────────── 数据加载 ───────────────────────

    def _load_all_data(self):
        """加载所有关键词和静态数据"""
        # 从 config.json 加载关键词
        self._cache["ad_keywords"] = self._config.get("AD_KEYWORDS", _DEFAULT_AD_KEYWORDS)
        self._cache["auto_mute_names"] = self._config.get("AUTO_MUTE_NAMES", _DEFAULT_AUTO_MUTE_NAMES)
        self._cache["convert_keywords_substr"] = self._config.get(
            "CONVERT_KEYWORDS", {}
        ).get("substr", _DEFAULT_CONVERT_SUBSTR)
        self._cache["convert_keywords_word"] = self._config.get(
            "CONVERT_KEYWORDS", {}
        ).get("word", _DEFAULT_CONVERT_WORD)

        # 从 data/*.json 加载静态内容（文件不存在则用内置默认值）
        self._cache["tarot_cards"] = self._load_json_file(
            "tarot_cards.json", _DEFAULT_TAROT_CARDS
        )
        self._cache["fortune_texts"] = self._load_json_file(
            "fortune_texts.json", _DEFAULT_FORTUNE_TEXTS
        )
        self._cache["badges"] = self._load_json_file(
            "badges.json", _DEFAULT_BADGES
        )

        logger.info(
            f"KeywordManager 加载完成: "
            f"ad={len(self._cache['ad_keywords'])} "
            f"mute={len(self._cache['auto_mute_names'])} "
            f"convert_substr={len(self._cache['convert_keywords_substr'])} "
            f"convert_word={len(self._cache['convert_keywords_word'])} "
            f"tarot={len(self._cache['tarot_cards'])} "
            f"fortune={len(self._cache['fortune_texts'])} "
            f"badges={len(self._cache['badges'])}"
        )

    def _load_json_file(self, filename: str, fallback) -> dict | list:
        """加载 data/ 目录下的 JSON 文件，失败时返回 fallback"""
        filepath = os.path.join(_DATA_DIR, filename)
        if not os.path.exists(filepath):
            logger.debug(f"数据文件不存在，使用内置默认值: {filename}")
            return fallback
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"已加载数据文件: {filename} ({len(data)} 项)")
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"数据文件加载失败，使用内置默认值: {filename} ({e})")
            return fallback

    # ─────────────────────── 公开接口 ───────────────────────

    def get_ad_keywords(self) -> list:
        """获取广告检测关键词列表"""
        return self._cache.get("ad_keywords", _DEFAULT_AD_KEYWORDS)

    def get_auto_mute_names(self) -> list:
        """获取自动禁言关键词列表"""
        return self._cache.get("auto_mute_names", _DEFAULT_AUTO_MUTE_NAMES)

    def get_convert_keywords_substr(self) -> list:
        """获取商业转化关键词（子串匹配）"""
        return self._cache.get("convert_keywords_substr", _DEFAULT_CONVERT_SUBSTR)

    def get_convert_keywords_word(self) -> list:
        """获取商业转化关键词（全词匹配）"""
        return self._cache.get("convert_keywords_word", _DEFAULT_CONVERT_WORD)

    def get_tarot_cards(self) -> dict:
        """获取塔罗牌库"""
        return self._cache.get("tarot_cards", _DEFAULT_TAROT_CARDS)

    def get_fortune_texts(self) -> list:
        """获取运势签库"""
        return self._cache.get("fortune_texts", _DEFAULT_FORTUNE_TEXTS)

    def get_badges(self) -> dict:
        """获取勋章定义"""
        return self._cache.get("badges", _DEFAULT_BADGES)

    def reload(self):
        """重新加载数据（用于配置更新后热重载）"""
        with self._lock:
            self._cache.clear()
            self._load_all_data()
        logger.info("KeywordManager 数据已重新加载")

    # ─────────────────────── 便捷方法 ───────────────────────

    def is_convert_message(self, msg: str) -> bool:
        """判断消息是否属于商业咨询类（统一入口，替代 _is_convert_message）"""
        if not msg:
            return False
        # 子串匹配
        if any(k in msg for k in self.get_convert_keywords_substr()):
            return True
        # 全词匹配
        import re as _re
        words = _re.split(r'[^\u4e00-\u9fff]+', msg)
        words = [w for w in words if w]
        for w in words:
            if w in self.get_convert_keywords_word():
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════
#  内置默认值（当 config.json 或 data/*.json 中没有配置时使用）
# ═══════════════════════════════════════════════════════════════════════

_DEFAULT_AD_KEYWORDS = [
    "加我", "私聊我", "私我", "关注我", "点击链接", "点我", "扫码",
    "赚钱", "日入", "日赚", "日挣", "月入", "躺赚", "稳赚", "暴利",
    "兼职", "副业", "刷单", "做任务", "拉人头",
    "免费领", "免费送", "限时优惠", "抢购", "秒杀",
    "微信号", "QQ群", "Telegram群", "群号",
    "http://", "https://", "t.me/", "t.me+",
    "菠菜", "博彩", "赌博", "娱乐城", "真人视讯",
    "贷款", "信用卡", "套现", "代还",
    "代购", "微商", "代理", "加盟",
    "红包", "返利", "佣金", "拉新",
    "推广", "引流", "精准引流", "涨粉",
    "网赚", "网赚项目", "创业项目", "无货源",
    "日结", "周结", "手工活", "手机赚钱",
    "投注", "彩票", "六合彩", "时时彩",
    "裸聊", "约炮", "同城交友", "上门服务",
    "搬砖", "招团队", "虚拟币", "数字货币", "加密货币",
    "找人合作", "合作",
    "新手", "当天上手", "就能上手", "零基础",
]

_DEFAULT_AUTO_MUTE_NAMES = [
    # 加密货币类
    "虚拟币", "搬砖", "币圈", "炒币", "数字货币",
    "加密货币", "区块链投资", "合约交易", "量化交易",
    "USDT", "BTC", "ETH交易", "空投", "挖矿",
    # 赚钱黑话类
    "日入", "日赚", "日挣", "躺赚", "稳赚", "暴利",
    "月入", "年入", "保底", "零成本", "无风险",
    "搞米", "安全搞米", "放电宝", "充电宝",
    # 招募引流类
    "招团队", "拉人头", "招代理", "招加盟",
    "兼职", "副业", "刷单", "做任务",
    # 色情引流类
    "裸聊", "约炮", "同城交友", "上门服务",
    # 灰色产业类
    "洗钱", "跑分", "代付", "代收", "资金盘",
    "博彩", "赌博", "娱乐城", "菠菜",
    # 联系方式引流类
    "加我", "私聊我", "私我", "关注我", "点击链接",
    "微信号", "QQ群", "Telegram群", "群号",
    "看简介", "看我简介", "看我主页", "看我资料",
    # 一眼广告词
    "各地", "约", "学生", "M36D", "白虎",
    "传递", "800约", "各地约",
]

_DEFAULT_CONVERT_SUBSTR = [
    # 原 v5.0 关键词
    "多少钱", "价格", "怎么买", "门槛", "开通", "会员",
    # 订阅/付费类
    "订阅", "月付", "年付", "季付", "周付", "包月", "包年", "包季",
    "续费", "充值", "解锁", "购买", "付费", "升级", "付款", "支付",
    # 权益/权限类
    "权益", "权限", "会员群", "VIP群",
    # 怎么加入/联系类
    "怎么进", "怎么加", "怎么联系", "怎么私聊",
    # 价格比较类
    "便宜", "划算", "折扣", "优惠",
    # 主动索要看货类
    "看看", "想看", "给我", "发一下", "有没有", "能看", "能玩",
    # 其他常用
    "可以看", "可以用", "能不能", "几号",
    # 内容/观看类
    "视频", "观看",
]

_DEFAULT_CONVERT_WORD = []

_DEFAULT_TAROT_CARDS = {
    "愚人":     "❌ 鲁莽的新开始。今天要三思而后行。",
    "魔术师":   "✨ 掌握主动权的日子。该出手就出手。",
    "女祭司":   "🔮 神秘而深邃。今天会有惊喜发现。",
    "皇帝":     "👑 权力与掌控。你今天有主宰感。",
    "皇后":     "👸 优雅而富有。这是收获的预兆。",
    "教皇":     "⛪ 精神升华。修身养性的好时机。",
    "恋人":     "💕 二选一的困局，但无论选什么都是对的。",
    "战车":     "🏃 飞快前进。不要踩刹车。",
    "力量":     "💪 内在磨练成果。你比想象中更强大。",
    "隐士":     "🕯️ 沉默与思考的周期。充电时刻到了。",
    "命运之轮": "♻️ 轮回与变化。运气随时可能转向。",
    "正义":     "⚖️ 公平与因果。该来的都会来。",
    "倒吊人":   "🙃 换个角度看世界。困境即机遇。",
    "死神":     "💀 结束与开始的交界。不是坏事，是蜕变。",
    "节制":     "🌊 平衡与和谐。温和的力量最强大。",
    "恶魔":     "😈 欲望的引诱。要分辨真心与迷恋。",
    "塔":       "⚡ 突如其来的变故。改变后会更好。",
    "星星":     "⭐ 希望与憧憬。梦想就在不远处。",
    "月亮":     "🌙 直觉与潜意识。听从内心的声音。",
    "太阳":     "☀️ 光明与喜悦。好运马上就来。",
    "审判":     "📯 觉醒与重生。你将成为新的自己。",
    "世界":     "🌍 完成与圆满。一个完美的结局。",
}

_DEFAULT_FORTUNE_TEXTS = [
    "今日宜大胆，运气偏爱勇者。",
    "桃花暗涌，保持神秘感最迷人。",
    "财运流动，注意把握时机。",
    "贵人就在身边，多表达感谢。",
    "直觉比逻辑更准，相信自己。",
    "今天适合说出那句话。",
    "低调行事，暗中积累能量。",
    "一切顺遂，今日宜主动出击。",
    "静待花开，着急没有用。",
    "好事将至，耐心是你的武器。",
]

_DEFAULT_BADGES = {
    # 活跃类勋章
    "early_bird": {"name": "早起鸟", "emoji": "🐦", "desc": "每天8点前发消息"},
    "night_owl": {"name": "夜猫子", "emoji": "🦉", "desc": "每天23点后发消息"},
    "social_butterfly": {"name": "社牛", "emoji": "🦋", "desc": "群消息超过100条"},
    "chatty_cathy": {"name": "话痨", "emoji": "💬", "desc": "单日消息超过50条"},
    # 互动类勋章
    "first_fan": {"name": "铁粉", "emoji": "❤️", "desc": "连续7天活跃"},
    "super_fan": {"name": "超级铁粉", "emoji": "💖", "desc": "连续30天活跃"},
    "og_member": {"name": "OG会员", "emoji": "👑", "desc": "加入超过30天"},
    # 特殊类勋章
    "treasure_hunter": {"name": "寻宝达人", "emoji": "💎", "desc": "碎片寻宝满7天"},
    "tarot_master": {"name": "塔罗师", "emoji": "🔮", "desc": "查看运势超过10次"},
    "lucky_star": {"name": "幸运星", "emoji": "⭐", "desc": "被随机点名3次"},
    # 消费类勋章
    "early_adopter": {"name": "尝鲜客", "emoji": "🚀", "desc": "首日体验会员"},
    "loyal_customer": {"name": "老会员", "emoji": "💎", "desc": "连续付费超过3个月"},
}
