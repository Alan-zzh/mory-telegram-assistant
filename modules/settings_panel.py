"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/settings_panel.py  ·  Telegram Bot 内联按钮设置面板 (完全体)    ║
║                                                                        ║
║  功能：管理员发送 /settings 后，Bot回复带内联按钮的主菜单，              ║
║        8个分类覆盖所有已实现模块，支持开关切换、数值修改、模式循环。      ║
║                                                                        ║
║  分类结构（8分类，~80按钮）：                                          ║
║    basic → 基础设置(群名/日志/权限/连接/语言)                           ║
║    security → 安全设置(验证/反垃圾/反刷屏/反突袭/反撤回/CAS/面具/夜间/色情/媒体/锁群)
║    members → 成员管理(警告/审批/僵尸/不活跃/服务消息/标签/认证/投票)    ║
║    messages → 消息管理(欢迎/告别/群规/置顶/举报/重发/链接)              ║
║    interact → 互动功能(AI回复/自动回复/自定义命令/笔记/小游戏/抽奖/盲盒/转盘/签到/红包/AFK)
║    economy → 经济系统(积分规则/等级/商城/优惠券/打赏/衰减/任务/成就)     ║
║    broadcast → 播报与统计(早安/晚安/新闻/定点播报/定时消息/数据面板/发言统计/U价)
║    advanced → 高级设置(模型/人设/违禁词/黑名单/命令/备份/联邦/NSFW)     ║
║
║  回调数据格式：settings_{category}_{action}_{key}                       ║
║    category: basic/security/members/messages/interact/economy/broadcast/advanced
║    action:   toggle/cycle/set/back/list/menu/view                       ║
║    key:      具体配置项名                                               ║
║                                                                        ║
║  被调用：main.py /settings 指令 + callback_query 路由                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import tempfile
import logging
from core.config_compat import normalize_runtime_config, compact_runtime_config
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

# ── 临时会话：等待管理员输入新值 ──────────────────────────────────────────
# {(chat_id, user_id): {"key": str, "msg": str, "callback_data": str}}
_pending_value_sessions = {}

# ── config.json 路径 ─────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

# ═════════════════════════════════════════════════════════════════════════
#  分类 → 键映射（8个分类，~80个按钮）
#  type: toggle(开关) / cycle(循环) / set(数值) / list(列表) / view(查看)
# ══════════════════════════════════════════════════════════════════════════

# ── 基础设置 ──────────────────────────────────────────────────────────────
BASIC_KEYS = {
    "language":              {"path": "LANGUAGE",                          "type": "cycle",
                              "options": ["zh", "en", "ja"],
                              "labels": {"zh": "中文", "en": "English", "ja": "日本語"},
                              "label": "语言", "default": "zh"},
}

# ── 安全设置 ──────────────────────────────────────────────────────────────
SECURITY_KEYS = {
    # 进群验证
    "verification_enable":   {"path": "VERIFICATION_CONFIG.enable",         "type": "toggle", "label": "进群验证"},
    "verification_mode":     {"path": "VERIFICATION_CONFIG.mode",           "type": "cycle",
                              "options": ["button", "math", "text"],
                              "labels": {"button": "按钮", "math": "数学题", "text": "文字"},
                              "label": "验证模式"},
    "verification_timeout":  {"path": "VERIFICATION_CONFIG.timeout",        "type": "set", "label": "验证超时", "unit": "秒", "default": 60},
    "verification_attempts": {"path": "VERIFICATION_CONFIG.max_attempts",   "type": "set", "label": "验证次数", "unit": "次", "default": 3},
    # 反垃圾/反刷屏
    "ad_detect_enable":      {"path": "AD_DETECT_CONFIG.enable",            "type": "toggle", "label": "反垃圾检测", "default": False},
    "ad_sensitivity":        {"path": "AD_DETECT_CONFIG.sensitivity",       "type": "set", "label": "敏感度", "unit": "分", "default": 3},
    "antiflood_limit":       {"path": "SPAM_LIMIT.messages_per_minute",     "type": "set", "label": "反刷屏阈值", "unit": "条/分", "default": 10},
    "spam_action":           {"path": "SPAM_ACTION",                        "type": "cycle",
                              "options": ["mute", "ban", "delete"],
                              "labels": {"mute": "禁言", "ban": "封禁", "delete": "删除"},
                              "label": "反刷屏动作", "default": "mute"},
    # 反突袭
    "anti_raid_enable":      {"path": "ANTI_RAID_CONFIG.enable",            "type": "toggle", "label": "反突袭保护", "default": False},
    "anti_raid_threshold":   {"path": "ANTI_RAID_CONFIG.threshold",         "type": "set", "label": "突袭阈值", "unit": "人", "default": 5},
    # 反撤回
    "antidelete_enable":     {"path": "ANTI_DELETE_CONFIG.enable",          "type": "toggle", "label": "反撤回检测", "default": False},
    # CAS检查
    "cas_check_enable":      {"path": "SPAM_WATCH_CONFIG.cas_enabled",      "type": "toggle", "label": "CAS检查", "default": False},
    # emoji面具
    "emoji_mask_enable":     {"path": "EMOJI_MASK_DETECT",                 "type": "toggle", "label": "emoji面具检测", "default": False},
    # 编辑检测
    "edit_detect_enable":    {"path": "EDIT_DETECT_ENABLE",                "type": "toggle", "label": "编辑消息检测", "default": False},
    # 夜间模式
    "nightmode_enable":      {"path": "NIGHT_MODE_CONFIG.enable",          "type": "toggle", "label": "夜间模式"},
    "nightmode_start":       {"path": "NIGHT_MODE_CONFIG.start_hour",      "type": "set", "label": "夜间开始", "unit": "点", "default": 23},
    "nightmode_end":         {"path": "NIGHT_MODE_CONFIG.end_hour",        "type": "set", "label": "夜间结束", "unit": "点", "default": 7},
    # 色情检测
    "nsfw_enable":           {"path": "NSFW_DETECT_CONFIG.enabled",        "type": "toggle", "label": "色情检测", "default": False},
    "nsfw_threshold":        {"path": "NSFW_DETECT_CONFIG.threshold",      "type": "set", "label": "NSFW阈值", "unit": "", "default": 0.7},
    # 媒体限制
    "lock_media":            {"path": "MESSAGE_LOCKS.media",               "type": "toggle", "label": "媒体限制", "default": False},
    "lock_sticker":          {"path": "MESSAGE_LOCKS.sticker",             "type": "toggle", "label": "贴纸限制", "default": False},
    "lock_poll":             {"path": "MESSAGE_LOCKS.poll",                "type": "toggle", "label": "投票限制", "default": False},
    "lock_link":             {"path": "MESSAGE_LOCKS.link",                "type": "toggle", "label": "链接限制", "default": False},
    "lock_list":             {"path": "_list_locks",                        "type": "list", "label": "锁群状态"},
    # 反刷屏
    "antiflood_enable":      {"path": "ANTIFLOOD_CONFIG.enabled",          "type": "toggle", "label": "反刷屏", "default": False},
    "antiflood_mute":        {"path": "ANTIFLOOD_CONFIG.mute_duration",    "type": "set", "label": "禁言时长", "unit": "秒", "default": 60},
    # 反突袭窗口
    "anti_raid_window":      {"path": "ANTI_RAID_CONFIG.window",           "type": "set", "label": "突袭窗口", "unit": "秒", "default": 60},
    # CAS/SpamWatch
    "cas_ban_action":        {"path": "SPAM_WATCH_CONFIG.ban_action",      "type": "cycle",
                              "options": ["kick", "ban", "mute"],
                              "labels": {"kick": "踢出", "ban": "封禁", "mute": "禁言"},
                              "label": "CAS处罚", "default": "ban"},
    # 夜间模式
    "nightmode_list":        {"path": "_list_night_mode",                  "type": "list", "label": "夜间状态"},
    # 反垃圾列表
    "ad_detect_list":        {"path": "_list_ad_detect",                   "type": "list", "label": "反垃圾状态"},
}

# ── 成员管理 ──────────────────────────────────────────────────────────────
MEMBERS_KEYS = {
    # 警告系统
    "warn_limit":            {"path": "WARNING_CONFIG.limit",              "type": "set", "label": "警告阈值", "unit": "次", "default": 3},
    "warn_action":           {"path": "WARNING_CONFIG.action",             "type": "cycle",
                              "options": ["mute", "ban", "kick"],
                              "labels": {"mute": "禁言", "ban": "封禁", "kick": "踢出"},
                              "label": "警告处罚", "default": "mute"},
    "warn_duration":         {"path": "WARNING_CONFIG.duration",           "type": "set", "label": "禁言时长", "unit": "秒", "default": 3600},
    # 审批白名单
    "approved_list":         {"path": "_list_approved",                    "type": "list", "label": "审批白名单"},
    # 僵尸清理
    "zombie_clean":          {"path": "_zombie_clean",                     "type": "list", "label": "僵尸清理"},
    # 不活跃清理
    "inactive_clean_enable": {"path": "AUTO_KICK_INACTIVE_DAYS.enable",    "type": "toggle", "label": "不活跃清理", "default": False},
    "inactive_days":         {"path": "AUTO_KICK_INACTIVE_DAYS.days",      "type": "set", "label": "不活跃天数", "unit": "天", "default": 30},
    # 服务消息清理
    "clean_service":         {"path": "CLEAN_SERVICE_DEFAULT",             "type": "toggle", "label": "服务消息清理", "default": False},
    # 用户标签
    "user_tags":             {"path": "_list_user_tags",                   "type": "list", "label": "用户标签"},
    # 认证用户
    "certified_users":       {"path": "_list_certified",                   "type": "list", "label": "认证用户"},
    # 投票踢人
    "votekick_enable":       {"path": "VOTEKICK_CONFIG.enable",            "type": "toggle", "label": "投票踢人", "default": False},
    "votekick_min_yes":      {"path": "VOTEKICK_CONFIG.min_yes",           "type": "set", "label": "最少赞成", "unit": "票", "default": 5},
    "votekick_ratio":        {"path": "VOTEKICK_CONFIG.min_ratio",         "type": "set", "label": "通过比例", "unit": "", "default": 0.6},
    "votekick_duration":     {"path": "VOTEKICK_CONFIG.duration",          "type": "set", "label": "投票时长", "unit": "秒", "default": 300},
    # 慢速模式
    "slowmode_enable":       {"path": "SLOW_MODE_DEFAULT.enabled",         "type": "toggle", "label": "慢速模式", "default": False},
    "slowmode_interval":     {"path": "SLOW_MODE_DEFAULT.interval",        "type": "set", "label": "发言间隔", "unit": "秒", "default": 5},
    # 用户信息
    "user_info":             {"path": "_user_info",                        "type": "list", "label": "用户信息"},
    # 远程管理
    "remote_manage":         {"path": "_list_connected_groups",            "type": "list", "label": "远程管理"},
}

# ── 消息管理 ──────────────────────────────────────────────────────────────
MESSAGES_KEYS = {
    # 进群欢迎
    "welcome_enable":        {"path": "WELCOME_MSG",                       "type": "toggle", "label": "入群欢迎"},
    "welcome_text":          {"path": "WELCOME_TEXT",                      "type": "set", "label": "欢迎模板", "default": ""},
    "welcome_clean":         {"path": "WELCOME_CLEAN",                     "type": "toggle", "label": "清理欢迎", "default": False},
    # 告别消息
    "goodbye_enable":        {"path": "GOODBYE_MSG",                       "type": "toggle", "label": "告别消息", "default": False},
    "goodbye_text":          {"path": "GOODBYE_TEXT",                      "type": "set", "label": "告别模板", "default": ""},
    # 群规
    "rules_enable":          {"path": "RULES_ENABLE",                      "type": "toggle", "label": "群规开关", "default": False},
    "rules_text":            {"path": "RULES_TEXT",                        "type": "set", "label": "群规内容", "default": ""},
    # 置顶管理
    "pin_list":              {"path": "_list_pins",                        "type": "list", "label": "置顶管理"},
    # 举报系统
    "report_enable":         {"path": "REPORT_CONFIG.enabled",             "type": "toggle", "label": "举报系统", "default": False},
    # 重发消息
    "echo_list":             {"path": "_list_echo",                        "type": "list", "label": "重发消息"},
    # 链接管理
    "anti_channel":          {"path": "ANTI_CHANNEL_DEFAULT",              "type": "toggle", "label": "反频道转发", "default": False},
    "invite_link":           {"path": "_list_invite_link",                 "type": "list", "label": "邀请链接"},
}

# ─ 互动功能 ──────────────────────────────────────────────────────────────
INTERACT_KEYS = {
    # AI回复
    "reply_chance":          {"path": "REPLY_CHANCE",                      "type": "set", "label": "回复概率", "unit": "%", "default": 10},
    "reply_speed":           {"path": "REPLY_SPEED",                       "type": "cycle",
                              "options": ["fast", "normal", "slow", "human"],
                              "labels": {"fast": "快速", "normal": "正常", "slow": "慢速", "human": "拟人"},
                              "label": "回复速度", "default": "human"},
    "sticker_chance":        {"path": "REPLY_STICKER_CHANCE",              "type": "set", "label": "贴纸概率", "unit": "%", "default": 5},
    # 自动回复
    "auto_reply":            {"path": "AUTO_REPLY_ENABLE",                 "type": "toggle", "label": "自动回复", "default": False},
    # 自定义命令
    "custom_commands":       {"path": "_list_custom_cmds",                 "type": "list", "label": "自定义命令"},
    # 群组笔记
    "group_notes":           {"path": "_list_notes",                       "type": "list", "label": "群组笔记"},
    # 小游戏
    "games_enable":          {"path": "GAMES_CONFIG.enable",               "type": "toggle", "label": "小游戏", "default": False},
    # 抽奖
    "lottery_enable":        {"path": "LOTTERY_CONFIG.enabled",            "type": "toggle", "label": "抽奖", "default": False},
    # 盲盒
    "blindbox_enable":       {"path": "BLIND_BOX_CONFIG.enabled",          "type": "toggle", "label": "盲盒", "default": False},
    "blindbox_cost":         {"path": "BLIND_BOX_CONFIG.cost",             "type": "set", "label": "盲盒消耗", "unit": "分", "default": 50},
    # 转盘
    "wheel_enable":          {"path": "LUCKY_WHEEL_CONFIG.enabled",        "type": "toggle", "label": "转盘", "default": False},
    "wheel_cost":            {"path": "LUCKY_WHEEL_CONFIG.cost",           "type": "set", "label": "转盘消耗", "unit": "分", "default": 30},
    # 签到
    "checkin_enable":        {"path": "CHECKIN_CONFIG.enable",             "type": "toggle", "label": "签到", "default": False},
    "checkin_base":          {"path": "CHECKIN_CONFIG.base_points",        "type": "set", "label": "签到积分", "unit": "分", "default": 5},
    # 红包
    "redpacket_enable":      {"path": "REDPACKET_CONFIG.enabled",          "type": "toggle", "label": "红包", "default": False},
    # AFK
    "afk_enable":            {"path": "AFK_CONFIG.enabled",                "type": "toggle", "label": "AFK状态", "default": False},
}

# ── 经济系统 ──────────────────────────────────────────────────────────────
ECONOMY_KEYS = {
    # 积分规则
    "points_message":        {"path": "POINTS_RULES.speech",               "type": "set", "label": "发言积分", "unit": "分", "default": 1},
    "points_daily_limit":    {"path": "POINTS_RULES.daily_limit",           "type": "set", "label": "每日上限", "unit": "分", "default": 50},
    "points_checkin":        {"path": "CHECKIN_CONFIG.base_points",        "type": "set", "label": "签到积分", "unit": "分", "default": 5},
    "points_invite":         {"path": "POINTS_PER_INVITE",                 "type": "set", "label": "邀请积分", "unit": "分", "default": 5},
    # 等级体系
    "level_titles":          {"path": "_list_level_titles",                "type": "list", "label": "等级称号"},
    # 商城
    "shop_enable":           {"path": "SHOP_CONFIG.enabled",               "type": "toggle", "label": "商城", "default": False},
    "shop_list":             {"path": "_list_shop_items",                  "type": "list", "label": "商城商品"},
    # 优惠券
    "coupon_enable":         {"path": "COUPON_CONFIG.enabled",             "type": "toggle", "label": "优惠券", "default": False},
    "coupon_list":           {"path": "_list_coupons",                     "type": "list", "label": "优惠券列表"},
    # 打赏
    "tip_min":               {"path": "TIP_CONFIG.min_amount",             "type": "set", "label": "最小打赏", "unit": "分", "default": 1},
    # 积分衰减
    "points_decay_enable":   {"path": "POINTS_DECAY.enabled",              "type": "toggle", "label": "积分衰减", "default": False},
    "points_decay_rate":     {"path": "POINTS_DECAY.rate",                 "type": "set", "label": "衰减比例", "unit": "%", "default": 1},
    "points_decay_min":      {"path": "POINTS_DECAY.minimum",              "type": "set", "label": "最低保留", "unit": "分", "default": 10},
    # 每日任务
    "daily_quest_enable":    {"path": "DAILY_QUEST_CONFIG.enable",         "type": "toggle", "label": "每日任务", "default": False},
    # 成就
    "achievement_enable":    {"path": "ACHIEVEMENT_CONFIG.enable",         "type": "toggle", "label": "成就系统", "default": False},
}

# ── 播报与统计 ───────────────────────────────────────────────────────────
BROADCAST_KEYS = {
    # 早/午/晚问候
    "greeting_morning":      {"path": "GREETING_CONFIG.morning_enabled",   "type": "toggle", "label": "早安问候", "default": False},
    "greeting_morning_time": {"path": "GREETING_CONFIG.morning_time",      "type": "set", "label": "早安时间", "default": "08:05"},
    "greeting_afternoon":    {"path": "GREETING_CONFIG.afternoon_enabled", "type": "toggle", "label": "午安问候", "default": False},
    "greeting_afternoon_time": {"path": "GREETING_CONFIG.afternoon_time",  "type": "set", "label": "午安时间", "default": "12:35"},
    "greeting_evening":      {"path": "GREETING_CONFIG.evening_enabled",   "type": "toggle", "label": "晚安问候", "default": False},
    "greeting_evening_time": {"path": "GREETING_CONFIG.evening_time",      "type": "set", "label": "晚安时间", "default": "23:05"},
    # 新闻播报
    "news_enabled":          {"path": "NEWS_BROADCAST_CONFIG.enabled",     "type": "toggle", "label": "新闻播报", "default": False},
    "news_source":           {"path": "NEWS_BROADCAST_CONFIG.preferred_source", "type": "cycle",
                              "options": ["real_first", "trendradar_first"],
                              "labels": {"real_first": "真实源优先", "trendradar_first": "热点源优先"},
                              "label": "新闻来源"},
    "news_morning_time":     {"path": "NEWS_BROADCAST_CONFIG.morning_time", "type": "set", "label": "早间新闻", "default": "09:05"},
    "news_afternoon_time":   {"path": "NEWS_BROADCAST_CONFIG.afternoon_time", "type": "set", "label": "午间新闻", "default": "13:05"},
    "news_evening_time":     {"path": "NEWS_BROADCAST_CONFIG.evening_time", "type": "set", "label": "晚间新闻", "default": "20:35"},
    # 定点播报
    "broadcasts":            {"path": "_list_broadcasts",                  "type": "list", "label": "定点播报列表"},
    # 定时消息
    "scheduled_msgs":        {"path": "_list_scheduled_msgs",              "type": "list", "label": "定时消息列表"},
    # 数据面板
    "visual_dashboard":      {"path": "VISUAL_DASHBOARD_ENABLE",           "type": "toggle", "label": "群数据面板", "default": False},
    # 发言统计
    "speech_stats":          {"path": "_list_speech_stats",                "type": "list", "label": "发言统计"},
    # 实时U价
    "exchange_rate":         {"path": "EXCHANGE_RATE_ENABLE",              "type": "toggle", "label": "实时U价", "default": False},
    # 私聊接管
    "relay_mode":            {"path": "RELAY_MODE_ENABLED",                "type": "toggle", "label": "私聊中继", "default": False},
}

# ── 高级设置 ──────────────────────────────────────────────────────────────
ADVANCED_KEYS = {
    # 模型
    "model":                 {"path": "_cycle_model",                      "type": "cycle_model", "label": "当前模型"},
    # 人设
    "persona":               {"path": "_view_persona",                     "type": "view", "label": "查看人设"},
    "persona_text":          {"path": "SYSTEM_PROMPT",                     "type": "set", "label": "人设文本", "default": ""},
    # 违禁词
    "banned_words":          {"path": "_list_banned_words",                "type": "list", "label": "违禁词列表"},
    # 黑名单
    "blacklist":             {"path": "_list_blacklist",                   "type": "list", "label": "黑名单列表"},
    # 命令管理
    "disabled_cmds":         {"path": "_list_disabled_cmds",               "type": "list", "label": "命令管理"},
    # 群设置备份
    "group_backup":          {"path": "_group_backup",                     "type": "list", "label": "群设置备份"},
    # 联邦封禁
    "federation":            {"path": "_list_federation",                  "type": "list", "label": "联邦封禁"},
    # NSFW配置
    "nsfw_enable":           {"path": "NSFW_DETECT_CONFIG.enabled",        "type": "toggle", "label": "NSFW检测", "default": False},
    "nsfw_threshold":        {"path": "NSFW_DETECT_CONFIG.threshold",      "type": "set", "label": "NSFW阈值", "unit": "", "default": 0.7},
    "nsfw_api_key":          {"path": "NSFW_DETECT_CONFIG.api_key",        "type": "set", "label": "NSFW密钥", "default": ""},
}

# 分类 → 键映射
CATEGORY_KEYS = {
    "basic": BASIC_KEYS,
    "security": SECURITY_KEYS,
    "members": MEMBERS_KEYS,
    "messages": MESSAGES_KEYS,
    "interact": INTERACT_KEYS,
    "economy": ECONOMY_KEYS,
    "broadcast": BROADCAST_KEYS,
    "advanced": ADVANCED_KEYS,
}

# 分类元数据（emoji + 中文名称）
CATEGORY_META = {
    "basic":     {"emoji": "📋", "name": "基础设置"},
    "security":  {"emoji": "🛡️", "name": "安全设置"},
    "members":   {"emoji": "👥", "name": "成员管理"},
    "messages":  {"emoji": "💬", "name": "消息管理"},
    "interact":  {"emoji": "🎮", "name": "互动功能"},
    "economy":   {"emoji": "💰", "name": "经济系统"},
    "broadcast": {"emoji": "📢", "name": "播报与统计"},
    "advanced":  {"emoji": "⚙️", "name": "高级设置"},
}


# ══════════════════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════════════════

def _load_config():
    """读取config.json"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return normalize_runtime_config(json.load(f))


def _save_config(cfg):
    """原子写入config.json（使用临时文件+os.replace防止写坏）"""
    fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(CONFIG_PATH))
    try:
        cfg = compact_runtime_config(cfg)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _is_admin(user_id, config):
    """检查是否管理员"""
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)
    return user_id in admin_ids


def _get_nested(config, path, default=None):
    """获取嵌套配置值，path 用 "." 分隔"""
    if path.startswith("_"):
        return default
    keys = path.split(".")
    obj = config
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        else:
            return default
    return obj


def _set_nested(config, path, value):
    """设置嵌套配置值，path 用 "." 分隔"""
    keys = path.split(".")
    obj = config
    for k in keys[:-1]:
        if k not in obj or not isinstance(obj[k], dict):
            obj[k] = {}
        obj = obj[k]
    obj[keys[-1]] = value


def _status_text(val):
    """开关状态文字"""
    if val:
        return "✅ 开"
    return "❌ 关"


# ══════════════════════════════════════════════════════════════════════════
#  主菜单渲染
# ══════════════════════════════════════════════════════════════════════════

def render_main_menu(config):
    """渲染主菜单（8个分类）"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    cats = list(CATEGORY_META.keys())
    for i in range(0, len(cats), 2):
        row = []
        for j in range(i, min(i + 2, len(cats))):
            cat = cats[j]
            meta = CATEGORY_META[cat]
            row.append(InlineKeyboardButton(f"{meta['emoji']} {meta['name']}", callback_data=f"settings_{cat}_menu"))
        keyboard.add(*row)
    text = "⚙️ <b>Mory小助理 设置面板</b>\n\n请选择要配置的分类："
    return text, keyboard


# ══════════════════════════════════════════════════════════════════════════
#  按钮构建
# ═════════════════════════════════════════════════════════════════════════

def _build_toggle_button(key_info, key_name, category, config):
    """构建开关按钮"""
    path = key_info["path"]
    val = _get_nested(config, path, key_info.get("default", False))
    label = key_info["label"]
    btn_text = f"{label}：{_status_text(val)}"
    callback = f"settings_{category}_toggle_{key_name}"
    return InlineKeyboardButton(btn_text, callback_data=callback)


def _build_cycle_button(key_info, key_name, category, config):
    """构建循环切换按钮"""
    path = key_info["path"]
    options = key_info.get("options", [])
    labels = key_info.get("labels", {})
    current = _get_nested(config, path, key_info.get("default", options[0] if options else ""))
    current_label = labels.get(current, str(current))
    label = key_info["label"]
    btn_text = f"{label}：{current_label}"
    callback = f"settings_{category}_cycle_{key_name}"
    return InlineKeyboardButton(btn_text, callback_data=callback)


def _build_set_button(key_info, key_name, category, config):
    """构建数值设置按钮"""
    path = key_info["path"]
    val = _get_nested(config, path, key_info.get("default"))
    label = key_info["label"]
    unit = key_info.get("unit", "")
    btn_text = f"{label}：{val}{unit}"
    callback = f"settings_{category}_set_{key_name}"
    return InlineKeyboardButton(btn_text, callback_data=callback)


def _build_list_button(key_info, key_name, category):
    """构建列表查看按钮"""
    label = key_info["label"]
    btn_text = f"📋 {label}"
    callback = f"settings_{category}_list_{key_name}"
    return InlineKeyboardButton(btn_text, callback_data=callback)


def _build_view_button(key_info, key_name, category):
    """构建查看按钮"""
    label = key_info["label"]
    btn_text = f"👁 {label}"
    callback = f"settings_{category}_view_{key_name}"
    return InlineKeyboardButton(btn_text, callback_data=callback)


def _build_cycle_model_button(key_info, key_name, category, config):
    """构建模型循环切换按钮"""
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    idx = config.get("CURRENT_MODEL_INDEX", 0)
    cur_name = pool[idx]["name"] if pool and idx < len(pool) else "未知"
    btn_text = f"🧠 当前模型：{cur_name}"
    callback = f"settings_{category}_cycle_{key_name}"
    return InlineKeyboardButton(btn_text, callback_data=callback)


def _build_submenu(category, keys, title, emoji, config):
    """通用子菜单构建"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = []

    for key_name, key_info in keys.items():
        ktype = key_info["type"]

        if ktype == "toggle":
            buttons.append(_build_toggle_button(key_info, key_name, category, config))
        elif ktype == "cycle":
            buttons.append(_build_cycle_button(key_info, key_name, category, config))
        elif ktype == "set":
            buttons.append(_build_set_button(key_info, key_name, category, config))
        elif ktype == "list":
            buttons.append(_build_list_button(key_info, key_name, category))
        elif ktype == "view":
            buttons.append(_build_view_button(key_info, key_name, category))
        elif ktype == "cycle_model":
            buttons.append(_build_cycle_model_button(key_info, key_name, category, config))

    # 每行2个按钮
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        keyboard.add(*row)

    # 返回主菜单
    keyboard.add(InlineKeyboardButton("🔙 返回主菜单", callback_data="settings_back_main"))

    text = f"{emoji} <b>{title}</b>\n\n点击按钮修改配置："
    return text, keyboard


def render_basic_menu(config):
    return _build_submenu("basic", BASIC_KEYS, "基础设置", "📋", config)

def render_security_menu(config):
    return _build_submenu("security", SECURITY_KEYS, "安全设置", "🛡️", config)

def render_members_menu(config):
    return _build_submenu("members", MEMBERS_KEYS, "成员管理", "👥", config)

def render_messages_menu(config):
    return _build_submenu("messages", MESSAGES_KEYS, "消息管理", "💬", config)

def render_interact_menu(config):
    return _build_submenu("interact", INTERACT_KEYS, "互动功能", "🎮", config)

def render_economy_menu(config):
    return _build_submenu("economy", ECONOMY_KEYS, "经济系统", "💰", config)

def render_broadcast_menu(config):
    return _build_submenu("broadcast", BROADCAST_KEYS, "播报与统计", "📢", config)

def render_advanced_menu(config):
    return _build_submenu("advanced", ADVANCED_KEYS, "高级设置", "⚙️", config)


# ══════════════════════════════════════════════════════════════════════════
#  配置修改操作
# ══════════════════════════════════════════════════════════════════════════

def _toggle_setting(key, category, config):
    """开关切换，返回新值"""
    keys_map = CATEGORY_KEYS.get(category, {})
    key_info = keys_map.get(key)
    if not key_info:
        return None
    path = key_info["path"]
    current = _get_nested(config, path, key_info.get("default", False))
    new_val = not current
    _set_nested(config, path, new_val)
    _save_config(config)
    logger.info(f"️ 设置面板：{path} 切换为 {new_val}")

    # ── 调用模块函数即时生效 ─────────────────────────────────────
    _apply_module_toggle(path, new_val, config)

    return new_val


def _apply_module_toggle(path, new_val, config):
    """调用模块函数即时生效（可选，模块不存在则跳过）"""
    try:
        # 夜间模式开关
        if path == "NIGHT_MODE_CONFIG.enable":
            from modules import night_mode
            chat_id = config.get("GROUP_ID", 0)
            if new_val:
                night_mode.start_night_mode(None, chat_id, config)
            else:
                night_mode.end_night_mode(None, chat_id, config)

        # 反频道转发开关 — 需同步DB表，模块优先读DB
        elif path == "ANTI_CHANNEL_DEFAULT":
            chat_id = config.get("GROUP_ID", 0)
            if chat_id:
                import time
                from core.database import _db_lock, Database
                try:
                    db = Database()
                    now_ts = int(time.time())
                    with _db_lock:
                        db.conn.execute(
                            "INSERT OR REPLACE INTO anti_channel_settings (chat_id, enabled, ts) VALUES (?,?,?)",
                            (chat_id, 1 if new_val else 0, now_ts)
                        )
                        db.conn.commit()
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
    except Exception as e:
        logger.warning(f"模块调用失败: {path} -> {e}")


def _cycle_setting(key, category, config):
    """模式循环切换，返回新值"""
    keys_map = CATEGORY_KEYS.get(category, {})
    key_info = keys_map.get(key)
    if not key_info:
        return None
    path = key_info["path"]
    options = key_info.get("options", [])
    if not options:
        return None
    current = _get_nested(config, path, key_info.get("default", options[0]))
    try:
        idx = options.index(current)
        new_idx = (idx + 1) % len(options)
    except ValueError:
        new_idx = 0
    new_val = options[new_idx]
    _set_nested(config, path, new_val)
    _save_config(config)
    logger.info(f"⚙️ 设置面板：{path} 循环切换为 {new_val}")
    return new_val


def _cycle_model(config):
    """模型循环切换，返回新模型名"""
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    if not pool:
        return None
    idx = config.get("CURRENT_MODEL_INDEX", 0)
    new_idx = (idx + 1) % len(pool)
    config["CURRENT_MODEL_INDEX"] = new_idx
    _save_config(config)
    new_name = pool[new_idx]["name"]
    logger.info(f"⚙️ 设置面板：模型切换为 {new_name}")
    return new_name


def _request_value(bot, chat_id, user_id, key, category, config):
    """请求管理员输入新值"""
    keys_map = CATEGORY_KEYS.get(category, {})
    key_info = keys_map.get(key)
    if not key_info:
        return

    path = key_info["path"]
    label = key_info["label"]
    unit = key_info.get("unit", "")
    current = _get_nested(config, path, key_info.get("default"))
    callback_data = f"settings_{category}_set_{key}"

    prompt = f"📝 请输入新的「{label}」值（当前：{current}{unit}）："

    # 记录等待会话
    _pending_value_sessions[(chat_id, user_id)] = {
        "key": key,
        "category": category,
        "path": path,
        "prompt": prompt,
        "callback_data": callback_data,
    }

    bot.send_message(chat_id, prompt)
    logger.info(f"⚙️ 设置面板：等待管理员输入 {label}")


def _apply_list_action(bot, chat_id, key, category, config, db=None):
    """处理列表查看操作"""
    keys_map = CATEGORY_KEYS.get(category, {})
    key_info = keys_map.get(key)
    if not key_info:
        return

    path = key_info["path"]
    label = key_info["label"]

    # ── 联邦封禁列表 ───────────────────────────────────────────────
    if path == "_list_federation":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT user_id, reason, ts FROM federation_bans ORDER BY ts DESC LIMIT 20"
                ).fetchall()
                if rows:
                    from datetime import datetime, timezone, timedelta
                    _CST = timezone(timedelta(hours=8))
                    lines = [f"📋 {label}（最近20条）：\n"]
                    for uid, reason, ts in rows:
                        dt = datetime.fromtimestamp(ts, _CST).strftime("%m-%d %H:%M") if ts else "?"
                        lines.append(f"  🚫 {uid} — {reason} ({dt})")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无记录")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 定点播报列表 ───────────────────────────────────────────────
    if path == "_list_broadcasts":
        broadcasts = config.get("SCHEDULED_BROADCASTS", [])
        if broadcasts:
            lines = [f"📋 {label}（共{len(broadcasts)}个）：\n"]
            for i, bc in enumerate(broadcasts, 1):
                status = "✅" if bc.get("enabled", False) else "❌"
                hh = int(bc.get("hour", 0))
                mm = int(bc.get("minute", 0))
                time_text = bc.get("time") or f"{hh:02d}:{mm:02d}"
                lines.append(f"  {i}. {status} {time_text} - {bc.get('content', '')[:30]}")
            bot.send_message(chat_id, "\n".join(lines))
        else:
            bot.send_message(chat_id, f"📋 {label}：暂无定点播报")
        return

    # ── 定时消息列表 ───────────────────────────────────────────────
    if path == "_list_scheduled_msgs":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT id, send_time, content, enabled FROM scheduled_messages ORDER BY id DESC LIMIT 20"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近20条）：\n"]
                    for sid, st, content, enabled in rows:
                        status = "✅" if enabled else "❌"
                        lines.append(f"  {sid}. {status} {st} - {content[:30]}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无定时消息")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 违禁词列表 ─────────────────────────────────────────────────
    if path == "_list_banned_words":
        words = config.get("BANNED_WORDS", [])
        if words:
            bot.send_message(chat_id, f" {label}：\n" + " / ".join(words))
        else:
            bot.send_message(chat_id, f"📋 {label}：暂无违禁词")
        return

    # ── 黑名单列表 ─────────────────────────────────────────────────
    if path == "_list_blacklist":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT user_id, reason FROM blacklist ORDER BY rowid DESC LIMIT 20"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近20人）：\n"]
                    for uid, reason in rows:
                        lines.append(f"  🚫 {uid} — {reason or '无原因'}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无记录")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 审批白名单 ─────────────────────────────────────────────────
    if path == "_list_approved":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT uid, approved_by, ts FROM approved_users WHERE chat_id=? ORDER BY ts DESC LIMIT 20",
                    (chat_id,)
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近20人）：\n"]
                    for uid, by, ts in rows:
                        lines.append(f"  ✅ {uid} (审批人: {by})")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无白名单")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 等级称号 ───────────────────────────────────────────────────
    if path == "_list_level_titles":
        titles = config.get("LEVEL_TITLES", {})
        if titles:
            lines = [f"📋 {label}：\n"]
            for level, title in sorted(titles.items()):
                lines.append(f"  Lv{level} — {title}")
            bot.send_message(chat_id, "\n".join(lines))
        else:
            bot.send_message(chat_id, f"📋 {label}：暂无配置")
        return

    # ── 商城商品 ───────────────────────────────────────────────────
    if path == "_list_shop_items":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT id, name, points_cost, stock FROM shop_items WHERE enabled=1 ORDER BY id"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}：\n"]
                    for sid, name, cost, stock in rows:
                        lines.append(f"  {sid}. {name} — {cost}积分 (库存{stock})")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f" {label}：暂无商品")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 优惠券列表 ─────────────────────────────────────────────────
    if path == "_list_coupons":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT id, code, type, value, expires_at FROM coupons WHERE enabled=1 ORDER BY id"
                ).fetchall()
                if rows:
                    from datetime import datetime, timezone, timedelta
                    _CST = timezone(timedelta(hours=8))
                    lines = [f"📋 {label}：\n"]
                    for cid, code, ctype, val, exp in rows:
                        dt = datetime.fromtimestamp(exp, _CST).strftime("%m-%d") if exp else "?"
                        lines.append(f"  {cid}. {code} — {ctype}({val}积分) 过期{dt}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无优惠券")
            except Exception as e:
                bot.send_message(chat_id, f"️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 发言统计 ───────────────────────────────────────────────────
    if path == "_list_speech_stats":
        if db:
            try:
                from datetime import datetime, timezone, timedelta
                _CST = timezone(timedelta(hours=8))
                today = datetime.now(_CST).strftime("%Y-%m-%d")
                rows = db.conn.execute(
                    "SELECT uid, count FROM speech_daily WHERE date=? ORDER BY count DESC LIMIT 10",
                    (today,)
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（今日TOP10）：\n"]
                    for uid, count in rows:
                        lines.append(f"  {uid} — {count}条")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：今日暂无数据")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 默认列表处理（自定义命令/群组笔记等） ─────────────────────────
    if path == "_list_custom_cmds":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT id, cmd_name, response FROM custom_commands ORDER BY id DESC LIMIT 20"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近20条）：\n"]
                    for cid, name, resp in rows:
                        lines.append(f"  {cid}. {name} → {resp[:30]}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无自定义命令")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    if path == "_list_notes":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT id, note_name FROM group_notes ORDER BY id DESC LIMIT 20"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}：\n"]
                    for nid, name in rows:
                        lines.append(f"  {nid}. {name}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无笔记")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    if path == "_list_disabled_cmds":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT DISTINCT cmd_name FROM disabled_commands ORDER BY cmd_name"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}：\n" + "、".join([r[0] for r in rows])]
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无禁用命令")
            except Exception as e:
                bot.send_message(chat_id, f"️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    if path == "_list_user_tags":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT uid, tag FROM user_tags ORDER BY uid DESC LIMIT 20"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近20条）：\n"]
                    for uid, tag in rows:
                        lines.append(f"  {uid} — {tag}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无标签")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    if path == "_list_certified":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT uid, certified_by, reason FROM certified_users ORDER BY ts DESC LIMIT 20"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近20人）：\n"]
                    for uid, by, reason in rows:
                        lines.append(f"  ✅ {uid} (认证人: {by}) — {reason or '无'}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f" {label}：暂无认证用户")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    if path == "_list_votekicks":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT id, target_uid, reason, yes_votes, no_votes, status FROM vote_kicks ORDER BY id DESC LIMIT 10"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近10条）：\n"]
                    for vid, target, reason, yes, no, status in rows:
                        lines.append(f"  {vid}. @user{target} — {reason} (赞成{yes}/反对{no}) [{status}]")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无投票")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 僵尸清理 ───────────────────────────────────────────────────
    if path == "_zombie_clean":
        if db:
            try:
                total = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                from datetime import datetime, timezone, timedelta
                _CST = timezone(timedelta(hours=8))
                threshold_days = _get_nested(config, "AUTO_KICK_INACTIVE_DAYS.days", 30)
                cutoff = int((datetime.now(_CST) - timedelta(days=threshold_days)).timestamp())
                inactive = db.conn.execute(
                    "SELECT COUNT(*) FROM users WHERE last_active < ?", (cutoff,)
                ).fetchone()[0]
                bot.send_message(
                    chat_id,
                    f"📋 {label}：\n"
                    f"  数据库用户：{total}\n"
                    f"  超过{threshold_days}天不活跃：{inactive}\n\n"
                    f"💡 发送 /zombieclean 触发僵尸扫描"
                )
            except Exception as e:
                bot.send_message(chat_id, f"📋 {label}：查询失败({e})，发送 /zombieclean 触发扫描")
        else:
            bot.send_message(chat_id, f"📋 {label}：发送 /zombieclean 触发僵尸扫描")
        return

    # ── 置顶管理 ───────────────────────────────────────────────────
    if path == "_list_pins":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT message_id, user_id, ts FROM reply_tracking WHERE replied=1 ORDER BY ts DESC LIMIT 10"
                ).fetchall()
                if rows:
                    lines = [f"📋 {label}（最近10条）：\n"]
                    for mid, uid, ts_val in rows:
                        lines.append(f"  📌 消息 {mid} by {uid}")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无记录")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 重发消息 ───────────────────────────────────────────────────
    if path == "_list_echo":
        bot.send_message(chat_id, f"📋 {label}：发送 /echo 跟随回复重发消息")
        return

    # ── 通用 fallback ──────────────────────────────────────────────
    if path == "_group_backup":
        bot.send_message(chat_id, f"📋 {label}：发送 /backup 备份当前群设置，/restore 恢复")
        return

    # ── 锁群状态 ───────────────────────────────────────────────────
    if path == "_list_locks":
        locks = config.get("MESSAGE_LOCKS", {})
        lines = [f"📋 {label}：\n"]
        for k, v in locks.items():
            status = "✅" if v else "❌"
            lines.append(f"  {status} {k}")
        bot.send_message(chat_id, "\n".join(lines))
        return

    # ── 夜间状态 ───────────────────────────────────────────────────
    if path == "_list_night_mode":
        nm = config.get("NIGHT_MODE_CONFIG", {})
        enabled = nm.get("enable", False)
        start = nm.get("start_hour", 23)
        end = nm.get("end_hour", 7)
        from datetime import datetime, timezone, timedelta
        _CST = timezone(timedelta(hours=8))
        now_hour = datetime.now(_CST).hour
        is_active = enabled and ((start > end and (now_hour >= start or now_hour < end)) or (start < end and start <= now_hour < end))
        text = f"📋 {label}：\n"
        text += f"  {'✅' if enabled else '❌'} 夜间模式\n"
        text += f"  {'🌙 运行中' if is_active else '☀️ 未运行'}\n"
        text += f"  时间：{start}:00 - {end}:00"
        bot.send_message(chat_id, text)
        return

    # ── 反垃圾状态 ─────────────────────────────────────────────────
    if path == "_list_ad_detect":
        ad = config.get("AD_DETECT_CONFIG", {})
        enabled = ad.get("enable", False)
        sensitivity = ad.get("sensitivity", 3)
        bot.send_message(chat_id, f"📋 {label}：\n  {'✅' if enabled else '❌'} 反垃圾检测\n  敏感度：{sensitivity}")
        return

    # ── 用户信息 ───────────────────────────────────────────────────
    if path == "_user_info":
        bot.send_message(chat_id, f"📋 {label}：回复用户消息 + /userinfo 查看详细信息")
        return

    # ── 远程管理 ───────────────────────────────────────────────────
    if path == "_list_connected_groups":
        if db:
            try:
                rows = db.conn.execute(
                    "SELECT uid, chat_id, ts FROM connected_chats ORDER BY ts DESC LIMIT 20"
                ).fetchall()
                if rows:
                    from datetime import datetime, timezone, timedelta
                    _CST = timezone(timedelta(hours=8))
                    lines = [f"📋 {label}（当前连接）：\n"]
                    for uid, cid, ts in rows:
                        dt = datetime.fromtimestamp(ts, _CST).strftime("%m-%d %H:%M") if ts else "?"
                        lines.append(f"  🔗 用户{uid} → 群{cid} ({dt})")
                    lines.append(f"\n💡 私聊发送 /connect 群组ID 连接群组")
                    bot.send_message(chat_id, "\n".join(lines))
                else:
                    bot.send_message(chat_id, f"📋 {label}：暂无远程连接\n💡 私聊发送 /connect 群组ID 连接群组")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 查询失败：{e}")
        else:
            bot.send_message(chat_id, f"📋 {label}：需要数据库连接")
        return

    # ── 邀请链接 ───────────────────────────────────────────────────
    if path == "_list_invite_link":
        try:
            link = bot.export_chat_invite_link(chat_id)
            bot.send_message(chat_id, f"📋 {label}：\n  🔗 {link}\n\n💡 使用 /invitelink 重新生成")
        except Exception as e:
            bot.send_message(chat_id, f"📋 {label}：无法获取邀请链接（{e}）\n💡 Bot需要管理员权限才能导出邀请链接")
        return

    # 通用 fallback
    bot.send_message(chat_id, f"📋 {label}：暂无数据")


def _apply_view_action(bot, chat_id, key, category, config):
    """处理查看操作"""
    keys_map = CATEGORY_KEYS.get(category, {})
    key_info = keys_map.get(key)
    if not key_info:
        return

    if key == "persona":
        if "BASE_PERSONA" in config:
            persona = config.get("BASE_PERSONA", "(空)")
            style = config.get("STYLE_APPEND", "")
            added = config.get("ADDED_KNOWLEDGE", "")
            knowledge = config.get("KNOWLEDGE", "")
            text = f"📋 当前人设：\n\n{persona}"
            if style:
                text += f"\n\n🎨 风格追加：\n{style}"
            if knowledge:
                text += f"\n\n📚 知识库：\n{knowledge}"
            if added:
                text += f"\n\n📝 追加知识：\n{added}"
        else:
            persona = config.get("SYSTEM_PROMPT", "(空)")
            text = f"📋 当前人设：\n\n{persona}"

        if len(text) > 4000:
            text = text[:4000] + "\n\n... (内容过长，已截断)"
        bot.send_message(chat_id, text)
        logger.info("⚙️ 设置面板：查看人设")


# ══════════════════════════════════════════════════════════════════════════
#  回调路由
# ══════════════════════════════════════════════════════════════════════════

def handle_settings_callback(bot, call, config, db=None):
    """
    主路由：处理所有 settings_ 开头的回调
    返回 True 表示已处理，False 表示不是设置面板回调
    """
    data = call.data
    if not data or not data.startswith("settings_"):
        return False

    user_id = call.from_user.id
    chat_id = call.message.chat.id

    # 权限检查
    if not _is_admin(user_id, config):
        bot.answer_callback_query(call.id, text="⛔ 无权限", show_alert=True)
        return True

    # 解析回调数据
    parts = data.split("_")
    if len(parts) < 3:
        bot.answer_callback_query(call.id, text="️ 无效操作")
        return True

    category = parts[1]
    action = parts[2]
    key = "_".join(parts[3:]) if len(parts) > 3 else ""

    # ── 主菜单入口 ───────────────────────────────────────────────────
    if action == "menu" and not key:
        text, keyboard = render_main_menu(config)
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id,
                                  reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id)
        return True

    # ── 返回主菜单 ──────────────────────────────────────────────────
    if action == "back" and key == "main":
        text, keyboard = render_main_menu(config)
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id,
                                  reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id)
        return True

    # ── 子菜单入口 ──────────────────────────────────────────────────
    render_map = {
        "basic": render_basic_menu,
        "security": render_security_menu,
        "members": render_members_menu,
        "messages": render_messages_menu,
        "interact": render_interact_menu,
        "economy": render_economy_menu,
        "broadcast": render_broadcast_menu,
        "advanced": render_advanced_menu,
    }

    if action == "menu" and category in render_map:
        text, keyboard = render_map[category](config)
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id,
                                  reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id)
        return True

    # ── 开关切换 ────────────────────────────────────────────────────
    if action == "toggle" and key:
        new_val = _toggle_setting(key, category, config)
        if new_val is not None:
            keys_map = CATEGORY_KEYS.get(category, {})
            key_info = keys_map.get(key, {})
            label = key_info.get("label", key)
            bot.answer_callback_query(call.id, text=f"{label}：{_status_text(new_val)}")
            if category in render_map:
                text, keyboard = render_map[category](config)
                try:
                    bot.edit_message_text(text, chat_id, call.message.message_id,
                                          reply_markup=keyboard, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
        else:
            bot.answer_callback_query(call.id, text="⚠️ 操作失败")
        return True

    # ── 模式循环切换 ────────────────────────────────────────────────
    if action == "cycle" and key:
        if key == "model":
            new_name = _cycle_model(config)
            if new_name:
                bot.answer_callback_query(call.id, text=f"模型切换为：{new_name}")
                if category in render_map:
                    text, keyboard = render_map[category](config)
                    try:
                        bot.edit_message_text(text, chat_id, call.message.message_id,
                                              reply_markup=keyboard, parse_mode="HTML")
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
            else:
                bot.answer_callback_query(call.id, text="️ 模型池为空")
        else:
            new_val = _cycle_setting(key, category, config)
            if new_val is not None:
                keys_map = CATEGORY_KEYS.get(category, {})
                key_info = keys_map.get(key, {})
                labels = key_info.get("labels", {})
                label = key_info.get("label", key)
                new_label = labels.get(new_val, str(new_val))
                bot.answer_callback_query(call.id, text=f"{label}：{new_label}")
                if category in render_map:
                    text, keyboard = render_map[category](config)
                    try:
                        bot.edit_message_text(text, chat_id, call.message.message_id,
                                              reply_markup=keyboard, parse_mode="HTML")
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
            else:
                bot.answer_callback_query(call.id, text="⚠️ 操作失败")
        return True

    # ── 数值修改（触发输入等待） ─────────────────────────────────────
    if action == "set" and key:
        _request_value(bot, chat_id, user_id, key, category, config)
        bot.answer_callback_query(call.id)
        return True

    # ── 列表查看 ───────────────────────────────────────────────────
    if action == "list" and key:
        _apply_list_action(bot, chat_id, key, category, config, db)
        bot.answer_callback_query(call.id)
        return True

    # ── 查看操作 ────────────────────────────────────────────────────
    if action == "view" and key:
        _apply_view_action(bot, chat_id, key, category, config)
        bot.answer_callback_query(call.id)
        return True

    bot.answer_callback_query(call.id, text="⚠️ 未知操作")
    return True


# ══════════════════════════════════════════════════════════════════════════
#  等待输入会话管理
# ══════════════════════════════════════════════════════════════════════════

def has_pending_session(chat_id, user_id):
    """检查是否有等待中的输入会话（供main.py调用）"""
    return (chat_id, user_id) in _pending_value_sessions


def apply_pending_value(bot, chat_id, user_id, value, config):
    """
    应用管理员输入的新值（供main.py调用）
    返回 True 表示成功消费该消息
    """
    session_key = (chat_id, user_id)
    session = _pending_value_sessions.get(session_key)
    if not session:
        return False

    key = session["key"]
    category = session["category"]
    path = session["path"]

    keys_map = CATEGORY_KEYS.get(category, {})
    key_info = keys_map.get(key, {})
    label = key_info.get("label", key)
    unit = key_info.get("unit", "")

    # 类型转换：int → float → string
    try:
        int_val = int(value)
        _set_nested(config, path, int_val)
        _save_config(config)
        bot.send_message(chat_id, f"✅ {label} 已设为 {int_val}{unit}")
        logger.info(f"️ 设置面板：{path} 设为 {int_val}")
    except ValueError:
        try:
            float_val = float(value)
            _set_nested(config, path, float_val)
            _save_config(config)
            bot.send_message(chat_id, f"✅ {label} 已设为 {float_val}{unit}")
            logger.info(f"⚙️ 设置面板：{path} 设为 {float_val}")
        except ValueError:
            _set_nested(config, path, value)
            _save_config(config)
            bot.send_message(chat_id, f"✅ {label} 已设为 {value}")
            logger.info(f"⚙️ 设置面板：{path} 设为 {value}")

    # 清除等待会话（并发安全：用 pop 避免 del KeyError）
    _pending_value_sessions.pop(session_key, None)
    return True
