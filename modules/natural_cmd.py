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
from datetime import datetime, timezone, timedelta

# 【v5.31.2 修复】VPS 运行在 UTC，显示给用户的时间必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))
from core.logging_util import get_logger

logger = get_logger("natural_cmd")


def _extract_quoted_text(msg: str) -> str:
    """优先提取引号或书名号里的内容。"""
    for pattern in [r'["“”\']([^"“”\']+)["“”\']', r'[「『]([^」』]+)[」』]']:
        match = re.search(pattern, msg)
        if match:
            return match.group(1).strip()
    return ""


def _get_special_auto_replies(config: dict) -> list:
    """确保特定词自动回复配置始终是列表。"""
    rules = config.get("SPECIAL_AUTO_REPLIES", [])
    if not isinstance(rules, list):
        rules = []
    config["SPECIAL_AUTO_REPLIES"] = rules
    return rules


def _normalize_keywords(text: str) -> list[str]:
    """把关键词文本拆成数组。"""
    if not text:
        return []
    raw = re.split(r"[，,、/|；;\s]+", text.strip())
    return [item.strip() for item in raw if item.strip()]


def _parse_named_fields(msg: str) -> dict:
    """解析 名称= / 关键词= / 回复= 这类字段。"""
    result = {}
    patterns = {
        "name": [r"名称\s*[=:：]\s*(.+?)(?=\s+(?:关键词|回复|润色模式|AI模式|启用|$)|$)"],
        "keywords": [r"关键词\s*[=:：]\s*(.+?)(?=\s+(?:名称|回复|润色模式|AI模式|启用|$)|$)"],
        "reply": [r"回复\s*[=:：]\s*(.+?)(?=\s+(?:名称|关键词|润色模式|AI模式|启用|$)|$)"],
        "ai_mode": [r"(?:润色模式|AI模式)\s*[=:：]\s*(.+?)(?=\s+(?:名称|关键词|回复|启用|$)|$)"],
    }
    for key, rule_list in patterns.items():
        for pattern in rule_list:
            match = re.search(pattern, msg, flags=re.IGNORECASE)
            if match:
                result[key] = match.group(1).strip().strip("；;，,。")
                break
    return result


def _find_special_rule(rules: list, hint: str):
    """按名称或关键词模糊定位特定回复规则。"""
    hint = (hint or "").strip().lower()
    if not hint:
        return None
    for rule in rules:
        name = str(rule.get("name", "")).strip().lower()
        if name == hint or (hint and hint in name):
            return rule
    for rule in rules:
        for kw in rule.get("keywords", []) or []:
            kw_text = str(kw).strip().lower()
            if kw_text == hint or (hint and hint in kw_text):
                return rule
    return None


def _build_special_reply_summary(rules: list) -> str:
    """生成特定回复列表摘要。"""
    if not rules:
        return "现在还没有设置特定词自动回复。"
    lines = ["🤖 当前特定词自动回复：", ""]
    for idx, rule in enumerate(rules, 1):
        status = "开启" if rule.get("enabled", True) else "关闭"
        keywords = " / ".join(rule.get("keywords", [])[:6]) or "未设关键词"
        base_reply = str(rule.get("base_reply", "")).strip()
        preview = base_reply[:38] + ("..." if len(base_reply) > 38 else "")
        lines.append(f"{idx}. {rule.get('name', f'规则{idx}')} [{status}]")
        lines.append(f"   关键词：{keywords}")
        lines.append(f"   回复：{preview or '未设回复'}")
    return "\n".join(lines)


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
    
    "REPLY_SPEED": {
        "category": "核心互动",
        "name": "回复速度",
        "type": "choice",
        "choices": ["fast", "normal", "slow", "human"],
        "default": "human",
        "desc": "回复速度模式：fast=秒回, normal=3-5秒, slow=5-12秒, human=智能拟人",
        "examples": ["把回复速度调成慢一点", "回复速度改成human", "调成fast"]
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
    
    "MYSTIC_BROADCAST_ENABLED": {
        "category": "功能开关",
        "name": "风水塔罗播报",
        "type": "boolean",
        "default": False,
        "desc": "早间风水、午间塔罗与晚间能量签",
        "examples": ["开启风水播报", "关闭塔罗播报"]
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
    
    "MYSTIC_HOUR_MORNING": {
        "category": "时间调度",
        "name": "早间风水时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 9,
        "desc": "早间风水小签时间(小时)",
        "examples": ["把早间风水时间改成8点"]
    },
    
    "MYSTIC_HOUR_AFTERNOON": {
        "category": "时间调度",
        "name": "午间塔罗时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 13,
        "desc": "午间塔罗牌时间(小时)",
        "examples": ["把午间塔罗时间改成14点"]
    },
    
    "MYSTIC_HOUR_EVENING": {
        "category": "时间调度",
        "name": "晚间能量签时间",
        "type": "hour",
        "min": 0, "max": 23,
        "default": 20,
        "desc": "晚间能量签时间(小时)",
        "examples": ["把晚间能量签时间改成21点"]
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


def _parse_hour(text: str, msg: str = "") -> int | None:
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
            if '下午' in msg or '晚上' in msg:
                if 0 < hour <= 12:
                    hour += 12
                elif hour == 12 and '晚上' in msg:
                    hour = 0
            return max(0, min(23, hour))
    return None


def _find_config_key(msg: str) -> str | None:
    """根据消息内容找到对应的配置key"""
    msg_lower = msg.lower()
    
    aliases = {
        "回复概率": "REPLY_CHANCE",
        "回复几率": "REPLY_CHANCE",
        "回复延迟": "REPLY_DELAY_MAX",
        "回复速度": "REPLY_SPEED",
        "回复长度": "MAX_MSG_LENGTH",
        "碎片寻宝": "PUZZLE_ENABLED",
        "寻宝": "PUZZLE_ENABLED",
        "暗号": "PUZZLE_WORD",
        "碎片暗号": "PUZZLE_WORD",
        "签到": "SIGNUP_ENABLED",
        "早安": "AUTO_GREETING",
        "晚安": "AUTO_GOODNIGHT",
        "早间风水时间": "MYSTIC_HOUR_MORNING",
        "午间塔罗时间": "MYSTIC_HOUR_AFTERNOON",
        "晚间能量签时间": "MYSTIC_HOUR_EVENING",
        "风水": "MYSTIC_BROADCAST_ENABLED",
        "塔罗播报": "MYSTIC_BROADCAST_ENABLED",
        "玄学播报": "MYSTIC_BROADCAST_ENABLED",
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

    name_to_key = {}
    for key, info in ALL_CONFIGS.items():
        name_to_key[info["name"].lower()] = key
        for alias, akey in aliases.items():
            name_to_key[alias.lower()] = akey
    
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


def _build_friendly_help(is_admin: bool = False) -> str:
    """构建大白话版帮助文本"""
    lines = [
        "📋 Mory小助理 - 说话就能聊！",
        "═" * 40,
        "",
    ]

    if not is_admin:
        lines.extend([
            "【🤖 我是谁】",
            "我是Mory，你的智能小助理",
            "可以陪你聊天、解答问题、帮你解决问题",
            "",
            "【💬 怎么跟我聊】",
            "直接发送消息即可，我会自动回复你",
            "不用记指令，像跟朋友聊天一样就行~",
            "",
            "【🌟 我能帮你】",
            "• 回答问题、聊天解闷",
            "• 推荐商品、介绍服务",
            "• 解决问题、提供帮助",
            "",
            "【🎯 怎么开始】",
            "发送「我要买东西」或「有什么推荐」",
            "我会一步步引导你找到想要的~",
            "",
            "═" * 40,
            "",
            "💬 有任何问题，直接问我就是！",
            "",
            "═" * 40,
        ])
    else:
        lines.extend([
            "【🔐 管理员指令】",
            "",
            "⚙️ 配置管理：",
            "  查看配置 / 查看设置",
            "    → 查看所有配置状态",
            "  设置概率 [0-100]",
            "    → 修改群聊随机回复概率",
            "  绑定主人",
            "    → 首次设置管理员",
            "  添加管理员",
            "    → 回复某人消息来添加其为管理员",
            "  查看管理员",
            "    → 查看所有管理员列表",
            "",
            "🧠 人设与知识：",
            "  设置人设 [文本]",
            "    → 修改机器人的核心人设",
            "  查看人设",
            "    → 查看当前人设内容",
            "  投喂资料 [文本]",
            "    → 追加业务知识库",
            "  查看资料",
            "    → 查看当前知识库内容",
            "  清空资料",
            "    → 清空知识库",
            "",
            "📢 消息管理：",
            "  代发 @ID 消息",
            "    → 私信任意用户",
            "  代发群 消息",
            "    → 以机器人名义发到主群",
            "  代发频道 消息",
            "    → 推送到所有频道",
            "  投票 问题 选项",
            "    → 群里发起投票",
            "",
            "📊 数据统计：",
            "  每日简报 / /report",
            "    → 生成运营数据简报",
            "  排行榜 / /rank",
            "    → 积分排行榜",
            "  查看画像 @用户ID",
            "    → 查看用户详细画像",
            "",
            "🤖 模型管理：",
            "  当前模型 / /model",
            "    → 查看所有模型和当前使用",
            "  切换模型 [名称]",
            "    → 手动切换AI模型",
            "  模型恢复 [模型名]",
            "    → 从黑名单恢复模型",
            "",
            "🚫 群管理：",
            "  /blacklist @ID",
            "    → 拉黑用户",
            "  /mute @ID 分钟",
            "    → 禁言用户（需机器人为群管理员）",
            "  清群无人理",
            "    → 删除群里所有无人回复的机器人消息",
            "  清全部回复",
            "    → 删除群里所有机器人的回复",
            "",
            "🧬 动态进化：",
            "  加热词 [词汇...]",
            "    → 给热词库追加新词汇",
            "  查热词",
            "    → 查看当前热词库",
            "  改风格 [描述]",
            "    → 快速调整说话风格",
            "  学知识 [内容]",
            "    → 让机器人学习新知识",
            "  忘记 [关键词]",
            "    → 从知识库中移除内容",
            "  进化 [指令]",
            "    → 高级进化：直接修改任意配置项",
            "",
            "═" * 40,
            "",
            "💡 提示：发送「查看配置」查看当前所有设置",
            "",
            "═" * 40,
        ])

    return "\n".join(lines)


def _handle_view_all_config(msg: str, config: dict, bot, m, mory_bot=None, is_admin: bool = False) -> bool:
    """处理「查看配置」或「查看指令」请求"""
    # 查看指令/帮助 -> 显示大白话说明
    help_keywords = [
        "查看指令", "帮助", "help", "怎么用", "有哪些指令", "教我怎么用", "指令说明",
        "你能做什么", "你有什么功能", "有什么指令", "功能列表", "指令列表",
        "启动指令", "开始指令", "如何使用", "使用说明", "操作指南",
        "指令", "帮助文档", "使用帮助"
    ]
    msg_stripped = msg.strip()
    if msg_stripped in help_keywords:
        mory_bot.reply_and_track(m, _build_friendly_help(is_admin=is_admin))
        logger.info("用户查看指令说明")
        return True

    # 自然语言触发（包含关键词）
    help_patterns = [
        "有哪些指令", "你能做什么", "什么功能", "功能列表", "指令列表",
        "怎么用", "如何使用", "使用说明", "操作指南",
        "有什么指令", "指令是什么", "怎么用你", "你能干嘛"
    ]
    msg_lower = msg_stripped.lower()
    for pattern in help_patterns:
        if pattern in msg_lower:
            mory_bot.reply_and_track(m, _build_friendly_help(is_admin=is_admin))
            logger.info("用户通过自然语言查看指令说明")
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
        
        mory_bot.reply_and_track(m, "\n".join(lines))
        logger.info("用户查看完整配置清单")
        return True
    
    return False


def _handle_special_auto_reply_config(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
    """处理特定词自动回复的自然语言配置。"""
    msg_clean = (msg or "").strip()
    markers = ["特定回复", "自动回复", "关键词回复", "特定词回复"]
    if not any(marker in msg_clean for marker in markers):
        return False

    rules = _get_special_auto_replies(config)

    if any(key in msg_clean for key in ["查看特定回复", "查看自动回复", "查看关键词回复", "看看特定回复", "列出特定回复"]):
        mory_bot.reply_and_track(m, _build_special_reply_summary(rules))
        return True

    is_add = msg_clean.startswith(("新增", "添加", "增加"))
    is_delete = msg_clean.startswith(("删除", "移除", "去掉"))
    is_modify = msg_clean.startswith(("修改", "编辑", "更新"))
    is_enable = msg_clean.startswith(("开启", "启用", "打开"))
    is_disable = msg_clean.startswith(("关闭", "禁用", "停用"))

    if is_add:
        fields = _parse_named_fields(msg_clean)
        keywords = _normalize_keywords(fields.get("keywords", ""))
        reply_text = fields.get("reply") or _extract_quoted_text(msg_clean)
        if not keywords or not reply_text:
            mory_bot.reply_and_track(
                m,
                "⚠️ 新增特定回复时，至少要告诉我关键词和回复内容。\n例子：新增特定回复 名称=价格咨询 关键词=价钱,价格,多少钱 回复=价格这块我不在群里说太满，你要是想细聊就直接来找我～"
            )
            return True
        rule_name = fields.get("name") or keywords[0]
        exists = _find_special_rule(rules, rule_name)
        if exists:
            mory_bot.reply_and_track(m, f"⚠️ 已经有「{exists.get('name', rule_name)}」这条规则了，直接发“修改特定回复 ...”就行。")
            return True
        rules.append({
            "name": rule_name,
            "enabled": True,
            "ai_polish": True,
            "ai_mode": fields.get("ai_mode", "convert_soft") or "convert_soft",
            "keywords": keywords,
            "base_reply": reply_text,
        })
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已新增特定回复「{rule_name}」\n关键词：{' / '.join(keywords)}")
        return True

    if is_delete:
        hint = msg_clean
        for prefix in ["删除", "移除", "去掉"]:
            hint = hint.replace(prefix, "", 1).strip()
        for marker in markers:
            hint = hint.replace(marker, "").strip()
        rule = _find_special_rule(rules, hint)
        if not rule:
            mory_bot.reply_and_track(m, "⚠️ 没找到你要删的那条特定回复，先发“查看特定回复”我给你列出来。")
            return True
        rules.remove(rule)
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已删除特定回复「{rule.get('name', '未命名规则')}」")
        return True

    if is_enable or is_disable:
        hint = msg_clean
        for prefix in ["开启", "启用", "打开", "关闭", "禁用", "停用"]:
            hint = hint.replace(prefix, "", 1).strip()
        for marker in markers:
            hint = hint.replace(marker, "").strip()
        rule = _find_special_rule(rules, hint)
        if not rule:
            mory_bot.reply_and_track(m, "⚠️ 没找到这条特定回复，先发“查看特定回复”确认一下名字。")
            return True
        rule["enabled"] = bool(is_enable)
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已{'开启' if is_enable else '关闭'}特定回复「{rule.get('name', '未命名规则')}」")
        return True

    if is_modify:
        body = msg_clean
        for prefix in ["修改", "编辑", "更新"]:
            body = body.replace(prefix, "", 1).strip()
        for marker in markers:
            body = body.replace(marker, "", 1).strip()
        fields = _parse_named_fields(msg_clean)

        hint = body
        for token in ["名称", "关键词", "回复", "润色模式", "AI模式", "=", "：", ":"]:
            idx = hint.find(token)
            if idx > 0:
                hint = hint[:idx].strip()
                break
        rule = _find_special_rule(rules, hint)
        if not rule:
            mory_bot.reply_and_track(m, "⚠️ 没找到你要修改的那条特定回复，先发“查看特定回复”看看现有规则。")
            return True

        changed = []
        if fields.get("name"):
            rule["name"] = fields["name"]
            changed.append("名称")
        if fields.get("keywords"):
            rule["keywords"] = _normalize_keywords(fields["keywords"])
            changed.append("关键词")
        if fields.get("reply"):
            rule["base_reply"] = fields["reply"]
            changed.append("回复")
        if fields.get("ai_mode"):
            rule["ai_mode"] = fields["ai_mode"]
            changed.append("润色模式")
        if not changed:
            quoted = _extract_quoted_text(msg_clean)
            if quoted:
                rule["base_reply"] = quoted
                changed.append("回复")

        if not changed:
            mory_bot.reply_and_track(
                m,
                "⚠️ 我听出来你想改特定回复了，但还缺一点信息。\n例子：修改特定回复 价格咨询 回复=价格这块我一般不在群里说太透，你想知道细一点就来找我。"
            )
            return True

        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已更新特定回复「{rule.get('name', '未命名规则')}」：{'、'.join(changed)}")
        return True

    return False


def _handle_toggle(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
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
        "风水": "MYSTIC_BROADCAST_ENABLED",
        "塔罗播报": "MYSTIC_BROADCAST_ENABLED",
        "玄学播报": "MYSTIC_BROADCAST_ENABLED",
        "欢迎": "WELCOME_MSG",
        "撤回": "ANTI_REVOKE",
        "防撤回": "ANTI_REVOKE",
        "即焚": "BURN_AFTER",
        "阅后即焚": "BURN_AFTER",
        "挽回": "RECOVER_ENABLED",
        "早间风水": "MYSTIC_BROADCAST_ENABLED",
        "午间塔罗": "MYSTIC_BROADCAST_ENABLED",
        "晚间能量签": "MYSTIC_BROADCAST_ENABLED",
    }
    
    for alias, key in toggle_aliases.items():
        if alias in feature:
            if key == "MYSTIC_BROADCAST_ENABLED":
                config.setdefault("MYSTIC_BROADCAST_CONFIG", {})["enabled"] = is_enable
                config.setdefault("NEWS_BROADCAST_CONFIG", {})["enabled"] = False
                config["AUTO_NEWS"] = False
            else:
                config[key] = is_enable
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 已{action}「{ALL_CONFIGS.get(key, {}).get('name', key)}」")
            logger.info(f"{'ON' if is_enable else 'OFF'}: {key}")
            return True
    
    # 尝试精确匹配
    for key, info in ALL_CONFIGS.items():
        if info["type"] == "boolean" and info["name"].replace("功能", "") in feature:
            if key == "MYSTIC_BROADCAST_ENABLED":
                config.setdefault("MYSTIC_BROADCAST_CONFIG", {})["enabled"] = is_enable
                config.setdefault("NEWS_BROADCAST_CONFIG", {})["enabled"] = False
                config["AUTO_NEWS"] = False
            else:
                config[key] = is_enable
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 已{action}「{info['name']}」")
            logger.info(f"{'ON' if is_enable else 'OFF'}: {key}")
            return True
    
    return False


def _handle_modify_choice(msg: str, config: dict, key: str, info: dict, m, save_config_fn, mory_bot=None) -> bool:
    """[Trae] 处理choice类型配置的修改（如回复速度）"""
    msg_lower = msg.lower()
    choices = info.get("choices", [])
    
    speed_aliases = {
        "快": "fast", "秒回": "fast", "快速": "fast", "最快": "fast",
        "正常": "normal", "中等": "normal", "默认": "normal",
        "慢": "slow", "慢点": "slow", "慢一点": "slow", "缓慢": "slow",
        "拟人": "human", "智能": "human", "像人": "human", "真人": "human",
    }
    
    for alias, val in speed_aliases.items():
        if alias in msg_lower:
            if val in choices:
                config[key] = val
                save_config_fn()
                speed_desc = {"fast": "秒回模式", "normal": "正常速度(3-5秒)", "slow": "慢速(5-12秒)", "human": "智能拟人(根据回复长度自动)"}
                mory_bot.reply_and_track(m, f"✅ 回复速度已调整为：{speed_desc.get(val, val)}")
                logger.info(f"修改{key}: {val}")
                return True
    
    for choice_val in choices:
        if choice_val in msg_lower:
            config[key] = choice_val
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 已修改「{info['name']}」为 {choice_val}")
            logger.info(f"修改{key}: {choice_val}")
            return True
    
    mory_bot.reply_and_track(m, f"⚠️ 可选值：{' / '.join(choices)}\n例如：把回复速度调成慢一点")
    return True


def _handle_modify_number(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
    """处理数值修改命令"""
    if not ("改成" in msg or "改为" in msg or "调成" in msg):
        return False
    
    key = _find_config_key(msg)
    if not key:
        return False
    
    info = ALL_CONFIGS.get(key)
    if not info:
        return False

    if info["type"] == "choice":
        return _handle_modify_choice(msg, config, key, info, m, save_config_fn, mory_bot)
    
    # 根据类型解析值
    val = None
    if info["type"] in ["number", "float"]:
        val = _extract_number(msg)
    elif info["type"] == "hour":
        val = _parse_hour(msg, msg)
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
            except (json.JSONDecodeError, TypeError, ValueError):
                current = {}
        if not isinstance(current, dict):
            current = {"messages_per_minute": 10, "ban_minutes": 5}
        current["messages_per_minute"] = int(val)
        config[key] = current
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已修改「{info['name']}」为每分钟 {int(val)} 条")
        logger.info(f"修改{key}: {val}")
        return True
    
    # 普通数值修改
    mystic_time_keys = {
        "MYSTIC_HOUR_MORNING": "morning_time",
        "MYSTIC_HOUR_AFTERNOON": "afternoon_time",
        "MYSTIC_HOUR_EVENING": "evening_time",
    }
    if key in mystic_time_keys:
        current = config.setdefault("MYSTIC_BROADCAST_CONFIG", {})
        old_value = str(current.get(mystic_time_keys[key], "00:00"))
        minute = old_value.split(":", 1)[1] if ":" in old_value else "00"
        current[mystic_time_keys[key]] = f"{int(val):02d}:{minute}"
    else:
        config[key] = val
    save_config_fn()
    
    # 格式化回复
    unit = info.get("unit", "")
    if info["type"] == "hour":
        unit = "点"
    display_val = f"{val}{unit}" if unit else str(val)
    
    mory_bot.reply_and_track(m, f"✅ 已修改「{info['name']}」为 {display_val}")
    logger.info(f"修改{key}: {val}")
    return True


def _handle_modify_text(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
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
            mory_bot.reply_and_track(m, f"✅ 欢迎语已更新：{text[:50]}{'...' if len(text)>50 else ''}")
            logger.info(f"修改欢迎语: {text[:50]}")
            return True
    
    # 暗号
    if any(k in msg for k in ["暗号", "碎片暗号"]):
        match = re.search(r'[改成改为][^a-zA-Z0-9]?([^\s，。！？]+)', msg)
        if match:
            word = match.group(1).strip()
            config["PUZZLE_WORD"] = word
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 碎片暗号已设为「{word}」")
            logger.info(f"修改暗号: {word}")
            return True
    
    # 早安/晚安模板
    if "早安模板" in msg:
        match = re.search(r'[""\']([^"\']+)[""\']', msg)
        if match:
            text = match.group(1).strip()
            config["GREETING_TEMPLATE"] = text
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 早安模板已更新")
            return True
    
    if "晚安模板" in msg:
        match = re.search(r'[""\']([^"\']+)[""\']', msg)
        if match:
            text = match.group(1).strip()
            config["GOODNIGHT_TEMPLATE"] = text
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 晚安模板已更新")
            return True
    
    return False


def _handle_list_operations(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
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
            new_words = [w.strip() for w in re.split(r'[，,、/|；;\s]+', word) if w.strip()]
            added = []
            for w in new_words:
                if w not in items:
                    items.append(w)
                    added.append(w)
            if added:
                config[key] = items
                save_config_fn()
                mory_bot.reply_and_track(m, f"✅ 已增加反感词：{'、'.join(added)}")
            else:
                mory_bot.reply_and_track(m, f"⚠️ 这些词已在列表中")
        else:
            removed = []
            for w in re.split(r'[，,、/|；;\s]+', word):
                w = w.strip()
                if w in items:
                    items.remove(w)
                    removed.append(w)
            if removed:
                config[key] = items
                save_config_fn()
                mory_bot.reply_and_track(m, f"✅ 已删除反感词：{'、'.join(removed)}")
            else:
                mory_bot.reply_and_track(m, f"⚠️ 这些词不在列表中")
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
            new_words = [w.strip() for w in re.split(r'[，,、/|；;\s]+', word) if w.strip()]
            added = []
            for w in new_words:
                if w not in items:
                    items.append(w)
                    added.append(w)
            if added:
                config[key] = items
                save_config_fn()
                mory_bot.reply_and_track(m, f"✅ 已增加敏感词：{'、'.join(added)}")
            else:
                mory_bot.reply_and_track(m, f"⚠️ 这些词已在列表中")
        else:
            removed = []
            for w in re.split(r'[，,、/|；;\s]+', word):
                w = w.strip()
                if w in items:
                    items.remove(w)
                    removed.append(w)
            if removed:
                config[key] = items
                save_config_fn()
                mory_bot.reply_and_track(m, f"✅ 已删除敏感词：{'、'.join(removed)}")
            else:
                mory_bot.reply_and_track(m, f"⚠️ 这些词不在列表中")
        return True
    
    return False


def _handle_model_switch(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
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
            mory_bot.reply_and_track(m, f"✅ 已切换到第{idx+1}个模型：{model_name}")
            logger.info(f"切换模型: {model_name}")
            return True
        else:
            mory_bot.reply_and_track(m, f"⚠️ 模型序号超出范围(1-{len(pools)})")
            return True
    
    # 按名称切换
    model_pools = config.get("MODEL_POOLS", {}).get("llm", [])
    for i, model in enumerate(model_pools):
        model_name = model.get("name", "")
        if model_name and model_name in msg:
            config["CURRENT_MODEL_INDEX"] = i
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 已切换到模型：{model_name}")
            logger.info(f"切换模型: {model_name}")
            return True
    
    return False


def _handle_model_restore(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
    """处理模型恢复：模型恢复 xxx"""
    if "模型恢复" not in msg and "恢复模型" not in msg:
        return False
    model_hint = msg.replace("模型恢复", "").replace("恢复模型", "").strip()
    if not model_hint:
        mory_bot.reply_and_track(m, "⚠️ 请指定要恢复的模型名，如「模型恢复 qwen3-max」")
        return True
    blacklisted = config.get("BLACKLISTED_MODELS", [])
    if not isinstance(blacklisted, list):
        blacklisted = []
    matched = [m for m in blacklisted if model_hint in m] if model_hint else []
    if not matched:
        matched = [m for m in blacklisted if model_hint in m]
    if not matched:
        mory_bot.reply_and_track(m, f"⚠️ 黑名单中没有找到包含「{model_hint}」的模型\n当前黑名单：{', '.join(blacklisted[:5]) or '空'}")
        return True
    for m_name in matched:
        blacklisted.remove(m_name)
    config["BLACKLISTED_MODELS"] = blacklisted
    save_config_fn()
    mory_bot.reply_and_track(m, f"✅ 已恢复模型：{'、'.join(matched)}")
    return True


def _handle_admin_management(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
    """处理管理员管理：删除管理员 xxx"""
    if "删除管理员" not in msg and "移除管理员" not in msg:
        return False
    hint = msg.replace("删除管理员", "").replace("移除管理员", "").strip()
    if not hint:
        mory_bot.reply_and_track(m, "⚠️ 请指定要删除的管理员ID，如「删除管理员 123456」")
        return True
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    primary = config.get("ADMIN_ID", 0)
    try:
        target_id = int(hint)
    except ValueError:
        mory_bot.reply_and_track(m, "⚠️ 管理员ID必须是数字")
        return True
    if target_id == primary:
        mory_bot.reply_and_track(m, "⛔ 不能删除主人管理员")
        return True
    if target_id in admin_ids:
        admin_ids.remove(target_id)
        config["ADMIN_IDS"] = admin_ids
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已删除管理员 {target_id}")
    else:
        mory_bot.reply_and_track(m, f"⚠️ {target_id} 不是管理员")
    return True


def _handle_ad_rule_management(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None, ad_detector=None) -> bool:
    """处理广告规则管理指令"""
    msg_clean = (msg or "").strip()
    markers = ["广告规则", "拦截规则"]
    if not any(marker in msg_clean for marker in markers):
        return False

    if ad_detector is None:
        mory_bot.reply_and_track(m, "⚠️ 广告检测模块未初始化")
        return True

    # 查看广告规则
    if any(k in msg_clean for k in ["查看广告规则", "列出广告规则", "广告规则列表", "看广告规则"]):
        rules = ad_detector.list_rules()
        if not rules:
            mory_bot.reply_and_track(m, "📋 暂无广告规则")
            return True
        lines = ["📋 当前广告规则：", ""]
        for idx, rule in enumerate(rules, 1):
            status = "✅" if rule.get("enabled") else "⛔"
            builtin_tag = "🔒" if rule.get("builtin") else ""
            lines.append(f"{idx}. {status} {rule.get('name', rule.get('id', '?'))} {builtin_tag}")
            lines.append(f"   类型: {rule.get('type', '?')} | 动作: {rule.get('action', '?')}")
            lines.append(f"   ID: {rule.get('id', '?')}")
        stats = ad_detector.get_stats()
        lines.append("")
        lines.append(f"📊 统计: 已拦截 {stats['total_detected']} 次 | 阈值 {stats['score_threshold']} 分")
        mory_bot.reply_and_track(m, "\n".join(lines))
        return True

    # 测试广告规则
    if msg_clean.startswith(("测试广告规则", "测试广告检测")):
        test_text = msg_clean
        for prefix in ["测试广告规则", "测试广告检测"]:
            test_text = test_text.replace(prefix, "", 1).strip()
        for sep in [":", "："]:
            if sep in test_text:
                test_text = test_text.split(sep, 1)[1].strip()
                break
        if not test_text:
            mory_bot.reply_and_track(m, "⚠️ 请提供测试文本，例如：测试广告规则 日入3K加微信")
            return True
        result = ad_detector.test_text("", test_text)
        mory_bot.reply_and_track(m, f"🧪 测试结果：\n{result}")
        return True

    # 广告规则统计
    if any(k in msg_clean for k in ["广告规则统计", "广告统计", "拦截统计"]):
        stats = ad_detector.get_stats()
        lines = [
            "📊 广告检测统计：",
            f"  已拦截: {stats['total_detected']} 次",
            f"  误判: {stats['false_positives']} 次",
            f"  评分阈值: {stats['score_threshold']} 分",
            f"  自定义规则: {stats['custom_rules_count']} 条",
            f"  内置规则: {stats['builtin_rules_count']} 条",
        ]
        mory_bot.reply_and_track(m, "\n".join(lines))
        return True

    # 新增广告规则
    if msg_clean.startswith(("新增", "添加", "增加")):
        body = msg_clean
        for prefix in ["新增", "添加", "增加"]:
            body = body.replace(prefix, "", 1).strip()
        for marker in markers:
            body = body.replace(marker, "").strip()
        body = body.lstrip(":：").strip()

        if not body:
            mory_bot.reply_and_track(m, "⚠️ 请描述新规则，例如：新增广告规则 关键词包含'日赚'和'微信'就封")
            return True

        keywords = _normalize_keywords(body)
        if not keywords:
            mory_bot.reply_and_track(m, "⚠️ 未识别到关键词，请检查格式")
            return True

        rule_name = f"自定义-{keywords[0]}"
        success, message = ad_detector.add_custom_rule({
            "name": rule_name,
            "type": "combo",
            "conditions": {"keywords": keywords, "required_count": 2},
            "action": "ban",
        })
        if success:
            save_config_fn()
        mory_bot.reply_and_track(m, message)
        return True

    # 删除广告规则
    if msg_clean.startswith(("删除", "移除", "去掉")):
        body = msg_clean
        for prefix in ["删除", "移除", "去掉"]:
            body = body.replace(prefix, "", 1).strip()
        for marker in markers:
            body = body.replace(marker, "").strip()
        body = body.lstrip(":：").strip()

        if not body:
            mory_bot.reply_and_track(m, "⚠️ 请指定要删除的规则ID或名称")
            return True

        success, message = ad_detector.remove_custom_rule(body)
        if success:
            save_config_fn()
        mory_bot.reply_and_track(m, message)
        return True

    # 开启/关闭广告规则
    is_enable = msg_clean.startswith(("开启", "启用", "打开"))
    is_disable = msg_clean.startswith(("关闭", "禁用", "停用"))
    if is_enable or is_disable:
        body = msg_clean
        for prefix in ["开启", "启用", "打开", "关闭", "禁用", "停用"]:
            body = body.replace(prefix, "", 1).strip()
        for marker in markers:
            body = body.replace(marker, "").strip()
        body = body.lstrip(":：").strip()

        if not body:
            mory_bot.reply_and_track(m, "⚠️ 请指定要操作规则ID或名称")
            return True

        success, message = ad_detector.toggle_rule(body, is_enable)
        if success:
            save_config_fn()
        mory_bot.reply_and_track(m, message)
        return True

    return False


def _handle_task_control(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
    """处理任务控制：开启风水播报 / 关闭午间塔罗等。"""
    task_map = {
        "早安问候": "AUTO_GREETING",
        "早安": "AUTO_GREETING",
        "午安问候": "AUTO_GREETING",
        "晚安问候": "AUTO_GOODNIGHT",
        "晚安": "AUTO_GOODNIGHT",
        "早间风水": "MYSTIC_BROADCAST_ENABLED",
        "午间塔罗": "MYSTIC_BROADCAST_ENABLED",
        "晚间能量签": "MYSTIC_BROADCAST_ENABLED",
        "风水播报": "MYSTIC_BROADCAST_ENABLED",
        "塔罗播报": "MYSTIC_BROADCAST_ENABLED",
        "玄学播报": "MYSTIC_BROADCAST_ENABLED",
        "签到": "SIGNUP_ENABLED",
        "碎片寻宝": "PUZZLE_ENABLED",
        "寻宝": "PUZZLE_ENABLED",
        "挽回": "RECOVER_ENABLED",
        "阅后即焚": "BURN_AFTER",
    }
    is_enable = any(msg.startswith(k) for k in ["开启", "打开", "启用"])
    is_disable = any(msg.startswith(k) for k in ["关闭", "禁用", "停用"])
    if not (is_enable or is_disable):
        return False
    for alias, key in task_map.items():
        if alias in msg:
            if key == "MYSTIC_BROADCAST_ENABLED":
                config.setdefault("MYSTIC_BROADCAST_CONFIG", {})["enabled"] = is_enable
                config.setdefault("NEWS_BROADCAST_CONFIG", {})["enabled"] = False
                config["AUTO_NEWS"] = False
            else:
                config[key] = is_enable
            save_config_fn()
            action = "开启" if is_enable else "关闭"
            mory_bot.reply_and_track(m, f"✅ 已{action}「{alias}」")
            return True
    return False


def _handle_persona_teaching(msg: str, config: dict, bot, m, save_config_fn, mory_bot=None) -> bool:
    """[Trae] 处理自然语言人设调教指令

    识别管理员对Bot人设/风格/行为的自然语言调整请求，
    将其翻译为STYLE_APPEND追加内容。

    示例：
    - "以后对我温柔一点" → 追加风格调整
    - "说话再骚一点" → 追加风格调整
    - "别那么快回复" → 修改REPLY_SPEED
    - "私聊的时候更黏人" → 追加私聊场景话术
    - "以后叫我哥哥" → 追加称呼偏好
    - "别再用'你觉得呢'结尾了" → 追加禁忌表达
    - "回复短一点" → 追加回复长度偏好
    """
    msg_clean = (msg or "").strip()

    teaching_keywords = [
        "以后", "说话", "回复", "语气", "风格", "叫我", "称呼",
        "更", "再", "别", "不要", "少", "多", "调教",
    ]
    has_teaching_intent = sum(1 for kw in teaching_keywords if kw in msg_clean) >= 2
    if not has_teaching_intent:
        return False

    speed_patterns = ["别那么快回复", "回复太快", "秒回", "回复慢一点", "回复速度"]
    for pattern in speed_patterns:
        if pattern in msg_clean:
            if "快" in msg_clean or "秒回" in msg_clean:
                config["REPLY_SPEED"] = "slow"
                save_config_fn()
                mory_bot.reply_and_track(m, "✅ 收到～以后回复慢一点，不秒回了")
                _add_teaching_log(config, "回复速度调慢", save_config_fn)
                return True
            elif "慢" in msg_clean:
                config["REPLY_SPEED"] = "normal"
                save_config_fn()
                mory_bot.reply_and_track(m, "✅ 好的～回复速度调正常了")
                _add_teaching_log(config, "回复速度调正常", save_config_fn)
                return True

    reply_chance_patterns = ["群里别太主动", "群里少说话", "群里安静点", "群里多说话", "群里主动点"]
    for pattern in reply_chance_patterns:
        if pattern in msg_clean:
            current = config.get("REPLY_CHANCE", 10)
            if "少" in msg_clean or "安静" in msg_clean or "别太主动" in msg_clean:
                new_val = max(1, current - 5)
            else:
                new_val = min(50, current + 10)
            config["REPLY_CHANCE"] = new_val
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 群聊回复概率已调整为 {new_val}%")
            _add_teaching_log(config, f"群聊回复概率→{new_val}%", save_config_fn)
            return True

    _ensure_structured(config)
    style = config.get("STYLE_APPEND", "")
    if len(style) > 3000:
        mory_bot.reply_and_track(m, "⚠️ 风格追加已经很长了，请先用「撤销调教」清理一下再调教～")
        return True

    timestamp = datetime.now(_CST).strftime('%m/%d %H:%M')
    instruction = f"\n【{timestamp}调教指令】：{msg_clean}。严格执行此调整直到主人再次修改。"
    config["STYLE_APPEND"] = style + instruction
    save_config_fn()

    _add_teaching_log(config, msg_clean, save_config_fn)

    confirmations = {
        "温柔": "收到～以后更温柔一点 💕",
        "骚": "好的～说话再撩一点 😏",
        "黏人": "嗯嗯～以后更黏人一点 🥺",
        "高冷": "收到～以后高冷一点 🧊",
        "短": "好的～以后回复短一点",
        "长": "好的～以后回复可以长一点",
        "叫": "好的～以后这么叫你",
        "别用": "收到～以后不用那个了",
        "不要": "收到～以后不那样了",
    }
    reply = "✅ 收到～我记住了，以后就这样"
    for key, resp in confirmations.items():
        if key in msg_clean:
            reply = f"✅ {resp}"
            break

    mory_bot.reply_and_track(m, reply)
    logger.info(f"📝 人设调教：{msg_clean[:50]}")
    return True


def _add_teaching_log(config: dict, instruction: str, save_config_fn):
    """[Trae] 记录调教指令到TEACHING_LOG"""
    log = config.get("TEACHING_LOG", [])
    if not isinstance(log, list):
        log = []
    log.append(f"[{datetime.now(_CST).strftime('%m/%d %H:%M')}] {instruction}")
    if len(log) > 20:
        log = log[-20:]
    config["TEACHING_LOG"] = log
    save_config_fn()


def _ensure_structured(config: dict):
    """确保config已迁移到结构化字段（BASE_PERSONA等）"""
    if "BASE_PERSONA" not in config and "SYSTEM_PROMPT" in config:
        config["BASE_PERSONA"] = config.pop("SYSTEM_PROMPT")
        config.setdefault("STYLE_APPEND", "")
        config.setdefault("ADDED_KNOWLEDGE", "")


# ══════════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════════

def handle_natural_admin(bot, m, config: dict, save_config_fn, mory_bot=None, is_admin: bool = False, ad_detector=None) -> bool:
    """
    处理自然语言配置指令。
    返回 True 表示已消费该消息。
    """
    msg = (m.text or "").strip()

    if not msg:
        return False

    # 1. 查看全部配置（所有用户可用）
    if _handle_view_all_config(msg, config, bot, m, mory_bot=mory_bot, is_admin=is_admin):
        return True

    # 以下指令需要管理员权限
    if not is_admin:
        return False

    # 1.5 特定词自动回复配置
    if _handle_special_auto_reply_config(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 1.6 [Trae] 人设调教（自然语言调整Bot风格/行为）
    if _handle_persona_teaching(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 2. 开关命令（开启/关闭xxx）
    if _handle_toggle(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 3. 模型切换
    if _handle_model_switch(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 3.5 模型恢复
    if _handle_model_restore(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 3.6 管理员管理
    if _handle_admin_management(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 3.7 任务控制
    if _handle_task_control(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 3.8 广告规则管理
    if _handle_ad_rule_management(msg, config, bot, m, save_config_fn, mory_bot=mory_bot, ad_detector=ad_detector):
        return True

    # 4. 列表操作（增加/删除xxx）
    if _handle_list_operations(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 5. 数值修改（把xxx改成yyy）
    if _handle_modify_number(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 6. 文本修改
    if _handle_modify_text(msg, config, bot, m, save_config_fn, mory_bot=mory_bot):
        return True

    # 没有匹配
    return False
