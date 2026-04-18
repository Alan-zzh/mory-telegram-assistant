"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/natural_cmd.py  ·  全能自然语言配置处理器                   ║
║                                                                        ║
║  【v21.38】支持所有配置项的自然语言修改                             ║
║                                                                        ║
║  指令格式：                                                           ║
║    查看配置 / 查看设置  -> 显示所有配置项及当前值                      ║
║    把[配置项]改成[值]    -> 修改指定配置                             ║
║    开启[功能] / 关闭[功能] -> 开关布尔配置                           ║
║    增加[配置项] [值]      -> 追加列表项                               ║
║    删除[配置项] [值]      -> 删除列表项                               ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import re
from core.logging_util import get_logger

logger = get_logger("natural_cmd")


# ══════════════════════════════════════════════════════════════════════════
# 【v21.38】完整配置清单 - 所有可配置的选项
# ══════════════════════════════════════════════════════════════════════════

ALL_CONFIGS = {
    # ═══════════════════════════════════════════════════════════════════════
    # 【A】核心互动配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "REPLY_CHANCE": {
        "category": "核心互动",
        "name": "群聊回复概率",
        "type": "number",
        "min": 0, "max": 100,
        "default": 10,
        "desc": "机器人主动回复群消息的概率",
        "examples": ["把回复概率改成20%", "回复几率调成50"]
    },
    
    "REPLY_DELAY_MIN": {
        "category": "核心互动",
        "name": "回复延迟下限",
        "type": "number",
        "min": 0, "max": 300,
        "default": 0,
        "desc": "机器人回复前的最短延迟(秒)",
        "examples": ["把回复延迟下限改成5秒"]
    },
    
    "REPLY_DELAY_MAX": {
        "category": "核心互动",
        "name": "回复延迟上限",
        "type": "number",
        "min": 0, "max": 600,
        "default": 30,
        "desc": "机器人回复前的最长延迟(秒)",
        "examples": ["把回复延迟上限改成60秒"]
    },
    
    "MAX_MSG_LENGTH": {
        "category": "核心互动",
        "name": "最大回复长度",
        "type": "number",
        "min": 10, "max": 5000,
        "default": 500,
        "desc": "AI单次回复的最大字符数",
        "examples": ["把最大回复长度改成1000"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【B】功能开关
    # ═══════════════════════════════════════════════════════════════════════
    
    "PUZZLE_ENABLED": {
        "category": "功能开关",
        "name": "碎片寻宝",
        "type": "boolean",
        "default": True,
        "desc": "群聊寻宝活动",
        "examples": ["开启碎片寻宝", "关闭寻宝"]
    },
    
    "PUZZLE_WORD": {
        "category": "功能开关",
        "name": "碎片暗号",
        "type": "text",
        "default": "寻宝",
        "desc": "触发寻宝的暗号",
        "examples": ["把碎片暗号改成888", "把暗号改成钻石"]
    },
    
    "SIGNUP_ENABLED": {
        "category": "功能开关",
        "name": "每日签到",
        "type": "boolean",
        "default": True,
        "desc": "每日签到功能",
        "examples": ["开启签到", "关闭签到"]
    },
    
    "AUTO_GREETING": {
        "category": "功能开关",
        "name": "每日早安",
        "type": "boolean",
        "default": True,
        "desc": "定时早安推送",
        "examples": ["开启早安", "关闭早安"]
    },
    
    "AUTO_GOODNIGHT": {
        "category": "功能开关",
        "name": "每日晚安",
        "type": "boolean",
        "default": True,
        "desc": "定时晚安推送",
        "examples": ["开启晚安", "关闭晚安"]
    },
    
    "AUTO_NEWS": {
        "category": "功能开关",
        "name": "新闻播报",
        "type": "boolean",
        "default": True,
        "desc": "定时新闻推送",
        "examples": ["开启新闻播报", "关闭新闻"]
    },
    
    "WELCOME_MSG": {
        "category": "功能开关",
        "name": "入群欢迎",
        "type": "boolean",
        "default": True,
        "desc": "新人入群欢迎",
        "examples": ["开启欢迎", "关闭欢迎"]
    },
    
    "ANTI_REVOKE": {
        "category": "功能开关",
        "name": "撤回检测",
        "type": "boolean",
        "default": False,
        "desc": "检测用户撤回的消息",
        "examples": ["开启防撤回", "关闭撤回检测"]
    },
    
    "BURN_AFTER": {
        "category": "功能开关",
        "name": "阅后即焚",
        "type": "boolean",
        "default": False,
        "desc": "敏感消息阅后自动删除",
        "examples": ["开启阅后即焚", "关闭即焚"]
    },
    
    "RECOVER_ENABLED": {
        "category": "功能开关",
        "name": "挽回功能",
        "type": "boolean",
        "default": True,
        "desc": "自动挽回流失用户",
        "examples": ["开启挽回", "关闭挽回"]
    },
    
    "AUTO_MORNING_NEWS": {
        "category": "功能开关",
        "name": "早间新闻",
        "type": "boolean",
        "default": True,
        "desc": "早上发送新闻",
        "examples": ["开启早间新闻", "关闭早间新闻"]
    },
    
    "AUTO_AFTERNOON_NEWS": {
        "category": "功能开关",
        "name": "午间新闻",
        "type": "boolean",
        "default": True,
        "desc": "中午发送新闻",
        "examples": ["开启午间新闻", "关闭午间新闻"]
    },
    
    "AUTO_EVENING_NEWS": {
        "category": "功能开关",
        "name": "晚间新闻",
        "type": "boolean",
        "default": True,
        "desc": "晚上发送新闻",
        "examples": ["开启晚间新闻", "关闭晚间新闻"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【C】时间调度配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "GREETING_HOUR": {
        "category": "时间调度",
        "name": "早安时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 9,
        "desc": "每日早安推送时间(小时)",
        "examples": ["把早安时间改成8点", "改成7点发早安"]
    },
    
    "GOODNIGHT_HOUR": {
        "category": "时间调度",
        "name": "晚安时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 22,
        "desc": "每日晚安推送时间(小时)",
        "examples": ["把晚安时间改成23点", "改成21点发晚安"]
    },
    
    "NEWS_HOUR_MORNING": {
        "category": "时间调度",
        "name": "早间新闻时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 9,
        "desc": "早间新闻推送时间(小时)",
        "examples": ["把早间新闻时间改成8点"]
    },
    
    "NEWS_HOUR_AFTERNOON": {
        "category": "时间调度",
        "name": "午间新闻时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 12,
        "desc": "午间新闻推送时间(小时)",
        "examples": ["把午间新闻时间改成11点"]
    },
    
    "NEWS_HOUR_EVENING": {
        "category": "时间调度",
        "name": "晚间新闻时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 18,
        "desc": "晚间新闻推送时间(小时)",
        "examples": ["把晚间新闻时间改成19点"]
    },
    
    "SIGNUP_RESET_HOUR": {
        "category": "时间调度",
        "name": "签到重置时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 0,
        "desc": "每日签到重置时间(小时)",
        "examples": ["把签到重置时间改成6点"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【D】安全与限制配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "SPAM_LIMIT": {
        "category": "安全限制",
        "name": "刷屏限制",
        "type": "spam",
        "default": {"messages_per_minute": 10, "ban_minutes": 5},
        "desc": "防刷屏：消息数/分钟 和 封禁时长",
        "examples": ["把刷屏限制改成5条", "改成每分钟3条"]
    },
    
    "MAX_REQUESTS_PER_USER": {
        "category": "安全限制",
        "name": "用户请求限制",
        "type": "number",
        "min": 1, "max": 1000,
        "default": 100,
        "desc": "单个用户每小时最大请求数",
        "examples": ["把用户请求限制改成50"]
    },
    
    "RATE_LIMIT_WINDOW": {
        "category": "安全限制",
        "name": "限流时间窗口",
        "type": "number",
        "min": 1, "max": 3600,
        "default": 3600,
        "desc": "限流计算时间窗口(秒)",
        "examples": ["把限流窗口改成1800秒"]
    },
    
    "BAN_DURATION_DEFAULT": {
        "category": "安全限制",
        "name": "默认封禁时长",
        "type": "number",
        "min": 1, "max": 10080,
        "default": 5,
        "desc": "刷屏默认封禁时长(分钟)",
        "examples": ["把默认封禁时长改成10分钟"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【E】AI模型配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "TEMPERATURE": {
        "category": "AI模型",
        "name": "创意温度",
        "type": "float",
        "min": 0.0, "max": 2.0,
        "default": 0.7,
        "desc": "AI回复的随机性(0=严谨, 2=创意)",
        "examples": ["把创意温度改成0.5", "调成1.2"]
    },
    
    "MAX_TOKENS": {
        "category": "AI模型",
        "name": "最大回复长度",
        "type": "number",
        "min": 50, "max": 8192,
        "default": 500,
        "desc": "AI单次回复最大token数",
        "examples": ["把最大token改成1000", "改成2048"]
    },
    
    "TOP_P": {
        "category": "AI模型",
        "name": "Top-P采样",
        "type": "float",
        "min": 0.0, "max": 1.0,
        "default": 0.8,
        "desc": "核采样概率阈值",
        "examples": ["把Top-P改成0.9"]
    },
    
    "FREQUENCY_PENALTY": {
        "category": "AI模型",
        "name": "频率惩罚",
        "type": "float",
        "min": -2.0, "max": 2.0,
        "default": 0.0,
        "desc": "重复惩罚(-2=鼓励重复, 2=避免重复)",
        "examples": ["把频率惩罚改成0.5"]
    },
    
    "PRESENCE_PENALTY": {
        "category": "AI模型",
        "name": "存在惩罚",
        "type": "float",
        "min": -2.0, "max": 2.0,
        "default": 0.0,
        "desc": "话题新鲜度惩罚",
        "examples": ["把存在惩罚改成0.3"]
    },
    
    "CURRENT_MODEL_INDEX": {
        "category": "AI模型",
        "name": "当前模型索引",
        "type": "number",
        "min": 0, "max": 100,
        "default": 0,
        "desc": "当前使用的AI模型序号",
        "examples": ["切换到第2个模型", "使用第3个模型"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【F】内容与互动配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "WELCOME_TEXT": {
        "category": "内容互动",
        "name": "欢迎语内容",
        "type": "text",
        "default": "欢迎入群~",
        "desc": "新人入群时发送的欢迎语",
        "examples": ["把欢迎语改成欢迎新朋友~", "改成Hello新朋友"]
    },
    
    "GREETING_TEMPLATE": {
        "category": "内容互动",
        "name": "早安模板",
        "type": "text",
        "default": "",
        "desc": "自定义早安问候语模板",
        "examples": ["把早安模板改成早上好呀~"]
    },
    
    "GOODNIGHT_TEMPLATE": {
        "category": "内容互动",
        "name": "晚安模板",
        "type": "text",
        "default": "",
        "desc": "自定义晚安问候语模板",
        "examples": ["把晚安模板改成晚安好梦~"]
    },
    
    "HATE_KEYWORDS": {
        "category": "内容互动",
        "name": "反感关键词",
        "type": "list",
        "default": ["丑", "假", "装", "垃圾", "死", "胖", "黑料"],
        "desc": "用户说这些词时机器人会冷淡回应",
        "examples": ["增加反感关键词滚", "删除反感关键词死"]
    },
    
    "BANNED_WORDS": {
        "category": "内容互动",
        "name": "敏感词",
        "type": "list",
        "default": ["赌博", "贩毒", "诈骗"],
        "desc": "消息包含这些词会被删除",
        "examples": ["增加敏感词菠菜", "删除敏感词诈骗"]
    },
    
    "AUTO_REPLY_TRIGGERS": {
        "category": "内容互动",
        "name": "自动回复触发词",
        "type": "list",
        "default": [],
        "desc": "包含这些词时必定回复",
        "examples": ["增加触发词在吗", "删除触发词你好"]
    },
    
    "IGNORE_BOTS": {
        "category": "内容互动",
        "name": "忽略的机器人",
        "type": "list",
        "default": ["afoolGroupBot"],
        "desc": "这些机器人的消息不处理",
        "examples": ["忽略新机器人xxx"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【G】数据与存储配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "LOG_LEVEL": {
        "category": "数据存储",
        "name": "日志级别",
        "type": "choice",
        "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
        "default": "INFO",
        "desc": "日志记录级别",
        "examples": ["把日志级别改成DEBUG", "改成WARNING"]
    },
    
    "BACKUP_INTERVAL": {
        "category": "数据存储",
        "name": "备份间隔",
        "type": "number",
        "min": 1, "max": 168,
        "default": 24,
        "desc": "自动备份间隔(小时)",
        "examples": ["把备份间隔改成12小时"]
    },
    
    "MAX_LOG_SIZE": {
        "category": "数据存储",
        "name": "日志大小限制",
        "type": "number",
        "min": 1, "max": 1000,
        "default": 100,
        "desc": "单日志文件最大MB",
        "examples": ["把日志大小限制改成50MB"]
    },
    
    # ═══════════════════════════════════════════════════════════════════════
    # 【H】价格与业务配置
    # ═══════════════════════════════════════════════════════════════════════
    
    "POINTS_PER_SIGNUP": {
        "category": "业务配置",
        "name": "签到积分",
        "type": "number",
        "min": 0, "max": 1000,
        "default": 10,
        "desc": "每次签到获得的积分",
        "examples": ["把签到积分改成20"]
    },
    
    "POINTS_PER_INVITE": {
        "category": "业务配置",
        "name": "邀请积分",
        "type": "number",
        "min": 0, "max": 1000,
        "default": 50,
        "desc": "邀请新用户获得的积分",
        "examples": ["把邀请积分改成100"]
    },
    
    "REPLY_STICKER_CHANCE": {
        "category": "业务配置",
        "name": "回复贴纸概率",
        "type": "number",
        "min": 0, "max": 100,
        "default": 0,
        "desc": "回复时附带贴纸的概率%",
        "examples": ["把贴纸概率改成30%"]
    },
    
    "MAX_STICKERS_PER_DAY": {
        "category": "业务配置",
        "name": "每日贴纸上限",
        "type": "number",
        "min": 0, "max": 1000,
        "default": 50,
        "desc": "每天最多发送的贴纸数",
        "examples": ["把每日贴纸上限定成100"]
    },
}


# ══════════════════════════════════════════════════════════════════════════
# 自然语言处理核心
# ══════════════════════════════════════════════════════════════════════════

def _extract_number(text: str) -> float | int | None:
    """从文本中提取数字"""
    patterns = [
        r'(\d+\.?\d*)%?',      # 带小数点的数字
        r'(\d+)条',           # 数字+条
        r'(\d+)分钟',         # 数字+分钟
        r'(\d+)秒',           # 数字+秒
        r'每分钟(\d+)',       # 每分钟+数字
        r'第(\d+)个?',        # 第X个
        r'(\d+)小时',         # 数字+小时
        r'(\d+)点',           # 数字+点（小时）
        r'改成(\d+\.?\d*)',   # 改成+数字
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            val_str = match.group(1)
            return float(val_str) if '.' in val_str else int(val_str)
    return None


def _parse_hour(text: str) -> int | None:
    """解析小时"""
    patterns = [
        r'(\d{1,2})点',
        r'凌晨(\d{1,2})',
        r'早上(\d{1,2})',
        r'中午(\d{1,2})',
        r'下午(\d{1,2})',
        r'晚上(\d{1,2})',
        r'夜里(\d{1,2})',
        r'改成\s*(\d{1,2})\s*点?',
        r'调成\s*(\d{1,2})\s*点?',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            hour = int(match.group(1))
            # 下午/晚上 > 12 的自动转换
            if '下午' in pattern or '晚上' in pattern:
                if hour <= 12:
                    hour += 12
            return max(0, min(23, hour))
    return None


def _find_config_key(msg: str) -> str | None:
    """根据消息内容找到对应的配置key"""
    msg_lower = msg.lower()
    
    # 配置名 -> key 的映射
    name_to_key = {}
    for key, info in ALL_CONFIGS.items():
        name_to_key[info["name"].lower()] = key
        # 添加别名
        aliases = {
            "回复概率": "REPLY_CHANCE",
            "回复几率": "REPLY_CHANCE",
            "回复延迟": "REPLY_DELAY_MAX",
            "回复长度": "MAX_MSG_LENGTH",
            "碎片寻宝": "PUZZLE_ENABLED",
            "寻宝": "PUZZLE_ENABLED",
            "暗号": "PUZZLE_WORD",
            "碎片暗号": "PUZZLE_WORD",
            "签到": "SIGNUP_ENABLED",
            "早安": "AUTO_GREETING",
            "晚安": "AUTO_GOODNIGHT",
            "新闻": "AUTO_NEWS",
            "欢迎": "WELCOME_MSG",
            "撤回": "ANTI_REVOKE",
            "即焚": "BURN_AFTER",
            "挽回": "RECOVER_ENABLED",
            "早安时间": "GREETING_HOUR",
            "晚安时间": "GOODNIGHT_HOUR",
            "刷屏": "SPAM_LIMIT",
            "防刷屏": "SPAM_LIMIT",
            "创意": "TEMPERATURE",
            "温度": "TEMPERATURE",
            "温度参数": "TEMPERATURE",
            "max_token": "MAX_TOKENS",
            "token": "MAX_TOKENS",
            "top-p": "TOP_P",
            "top_p": "TOP_P",
            "频率": "FREQUENCY_PENALTY",
            "存在": "PRESENCE_PENALTY",
            "模型": "CURRENT_MODEL_INDEX",
            "欢迎语": "WELCOME_TEXT",
            "日志": "LOG_LEVEL",
            "备份": "BACKUP_INTERVAL",
            "积分": "POINTS_PER_SIGNUP",
            "贴纸": "REPLY_STICKER_CHANCE",
            "反感词": "HATE_KEYWORDS",
            "敏感词": "BANNED_WORDS",
            "触发词": "AUTO_REPLY_TRIGGERS",
            "忽略": "IGNORE_BOTS",
        }
        for alias, key in aliases.items():
            name_to_key[alias.lower()] = key
    
    # 精确匹配
    for name, key in name_to_key.items():
        if name in msg_lower:
            return key
    
    # 部分匹配
    for key, info in ALL_CONFIGS.items():
        name_lower = info["name"].lower()
        # 检查关键词是否在消息中
        keywords = name_lower.replace(" ", "")
        if keywords[:4] in msg_lower:
            return key
    
    return None


def _build_friendly_help() -> str:
    """构建大白话版帮助文本"""
    lines = [
        "📋 Mory小助理 - 说话就能改配置！",
        "═" * 36,
        "",
        "【💬 你可以这样跟我说】",
        "",
        "🔢 调数字（把xxx改成数字）：",
        "  把回复概率改成30",
        "    → 机器人主动回复的频率",
        "  把刷屏限制改成5",
        "    → 超过5条/分钟就被禁言",
        "  把签到积分改成20",
        "    → 签到一次给20积分",
        "  把最大长度改成1000",
        "    → 机器人回复最长多少字",
        "",
        "🔘 开关功能（开启/关闭 + 功能名）：",
        "  开启碎片寻宝 / 关闭碎片寻宝",
        "    → 群里玩寻宝游戏",
        "  开启签到 / 关闭签到",
        "    → 用户可以每天签到领积分",
        "  开启早安 / 关闭早安",
        "    → 每天早上自动发早安",
        "  开启晚安 / 关闭晚安",
        "    → 每天晚上自动发晚安",
        "  开启新闻 / 关闭新闻",
        "    → 每天自动推送新闻",
        "  开启欢迎 / 关闭欢迎",
        "    → 新人进群自动打招呼",
        "  开启撤回检测 / 关闭撤回检测",
        "    → 记录谁撤回了消息",
        "",
        "⏰ 调时间（把xxx时间改成几点）：",
        "  把早安时间改成8点",
        "    → 早上8点发早安",
        "  把晚安时间改成23点",
        "    → 晚上11点发晚安",
        "",
        "📝 改文字内容：",
        "  把暗号改成888",
        "    → 寻宝暗号改成 888",
        "  把欢迎语改成欢迎新朋友~",
        "    → 新人进群的欢迎语",
        "",
        "🤖 调AI参数：",
        "  把温度调成0.5",
        "    → AI回复的创意程度",
        "  切换到第2个模型",
        "    → 换用别的AI模型",
        "",
        "📋 加/删列表项：",
        "  增加敏感词菠菜",
        "    → 说菠菜会被警告",
        "  删除敏感词赌博",
        "    → 把赌博从敏感词删掉",
        "",
        "═" * 36,
        "",
        "【🔐 只有管理员能用】",
        "",
        "发送「查看配置」看看现在都怎么设置的",
        "",
        "═" * 36,
    ]
    return "\n".join(lines)


def _handle_view_all_config(msg: str, config: dict, bot, m) -> bool:
    """处理「查看配置」或「查看指令」请求"""
    # 查看指令/帮助 -> 显示大白话说明
    help_keywords = ["查看指令", "帮助", "help", "怎么用", "有哪些指令", "教我怎么用", "指令说明"]
    if msg.strip() in help_keywords:
        bot.reply_to(m, _build_friendly_help())
        logger.info("用户查看指令说明")
        return True
    
    # 查看配置 -> 显示当前配置状态
    view_keywords = [
        "查看配置", "查看设置", "查看所有配置", "配置是什么",
        "现在怎么设置的", "有哪些配置", "查看全部"
    ]
    
    if msg.strip() in view_keywords:
        lines = [
            "⚙️ Mory小助理 完整配置清单",
            "=" * 36,
        ]
        
        # 按分类显示
        categories = {}
        for key, info in ALL_CONFIGS.items():
            cat = info["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((key, info))
        
        for cat, items in categories.items():
            lines.append("")
            lines.append(f"【{cat}】")
            for key, info in items:
                val = config.get(key, info["default"])
                
                # 格式化显示值
                if info["type"] == "boolean":
                    display = "开启" if val else "关闭"
                elif info["type"] == "number":
                    unit = info.get("unit", info.get("desc", "").split("(")[-1].split(")")[0] if "(" in info.get("desc", "") else "")
                    display = f"{val}{unit}" if unit else str(val)
                elif info["type"] == "float":
                    display = f"{val}"
                elif info["type"] == "spam":
                    if isinstance(val, dict):
                        display = f"{val.get('messages_per_minute', '?')}条/{val.get('ban_minutes', '?')}分钟"
                    else:
                        display = "未设置"
                elif info["type"] == "list":
                    display = f"[{len(val) if isinstance(val, list) else 0}项]"
                elif info["type"] == "text":
                    display = val[:20] + "..." if val and len(str(val)) > 20 else (val or "未设置")
                elif info["type"] == "choice":
                    display = val
                else:
                    display = str(val)[:30]
                
                lines.append(f"  {info['name']}: 【{display}】")
        
        lines.append("")
        lines.append("=" * 36)
        lines.append("")
        lines.append("💡 发送「查看指令」看大白话版使用说明")
        
        bot.reply_to(m, "\n".join(lines))
        logger.info("用户查看完整配置清单")
        return True
    
    return False


def _handle_toggle(msg: str, config: dict, bot, m, save_config_fn) -> bool:
    """处理开关命令"""
    msg_lower = msg.lower()
    
    is_enable = any(msg_lower.startswith(k) for k in ["开启", "打开", "启用", "开启"])
    is_disable = any(msg_lower.startswith(k) for k in ["关闭", "禁用", "停用"])
    
    if not (is_enable or is_disable):
        return False
    
    # 提取功能名
    action = "开启" if is_enable else "关闭"
    feature = msg_lower.replace("开启", "").replace("关闭", "").replace("打开", "").replace("启用", "").replace("禁用", "").replace("停用", "").strip()
    
    # 找到对应的配置key
    toggle_aliases = {
        "碎片": "PUZZLE_ENABLED",
        "寻宝": "PUZZLE_ENABLED",
        "签到": "SIGNUP_ENABLED",
        "早安": "AUTO_GREETING",
        "晚安": "AUTO_GOODNIGHT",
        "新闻": "AUTO_NEWS",
        "欢迎": "WELCOME_MSG",
        "撤回": "ANTI_REVOKE",
        "防撤回": "ANTI_REVOKE",
        "即焚": "BURN_AFTER",
        "阅后即焚": "BURN_AFTER",
        "挽回": "RECOVER_ENABLED",
        "早间新闻": "AUTO_MORNING_NEWS",
        "午间新闻": "AUTO_AFTERNOON_NEWS",
        "晚间新闻": "AUTO_EVENING_NEWS",
    }
    
    for alias, key in toggle_aliases.items():
        if alias in feature:
            config[key] = is_enable
            save_config_fn()
            bot.reply_to(m, f"✅ 已{action}「{ALL_CONFIGS.get(key, {}).get('name', key)}」")
            logger.info(f"{'ON' if is_enable else 'OFF'}: {key}")
            return True
    
    # 尝试精确匹配
    for key, info in ALL_CONFIGS.items():
        if info["type"] == "boolean" and info["name"].replace("功能", "") in feature:
            config[key] = is_enable
            save_config_fn()
            bot.reply_to(m, f"✅ 已{action}「{info['name']}」")
            logger.info(f"{'ON' if is_enable else 'OFF'}: {key}")
            return True
    
    return False


def _handle_modify_number(msg: str, config: dict, bot, m, save_config_fn) -> bool:
    """处理数值修改命令"""
    # 检查是否包含"改成"或"改成"
    if not ("改成" in msg or "改为" in msg or "调成" in msg or "调成" in msg or "改成" in msg):
        return False
    
    # 找到配置key
    key = _find_config_key(msg)
    if not key:
        return False
    
    info = ALL_CONFIGS.get(key)
    if not info:
        return False
    
    # 根据类型解析值
    val = None
    if info["type"] in ["number", "float"]:
        val = _extract_number(msg)
    elif info["type"] == "hour":
        val = _parse_hour(msg)
    elif info["type"] == "spam":
        val = _extract_number(msg)
    
    if val is None:
        return False
    
    # 范围检查
    if "min" in info and "max" in info:
        val = max(info["min"], min(info["max"], val))
    
    # 特殊处理
    if info["type"] == "float":
        val = float(val)
    elif info["type"] == "spam":
        # 刷屏限制是字典
        current = config.get(key, info["default"])
        if isinstance(current, str):
            try:
                current = json.loads(current)
            except:
                current = {}
        if not isinstance(current, dict):
            current = {"messages_per_minute": 10, "ban_minutes": 5}
        current["messages_per_minute"] = int(val)
        config[key] = current
        save_config_fn()
        bot.reply_to(m, f"✅ 已修改「{info['name']}」为每分钟 {int(val)} 条")
        logger.info(f"修改{key}: {val}")
        return True
    
    # 普通数值修改
    config[key] = val
    save_config_fn()
    
    # 格式化回复
    unit = info.get("unit", "")
    if info["type"] == "hour":
        unit = "点"
    display_val = f"{val}{unit}" if unit else str(val)
    
    bot.reply_to(m, f"✅ 已修改「{info['name']}」为 {display_val}")
    logger.info(f"修改{key}: {val}")
    return True


def _handle_modify_text(msg: str, config: dict, bot, m, save_config_fn) -> bool:
    """处理文本修改命令"""
    if not ("改成" in msg or "改为" in msg or "改成" in msg):
        return False
    
    text_configs = ["WELCOME_TEXT", "GREETING_TEMPLATE", "GOODNIGHT_TEMPLATE", "PUZZLE_WORD"]
    
    # 欢迎语
    if "欢迎语" in msg:
        # 提取引号内容
        match = re.search(r'[""\']([^"\']+)[""\']', msg)
        if match:
            text = match.group(1).strip()
        else:
            # 提取「」内容
            match = re.search(r'[「『]([^」』]+)[」』]', msg)
            if match:
                text = match.group(1).strip()
            else:
                # 提取"改成"后面的内容
                parts = re.split(r'改成|改为', msg)
                if len(parts) > 1:
                    text = parts[-1].strip().rstrip('。！？')
                else:
                    return False
        
        if text:
            config["WELCOME_TEXT"] = text
            save_config_fn()
            bot.reply_to(m, f"✅ 欢迎语已更新：{text[:50]}{'...' if len(text)>50 else ''}")
            logger.info(f"修改欢迎语: {text[:50]}")
            return True
    
    # 暗号
    if any(k in msg for k in ["暗号", "碎片暗号"]):
        match = re.search(r'[改成改为][^a-zA-Z0-9]?([^\s，。！？]+)', msg)
        if match:
            word = match.group(1).strip()
            config["PUZZLE_WORD"] = word
            save_config_fn()
            bot.reply_to(m, f"✅ 碎片暗号已设为「{word}」")
            logger.info(f"修改暗号: {word}")
            return True
    
    # 早安/晚安模板
    if "早安模板" in msg:
        match = re.search(r'[""\']([^"\']+)[""\']', msg)
        if match:
            text = match.group(1).strip()
            config["GREETING_TEMPLATE"] = text
            save_config_fn()
            bot.reply_to(m, f"✅ 早安模板已更新")
            return True
    
    if "晚安模板" in msg:
        match = re.search(r'[""\']([^"\']+)[""\']', msg)
        if match:
            text = match.group(1).strip()
            config["GOODNIGHT_TEMPLATE"] = text
            save_config_fn()
            bot.reply_to(m, f"✅ 晚安模板已更新")
            return True
    
    return False


def _handle_list_operations(msg: str, config: dict, bot, m, save_config_fn) -> bool:
    """处理列表操作（增加/删除）"""
    is_add = msg.startswith("增加") or msg.startswith("添加") or msg.startswith("新增")
    is_del = msg.startswith("删除") or msg.startswith("移除") or msg.startswith("去掉")
    
    if not (is_add or is_del):
        return False
    
    # 反感词
    if "反感词" in msg:
        key = "HATE_KEYWORDS"
        items = config.get(key, ALL_CONFIGS[key]["default"])
        if not isinstance(items, list):
            items = []
        
        # 提取词
        match = re.search(r'[词键][^a-zA-Z0-9]?([^\s，。！？]+)', msg)
        if match:
            word = match.group(1).strip()
        else:
            parts = re.split(r'增加|添加|删除|移除', msg)
            word = parts[-1].strip() if len(parts) > 1 else ""
        
        if not word:
            return False
        
        if is_add:
            if word not in items:
                items.append(word)
                config[key] = items
                save_config_fn()
                bot.reply_to(m, f"✅ 已增加反感词「{word}」")
            else:
                bot.reply_to(m, f"⚠️ 「{word}」已在列表中")
        else:
            if word in items:
                items.remove(word)
                config[key] = items
                save_config_fn()
                bot.reply_to(m, f"✅ 已删除反感词「{word}」")
            else:
                bot.reply_to(m, f"⚠️ 「{word}」不在列表中")
        return True
    
    # 敏感词
    if "敏感词" in msg:
        key = "BANNED_WORDS"
        items = config.get(key, ALL_CONFIGS[key]["default"])
        if not isinstance(items, list):
            items = []
        
        match = re.search(r'[词键][^a-zA-Z0-9]?([^\s，。！？]+)', msg)
        if match:
            word = match.group(1).strip()
        else:
            parts = re.split(r'增加|添加|删除|移除', msg)
            word = parts[-1].strip() if len(parts) > 1 else ""
        
        if not word:
            return False
        
        if is_add:
            if word not in items:
                items.append(word)
                config[key] = items
                save_config_fn()
                bot.reply_to(m, f"✅ 已增加敏感词「{word}」")
            else:
                bot.reply_to(m, f"⚠️ 「{word}」已在列表中")
        else:
            if word in items:
                items.remove(word)
                config[key] = items
                save_config_fn()
                bot.reply_to(m, f"✅ 已删除敏感词「{word}」")
            else:
                bot.reply_to(m, f"⚠️ 「{word}」不在列表中")
        return True
    
    return False


def _handle_model_switch(msg: str, config: dict, bot, m, save_config_fn) -> bool:
    """处理模型切换"""
    if not any(k in msg for k in ["切换", "使用", "换", "模型"]):
        return False
    
    # 切换到第X个
    match = re.search(r'第\s*(\d+)\s*个?', msg)
    if match:
        idx = int(match.group(1)) - 1  # 转成0-indexed
        pools = config.get("MODEL_POOLS", {}).get("llm", [])
        if 0 <= idx < len(pools):
            config["CURRENT_MODEL_INDEX"] = idx
            save_config_fn()
            model_name = pools[idx].get("name", f"模型{idx+1}")
            bot.reply_to(m, f"✅ 已切换到第{idx+1}个模型：{model_name}")
            logger.info(f"切换模型: {model_name}")
            return True
        else:
            bot.reply_to(m, f"⚠️ 模型序号超出范围(1-{len(pools)})")
            return True
    
    # 按名称切换
    model_pools = config.get("MODEL_POOLS", {}).get("llm", [])
    for i, model in enumerate(model_pools):
        model_name = model.get("name", "")
        if model_name and model_name in msg:
            config["CURRENT_MODEL_INDEX"] = i
            save_config_fn()
            bot.reply_to(m, f"✅ 已切换到模型：{model_name}")
            logger.info(f"切换模型: {model_name}")
            return True
    
    return False


# ══════════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════════

def handle_natural_admin(bot, m, config: dict, save_config_fn) -> bool:
    """
    处理自然语言配置指令。
    返回 True 表示已消费该消息。
    """
    msg = (m.text or "").strip()
    
    if not msg:
        return False
    
    # 1. 查看全部配置
    if _handle_view_all_config(msg, config, bot, m):
        return True
    
    # 2. 开关命令（开启/关闭xxx）
    if _handle_toggle(msg, config, bot, m, save_config_fn):
        return True
    
    # 3. 模型切换
    if _handle_model_switch(msg, config, bot, m, save_config_fn):
        return True
    
    # 4. 列表操作（增加/删除xxx）
    if _handle_list_operations(msg, config, bot, m, save_config_fn):
        return True
    
    # 5. 数值修改（把xxx改成yyy）
    if _handle_modify_number(msg, config, bot, m, save_config_fn):
        return True
    
    # 6. 文本修改
    if _handle_modify_text(msg, config, bot, m, save_config_fn):
        return True
    
    # 没有匹配
    return False
