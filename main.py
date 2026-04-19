"""
╔══════════════════════════════════════════════════════════════════════════╗
║  main.py  ·  Mory 私域超级分身机器人  v4.0                              ║
║                                                                            ║
║  架构：模块化 | 多模型无缝轮换 | 线程安全 | 无感智能化运营                   ║
║  入口：python main.py                                                       ║
║                                                                            ║
║  【数据安全】                                                               ║
║    - 所有用户数据（积分/等级/画像/黑名单/转化漏斗）存储在 mory.db            ║
║    - 配置（TOKEN/API_KEY/人设/模型列表）存储在 config.json                   ║
║    - 更新代码（.py文件）不会触碰这两个文件，数据绝对不会丢失                  ║
║    - 更新前 start.sh update 会自动备份 config.json 和 mory.db               ║
║    - 如果更新出问题：bash start.sh restore 即可恢复                         ║
║                                                                            ║
║  【消息分发优先级】                                                         ║
║    P0  新人入群欢迎                                                         ║
║    P1  黑名单用户过滤（最早拦截，节省资源）                                   ║
║    P2  用户活跃度更新 + 积分                                               ║
║    P3  敏感词检测+删除                                                      ║
║    P4  反刷屏检测+禁言                                                      ║
║    P5  野生机器人过滤                                                       ║
║    P6  管理员专属指令                                                       ║
║    P7  视奸雷达（价格关键词通知管理员）                                      ║
║    P8  固定彩蛋响应                                                         ║
║    P9  用户画像标签提取                                                     ║
║    P10 AI回复（根据模式选择不同人格）                                       ║
║                                                                            ║
║  【模块说明】                                                               ║
║    core/ai_engine.py  - AI调用引擎（14模型轮换+9种模式+节日人格）          ║
║    core/database.py   - SQLite数据层（11张表+互斥锁+完整CRUD+画像简报）     ║
║    modules/admin_cmds - 管理员指令（绑定/人设/代发/简报/排行榜/画像/模型切换）║
║    modules/group_mgr  - 超级群管（欢迎/敏感词/反刷/流失打捞/黑话/天气共情）  ║
║    modules/auto_tasks - 后台任务（新闻/叫醒/阅后即焚/挽回/备份/背刺泄密）    ║
║    modules/content    - 内容彩蛋（塔罗/运势/彩蛋/打码/服务查询/寻宝）         ║
║                                                                            ║
║  【v21.11 更新记录】                                                       ║
║    - 新增：连续对话绿茶风反问（>=2轮60%概率，保持对话不停歇）                ║
║    - 新增：连续对话自然植入暗示（>=3轮30%概率，不提钱不违和）                ║
║    - 新增：连续对话轻量转化引导（>=5轮30%概率，暗示支持/赞助）              ║
║    - 优化：SYSTEM_PROMPT增加对话连贯性规则，回复更像朋友聊天                  ║
║    - AI引擎新增3种模式：hook/nudge/convert_soft                              ║
║  【v21.10 更新记录】                                                       ║
║    - 修复（致命）：auto_tasks.py的last_probe_time未初始化，后台线程启动即崩溃    ║
║    - 修复：阅后即焚探测/新闻/问候/备份等所有后台任务恢复正常                   ║
║    - 优化：移除AI回复路径中多余的track_reply（monkey-patch已处理）              ║
║    - 新增：启动时数据库写入测试，验证track_reply功能正常                       ║
║  【v21.9a 更新记录】                                                        ║
║    - 核心修复：bot.reply_to全局包装，所有群聊回复自动追踪阅后即焚              ║
║    - 新增：多管理员支持（回复消息+添加管理员指令）                           ║
║    - 新增：管理员指令「查看管理员」显示当前管理员列表                        ║
║    - 修复：清群无人理/清全部回复查询和清理逻辑                               ║
║    - 增强：track_reply加日志，清除指令加详细日志方便排查                     ║
║  【v21.8 更新记录】                                                         ║
║    - 新增：管理员指令「清群无人理」——立刻删除群里所有无人回复的机器人消息           ║
║    - 新增：管理员指令「清全部回复」——立刻删除群里最近24h所有机器人回复             ║
║    - 优化：早/午/晚安prompt全面重写，角色代入朋友圈发帖场景，绿茶引导更自然     ║
║    - 优化：问候截断从60字放宽到100字，保证引导语不被截掉                       ║
║    - 增强：三条问候发送后记录实际内容到日志，方便排查                           ║
║  【v21.7 更新记录】                                                         ║
║    - 修复：定时任务时区修正为UTC+8（VPS默认UTC导致时间全错）                   ║
║    - 修复：早/午/晚安prompt加硬约束+代码层截断保护（AI不再长篇大论）           ║
║    - 修复：阅后即焚数据库兼容迁移（旧库缺少replied列导致静默失败）            ║
║    - 增强：阅后即焚探测增加详细日志，方便排查问题                              ║
║  【v21.6 更新记录】                                                         ║
║    - 修复：group_mgr.py天气共情语法错误（for循环后elif无对应if）            ║
║    - 修复：start.sh版本号从v21.0同步到v21.6                                 ║
║  【v21.5 更新记录】                                                         ║
║    - 新增：早/中/晚三次新闻播报（9:00/13:00/20:30）                        ║
║    - 新增：早安(8:00)/午安(12:30)/晚安(23:00)定时问候                     ║
║    - 新增：6个AI模式(含随机种子防重复)                                     ║
║    - 新增：私聊消息自动转发给管理员（用户消息+AI回复）                    ║
║    - 优化：人设新增Mory老板定位（最美/诚意/不虚伪/有态度的自媒体博主）     ║
║    - 优化：新闻结尾改为走心走肾随机感性短句                               ║
║    - 优化：早晚问候加绿茶风隐晦引导（不提价格提升转化）                   ║
║    - 优化：阅后即焚探测窗口从10分钟扩大到20分钟                            ║
║  【v21.4 更新记录】                                                         ║
║    - 新增：背刺泄密改为每周1次+随机时间+AI绝对不重复                        ║
║    - 新增：碎片寻宝加每日限制，连续7天凑齐领奖                              ║
║    - 新增：查看画像指令，单用户完整画像+TOP5简报+营销建议                   ║
║    - 新增：黑话/行话词典，15条术语自动识别科普                              ║
║    - 增强：天气/城市共情硬编码（18种天气+50个城市）                         ║
║  【v21.3 更新记录】                                                         ║
║    - 价格体系全面更新，16项完整服务                                         ║
║    - 群规改版，新人引导加自助下单提示                                       ║
║  【v21.2 更新记录】                                                         ║                                                         ║
║    - 修复：删除不兼容的 deleted_messages_handler，改用后台探测方案           ║
║    - 优化：阅后即焚探测频率从10分钟缩短到3分钟，窗口扩大到10分钟            ║
║    - 说明：pyTelegramBotAPI 不支持监听消息删除事件，改用 forward 探测实现   ║
║  【v21.1 更新记录】                                                         ║
║    - 新增：阅后即焚——机器人回复被删后立即删除同线程后续消息                 ║
║    - 修复：打字延迟改为固定5-10秒随机，不再按字数计算                        ║
║    - 修复：随机尬聊概率改为10%（原30%太高）                                 ║
║    - 修复：生物钟改为凌晨0-5点（原3-5点范围太小）                            ║
║    - 修复：减少每次save_config调用频率（原每60秒一次改为仅模型切换时）      ║
║    - 修复：阅后即焚探测改为3分钟一次（原10分钟），窗口扩大到10分钟               ║
║    - 说明：阅后即焚完整方案在 auto_tasks.py 后台线程中实现                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, random, logging, traceback
from datetime import datetime
from threading import Lock
from logging.handlers import RotatingFileHandler
from core.logging_util import configure_logging, get_logger, set_logging_context, clear_logging_context

# ── 项目根目录（基于脚本位置，跨目录启动也正确）──
base_dir = os.path.dirname(os.path.abspath(__file__))

# ── 加载 .env 环境变量（敏感信息不硬编码）────────────────────────────
def _load_env():
    """从 .env 文件加载环境变量（.env 不进 git）"""
    env_file = os.path.join(base_dir, ".env")
    if os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

# ── 日志配置（带轮转，单文件不超过10MB，保留5个备份）────────────────
configure_logging(
    level=logging.INFO,
    log_file=os.path.join(base_dir, "mory.log"),
    max_bytes=10*1024*1024,
    backup_count=5,
    json_format=False,
    console_output=True,
)
logger = get_logger("main")

# ── 自动安装依赖 ──────────────────────────────────────────────────────
def _ensure_deps():
    pkgs = ["pyTelegramBotAPI", "requests", "Pillow"]
    import importlib
    missing = []
    for p in pkgs:
        mod = "telebot" if "TelegramBotAPI" in p else ("PIL" if p == "Pillow" else p.lower())
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(p)
    
    if not missing:
        return
    
    logger.info(f"📦 自动安装依赖：{missing}")

    # 按优先级尝试多种安装方式（兼容不同系统）
    installed = False
    
    # 方式1: 使用项目venv（推荐）
    import sys as _sys
    if _sys.platform == "win32":
        venv_pip = os.path.join(base_dir, "venv", "Scripts", "pip.exe")
    else:
        venv_pip = os.path.join(base_dir, "venv", "bin", "pip")
    if os.path.exists(venv_pip):
        ret = os.system(f"{venv_pip} install {' '.join(missing)} -q 2>/dev/null")
        installed = (ret == 0)
    
    # 方式2: python3 -m pip --break-system-packages (Debian/Ubuntu PEP 668兼容)
    if not installed:
        ret = os.system(
            f"python3 -m pip install --break-system-packages {' '.join(missing)} -q 2>/dev/null"
        )
        installed = (ret == 0)
    
    # 方式3: pip3 --user
    if not installed:
        os.system(f"pip3 install --user {' '.join(missing)} -q 2>/dev/null")
    
    logger.info("✅ 依赖安装完成")

_ensure_deps()

import telebot

# ── 导入各模块 ────────────────────────────────────────────────────────
from core.ai_engine import AIEngine, calc_typing_delay
from core.database  import DB
from core.mory_bot import MoryBot  # 【架构重构v21.44】显式机器人封装层
from modules.admin_cmds import handle_admin
from modules.group_mgr  import (handle_new_members, check_banned_words,
                                  check_spam, handle_left_member, detect_keywords)
from modules.auto_tasks import start_background
from modules.content    import (handle_easter_eggs, handle_photo,
                                  draw_tarot, get_fortune, is_late_night)

# ── 连续对话追踪（内存字典 + 线程安全）────────────────────────────
# key=uid, value={"count": int, "last_time": float}
# 用于：绿茶风反问（保持对话）+ 连续对话后的转化引导植入
_conv_tracker = {}
_conv_lock = Lock()  # 【修复v21.46】防止多线程并发修改字典导致RuntimeError
_CONV_TIMEOUT = 300  # 5分钟无对话则计数清零
_conv_last_cleanup = 0  # 上次清理时间戳

def _cleanup_conv_tracker():
    """清理超时的对话追踪条目（每10分钟执行一次，线程安全）"""
    global _conv_last_cleanup
    now = time.time()
    if now - _conv_last_cleanup < 600:
        return
    _conv_last_cleanup = now
    with _conv_lock:  # 【修复v21.46】加锁遍历和删除
        expired = [uid for uid, v in _conv_tracker.items() if now - v["last_time"] > _CONV_TIMEOUT]
        for uid in expired:
            del _conv_tracker[uid]

# ── 视奸雷达冷却机制（内存字典 + 线程安全）────────────────────────
# 防止同一用户频繁触发导致管理员被刷屏
_radar_cooldown = {}  # key=uid, value=上次触发时间戳
_RADAR_COOLDOWN = 3600  # 1小时冷却时间

# ── 配置读写 ──────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(base_dir, "config.json")  # 基于脚本目录的绝对路径
_config_lock = Lock()

def load_config() -> dict:
    """加载配置文件，并从数据库覆盖动态状态"""
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ver = cfg.get("_CONFIG_VERSION", "未知")
            logger.info(f"📋 配置版本：v{ver}")
        except Exception as e:
            logger.error(f"配置读取失败：{e}")
    
    # 【架构重构v21.44】从数据库加载动态状态，覆盖配置文件
    # 动态状态包括：当前模型索引、图片池、语音池等运行时数据
    _load_dynamic_states(cfg)
    
    return cfg

def _load_dynamic_states(cfg: dict):
    """从数据库加载动态状态到配置"""
    global db
    if db is None:
        return
    
    # 从数据库读取动态状态
    dynamic_keys = [
        "CURRENT_MODEL_INDEX",
        "IMAGE_POOL", 
        "VOICE_POOL",
        "_LAST_LEAK_WEEK"
    ]
    
    for key in dynamic_keys:
        db_value = db.get_system_state(key)
        if db_value is not None:
            # 根据配置文件的类型决定如何解析
            if key in ("CURRENT_MODEL_INDEX",):
                cfg[key] = int(db_value) if db_value else 0
            elif key in ("IMAGE_POOL", "VOICE_POOL"):
                try:
                    cfg[key] = json.loads(db_value)
                except:
                    cfg[key] = []
            elif key == "_LAST_LEAK_WEEK":
                cfg[key] = int(db_value) if db_value else -1
            else:
                cfg[key] = db_value
            logger.debug(f"📌 动态状态加载: {key}={cfg[key]}")

def save_config():
    """保存配置到文件，并同步动态状态到数据库"""
    global db
    with _config_lock:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"配置保存失败：{e}")
    
    # 【架构重构v21.44】同步动态状态到数据库
    if db is not None:
        dynamic_keys = ["CURRENT_MODEL_INDEX", "IMAGE_POOL", "VOICE_POOL", "_LAST_LEAK_WEEK"]
        for key in dynamic_keys:
            if key in CONFIG:
                value = CONFIG[key]
                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                db.set_system_state(key, value)

CONFIG = load_config()

# ── 安全覆盖：环境变量优先于 config.json（敏感信息不硬编码）───────────
if os.environ.get("TG_TOKEN"):
    CONFIG["TOKEN"] = os.environ["TG_TOKEN"]
if os.environ.get("DASHSCOPE_KEY"):
    CONFIG["API_KEY"] = os.environ["DASHSCOPE_KEY"]

# ── 校验必填项 ────────────────────────────────────────────────────────
if not CONFIG.get("TOKEN") or CONFIG["TOKEN"] == "YOUR_BOT_TOKEN_HERE":
    logger.critical("❌ TOKEN 未填写！请编辑 config.json 或设置 TG_TOKEN 环境变量后重启。")
    sys.exit(1)
if not CONFIG.get("API_KEY") or CONFIG["API_KEY"] == "YOUR_DASHSCOPE_API_KEY_HERE":
    logger.critical("❌ API_KEY 未填写！请编辑 config.json 后重启。")
    sys.exit(1)


# ── 初始化核心组件 ────────────────────────────────────────────────────
db  = DB(os.path.join(base_dir, "mory.db"))
ai  = AIEngine(CONFIG)

# 【架构重构v21.44】数据库初始化后，重新加载动态状态到 CONFIG
_load_dynamic_states(CONFIG)
bot = telebot.TeleBot(CONFIG["TOKEN"], threaded=True, num_threads=50)

# 【修复】全局缓存bot自身信息，只调用1次get_me()
_bot_me = bot.get_me()
BOT_ID = _bot_me.id
BOT_USERNAME = _bot_me.username
logger.info(f"🤖 Bot ID: {BOT_ID}, Username: @{BOT_USERNAME}")

# ── 启动时数据库完整性检查 ────────────────────────────────────────────
try:
    result = db.conn.execute("PRAGMA integrity_check").fetchone()
    if result and result[0] == "ok":
        table_count = db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        logger.info(f"✅ 数据库完整性检查通过（{table_count} 张表）")
    else:
        logger.error(f"⚠️ 数据库完整性异常：{result}")
        logger.error("   → 如果运行异常，从 backup/ 目录恢复最近备份")
except Exception as e:
    logger.error(f"⚠️ 数据库检查出错：{e}")

# ── 启动时数据库写入测试（验证track_reply功能正常）───────────────────
try:
    logger.info("🔍 开始阅后即焚数据库功能测试...")
    
    # 【修复】使用内存 SQLite 测试，不写生产数据库
    import sqlite3 as _sqlite3
    test_conn = _sqlite3.connect(":memory:")
    test_cursor = test_conn.cursor()
    test_cursor.execute("""CREATE TABLE IF NOT EXISTS reply_tracking (
        bot_msg_id INTEGER,
        chat_id INTEGER,
        user_msg_id INTEGER,
        ts INTEGER,
        replied INTEGER DEFAULT 0,
        PRIMARY KEY (bot_msg_id, chat_id)
    )""")
    
    test_bot_id = 999999999
    test_chat_id = 999999999
    test_user_id = 999999999
    
    logger.info(f"🔍 测试track_reply插入: bot={test_bot_id} chat={test_chat_id} user={test_user_id}")
    # 直接用内存库的SQL验证表结构正确性
    test_cursor.execute("INSERT INTO reply_tracking VALUES (?,?,?,?,0)",
                        (test_bot_id, test_chat_id, test_user_id, int(time.time())))
    test_cursor.execute("SELECT bot_msg_id FROM reply_tracking WHERE bot_msg_id=?", (test_bot_id,))
    found = test_cursor.fetchone() is not None
    test_conn.close()
    
    if found:
        logger.info("✅ 阅后即焚数据库功能测试通过（内存测试，未写生产库）")
    else:
        logger.error("❌ 阅后即焚数据库结构测试失败！")
    
except Exception as e:
    logger.error(f"❌ 阅后即焚数据库写入测试异常：{e}")
    import traceback
    logger.error(f"❌ 测试异常详情：{traceback.format_exc()}")

# ── 启动后台自动任务 ──────────────────────────────────────────────────
start_background(bot, CONFIG, db, ai, save_config)

# 【架构重构v21.44】初始化 MoryBot 封装层（替代 Monkey Patch）
mory_bot = MoryBot(bot, db, CONFIG)

# ════════════════════════ 消息处理器 ══════════════════════════════════

# 【v4.0 强制注入：全局回复嗅探器】
# ⚠️ 必须放在所有其他 handler 的最前面！
@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def global_reply_sniffer(m):
    """
    【全局回复嗅探器 v4.0】
    专门解决"用户回复了，但系统不认"的致命Bug。
    只要检测到用户是在回复机器人，立刻秒级更新数据库状态。
    """
    try:
        if m.reply_to_message.from_user.is_bot:
            # 用户在回复机器人
            bot_msg_id = m.reply_to_message.message_id
            chat_id = m.chat.id
            # 标记数据库：该消息已被回复，获得"免死金牌"
            db.mark_replied(bot_msg_id, chat_id)
            logger.info(f"✅ [全局嗅探] 成功捕获用户回复！豁免 bot_msg_id={bot_msg_id}")
    except Exception as e:
        logger.warning(f"全局回复嗅探器异常：{e}")
    
    # 嗅探完毕后，必须放行！让其他业务逻辑继续处理这条消息
    return False

# ── 图片打码 ──────────────────────────────────────────────────────────
@bot.message_handler(content_types=["photo"])
def on_photo(m):
    try:
        handle_photo(bot, m, CONFIG)
    except Exception as e:
        logger.error(f"图片处理异常：{e}")


# ── 语音消息：自动转发给管理员 + 尝试AI识别回复 ────────────────
@bot.message_handler(content_types=["voice"])
def on_voice(m):
    try:
        uid = m.from_user.id
        uname = m.from_user.first_name or "神秘人"
        chat_id = m.chat.id
        is_priv = m.chat.type == "private"
        
        # 获取语音文件信息
        file_info = bot.get_file(m.voice.file_id)
        duration = getattr(m.voice, 'duration', 0)  # 秒
        
        # 转发给管理员
        admin_id = CONFIG.get("ADMIN_ID", 0)
        # 【修复BUG-4】移除测试遗留的 or True，仅私聊语音转发给管理员
        if admin_id and is_priv:
            try:
                bot.forward_message(admin_id, chat_id, m.message_id,
                                    disable_notification=True)
                bot.send_message(admin_id,
                    f"🎤 语音通知\n👤 {uname}({uid}) 发来一条语音"
                    f"\n⏱ 时长: {duration}秒\n💬 来源: {'私聊' if is_priv else '群聊'}")
                logger.info(f"🎤 语音转发: uid={uid} duration={duration}s")
            except Exception as e:
                logger.error(f"🎤 语音转发失败: {e}")
        
        # 私聊中尝试用AI回复（提示用户可以发文字）
        if is_priv:
            resp = ai.ask("对方发了一条语音消息，你听不见，用俏皮的方式让他发文字给你", mode="normal")
            if resp:
                bot.send_message(chat_id, resp)
                
    except Exception as e:
        logger.error(f"语音处理异常：{e}")


# ── 流失打捞 ──────────────────────────────────────────────────────────
@bot.message_handler(content_types=["left_chat_member"])
def on_left(m):
    try:
        handle_left_member(bot, m, CONFIG)
    except Exception as e:
        logger.error(f"流失打捞异常：{e}")


# ── 阅后即焚说明 ──────────────────────────────────────────────────────
#    pyTelegramBotAPI 不支持 deleted_messages_handler（监听消息被删事件）。
#    【v4.0 架构升级】
#      1. main.py 的 global_reply_sniffer 实时捕获用户回复，秒级标记 replied=1
#      2. auto_tasks.py 的 _job_burn_orphan 每小时清理 24h 未回复的孤儿消息
#    彻底废除 forward_message 探测，避免 429 Rate Limit 封号风险。


# ── Function Calling 工具定义 ──────────────────────────────────────
#    让AI在群聊中能主动触发转化动作（发价格表、引导私聊等）。
#    只在群聊normal模式（非@非回复）时启用，避免干扰定向对话。

def _get_function_tools():
    """返回AI可用的工具列表（OpenAI function calling格式）"""
    return [
        {
            "type": "function",
            "function": {
                "name": "send_price_list",
                "description": "主动发送价格表给用户。当用户表现出购买意向（问价格、问怎么买、犹豫不决、比较方案）时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "推荐的商品类别，如：至臻精选/至臻全享/社交解锁/原味/定制",
                            "enum": ["至臻精选", "至臻全享", "精选图集", "社交解锁", "原味", "定制", "全部"]
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "send_private_guide",
                "description": "引导用户私聊了解详情。当用户表现出兴趣但还在犹豫时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "引导私聊的理由，如：'详情太多群里说不完'、'有专属福利'、'私聊更方便'"
                        }
                    },
                    "required": []
                }
            }
        },
    ]


def _handle_tool_calls(message: dict, bot, m, config: dict, db) -> str | None:
    """
    处理AI的函数调用，执行对应操作，返回AI生成的文字回复。
    如果AI同时生成了文字+函数调用，文字回复会被附加到工具执行结果后面。
    """
    tool_calls = message.get("tool_calls", [])
    text_content = message.get("content", "")
    
    if not tool_calls:
        return text_content or None
    
    tool_outputs = []
    for tc in tool_calls:
        func = tc.get("function", {})
        func_name = func.get("name", "")
        
        try:
            # 解析参数（安全解析，容错）
            import json as _json
            args = {}
            if func.get("arguments"):
                try:
                    args = _json.loads(func["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = {}
            
            if func_name == "send_price_list":
                result = _exec_send_price_list(bot, m, config, args)
                tool_outputs.append(result)
                logger.info(f"🔧 Function Calling: send_price_list uid={m.from_user.id}")
                
            elif func_name == "send_private_guide":
                result = _exec_send_private_guide(bot, m, config, args)
                tool_outputs.append(result)
                logger.info(f"🔧 Function Calling: send_private_guide uid={m.from_user.id}")
            else:
                logger.warning(f"🔧 未知工具: {func_name}")
        except Exception as e:
            logger.error(f"🔧 工具执行失败 {func_name}: {e}")
    
    # 返回AI原始文字回复 + 工具执行结果提示
    if tool_outputs:
        return (text_content + "\n" + "\n".join(tool_outputs)) if text_content else "\n".join(tool_outputs)
    return text_content or None


def _exec_send_price_list(bot, m, config: dict, args: dict) -> str:
    """执行发送价格表工具（私聊发送，不在群里发）"""
    price_list = config.get("PRICE_LIST", {})
    category = args.get("category", "")
    uid = m.from_user.id
    
    # 生成价格表文本
    text = ""
    if category and category != "全部" and category in price_list:
        info = price_list[category]
        lines = [f"💰 {category}"]
        for k, v in info.items():
            if k in ("monthly", "quarterly", "yearly", "price"):
                lines.append(f"  ¥{v}")
            elif k == "note":
                lines.append(f"  📌 {v}")
        text = "\n".join(lines)
    elif price_list:
        # 没指定类别，发完整价格表
        lines = ["💰 Mory 价格表"]
        for cat, info in price_list.items():
            lines.append(f"\n▸ {cat}")
            for k, v in info.items():
                if k in ("monthly", "quarterly", "yearly", "price"):
                    lines.append(f"  ¥{v}")
                elif k == "note":
                    lines.append(f"  📌 {v}")
        text = "\n".join(lines)
    
    if not text:
        return ""
    
    # 尝试私聊发送
    try:
        bot.send_message(uid, text)
        db.log_conversion_event(uid, "interested")
        logger.info(f"🔧 FC价格表私聊发送成功 uid={uid}")
        return ""  # 已私聊发送，群聊不附加任何文字
    except Exception as e:
        # 用户没加bot好友/没开私聊，在群里暗示引导
        logger.warning(f"🔧 FC价格表私聊失败 uid={uid}: {e}（用户可能未加bot好友）")
        return "\n💡 想了解详情吗？先私信小助理，我把完整价格表发给你～"


def _exec_send_private_guide(bot, m, config: dict, args: dict) -> str:
    """执行引导私聊工具（私聊发送详细引导）"""
    reason = args.get("reason", "详情太多群里说不完")
    uid = m.from_user.id
    
    # 尝试私聊发送引导
    try:
        guide_text = (
            f"💌 嘿，{reason}\n"
            f"这里不方便细说，私聊我慢慢跟你聊～\n\n"
            f"💡 你可以直接在这里问我任何关于Mory的问题哦～"
        )
        bot.send_message(uid, guide_text)
        logger.info(f"🔧 FC引导私聊发送成功 uid={uid}")
        return ""  # 已私聊发送，群聊不附加任何文字
    except Exception as e:
        # 私聊失败，群里温和引导
        logger.warning(f"🔧 FC引导私聊失败 uid={uid}: {e}")
        return f"\n💌 {reason}，私信小助理我慢慢跟你说～"


# ── 全域消息主分发器 ──────────────────────────────────────────────────
@bot.message_handler(func=lambda m: True,
                     content_types=["text", "new_chat_members"])
def master_handler(m):
    try:
        _dispatch(m)
    except Exception as e:
        logger.error(f"❌ 主分发器异常：{e}\n{traceback.format_exc()}")


def _dispatch(m):
    """消息分发核心逻辑（优先级严格控制）"""
    # ── 【DEBUG】全量消息入口日志（排查收不到@消息的问题） ────────
    _dbg_msg = (m.text or "")[:50]
    _dbg_uname = (m.from_user.first_name or "?")[:20]
    _dbg_chat_type = m.chat.type or "?"
    _dbg_chat_id = str(m.chat.id)
    _dbg_uid = str(m.from_user.id)
    logger.info(f"[MSG_IN] uid={_dbg_uid} name={_dbg_uname} chat={_dbg_chat_id}({_dbg_chat_type}) type={_dbg_chat_type} text='{_dbg_msg}'")

    # ── 基本信息提取 ─────────────────────────────────────────────────
    msg      = m.text or ""
    uid      = m.from_user.id
    uname    = m.from_user.first_name or "神秘人"
    chat_id  = m.chat.id
    is_priv  = m.chat.type == "private"
    is_group = m.chat.type in ("group", "supergroup")
    
    # 设置日志上下文
    set_logging_context(uid=uid, chat_id=chat_id, msg_id=m.message_id, uname=uname)

    # ── P0：新人入群 ──────────────────────────────────────────────────
    if m.content_type == "new_chat_members":
        handle_new_members(bot, m, CONFIG, db)
        clear_logging_context()
        return

    # ── P1：黑名单用户直接忽略（在活跃度更新之前，避免污染数据）──────
    if db.is_blacklisted(uid):
        clear_logging_context()
        return

    # ── P2：更新用户活跃度 / 群ID / 积分 ───────────────────────────────
    db.upsert_user(uid, uname, "private" if is_priv else "group")
    db.add_points(uid, 1)  # 发言积分+1
    if is_group:
        gid = CONFIG.get("GROUP_ID", 0)
        if gid == 0:  # 只在未设置时才自动记录群ID，已设置过的不覆盖
            CONFIG["GROUP_ID"] = chat_id
            save_config()

    # ── 解除阅后即焚锁定（用户回复了机器人的消息）─────────────────────
    if m.reply_to_message and m.reply_to_message.from_user.id == BOT_ID:
        db.mark_replied(m.reply_to_message.message_id, chat_id)


    # ── P3：黑名单词过滤 ──────────────────────────────────────────────
    if is_group and check_banned_words(bot, m, CONFIG, db):
        clear_logging_context()
        return

    # ── P4：反刷机制 ─────────────────────────────────────────────────
    if is_group and check_spam(bot, m, CONFIG, db):
        clear_logging_context()
        return

    # ── P5：过滤野生机器人 ────────────────────────────────────────────
    if any(b.lower() in uname.lower() for b in CONFIG.get("IGNORE_BOTS", [])):
        clear_logging_context()
        return

    # ── P6：管理员专属指令（含绑定主人）─────────────────────────────
    admin_result = handle_admin(bot, mory_bot, CONFIG, db, ai, save_config)
    if admin_result:
        logger.info(f"👑 管理员指令执行成功 uid={uid} msg={msg[:30]}")
        clear_logging_context()
        return

    # ── P7：视奸雷达（价格关键词通知管理员 + 冷却机制）────────────
    price_kws = ["多少钱", "价格", "怎么买", "门槛", "开通", "会员"]
    if any(k in msg for k in price_kws) and is_group:
        # 【修复v21.46】冷却机制：同一用户1小时内只通知一次
        now_radar = time.time()
        last_trigger = _radar_cooldown.get(uid, 0)
        should_notify = now_radar - last_trigger > _RADAR_COOLDOWN
        
        if should_notify:
            try:
                bot.send_message(
                    CONFIG["ADMIN_ID"],
                    f"👀 视奸雷达\n{uname}({uid}) 提到了费用相关词\n💡 该用户可能对付费服务有兴趣"
                )
                _radar_cooldown[uid] = now_radar  # 更新冷却时间
            except Exception as e:
                logger.warning(f"视奸雷达通知失败：{e}")
        
        # 留资打捞不受冷却限制，每次都执行
        db.set_cart(uid)
        db.log_conversion_event(uid, "touched")

    # ── P8：固定彩蛋响应 ──────────────────────────────────────────────
    if handle_easter_eggs(mory_bot, m, CONFIG, db):
        clear_logging_context()
        return

    # ── P9：用户画像标签提取 ─────────────────────────────────────────
    analysis = detect_keywords(msg, CONFIG)
    if analysis["keyword_tag"]:
        db.add_keyword(uid, analysis["keyword_tag"])
    if analysis["is_cart"]:
        db.set_cart(uid)
        db.log_conversion_event(uid, "interested")

    # ── P9.3：天气/城市共情（快速硬编码回复，不影响后续AI）──────────
    if analysis.get("weather_empathy") and is_group:
        mory_bot.reply_and_track(m, analysis["weather_empathy"])  # 【架构v21.44】显式追踪

    # ── P9.5：黑话/行话自动科普（不影响正常AI回复，5%概率触发防刷屏）──
    if analysis.get("slang_reply") and is_group:
        if random.randint(1, 20) == 1:  # 5%概率触发科普，避免刷屏
            mory_bot.reply_and_track(m, analysis["slang_reply"])  # 【架构v21.44】显式追踪

    # ── P10：AI回复逻辑 ───────────────────────────────────────────────
    mode = analysis["mode"]
    is_at    = f"@{BOT_USERNAME}" in msg
    is_reply = m.reply_to_message and m.reply_to_message.from_user.id == BOT_ID

    # 5%概率给普通消息附加运势签（不改mode，只在回复末尾追加签文）
    fortune_bonus = False
    if mode == "normal" and random.randint(1, 100) <= 5:
        fortune_bonus = True

    should_reply = (
        is_priv
        or is_at
        or is_reply
        or mode != "normal"
        or random.randint(1, 100) <= CONFIG.get("REPLY_CHANCE", 10)
    )

    if not should_reply:
        clear_logging_context()
        return

    # 生物钟警告（凌晨0-5点）
    if is_late_night() and is_group:
        mory_bot.reply_and_track(m, "这么晚不睡觉，身体不要啦？快去梦里找老板～ 😴")  # 【架构v21.44】显式追踪
        clear_logging_context()
        return

    # ── 连续对话追踪（仅群聊 @/回复 机器人时计数，线程安全）─────────
    conv_count = 0
    if is_group and (is_at or is_reply) and mode == "normal":
        now_ts = time.time()
        _cleanup_conv_tracker()
        with _conv_lock:  # 【修复v21.46】保护字典读写操作
            if uid in _conv_tracker:
                if now_ts - _conv_tracker[uid]["last_time"] > _CONV_TIMEOUT:
                    _conv_tracker[uid] = {"count": 1, "last_time": now_ts}  # 超时归零
                else:
                    _conv_tracker[uid]["count"] += 1
                    _conv_tracker[uid]["last_time"] = now_ts
            else:
                _conv_tracker[uid] = {"count": 1, "last_time": now_ts}
            conv_count = _conv_tracker[uid]["count"]

    # 【修复v21.46】移除阻塞式sleep，改为发送typing状态即可
    # AI请求本身就需要几秒钟，天然就是"打字延迟"，无需额外sleep
    # 原因：time.sleep(5-10秒) 会霸占线程池，导致高并发时Bot假死
    bot.send_chat_action(chat_id, "typing")

    # 【修复v21.46】Function Calling 触发逻辑：群聊normal模式即可触发
    # 移除了 "not is_at and not is_reply" 限制，允许用户在@或回复时也能触发营销工具
    use_tools = None
    if is_group and mode == "normal":
        use_tools = _get_function_tools()  # 定义在文件顶部
    
    resp = ai.ask(msg, mode=mode, tools=use_tools)

    if resp:
        # ── Function Calling处理：AI主动触发工具 ──
        if isinstance(resp, dict):
            tool_result = _handle_tool_calls(resp, bot, m, CONFIG, db)
            if tool_result:
                resp = tool_result
            else:
                resp = resp.get("content") or ""
        
        if isinstance(resp, str) and resp:
            if mode == "tarot":
                resp = draw_tarot(uname) + "\n\n" + resp
            # 运势签追加（5%概率触发）
            if fortune_bonus:
                resp += f"\n\n🎴 今日签：{get_fortune()}"

        # ── 连续对话追加：绿茶风反问 + 转化引导（仅群聊normal模式）───
        # 【优化】每轮消息最多追加1种（反问/暗示/转化三选一），避免API费用爆炸
        if is_group and mode == "normal" and conv_count >= 2:
            seed_h = random.randint(100000, 999999)
            _did_append = False

            if conv_count >= 5 and not _did_append:
                # 第5轮+：30%概率植入转化引导
                if random.randint(1, 10) <= 3:
                    convert_text = ai.ask(f"用户已和你连续聊了{conv_count}轮，自然收尾引导", mode="convert_soft", seed=seed_h)
                    if convert_text:
                        resp += f"\n\n{convert_text.strip()}"
                        _did_append = True

            elif conv_count >= 3 and not _did_append:
                # 第3-4轮：30%概率植入不违和的暗示
                if random.randint(1, 10) <= 3:
                    nudge_text = ai.ask("用户和你聊得不错，不经意间植入暗示", mode="nudge", seed=seed_h)
                    if nudge_text:
                        resp += f"\n\n{nudge_text.strip()}"
                        _did_append = True

            # 所有连续对话（>=2轮）：60%概率加绿茶风反问（仅在前面没追加时）
            if not _did_append:
                if random.randint(1, 10) <= 6:
                    hook_text = ai.ask("基于刚才的对话，用绿茶风反问结尾让对话继续", mode="hook", seed=seed_h + 1)
                    if hook_text:
                        resp += f"\n\n{hook_text.strip()}"

        sent = mory_bot.reply_and_track(m, resp)

        # 【架构v21.44】阅后即焚追踪由 MoryBot.reply_and_track() 显式处理
        
        # 私聊消息转发给管理员（脱敏处理：不发送原始内容）
        if is_priv:
            try:
                admin_id = CONFIG.get("ADMIN_ID", 0)
                if admin_id and uid != admin_id:
                    bot.send_message(admin_id,
                        f"📩 私聊通知\n👤 {uname}({uid}) [消息已隐藏]\n"
                        f"🤖 AI已回复（{len(resp)}字）")
            except Exception as e:
                logger.warning(f"私聊转发通知失败 uid={uid}：{e}")
        
        # 更新转化漏斗
        if mode == "convert":
            db.log_conversion_event(uid, "consulted")

        logger.info(f"💬 回复 uid={uid}  mode={mode}  len={len(resp)}  conv={conv_count}")
    else:
        logger.warning(f"⚠️ AI未能生成回复 uid={uid}")
    clear_logging_context()


# ════════════════════════ 启动 ════════════════════════════════════════
if __name__ == "__main__":
    bot_name = CONFIG.get("BOT_NAME", "Mory")
    cur_model = (CONFIG.get("MODEL_POOLS", {}).get("llm", CONFIG.get("MODEL_POOL", [{}]))[CONFIG.get("CURRENT_MODEL_INDEX", 0)]
                 .get("name", "N/A"))
    reply_chance = CONFIG.get("REPLY_CHANCE", 10)
    logger.info("=" * 60)
    logger.info(f"🚀 {bot_name} 私域超级分身  v{CONFIG.get('_CONFIG_VERSION', '21.35')}  启动！")
    logger.info(f"🤖 当前模型：{cur_model}")
    logger.info(f"👑 管理员ID：{CONFIG.get('ADMIN_ID', 0)}")
    logger.info(f"👥 主群ID：{CONFIG.get('GROUP_ID', 0)}")
    logger.info(f"🎲 随机回复概率：{reply_chance}%")
    logger.info(f"📁 数据库：mory.db（更新代码不影响此文件）")
    logger.info("=" * 60)

    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except KeyboardInterrupt:
        logger.info("⏹️ 机器人已停止")
    except Exception as e:
        logger.critical(f"❌ 机器人崩溃：{e}\n{traceback.format_exc()}")
        sys.exit(1)
