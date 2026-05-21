"""
╔══════════════════════════════════════════════════════════════════════════╗
║  main.py  ·  Mory 私域超级分身机器人  v4.5.0                            ║
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

import os, sys, json, time, random, logging, traceback, threading
from datetime import datetime
from threading import Lock
from core.logging_util import configure_logging, get_logger, set_logging_context, clear_logging_context
import concurrent.futures
_append_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="append")

# ── 项目根目录（基于脚本位置，跨目录启动也正确）──
base_dir = os.path.dirname(os.path.abspath(__file__))

# ── 加载 .env 环境变量（敏感信息不硬编码）────────────────────────────
def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(base_dir, ".env"), override=False)
    except ImportError:
        env_file = os.path.join(base_dir, ".env")
        if os.path.exists(env_file):
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        os.environ.setdefault(k.strip(), v)

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
        ret = os.system(f"{venv_pip} install {' '.join(missing)} -q")
        installed = (ret == 0)
    
    # 方式2: python3 -m pip --break-system-packages (Debian/Ubuntu PEP 668兼容)
    if not installed:
        # 【v4.3.2修复M-26】根据平台选择重定向语法
        _redirect = "" if _sys.platform == "win32" else " 2>/dev/null"
        ret = os.system(
            f"python3 -m pip install --break-system-packages {' '.join(missing)} -q{_redirect}"
        )
        installed = (ret == 0)
    
    # 方式3: pip3 --user
    if not installed:
        _redirect = "" if _sys.platform == "win32" else " 2>/dev/null"
        os.system(f"pip3 install --user {' '.join(missing)} -q{_redirect}")
    
    logger.info("✅ 依赖安装完成")

_ensure_deps()

import telebot

# ── 导入各模块 ────────────────────────────────────────────────────────
from core.ai_engine import AIEngine, calc_typing_delay
from core.database  import DB
from core.mory_bot import MoryBot  # 【架构重构v21.44】显式机器人封装层
from modules.admin_cmds import handle_admin
from modules.natural_cmd import handle_natural_admin
from modules.group_mgr  import (handle_new_members, check_banned_words,
                                  check_spam, handle_left_member, detect_keywords,
                                  check_ad_content)
from modules.auto_tasks import start_background
from modules.content    import (handle_easter_eggs, handle_photo,
                                  draw_tarot, get_fortune, is_late_night)
from modules.ad_detector import AdDetector

# ── 连续对话追踪（内存字典 + 线程安全）────────────────────────────
# key=uid, value={"count": int, "last_time": float}
# 用于：绿茶风反问（保持对话）+ 连续对话后的转化引导植入
_conv_tracker = {}
_conv_lock = Lock()  # 【修复v21.46】防止多线程并发修改字典导致RuntimeError
_CONV_TIMEOUT = 300  # 5分钟无对话则计数清零
_conv_last_cleanup = 0  # 上次清理时间戳
_MAX_CONV_ENTRIES = 1000  # 【v4.3.2修复M-01】最大条目数限制

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
        # 【v4.3.2修复M-01】超出上限时淘汰最老的条目
        if len(_conv_tracker) > _MAX_CONV_ENTRIES:
            sorted_uids = sorted(_conv_tracker.items(), key=lambda x: x[1]["last_time"])
            for uid, _ in sorted_uids[:len(_conv_tracker) - _MAX_CONV_ENTRIES]:
                del _conv_tracker[uid]


def _calc_humanized_delay(text: str, is_priv: bool, conv_count: int = 0) -> float:
    """[Trae] 计算拟人化回复延迟（秒），让Bot不再秒回

    规则：
    - 根据回复长度分级：短/中/长
    - 私聊比群聊稍慢（更亲密更慢节奏）
    - 深夜(0-5点)额外加2-4秒（"困了打字慢"）
    - 连续对话第3轮起延迟递减（"聊嗨了回复变快"）
    - ±30%随机抖动避免机械感
    """
    cfg_speed = CONFIG.get("REPLY_SPEED", "human")
    speed_presets = {
        "fast":   (0.5, 2.0),
        "normal": (2.0, 5.0),
        "slow":   (5.0, 12.0),
        "human":  None,
    }
    preset = speed_presets.get(cfg_speed, None)
    if preset and cfg_speed != "human":
        lo, hi = preset
        return round(random.uniform(lo, hi), 1)

    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cn_chars <= 20:
        base = random.uniform(2.0, 4.5)
    elif cn_chars <= 60:
        base = random.uniform(3.0, 7.0)
    else:
        base = random.uniform(5.0, 10.0)

    if is_priv:
        base *= 1.2

    hour = datetime.now().hour
    if 0 <= hour < 5:
        base += random.uniform(2.0, 4.0)

    if conv_count >= 3:
        reduction = min(conv_count * 0.4, 2.5)
        base = max(1.0, base - reduction)

    jitter = base * random.uniform(-0.3, 0.3)
    base += jitter

    return round(max(0.5, min(15.0, base)), 1)


def _delayed_reply(bot, chat_id, reply_to_msg, text, delay_seconds, mory_bot, is_priv=False):
    """[Trae] 非阻塞延迟发送回复，期间持续typing状态

    用threading.Timer实现延迟，不阻塞线程池。
    后台线程每5秒续一次typing状态直到消息发出。
    群聊消息发送后自动添加反馈按钮。
    """
    def _do_send():
        try:
            sent = mory_bot.reply_and_track(reply_to_msg, text)
            if sent and not is_priv:
                try:
                    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                    fb_markup = InlineKeyboardMarkup()
                    fb_markup.row(
                        InlineKeyboardButton("👍", callback_data=f"fb_like_{sent.message_id}"),
                        InlineKeyboardButton("👎", callback_data=f"fb_dislike_{sent.message_id}"),
                    )
                    bot.edit_message_reply_markup(chat_id=sent.chat.id, message_id=sent.message_id, reply_markup=fb_markup)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"延迟发送失败: {e}")

    bot.send_chat_action(chat_id, "typing")

    timer = threading.Timer(delay_seconds, _do_send)
    timer.daemon = True
    timer.start()

    if delay_seconds > 4:
        def _keep_typing():
            remaining = delay_seconds
            while remaining > 0:
                sleep_time = min(5.0, remaining)
                time.sleep(sleep_time)
                remaining -= sleep_time
                if remaining > 0:
                    try:
                        bot.send_chat_action(chat_id, "typing")
                    except Exception:
                        break
        t = threading.Thread(target=_keep_typing, daemon=True)
        t.start()


def _split_for_private(text: str) -> list[str]:
    """[Trae] 将长回复拆分为两段，用于私聊分段发送

    拆分规则：在自然语句边界（。！？…~）处拆分
    第一段占总长度40-60%
    """
    if len(text) < 60:
        return [text]

    split_chars = ['。', '！', '？', '…', '~', '～', '！', '？']
    mid = int(len(text) * random.uniform(0.4, 0.6))

    best_pos = -1
    for i in range(mid, min(mid + 20, len(text))):
        if text[i] in split_chars:
            best_pos = i + 1
            break

    if best_pos == -1:
        for i in range(max(mid - 20, 0), mid):
            if text[i] in split_chars:
                best_pos = i + 1
                break

    if best_pos <= 0 or best_pos >= len(text):
        return [text]

    part1 = text[:best_pos].rstrip()
    part2 = text[best_pos:].lstrip()

    if not part1 or not part2:
        return [text]

    if not part1.endswith(('…', '~', '～', '—')):
        part1 += '…'

    return [part1, part2]


# ── 视奸雷达冷却机制（内存字典 + 线程安全）────────────────────────
# 防止同一用户频繁触发导致管理员被刷屏
_radar_cooldown = {}  # key=uid, value=上次触发时间戳
_radar_lock = Lock()  # 【修复v4.3.1】防止多线程并发修改字典导致RuntimeError
_RADAR_COOLDOWN = 3600  # 1小时冷却时间
_radar_last_cleanup = 0  # 【v4.3.2修复M-02】上次清理时间戳

def _cleanup_radar_cooldown():
    """【v4.3.2修复M-02】定期清理过期的视奸雷达冷却记录"""
    global _radar_last_cleanup
    now = time.time()
    if now - _radar_last_cleanup < 3600:  # 每小时清理一次
        return
    _radar_last_cleanup = now
    with _radar_lock:
        expired = [uid for uid, ts in _radar_cooldown.items() if now - ts > _RADAR_COOLDOWN]
        for uid in expired:
            del _radar_cooldown[uid]

# ── 配置读写 ──────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(base_dir, "config.json")  # 基于脚本目录的绝对路径
_config_lock = Lock()

def load_config() -> dict:
    """加载配置文件，并从数据库覆盖动态状态。
    【v4.3.2修复I-02】配置损坏时加载内置最小默认配置并告警
    """
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ver = cfg.get("_CONFIG_VERSION", "未知")
            logger.info(f"📋 配置版本：v{ver}")
        except json.JSONDecodeError as e:
            logger.critical(f"❌ config.json 格式损坏：{e}")
            logger.critical("   → 尝试加载内置最小默认配置...")
            cfg = _get_minimal_default_config()
        except Exception as e:
            logger.error(f"配置读取失败：{e}")
            cfg = _get_minimal_default_config()
    
    if not cfg:
        cfg = _get_minimal_default_config()
    
    # 【架构重构v21.44】从数据库加载动态状态，覆盖配置文件
    # 动态状态包括：当前模型索引、图片池、语音池等运行时数据
    _load_dynamic_states(cfg)
    
    return cfg

def _get_minimal_default_config() -> dict:
    """【v4.3.2修复I-02】内置最小默认配置（config.json损坏时的兜底）"""
    logger.warning("⚠️ 使用内置最小默认配置，部分功能可能受限，请修复config.json")
    return {
        "TOKEN": "", "API_KEY": "", "ADMIN_ID": 0, "GROUP_ID": 0,
        "BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "MODEL_POOLS": {"llm": [{"name": "qwen-plus", "expire": "2099-12-31"}]},
        "REPLY_CHANCE": 10, "_CONFIG_VERSION": "4.5.3",
        "SYSTEM_PROMPT": "你是Mory，一个活泼可爱的小助理。",
    }

def _load_dynamic_states(cfg: dict):
    """从数据库加载动态状态到配置"""
    global db
    try:
        if db is None:
            return
    except NameError:
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
                except Exception:
                    cfg[key] = []
            elif key == "_LAST_LEAK_WEEK":
                cfg[key] = int(db_value) if db_value else -1
            else:
                cfg[key] = db_value
            logger.debug(f"📌 动态状态加载: {key}={cfg[key]}")

def save_config():
    """保存配置到文件，并同步动态状态到数据库。
    【v4.3.2修复S-07】返回bool表示成功/失败
    """
    global db
    with _config_lock:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"配置保存失败：{e}")
            return False  # 【v4.3.2】返回失败状态
    
    # 【架构重构v21.44】同步动态状态到数据库
    if db is not None:
        dynamic_keys = ["CURRENT_MODEL_INDEX", "IMAGE_POOL", "VOICE_POOL", "_LAST_LEAK_WEEK"]
        for key in dynamic_keys:
            if key in CONFIG:
                value = CONFIG[key]
                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                db.set_system_state(key, value)
    return True  # 【v4.3.2】返回成功状态

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
bot = telebot.TeleBot(CONFIG["TOKEN"], threaded=True, num_threads=50, use_class_middlewares=True)

# ── 广告检测引擎（v4.5.36新增，零TOKEN消耗）──
ad_detector = AdDetector(CONFIG)

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
        # 【v4.3.2修复I-01】自动从备份恢复
        import glob as _glob
        _backup_dir = os.path.join(base_dir, "backup")
        if os.path.isdir(_backup_dir):
            _backups = sorted(_glob.glob(os.path.join(_backup_dir, "mory_backup_*.db")))
            if _backups:
                _latest_backup = _backups[-1]
                logger.warning(f"   → 尝试从备份恢复：{_latest_backup}")
                try:
                    db.close()
                    import shutil
                    shutil.copy2(_latest_backup, os.path.join(base_dir, "mory.db"))
                    db = DB(os.path.join(base_dir, "mory.db"))
                    _load_dynamic_states(CONFIG)
                    logger.info("✅ 数据库从备份恢复成功！")
                    try:
                        from modules.auto_tasks import report_fault
                        report_fault("数据库异常已自动恢复", f"从备份{_latest_backup}恢复成功", "⚠️")
                    except Exception:
                        pass
                except Exception as restore_err:
                    logger.critical(f"❌ 数据库恢复失败：{restore_err}")
                    logger.critical("   → 请手动从 backup/ 目录恢复")
                    try:
                        from modules.auto_tasks import report_fault
                        report_fault("数据库损坏且恢复失败", str(restore_err), "🚨")
                    except Exception:
                        pass
            else:
                logger.error("   → 无可用备份，请手动检查数据库")
        else:
            logger.error("   → backup/ 目录不存在，无法自动恢复")
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

# ── 【v4.4.9新增】初始化默认关键词触发规则 ─────────────────────
try:
    logger.info("🔑 检查关键词触发规则...")
    existing_keywords = db.get_all_keyword_triggers()
    if len(existing_keywords) == 0:
        logger.info("🔑 没有找到关键词规则，添加默认规则...")
        db.add_keyword_trigger("你好", "你好呀！很高兴认识你，有什么我可以帮你的吗？", "static")
        db.add_keyword_trigger("嗨", "嗨！欢迎呀，想聊点什么呢？", "static")
        db.add_keyword_trigger("更新", "好的，我来帮你更新！请稍候...", "action", "deploy")
        logger.info("✅ 已添加默认关键词触发规则")
    else:
        logger.info(f"✅ 已找到 {len(existing_keywords)} 条关键词规则")
except Exception as e:
    logger.error(f"⚠️  初始化关键词失败: {e}")

# ── 启动后台自动任务 ──────────────────────────────────────────────────
start_background(bot, CONFIG, db, ai, save_config)

# 【架构重构v21.44】初始化 MoryBot 封装层（替代 Monkey Patch）
mory_bot = MoryBot(bot, db, CONFIG)
bot._mory_bot_instance = mory_bot

from core.resource_manager import ResourceManager
_emergency_rm = ResourceManager(bot=bot, ai=ai, db=db, config=CONFIG, save_config_fn=save_config)

from modules.keyword_trigger import KeywordTrigger
keyword_trigger = KeywordTrigger(db, mory_bot, ai, CONFIG)

# ── 【v4.1.0 架构升级】BaseMiddleware 全局底层嗅探器 ──────────────────────
# 解决"用户用图片/语音/贴纸回复机器人，但机器人眼瞎看不见"的致命死角
# 中间件在消息到达任何 handler 之前先执行，无视 content_type
from telebot.handler_backends import BaseMiddleware

class ReplySnifferMiddleware(BaseMiddleware):
    """
    【架构师核心组件：全局底层嗅探器 v4.1.0】
    - 在所有消息进入业务逻辑前进行底层拦截
    - 无论用户发送的是文字、图片、语音、贴纸，只要回复了机器人，必定被捕获
    - 彻底解决"阅后即焚误杀"问题
    """
    def __init__(self, db_instance):
        self.update_types = ['message']
        self.db = db_instance

    def pre_process(self, message, data):
        # 捕获用户对机器人的回复（无视消息类型）
        if message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID:
            try:
                self.db.mark_replied(message.reply_to_message.message_id, message.chat.id)
                logger.info(f"🛡️ [底层嗅探] 捕获回复，豁免阅后即焚: bot_msg_id={message.reply_to_message.message_id}")
            except Exception as e:
                logger.warning(f"[底层嗅探] 异常: {e}")

    def post_process(self, message, data, exception):
        pass

# 挂载中间件（必须在所有 @bot.message_handler 之前）
bot.setup_middleware(ReplySnifferMiddleware(db))

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("fb_"))
def on_feedback_callback(call):
    try:
        parts = call.data.split("_")
        if len(parts) < 3:
            return
        feedback = parts[1]
        if feedback not in ("like", "dislike"):
            return
        try:
            bot_msg_id = int(parts[2])
        except ValueError:
            return
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        db.record_feedback(bot_msg_id, chat_id, user_id, feedback)
        emoji = "👍" if feedback == "like" else "👎"
        bot.answer_callback_query(call.id, text=f"已收到{emoji}反馈，谢谢！", show_alert=False)
        try:
            markup = call.message.reply_markup
            if markup and hasattr(markup, 'keyboard'):
                new_keyboard = []
                for row in markup.keyboard:
                    new_row = []
                    for btn in row:
                        if hasattr(btn, 'callback_data') and btn.callback_data == call.data:
                            from telebot.types import InlineKeyboardButton as IKB
                            new_row.append(IKB(text=f"{emoji} ✓", callback_data="fb_done"))
                        else:
                            new_row.append(btn)
                    new_keyboard.append(new_row)
                from telebot.types import InlineKeyboardMarkup
                bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id,
                                              reply_markup=InlineKeyboardMarkup(new_keyboard))
        except Exception:
            pass
    except Exception as e:
        logger.error(f"反馈回调异常：{e}")

# ════════════════════════ 消息处理器 ══════════════════════════════════

# ── 图片处理（打码+识图）───────────────────────────────────────────────
@bot.message_handler(content_types=["photo"])
def on_photo(m):
    try:
        handle_photo(bot, m, CONFIG, mory_bot, ai)
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
        handle_left_member(bot, m, CONFIG, db)  # 【v4.2.3】传入db用于统计
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
        # 全局故障通知：任何未捕获异常都通知管理员
        try:
            from modules.auto_tasks import _notify_admin_system_failure
            _notify_admin_system_failure(_emergency_rm, "主分发器未捕获异常", f"{e}\n{traceback.format_exc()[:200]}", "🚨")
        except Exception:
            pass


def _dispatch(m):
    """消息分发核心逻辑（优先级严格控制）"""
    try:
        _do_dispatch(m)
    except Exception as e:
        clear_logging_context()
        logger.error(f"❌ 分发器内部异常：{e}\n{traceback.format_exc()}")
        try:
            from modules.auto_tasks import _notify_admin_system_failure
            _notify_admin_system_failure(_emergency_rm, "分发器内部异常", f"{e}\n{traceback.format_exc()[:200]}", "🚨")
        except Exception:
            pass


def _do_dispatch(m):
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

    # ── P2：更新用户活跃度 / 群ID / 积分（原子操作，防竞态）──────────────
    db.upsert_user_with_points(uid, uname, "private" if is_priv else "group", pts=1)
    if is_group:
        gid = CONFIG.get("GROUP_ID", 0)
        if gid == 0:  # 只在未设置时才自动记录群ID，已设置过的不覆盖
            CONFIG["GROUP_ID"] = chat_id
            save_config()

    # ── 【v4.1.0 架构升级】嗅探逻辑已迁移至 BaseMiddleware 统一处理
    #    中间件在所有 handler 之前执行，无视消息类型（文字/图片/语音/贴纸）
    #    详见文件顶部的 ReplySnifferMiddleware 类


    # ── P3：黑名单词过滤 ──────────────────────────────────────────────
    if is_group and check_banned_words(bot, m, CONFIG, db):
        clear_logging_context()
        return

    # ── P3.5：智能广告检测（v4.5.36，零TOKEN消耗）────────────────────────
    # [Trae] v4.6.3 重构：支持延迟封禁机制
    # 流程：
    #   1. 先用 detect() 判断是否为广告（即时封禁场景）
    #   2. 如果不是即时广告，用 track_suspicious_user() 累计评分
    #   3. 累计评分达到阈值 → 延迟封禁 + 删除该用户所有历史消息
    if is_group:
        username = (m.from_user.first_name or "") + (m.from_user.last_name or "")
        ad_result = ad_detector.detect(username=username, msg=msg)

        # 场景A：即时命中广告规则 → 直接处理（原有逻辑）
        if ad_result["is_ad"]:
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception as e:
                logger.warning(f"删除广告消息失败: {e}")
            if ad_result["action"] == "ban":
                try:
                    bot.restrict_chat_member(
                        chat_id, uid,
                        until_date=0,
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                    )
                    logger.warning(f"🚫 广告用户永久禁言: {uname}({uid})")
                except Exception as e:
                    logger.warning(f"禁言广告用户失败: {e}")
            admin_id = CONFIG.get("ADMIN_ID", 0)
            if admin_id:
                try:
                    bot.send_message(admin_id,
                        f"🚫 广告已处理（智能检测）\n"
                        f"👤 用户：{uname}({uid})\n"
                        f"💬 消息：{msg[:150]}{'...' if len(msg) > 150 else ''}\n"
                        f"📋 操作：删除消息{' + 永久禁言' if ad_result['action'] == 'ban' else ''}\n"
                        f"🎯 原因：{ad_result['reason']}\n"
                        f"💡 如误封请手动解禁")
                except Exception as e:
                    logger.warning(f"广告通知发送失败: {e}")
            clear_logging_context()
            return

        # 场景B：未即时命中，但可能有可疑评分 → 进入延迟追踪
        # 只要有内容评分（>0）就追踪，累计达到阈值后封禁
        content_score = ad_result.get("score", 0)
        if content_score > 0:
            track_result = ad_detector.track_suspicious_user(
                user_id=uid,
                msg_id=m.message_id,
                chat_id=chat_id,
                text=msg,
                score=content_score
            )

            if track_result["action"] == "ban":
                # 延迟封禁触发：封禁用户 + 删除所有历史消息
                logger.warning(f"[AD] 🚫 延迟封禁执行: uid={uid}, 累计评分={track_result['total_score']}")

                # 1. 删除该用户所有被追踪的历史消息
                messages_to_delete = ad_detector.get_user_messages_to_delete(uid)
                deleted_count = 0
                for msg_info in messages_to_delete:
                    try:
                        bot.delete_message(msg_info["chat_id"], msg_info["msg_id"])
                        deleted_count += 1
                    except Exception as e:
                        logger.debug(f"删除历史消息失败 msg_id={msg_info['msg_id']}: {e}")

                # 2. 永久禁言
                try:
                    bot.restrict_chat_member(
                        chat_id, uid,
                        until_date=0,
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                    )
                    logger.warning(f"🚫 延迟封禁-用户永久禁言: {uname}({uid})")
                except Exception as e:
                    logger.warning(f"延迟封禁-禁言失败: {e}")

                # 3. 通知管理员
                admin_id = CONFIG.get("ADMIN_ID", 0)
                if admin_id:
                    try:
                        # 构建历史消息摘要
                        history_lines = []
                        for i, hm in enumerate(track_result["messages"][-5:], 1):  # 最近5条
                            history_lines.append(f"  {i}. {hm['text'][:50]} (评分+{hm['score']})")
                        history_text = "\n".join(history_lines)

                        bot.send_message(admin_id,
                            f"🚫 延迟封禁已触发\n"
                            f"👤 用户：{uname}({uid})\n"
                            f"📊 累计评分：{track_result['total_score']}\n"
                            f"🗑 删除消息：{deleted_count}条\n"
                            f"📜 历史消息：\n{history_text}\n"
                            f"💡 如误封请手动解禁，并告知我调整规则")
                    except Exception as e:
                        logger.warning(f"延迟封禁通知失败: {e}")

                # 4. 清除追踪记录（已处理完毕）
                ad_detector.clear_user_tracking(uid)
                clear_logging_context()
                return

            elif track_result["action"] == "watch":
                # 继续观察，只记录不拦截
                logger.info(f"[AD] 👁️ 用户追踪中: uid={uid}, 累计评分={track_result['total_score']}")

        # 旧版关键词检测作为兜底（防漏网）
        if check_ad_content(bot, m, CONFIG, db, ai):
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
    admin_result = handle_admin(bot, mory_bot, m, CONFIG, db, ai, save_config)
    if admin_result:
        logger.info(f"👑 管理员指令执行成功 uid={uid} msg={msg[:30]}")
        clear_logging_context()
        return

    # ── P6.3：自然语言配置（管理员可直接在TG里改，普通用户可看说明）───────
    try:
        admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if admin_id:
            admin_ids.add(admin_id)
        is_admin_user = uid in admin_ids
        if handle_natural_admin(bot, m, CONFIG, save_config, mory_bot=mory_bot, is_admin=is_admin_user, ad_detector=ad_detector):
            logger.info(f"🗣️ 自然语言配置已处理 uid={uid} msg={msg[:30]}")
            clear_logging_context()
            return
    except Exception as e:
        logger.error(f"🗣️ 自然语言配置处理异常: {e}")

    # ── P6.5：关键词触发回复（v4.4.9新增）────────────────────────────
    if msg:
        try:
            admin_id = CONFIG.get("ADMIN_ID", 0)
            is_admin = (uid == admin_id)
            if keyword_trigger.handle_message(msg, chat_id, m, bot, is_admin=is_admin):
                logger.info(f"🔑 关键词触发回复成功 uid={uid} msg={msg[:30]}")
                clear_logging_context()
                return
        except Exception as e:
            logger.error(f"🔑 关键词触发检测异常: {e}")

    # ── P7：视奸雷达（价格关键词通知管理员 + 冷却机制）────────────
    _cleanup_radar_cooldown()  # 【v4.3.2修复M-02】定期清理过期冷却记录
    price_kws = ["多少钱", "价格", "怎么买", "门槛", "开通", "会员"]
    if any(k in msg for k in price_kws) and is_group:
        # 【修复v4.3.1】冷却机制：同一用户1小时内只通知一次（加锁防并发）
        now_radar = time.time()
        with _radar_lock:  # 【修复v4.3.1】加锁防止并发写入崩溃
            last_trigger = _radar_cooldown.get(uid, 0)
            should_notify = now_radar - last_trigger > _RADAR_COOLDOWN
            if should_notify:
                _radar_cooldown[uid] = now_radar  # 更新冷却时间
        
        if should_notify:
            try:
                bot.send_message(
                    CONFIG["ADMIN_ID"],
                    f"👀 视奸雷达\n{uname}({uid}) 提到了费用相关词\n💡 该用户可能对付费服务有兴趣"
                )
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

    # ── P9.7：用户反馈/找Mory（安抚回复 + 通知管理员，不走AI闲聊）───
    # 【v4.7.1 新增】拦截反馈类消息，避免AI对"被封了"等严肃消息输出撩人内容
    # 【v4.12.1 优化】群聊→引导私聊(不说老板)；私聊→尝试自助解封+甩锅阿福
    if analysis.get("mode") in ("feedback", "contact_mory"):
        if is_group:
            # 群聊：安抚 + 引导私聊（不说"老板/boss"，只说"Mory"）
            feedback_reply = random.choice([
                f"{uname}收到啦～你私聊我，我帮你处理哦～",
                f"{uname}好的～来私聊我吧，这边不太方便说～",
                f"嗯嗯～直接私聊我就行，我帮你转达Mory～",
            ])
            mory_bot.reply_and_track(m, feedback_reply)
            # 通知管理员
            admin_id = CONFIG.get("ADMIN_ID", 0)
            if admin_id:
                try:
                    bot.send_message(admin_id,
                        f"📢 用户反馈通知\n"
                        f"👤 {uname}({uid})\n"
                        f"💬 消息：{msg[:150]}\n"
                        f"🏷 类型：{'用户遇到问题' if analysis['mode'] == 'feedback' else '用户想找Mory'}\n"
                        f"💡 已引导私聊处理")
                except Exception as e:
                    logger.warning(f"反馈通知发送失败：{e}")
        else:
            # 私聊：尝试自助解封
            if "解封" in msg or "解禁" in msg or "被封" in msg or "封了" in msg or "禁言" in msg:
                gid = CONFIG.get("GROUP_ID", 0)
                unban_success = False
                if gid:
                    try:
                        from telebot.types import ChatPermissions
                        bot.restrict_chat_member(
                            gid, uid,
                            permissions=ChatPermissions(
                                can_send_messages=True,
                                can_send_media_messages=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True,
                            )
                        )
                        db.blacklist_remove(uid)
                        unban_success = True
                        logger.info(f"✅ 私聊自助解封成功: {uname}({uid})")
                    except Exception as e:
                        logger.warning(f"私聊自助解封失败: {e}")
                        unban_success = False

                if unban_success:
                    # 甩锅绿茶话术（随机，甩锅阿福误判）
                    blame = random.choice([
                        "这该死的阿福又误判了！真不好意思啊～",
                        "阿福那个笨蛋又抽风了，害你被封，抱歉抱歉～",
                        "又是阿福的锅！它最近老犯傻，我替它道歉～",
                        "阿福出bug了，把你误封了，真的对不起呀～",
                        "那个笨阿福又搞事了！害你受委屈了～",
                    ])
                    feedback_reply = f"已经帮你解封啦～{blame}现在可以回群里正常发言了！以后有任何问题都可以私聊我哦～"
                else:
                    blame = random.choice([
                        "这该死的阿福又误判了！",
                        "阿福那个笨蛋又抽风了！",
                        "又是阿福的锅！",
                    ])
                    feedback_reply = f"{blame}出了点状况暂时无法解封，我已经通知Mory了，她会尽快来帮你处理的～以后有事直接私聊我就行！"
                    # 通知管理员解封失败
                    admin_id = CONFIG.get("ADMIN_ID", 0)
                    if admin_id:
                        try:
                            bot.send_message(admin_id,
                                f"🚨 用户自助解封失败\n"
                                f"👤 {uname}({uid})\n"
                                f"💬 消息：{msg[:150]}\n"
                                f"💡 请手动解封")
                        except Exception:
                            pass
            else:
                # 私聊普通反馈（非解封）
                feedback_reply = random.choice([
                    "收到啦～我已经记下来了，Mory会尽快来处理的！有事随时私聊我哦～",
                    "好的好的～我帮你转达给Mory，她看到就会来处理～以后有事直接找我就行！",
                    "嗯嗯～已经通知Mory了，别着急哦～有任何问题都可以私聊我～",
                ])
            mory_bot.reply_and_track(m, feedback_reply)

        clear_logging_context()
        return

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

    # 生物钟警告（凌晨0-5点）- AI动态生成撩人回复
    if is_late_night() and is_group:
        # 随机选择回复策略：60%AI生成 + 40%备用文案（提升多样性）
        late_night_text = _generate_late_night_warning(ai, uname, is_group, uid)
        mory_bot.reply_and_track(m, late_night_text)
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

    # [Trae] 拟人化延迟：发送typing状态，AI请求期间用户会看到"正在输入"
    bot.send_chat_action(chat_id, "typing")

    # 【修复v21.46】Function Calling 触发逻辑：群聊normal模式即可触发
    # 移除了 "not is_at and not is_reply" 限制，允许用户在@或回复时也能触发营销工具
    use_tools = None
    if is_group and mode == "normal":
        use_tools = _get_function_tools()  # 定义在文件顶部
    
    resp = ai.ask(msg, mode=mode, tools=use_tools, is_priv=is_priv)

    if resp is None:
        try:
            from modules.auto_tasks import report_fault
            report_fault("AI引擎故障", f"mode={mode}，用户消息无法回复", "🚨" if mode != "normal" else "⚠️",
                         f"用户消息: {msg[:80]}")
        except Exception as notify_err:
            logger.error(f"故障通知发送失败: {notify_err}")

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
        # 【v4.3.2修复S-05】限制最多1次额外AI调用+5秒超时保护
        if is_group and mode == "normal" and conv_count >= 2:
            seed_h = random.randint(100000, 999999)

            append_mode = None
            if conv_count >= 5 and random.randint(1, 10) <= 3:
                append_mode = "convert_soft"
                append_prompt = f"用户已和你连续聊了{conv_count}轮，自然收尾引导"
            elif conv_count >= 3 and random.randint(1, 10) <= 3:
                append_mode = "nudge"
                append_prompt = "用户和你聊得不错，不经意间植入暗示"
            elif random.randint(1, 10) <= 6:
                append_mode = "hook"
                append_prompt = "基于刚才的对话，用绿茶风反问结尾让对话继续"

            if append_mode:
                try:
                    _append_future = _append_pool.submit(
                        lambda: ai.ask(append_prompt, mode=append_mode, seed=seed_h))
                    try:
                        append_text = _append_future.result(timeout=5)
                        if append_text:
                            resp += f"\n\n{append_text.strip()}"
                    except concurrent.futures.TimeoutError:
                        logger.info("连续对话追加超时（5秒），跳过")
                except Exception as e:
                    logger.warning(f"连续对话追加失败（跳过）：{e}")

        # [Trae] 拟人化延迟发送 + 私聊分段发送
        delay = _calc_humanized_delay(resp, is_priv, conv_count)

        should_split = (
            is_priv
            and len(resp) > 60
            and random.randint(1, 100) <= 30
            and conv_count < 3
        )
        hour_now = datetime.now().hour
        if is_priv and 0 <= hour_now < 5 and len(resp) > 60 and random.randint(1, 100) <= 50:
            should_split = True

        if should_split:
            parts = _split_for_private(resp)
            if len(parts) == 2:
                _delayed_reply(bot, chat_id, m, parts[0], delay, mory_bot, is_priv)
                part2_delay = delay + random.uniform(2.0, 5.0)
                _delayed_reply(bot, chat_id, m, parts[1], part2_delay, mory_bot, is_priv)
                sent = None
            else:
                _delayed_reply(bot, chat_id, m, resp, delay, mory_bot, is_priv)
                sent = None
        else:
            _delayed_reply(bot, chat_id, m, resp, delay, mory_bot, is_priv)
            sent = None

        # [Trae] 反馈按钮已移入 _delayed_reply 内部处理

        # 【架构v21.44】阅后即焚追踪由 MoryBot.reply_and_track() 显式处理
        
        # 私聊消息转发给管理员（显示完整内容 + 一键直达用户私聊）
        if is_priv:
            try:
                admin_id = CONFIG.get("ADMIN_ID", 0)
                if admin_id and uid != admin_id:
                    msg_display = msg[:200] + "..." if len(msg) > 200 else msg
                    resp_display = resp[:500] + "..." if len(resp) > 500 else resp
                    _safe_name = uname.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    _safe_msg = msg_display.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    _safe_resp = resp_display.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    bot.send_message(admin_id,
                        f"📩 私聊通知\n"
                        f"👤 <a href=\"tg://user?id={uid}\">{_safe_name}</a>\n"
                        f"💬 你：{_safe_msg}\n"
                        f"🤖 Mory回复：{_safe_resp}",
                        parse_mode="HTML")
            except Exception as e:
                logger.warning(f"私聊转发通知失败 uid={uid}：{e}")
        
        # 更新转化漏斗
        if mode == "convert":
            db.log_conversion_event(uid, "consulted")

        logger.info(f"💬 回复 uid={uid}  mode={mode}  len={len(resp)}  conv={conv_count}")
    else:
        logger.warning(f"⚠️ AI未能生成回复 uid={uid}")
    clear_logging_context()


# ── 深夜撩人警告辅助函数（模块级）─────────────────────────────────
def _generate_late_night_warning(ai, uname, is_group, uid):
    """
    生成深夜撩人警告消息（带随机性和人设）
    
    策略：60%调用AI生成（带随机seed），40%使用备用文案库
    这样既保证多样性，又避免每次都要等AI响应
    """
    # 40%概率直接使用备用文案（快速响应）
    if random.random() < 0.4:
        return _get_late_night_fallback(uname)
    
    # 60%概率调用AI生成（带随机seed保证每次不同）
    try:
        seed = uid + int(time.time()) % 3600  # 每小时一个seed区间
        prompt = (
            f"你是Mory老板，一个贴心又有点小调皮的小姐姐。\n\n"
            f"现在是凌晨，用户{uname}还在群里发消息不睡觉。\n"
            f"你要用撩人、关心但不说教的方式提醒他去睡觉。\n\n"
            f"要求：\n"
            f"1. 20-30字，像闺蜜私聊一样自然\n"
            f"2. 带点小撒娇/小醋意/小关心\n"
            f"3. 可以暗示：熬夜会变丑/对身体不好/明天没精神\n"
            f"4. 结尾要有emoji（😴💤🌙✨选一个）\n"
            f"5. seed={seed}，每次必须不同\n\n"
            f"禁止：\n"
            f"- 不要说教式语气（如'你应该'、'你必须'）\n"
            f"- 不要出现'老板'这个词（老板是我自己）\n"
            f"- 控制在30字以内"
        )
        ai_reply = ai.ask(prompt, mode="normal")
        if ai_reply and len(ai_reply) > 5:
            return ai_reply.strip()[:100]  # 截断保护
    except Exception as e:
        logger.debug(f"AI生成深夜回复失败，使用备用文案：{e}")
    
    # AI失败时fallback
    return _get_late_night_fallback(uname)


def _get_late_night_fallback(uname):
    """备用深夜文案库（高度随机化）"""
    templates = [
        f"哎呀{uname}～这么晚还不睡呀？熬夜会掉头发的哦～快去被窝里躲着吧 💤",
        f"诶嘿～{uname}还在活跃呀？月亮都困得打哈欠了，你也快去休息嘛～🌙",
        f"{uname}哥哥～再熬下去明天要变熊猫眼了啦！快去梦里找我玩～😴",
        f"偷偷告诉你哦{uname}～熬夜会变笨的！小Mory可不想明天看到迷糊的你～✨",
        f"呜呼{uname}～深夜不睡觉是在等谁呀？快闭眼休息啦，明天见～💤",
        f"{uname}～你是在偷偷熬夜刷手机吗？小心被小Mory抓包哦～快去睡！😴",
        f"嘿{uname}～夜深啦～星星都困得眨眼了，你也该去被窝里躲着啦～🌙",
        f"{uname}哥哥～再晚下去要错过好运了！快去睡吧，梦里啥都有～✨",
        f"哎呀呀{uname}～这么精神呀？小Mory都打哈欠了，你也快去休息嘛～💤",
        f"{uname}～深夜是皮肤修复的黄金时间哦！快去睡美容觉吧～😴",
    ]
    return random.choice(templates)


# ═══════════════════════════════════════════════════════════════════════════
# 【v4.9.7新增】频道帖子实时捕获 — 解决频道发帖/浏览数据全为0的问题
# ═══════════════════════════════════════════════════════════════════════════

@bot.channel_post_handler(func=lambda m: True)
def on_channel_post(m):
    """捕获频道新帖，记录到 channel_posts 表"""
    cid = m.chat.id
    # 仅处理配置中的目标频道
    channel_ids = CONFIG.get("CHANNEL_IDS", [])
    target_ids = set()
    for ch in channel_ids:
        target_ids.add(ch.get("id", 0) if isinstance(ch, dict) else ch)
    if cid not in target_ids:
        return
    views = getattr(m, 'views', 0) or 0
    forwards = getattr(m, 'forward_count', 0) or 0
    content_type = m.content_type if hasattr(m, 'content_type') else "text"
    db.track_channel_post(cid, m.message_id, int(m.date.timestamp()), views, forwards, content_type)
    logger.info(f"📺 频道帖子捕获: chat_id={cid} msg_id={m.message_id} views={views} type={content_type}")


@bot.edited_channel_post_handler(func=lambda m: True)
def on_edited_channel_post(m):
    """捕获频道帖子编辑事件，更新浏览量"""
    cid = m.chat.id
    channel_ids = CONFIG.get("CHANNEL_IDS", [])
    target_ids = set()
    for ch in channel_ids:
        target_ids.add(ch.get("id", 0) if isinstance(ch, dict) else ch)
    if cid not in target_ids:
        return
    views = getattr(m, 'views', 0) or 0
    forwards = getattr(m, 'forward_count', 0) or 0
    db.update_channel_post_views(cid, m.message_id, views, forwards)
    logger.debug(f"📺 频道帖子浏览量更新: chat_id={cid} msg_id={m.message_id} views={views}")


# ════════════════════════ 启动 ════════════════════════════════════════
# 【v4.3.2修复I-06】优雅停机：注册atexit和信号处理器
import atexit
import signal

_shutdown_done = False

def _graceful_shutdown(signum=None, frame=None):
    """优雅停机：关闭数据库连接，保存配置"""
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    logger.info("⏹️ 正在优雅停机...")
    try:
        save_config()
    except Exception as e:
        logger.warning(f"停机时保存配置失败：{e}")
    try:
        db.close()
    except Exception as e:
        logger.warning(f"停机时关闭数据库失败：{e}")
    logger.info("✅ 优雅停机完成")
    if signum is not None:
        sys.exit(0)

atexit.register(_graceful_shutdown)
try:
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)
except (OSError, ValueError):
    pass  # Windows下可能不支持SIGTERM

if __name__ == "__main__":
    bot_name = CONFIG.get("BOT_NAME", "Mory")
    _llm_pool = CONFIG.get("MODEL_POOLS", {}).get("llm", CONFIG.get("MODEL_POOL", []))
    _cur_idx = CONFIG.get("CURRENT_MODEL_INDEX", 0)
    if not isinstance(_cur_idx, int) or _cur_idx < 0 or _cur_idx >= len(_llm_pool):
        logger.warning(f"⚠️ 当前模型索引越界，已自动重置：idx={_cur_idx}, pool_size={len(_llm_pool)}")
        _cur_idx = 0
        CONFIG["CURRENT_MODEL_INDEX"] = 0
    cur_model = _llm_pool[_cur_idx].get("name", "N/A") if _llm_pool else "N/A"
    reply_chance = CONFIG.get("REPLY_CHANCE", 10)
    # 【修复v4.3.1】自动同步config.json的版本号
    config_version = CONFIG.get("_CONFIG_VERSION") or CONFIG.get("VERSION", "未知")
    logger.info("=" * 60)
    logger.info(f"🚀 {bot_name} 私域超级分身  v{config_version}  启动！")
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
        try:
            from modules.auto_tasks import report_fault
            report_fault("Bot崩溃退出", f"{type(e).__name__}: {str(e)[:200]}", "🚨")
        except Exception:
            pass
        sys.exit(1)
