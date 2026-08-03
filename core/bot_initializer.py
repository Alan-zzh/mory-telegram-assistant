"""
core/bot_initializer.py  ·  Bot初始化工厂

从 main.py 提取的初始化逻辑，负责：
- 环境变量加载
- 依赖检查
- 配置管理（加载/保存/热重载/动态状态）
- BotContext 数据类
- initialize_bot() 工厂函数
"""

import os, sys, json, time, logging, subprocess, threading
from threading import Lock
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from core.config_compat import normalize_runtime_config, compact_runtime_config

# ── 项目根目录 ──
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 配置文件路径 ──
CONFIG_FILE = os.path.join(base_dir, "config.json")
_config_lock = Lock()
_loaded_config_mtime = 0.0

# ── 日志（延迟获取，避免循环依赖）──
def _get_logger():
    from core.logging_util import get_logger
    return get_logger("bot_initializer")


# ═══════════════════════════════════════════════════════════════
#  环境变量加载
# ═══════════════════════════════════════════════════════════════
def _load_env():
    """加载 .env 环境变量（敏感信息不硬编码）"""
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


# ═══════════════════════════════════════════════════════════════
#  启动 preflight 健康检查
# ═══════════════════════════════════════════════════════════════
def preflight_check(cfg: dict, db_instance=None, ai_instance=None) -> dict:
    """【v5.11.0】启动前配置健康度自检：5 项关键检查 + 致命问题阻断启动

    Returns:
        dict: {
            "ok": bool,
            "fatal": [str],  # 致命问题（会阻断启动）
            "warnings": [str],  # 警告（不阻断但需关注）
            "checks": {  # 每项检查的详细结果
                "token": {"ok": bool, "value": str, "reason": str},
                "group_id": {"ok": bool, "value": int, "reason": str},
                "channel_ids": {"ok": bool, "value": list, "reason": str},
                "database": {"ok": bool, "reason": str},
                "ai_engine": {"ok": bool, "reason": str},
            }
        }
    """
    logger = _get_logger()
    result = {
        "ok": True,
        "fatal": [],
        "warnings": [],
        "checks": {},
    }

    # 1. TOKEN 非占位
    token = cfg.get("TOKEN", "")
    token_ok = bool(token) and token != "YOUR_TELEGRAM_BOT_TOKEN" and ":" in token
    result["checks"]["token"] = {
        "ok": token_ok,
        "value": "***" + token[-6:] if token else "(empty)",
        "reason": "" if token_ok else "TOKEN 为空或仍是占位符"
    }
    if not token_ok:
        result["fatal"].append("❌ TOKEN 无效（请设置真实的 Telegram Bot Token）")

    # 2. GROUP_ID 或 CHANNEL_IDS 至少 1 个
    gid = int(cfg.get("GROUP_ID", 0) or 0)
    channel_ids = cfg.get("CHANNEL_IDS", []) or []
    has_target = gid > 0 or len(channel_ids) > 0
    result["checks"]["group_id"] = {
        "ok": gid > 0,
        "value": gid,
        "reason": "" if gid > 0 else "GROUP_ID 为 0，关键任务将无法发送",
    }
    result["checks"]["channel_ids"] = {
        "ok": len(channel_ids) > 0,
        "value": [c.get("name", c.get("id", "?")) if isinstance(c, dict) else c for c in channel_ids],
        "reason": "" if channel_ids else "CHANNEL_IDS 为空，频道数据日报将无内容",
    }
    if not has_target:
        result["fatal"].append("❌ 缺少发送目标：GROUP_ID 与 CHANNEL_IDS 都为空")
    elif gid == 0:
        result["warnings"].append("⚠️ GROUP_ID 为 0，群内任务（问候/新闻）将 abort")
    elif not channel_ids:
        result["warnings"].append("⚠️ CHANNEL_IDS 为空，频道数据日报将无内容")

    # 3. 数据库可读写（加 3 次重试，数据库锁是瞬态的）
    db_ok = False
    db_reason = "未提供 db_instance"
    if db_instance is not None:
        for attempt in range(3):
            try:
                test_key = "_preflight_test"
                db_instance.set_system_state(test_key, "ok")
                val = db_instance.get_system_state(test_key)
                db_instance.set_system_state(test_key, None)
                db_ok = val == "ok"
                db_reason = "" if db_ok else "数据库读写测试失败"
                break
            except Exception as e:
                db_reason = f"数据库异常: {e}"
                if attempt < 2:
                    time.sleep(1)  # 等待 1 秒后重试（数据库锁是瞬态的）
                else:
                    logger.warning(f"数据库重试 {attempt + 1}/3 仍失败: {db_reason}")
    result["checks"]["database"] = {
        "ok": db_ok,
        "reason": db_reason,
    }
    if not db_ok and db_instance is not None:
        result["fatal"].append(f"❌ 数据库不可读写：{db_reason}")

    # 4. AI engine 可 ping
    ai_ok = False
    ai_reason = "未提供 ai_instance"
    if ai_instance is not None:
        try:
            if hasattr(ai_instance, "ping"):
                ai_ok = bool(ai_instance.ping())
                ai_reason = "" if ai_ok else "AI ping 返回 False"
            else:
                ai_ok = True  # 没有 ping 方法就假设可用
                ai_reason = "无 ping 方法，跳过"
        except Exception as e:
            ai_reason = f"AI ping 异常: {e}"
    result["checks"]["ai_engine"] = {
        "ok": ai_ok,
        "reason": ai_reason,
    }
    if not ai_ok and ai_instance is not None:
        result["warnings"].append(f"⚠️ AI 引擎 ping 失败：{ai_reason}")

    # 5. scheduler 可注册（轻量探测）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        test_sched = BackgroundScheduler()
        # 不实际 start()，只验证可以实例化
        result["checks"]["scheduler"] = {"ok": True, "reason": "可实例化"}
    except ImportError:
        result["checks"]["scheduler"] = {"ok": False, "reason": "APScheduler 未安装"}
        result["warnings"].append("⚠️ APScheduler 未安装，将回退到旧版循环")
    except Exception as e:
        result["checks"]["scheduler"] = {"ok": False, "reason": str(e)}
        result["fatal"].append(f"❌ scheduler 异常: {e}")

    # 汇总
    result["ok"] = len(result["fatal"]) == 0

    # 输出日志
    if result["ok"]:
        logger.info(f"✅ preflight 通过：5 项检查全部 OK")
    else:
        logger.error(f"❌ preflight 失败：{len(result['fatal'])} 个致命问题")
        for f in result["fatal"]:
            logger.error(f"  {f}")
    for w in result["warnings"]:
        logger.warning(f"  {w}")

    # 致命问题时通过 _FaultReporter 通知 admin
    if not result["ok"]:
        try:
            from modules.auto_tasks import report_fault
            report_fault(
                "preflight启动检查失败",
                "\n".join(result["fatal"]),
                "🚨"
            )
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    return result


# ═══════════════════════════════════════════════════════════════
#  依赖检查
# ═══════════════════════════════════════════════════════════════
def _ensure_deps():
    """自动安装缺失依赖（pyTelegramBotAPI, requests, Pillow）"""
    logger = _get_logger()
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

    # 【v5.31.x 优化/稳定性】生产环境默认【只校验不安装】。
    # 原逻辑在生产启动时联网自动 pip 安装缺失依赖：会拖慢启动、可能拉入不兼容版本、
    # 破坏 requirements.lock 可复现性，且无网时静默掩盖真实部署缺陷。
    # 仅在显式开启 MORY_AUTO_INSTALL_DEPS=1/true 时才回退到自动安装（本地/DEBUG 用）。
    _auto_install = os.environ.get("MORY_AUTO_INSTALL_DEPS", "").lower() in ("1", "true", "yes")
    if not _auto_install:
        logger.error(
            f"❌ 启动缺少依赖：{missing}。生产环境已禁用自动安装（避免破坏可复现性）。"
            f"请在部署时通过 requirements 安装，或在本地设置 MORY_AUTO_INSTALL_DEPS=1 允许自动安装后重试。"
        )
        raise RuntimeError(f"缺失依赖且自动安装未开启：{missing}")

    logger.info(f"📦 自动安装依赖（MORY_AUTO_INSTALL_DEPS 已开启）：{missing}")

    installed = False
    import sys as _sys

    # 方式1: 使用项目venv（推荐）
    if _sys.platform == "win32":
        venv_pip = os.path.join(base_dir, "venv", "Scripts", "pip.exe")
    else:
        venv_pip = os.path.join(base_dir, "venv", "bin", "pip")
    if os.path.exists(venv_pip):
        import subprocess
        ret = subprocess.run([venv_pip, "install"] + missing + ["-q"], capture_output=True).returncode
        installed = (ret == 0)

    # 方式2: python3 -m pip --break-system-packages (Debian/Ubuntu PEP 668兼容)
    if not installed:
        ret = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages"] + missing + ["-q"],
            capture_output=True
        ).returncode
        installed = (ret == 0)

    # 方式3: pip3 --user
    if not installed:
        subprocess.run(["pip3", "install", "--user"] + missing + ["-q"], capture_output=True)

    logger.info("✅ 依赖安装完成")


# ═══════════════════════════════════════════════════════════════
#  配置管理
# ═══════════════════════════════════════════════════════════════
def load_config() -> dict:
    """加载配置文件，并从数据库覆盖动态状态。
    配置损坏时加载内置最小默认配置并告警
    优先级：环境变量 > config.json（密钥类字段）
    """
    logger = _get_logger()
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = normalize_runtime_config(json.load(f))
            global _loaded_config_mtime
            _loaded_config_mtime = os.path.getmtime(CONFIG_FILE)
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

    # ── 环境变量覆盖密钥类字段（优先级高于config.json）──
    _env_overrides = {
        "TOKEN": "TG_TOKEN",
        "API_KEY": "DASHSCOPE_KEY",
        "ADMIN_ID": "ADMIN_ID",
        "GROUP_ID": "GROUP_ID",
    }
    for cfg_key, env_key in _env_overrides.items():
        env_val = os.environ.get(env_key, "")
        if env_val:
            cfg[cfg_key] = env_val

    # 从数据库加载动态状态，覆盖配置文件
    _load_dynamic_states(cfg)

    return cfg


def save_config(cfg: dict, db_instance=None):
    """保存配置到文件，并同步动态状态到数据库。
    返回bool表示成功/失败
    """
    logger = _get_logger()
    with _config_lock:
        try:
            global _loaded_config_mtime
            if os.path.exists(CONFIG_FILE):
                current_mtime = os.path.getmtime(CONFIG_FILE)
                if _loaded_config_mtime and current_mtime > _loaded_config_mtime:
                    logger.warning("检测到磁盘配置比当前进程更新，跳过本次保存以避免旧内存覆盖新配置")
                    return False
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(compact_runtime_config(cfg), f, ensure_ascii=False, indent=2)
            _loaded_config_mtime = os.path.getmtime(CONFIG_FILE)
        except Exception as e:
            logger.error(f"配置保存失败：{e}")
            return False

    # 同步动态状态到数据库
    if db_instance is not None:
        dynamic_keys = ["CURRENT_MODEL_INDEX", "IMAGE_POOL", "VOICE_POOL", "_LAST_LEAK_WEEK"]
        for key in dynamic_keys:
            if key in cfg:
                value = cfg[key]
                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                db_instance.set_system_state(key, value)
    return True


def _get_minimal_default_config() -> dict:
    """内置最小默认配置（config.json损坏时的兜底）"""
    _get_logger().warning("⚠️ 使用内置最小默认配置，部分功能可能受限，请修复config.json")
    return {
        "TOKEN": "", "API_KEY": "", "ADMIN_ID": 0, "GROUP_ID": 0,
        "BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        # 兜底配置不设过期，确保 config.json 损坏时始终可用
        "MODEL_POOLS": {"llm": [
            {"name": "qwen3.6-27b"},
            {"name": "qwen3.7-max-2026-05-17"},
            {"name": "qwen3.7-max-preview"},
            {"name": "qwen3.7-plus-2026-05-26"},
            {"name": "qwen3.7-max-2026-06-08"},
            {"name": "kimi-k2.7-code"},
        ]},
        "REPLY_CHANCE": 10, "_CONFIG_VERSION": "5.0.0",
        "SYSTEM_PROMPT": "你是Mory，一个活泼可爱的小助理。",
    }


def _load_dynamic_states(cfg: dict, db_instance=None):
    """从数据库加载动态状态到配置"""
    logger = _get_logger()
    if db_instance is None:
        return

    # 从数据库读取动态状态
    dynamic_keys = [
        "CURRENT_MODEL_INDEX",
        "IMAGE_POOL",
        "VOICE_POOL",
        "_LAST_LEAK_WEEK"
    ]

    for key in dynamic_keys:
        db_value = db_instance.get_system_state(key)
        if db_value is not None:
            if key in ("CURRENT_MODEL_INDEX",):
                cfg[key] = int(db_value) if db_value else 0
            elif key in ("IMAGE_POOL", "VOICE_POOL"):
                try:
                    cfg[key] = json.loads(db_value)
                except Exception as e:
                    logger.debug(f"动态状态{key} JSON解析失败，回退默认值（非致命）：{e}")
                    cfg[key] = []
            elif key == "_LAST_LEAK_WEEK":
                cfg[key] = int(db_value) if db_value else -1
            else:
                cfg[key] = db_value
            # 日志脱敏：只记录键+类型/长度，禁止明文值进入 DEBUG（防止 token/key/长 list 意外落盘）
            _v = cfg[key]
            if _v is None:
                _safe = "None"
            elif isinstance(_v, str):
                _safe = f"str(len={len(_v)})"
            elif isinstance(_v, (list, dict, tuple, set)):
                _safe = f"{type(_v).__name__}(len={len(_v)})"
            else:
                _safe = type(_v).__name__
            logger.debug(f"📌 动态状态加载: {key}=<{_safe}>")


def _check_config_hot_reload(cfg: dict):
    """检查config.json是否被外部修改（Dashboard/settings_panel），如有则重新加载"""
    logger = _get_logger()
    # 使用闭包保存mtime，避免模块级全局变量
    if not hasattr(_check_config_hot_reload, "_mtime"):
        _check_config_hot_reload._mtime = 0

    try:
        mtime = os.path.getmtime(CONFIG_FILE)
        if _check_config_hot_reload._mtime == 0:
            _check_config_hot_reload._mtime = mtime
            return
        if mtime > _check_config_hot_reload._mtime:
            logger.info("🔄 检测到config.json变更，热重载中...")
            new_cfg = load_config()
            # 保留运行时动态状态
            for key in ("CURRENT_MODEL_INDEX", "IMAGE_POOL", "VOICE_POOL"):
                if key in cfg and key not in new_cfg:
                    new_cfg[key] = cfg[key]
            cfg.clear()
            cfg.update(new_cfg)
            _check_config_hot_reload._mtime = mtime
            logger.info("✅ 配置热重载完成")
    except Exception as e:
        logger.debug(f"配置热重载检查失败: {e}")


RELOAD_FLAG = Path(base_dir) / 'reload_flag'


def start_config_reload_watcher(cfg: dict, interval: int = 30):
    """启动后台线程，定期检查reload_flag文件，发现后重载config.json到内存

    Dashboard修改config.json后会创建reload_flag文件作为信号，
    本线程检测到信号后读取最新配置并原地更新cfg字典，
    所有引用同一cfg对象的模块自动获得新配置。
    """
    logger = _get_logger()

    def _watcher_loop():
        while True:
            try:
                time.sleep(interval)
                if RELOAD_FLAG.exists():
                    logger.info("[配置重载] 检测到reload_flag信号，开始重载...")
                    try:
                        new_cfg = load_config()
                        for key in ("CURRENT_MODEL_INDEX", "IMAGE_POOL", "VOICE_POOL"):
                            if key in cfg and key not in new_cfg:
                                new_cfg[key] = cfg[key]
                        cfg.clear()
                        cfg.update(new_cfg)
                        if hasattr(_check_config_hot_reload, "_mtime"):
                            try:
                                _check_config_hot_reload._mtime = os.path.getmtime(CONFIG_FILE)
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                        logger.info("[配置重载] Dashboard配置变更已同步到Bot内存")
                    except json.JSONDecodeError as e:
                        logger.error(f"[配置重载] config.json格式损坏，跳过本次重载: {e}")
                    except Exception as e:
                        logger.error(f"[配置重载] 失败: {e}")
                    finally:
                        try:
                            RELOAD_FLAG.unlink(missing_ok=True)
                        except Exception as e:
                            logger.debug(f"操作异常: {e}")
            except Exception as e:
                logger.debug(f"操作异常: {e}")
    t = threading.Thread(target=_watcher_loop, daemon=True, name="config_reload_watcher")
    t.start()
    logger.info(f"[配置重载] reload_flag监听已启动（间隔{interval}秒）")


# ═══════════════════════════════════════════════════════════════
#  BotContext 数据类
# ═══════════════════════════════════════════════════════════════

# [TRAE SOLO CN] v5.19.0 全局 BotContext 引用（供 antiflood 等无 ctx 引用的模块访问）
_GLOBAL_CTX: Optional["BotContext"] = None


def _get_global_ctx() -> Optional["BotContext"]:
    """获取全局 BotContext 引用。"""
    return _GLOBAL_CTX


@dataclass
class BotContext:
    """Bot核心上下文，封装所有全局单例对象"""
    config: dict = None                # CONFIG字典
    bot: Any = None                    # TeleBot实例
    db: Any = None                     # DB数据库实例
    ai: Any = None                     # AIEngine实例
    mory_bot: Any = None               # MoryBot封装层
    resource_manager: Any = None       # ResourceManager
    keyword_trigger: Any = None        # KeywordTrigger
    keyword_manager: Any = None        # KeywordManager（统一关键词管理）
    ad_detector: Any = None            # AdDetector
    proactive_engage: Any = None       # [v5.14.0] ProactiveEngage 商业搭讪
    intent_router: Any = None          # [v5.19.0] IntentRouter 意图路由
    profile_learner: Any = None        # [v5.19.0] ProfileLearner 画像学习器
    bot_id: int = 0                    # BOT_ID
    bot_username: str = ""             # BOT_USERNAME
    save_config: Callable = None       # 保存配置函数
    append_pool: ThreadPoolExecutor = None  # 追加线程池


# ═══════════════════════════════════════════════════════════════
#  initialize_bot() 工厂函数
# ═══════════════════════════════════════════════════════════════
def _recover_zombie_tasks_or_raise(db, attempts: int = 3, sleep_fn=time.sleep) -> int:
    """启动前有界重试回收旧任务；失败则阻止带脏锁启动。"""
    task_logger = _get_logger()
    attempts = max(1, int(attempts))
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return db.cleanup_zombie_running(timeout_seconds=0)
        except Exception as exc:
            last_error = exc
            task_logger.error(f"启动清理旧任务失败 ({attempt}/{attempts}): {exc}")
            if attempt < attempts:
                sleep_fn(min(2.0, 0.5 * attempt))
    raise RuntimeError("启动清理旧任务连续失败，拒绝启动调度器") from last_error


def initialize_bot() -> BotContext:
    """初始化Bot所有核心组件，返回BotContext"""

    logger = _get_logger()

    # 1. 加载环境变量
    _load_env()

    # 2. 配置日志
    from core.logging_util import configure_logging, get_logger as _gl
    configure_logging(
        level=logging.INFO,
        log_file=os.path.join(base_dir, "mory.log"),
        max_bytes=10*1024*1024,
        backup_count=5,
        json_format=False,
        console_output=True,
    )

    # 3. 检查依赖
    _ensure_deps()

    # 4. 加载配置
    cfg = load_config()

    # 5. 安全覆盖：环境变量优先于 config.json
    if os.environ.get("TG_TOKEN"):
        cfg["TOKEN"] = os.environ["TG_TOKEN"]
    if os.environ.get("DASHSCOPE_KEY"):
        cfg["API_KEY"] = os.environ["DASHSCOPE_KEY"]

    # 6. 校验必填项
    _PLACEHOLDER_TOKENS = ("YOUR_BOT_TOKEN_HERE", "YOUR_TELEGRAM_BOT_TOKEN")
    _PLACEHOLDER_KEYS = ("YOUR_DASHSCOPE_API_KEY_HERE", "YOUR_DASHSCOPE_API_KEY")
    if not cfg.get("TOKEN") or cfg["TOKEN"] in _PLACEHOLDER_TOKENS:
        logger.critical("❌ TOKEN 未填写！请编辑 config.json 或设置 TG_TOKEN 环境变量后重启。")
        sys.exit(1)
    if not cfg.get("API_KEY") or cfg["API_KEY"] in _PLACEHOLDER_KEYS:
        logger.critical("❌ API_KEY 未填写！请编辑 config.json 后重启。")
        sys.exit(1)

    # 7. 创建DB
    from core.database import DB
    db = DB(os.path.join(base_dir, "mory.db"))

    # 8. 创建AIEngine
    from core.ai_engine import AIEngine
    ai = AIEngine(cfg)

    # 9. 数据库初始化后，重新加载动态状态到 CONFIG
    _load_dynamic_states(cfg, db)

    # 10. 创建TeleBot
    import telebot
    from core.telebot_compat import (
        TelegramPollingExceptionHandler,
        preserve_telegram_extra_fields,
    )
    preserve_telegram_extra_fields()
    # 【v5.31.x 优化】单 Bot 单 VPS：实测 RSS~92MB、FD 仅 19，并发并不高。
    # 50 线程常驻纯耗调度，降到 10 对单群/中等流量绰绰有余，稳定前提下省 ~40 线程。
    bot = telebot.TeleBot(
        cfg["TOKEN"],
        threaded=True,
        num_threads=10,
        use_class_middlewares=True,
        exception_handler=TelegramPollingExceptionHandler(),
    )

    # 11. 广告检测引擎
    from modules.ad_detector import AdDetector
    ad_detector = AdDetector(cfg, db)

    # 12. 获取BOT_ID/BOT_USERNAME
    _bot_me = None
    for _attempt in range(3):
        try:
            _bot_me = bot.get_me()
            break
        except Exception as e:
            if _attempt == 2:
                logger.critical(f"❌ bot.get_me() 连续 3 次失败: {e}")
                sys.exit(1)
            logger.warning(f"⚠️ bot.get_me() 第 {_attempt+1} 次失败，重试中: {e}")
            time.sleep(2 ** _attempt)
    bot_id = _bot_me.id
    bot_username = _bot_me.username
    logger.info(f"🤖 Bot ID: {bot_id}, Username: @{bot_username}")

    # 13. 数据库完整性检查 + 自动恢复
    _check_db_integrity(db, cfg)

    # 13.5 【P1-2】清理 task_execution_history 僵尸 running 记录
    # 进程被 SIGKILL 时 running 状态永久残留,启动时一次性清理
    # 此处在后台任务启动前执行，现存 running 均属于旧进程，可立即回收。
    zombie_count = _recover_zombie_tasks_or_raise(db)
    if zombie_count > 0:
        logger.warning(f"🧹 启动清理: {zombie_count} 条僵尸 running 任务记录已标记为 failed")

    # 14. 数据库写入测试（内存测试，不写生产库）
    _test_db_write()

    # 15. 初始化默认关键词触发规则
    _init_keyword_triggers(db)

    # 16. 启动后台自动任务
    from modules.auto_tasks import start_background
    # 构建save_config闭包
    _save_cfg = lambda: save_config(cfg, db)
    start_background(bot, cfg, db, ai, _save_cfg)

    # 17. 创建MoryBot封装层
    from core.mory_bot import MoryBot
    mory_bot = MoryBot(bot, db, cfg)
    bot._mory_bot_instance = mory_bot

    # 18. 创建ResourceManager
    from core.resource_manager import ResourceManager
    resource_manager = ResourceManager(bot=bot, ai=ai, db=db, config=cfg, save_config_fn=_save_cfg)

    # 19. 创建KeywordTrigger
    from modules.keyword_trigger import KeywordTrigger
    keyword_trigger = KeywordTrigger(db, mory_bot, ai, cfg)

    # 19.1 创建KeywordManager（统一关键词与静态数据管理）
    from core.keyword_manager import KeywordManager
    keyword_manager = KeywordManager(cfg, db)

    # 19.5 [v5.14.0] 创建ProactiveEngage - 商业问题主动搭讪
    from modules.proactive_engage import ProactiveEngage
    proactive_engage = ProactiveEngage(db, mory_bot, ai, cfg, keyword_manager)

    # 19.6 [TRAE SOLO CN] v5.19.0 创建 IntentRouter 意图路由器
    from core.intent_router import IntentRouter
    intent_router = IntentRouter(ai, cfg)

    # 19.7 [TRAE SOLO CN] v5.19.0 创建 ProfileLearner 画像学习器（默认关闭）
    from core.profile_learner import ProfileLearner
    profile_learner = ProfileLearner(db, cfg, ai)

    # 20. 注册中间件
    from telebot.handler_backends import BaseMiddleware

    class ReplySnifferMiddleware(BaseMiddleware):
        """全局底层嗅探器：捕获用户对机器人回复，豁免阅后即焚"""
        def __init__(self, db_instance, bot_id_val):
            self.update_types = ['message']
            self.db = db_instance
            self._bot_id = bot_id_val

        def pre_process(self, message, data):
            if message.reply_to_message and message.reply_to_message.from_user.id == self._bot_id:
                try:
                    self.db.mark_replied(message.reply_to_message.message_id, message.chat.id)
                    logger.info(f"🛡️ [底层嗅探] 捕获回复，豁免阅后即焚: bot_msg_id={message.reply_to_message.message_id}")
                except Exception as e:
                    logger.warning(f"[底层嗅探] 异常: {e}")

        def post_process(self, message, data, exception):
            pass

    bot.setup_middleware(ReplySnifferMiddleware(db, bot_id))

    # 21. 创建追加线程池
    append_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="append")

    # 22. 返回BotContext
    ctx = BotContext(
        config=cfg,
        bot=bot,
        db=db,
        ai=ai,
        mory_bot=mory_bot,
        resource_manager=resource_manager,
        keyword_trigger=keyword_trigger,
        keyword_manager=keyword_manager,
        ad_detector=ad_detector,
        proactive_engage=proactive_engage,  # [v5.14.0]
        intent_router=intent_router,        # [v5.19.0]
        profile_learner=profile_learner,    # [v5.19.0]
        bot_id=bot_id,
        bot_username=bot_username,
        save_config=_save_cfg,
        append_pool=append_pool,
    )

    # [TRAE SOLO CN] v5.19.0 设置全局 BotContext 引用
    global _GLOBAL_CTX
    _GLOBAL_CTX = ctx

    # [TRAE SOLO CN] 启动追溯封禁：处理重启前未完成的广告封禁
    try:
        ad_detector.process_pending_bans(bot, cfg)
    except Exception as e:
        logger.warning(f"启动追溯封禁失败: {e}")

    # [TRAE SOLO CN] 启动追溯扫描：扫描群内历史消息删除漏网广告
    # 优化：加冷却机制（24小时内只扫一次），且只在有实际删除时才通知管理员
    if cfg.get("RETROACTIVE_SCAN_ENABLED", False):
        def _run_retroactive_scan():
            try:
                admin_id = cfg.get("ADMIN_ID", 0)
                group_id = cfg.get("GROUP_ID", 0)
                scan_range = cfg.get("RETROACTIVE_SCAN_RANGE", 200)
                if not admin_id or not group_id:
                    return
                # 冷却检查：24小时内只扫一次
                try:
                    last_scan = db.conn.execute(
                        "SELECT ts FROM retroactive_scan_log ORDER BY ts DESC LIMIT 1"
                    ).fetchone()
                    if last_scan:
                        import time as _time
                        last_ts = float(last_scan[0]) if last_scan[0] else 0
                        if _time.time() - last_ts < 86400:
                            logger.info("[启动追溯扫描] 24小时内已扫描过，跳过")
                            return
                except Exception as e:
                    logger.debug(f"查询 retroactive_scan_log 失败，继续执行扫描: {e}")
                # 使用已持久化的最后一条群消息定位扫描范围。禁止为取 message_id
                # 在群里发送再删除“.”，避免制造删除提示和额外群内副作用。
                end_id = _get_latest_snapshot_message_id(db, group_id)
                if not end_id:
                    logger.info("[启动追溯扫描] 无历史消息快照，安全跳过")
                    return
                start_id = max(1, end_id - scan_range + 1)
                logger.info(f"[启动追溯扫描] 开始扫描 msg_id {start_id}~{end_id}")
                scan_result = ad_detector.retroactive_scan(bot, group_id, start_id, end_id, admin_id, config=cfg)
                # 记录扫描日志
                try:
                    import time as _time
                    db.conn.execute(
                        "INSERT INTO retroactive_scan_log(ts, scanned, ads_found, deleted) VALUES (?,?,?,?)",
                        (_time.time(), scan_result["scanned"], scan_result["ads_found"], scan_result["deleted"])
                    )
                    db.conn.commit()
                except Exception as e:
                    # 【v5.31.2 修复】日志写入失败会导致下次启动重复扫描，浪费 API 配额
                    logger.warning(f"启动追溯扫描日志写入失败: {e}")
                # 只在有实际删除时才通知管理员
                if scan_result["deleted"] > 0:
                    report = (
                        f"🔍 启动追溯扫描完成\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"📊 扫描范围: {start_id}~{end_id}\n"
                        f"📋 扫描消息: {scan_result['scanned']}条\n"
                        f"🚫 发现广告: {scan_result['ads_found']}条\n"
                        f"️ 删除成功: {scan_result['deleted']}条\n"
                        f"⚠️ 删除失败: {scan_result['failed']}条\n"
                        f"⏭️ 正常跳过: {scan_result['skipped']}条\n"
                        f"📭 不存在: {scan_result['not_found']}条"
                    )
                    try:
                        bot.send_message(admin_id, report)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                else:
                    logger.info(f"[启动追溯扫描] 扫描完成，删除={scan_result['deleted']}，无有效删除不通知")
            except Exception as e:
                logger.warning(f"启动追溯扫描失败: {e}")

        t = threading.Thread(target=_run_retroactive_scan, daemon=True, name="retroactive_scan")
        t.start()

    # [TRAE SOLO CN] 启动补清理：处理重启前丢失的定时删除任务
    def _run_startup_cleanup():
        try:
            from core.helpers import can_orphan_cleanup
            window = 86400
            orphans = db.get_orphan_messages(window)
            if not orphans:
                logger.info("[启动补清理] 无超时消息需要清理")
                return
            if not can_orphan_cleanup(cfg):
                logger.info(f"[启动补清理] ORPHAN_CLEANUP_ENABLED=False，跳过{len(orphans)}条超时消息")
                return
            deleted_count = 0
            not_found = 0
            for bot_mid, cid, user_mid in orphans:
                try:
                    bot.delete_message(cid, int(bot_mid))
                    deleted_count += 1
                    db.delete_tracked(bot_mid, cid)
                except Exception as e:
                    err_str = str(e).lower()
                    if "not found" in err_str:
                        not_found += 1
                    else:
                        logger.debug(f"[启动补清理] 删除失败: chat={cid} msg={bot_mid}: {e}")
                    db.delete_tracked(bot_mid, cid)
            logger.info(f"[启动补清理] 完成: 删除={deleted_count} 不存在={not_found} 总计={len(orphans)}")
        except Exception as e:
            logger.warning(f"启动补清理失败: {e}")

    t2 = threading.Thread(target=_run_startup_cleanup, daemon=True, name="startup_cleanup")
    t2.start()

    return ctx


# ═══════════════════════════════════════════════════════════════
#  辅助函数（initialize_bot内部使用）
# ═══════════════════════════════════════════════════════════════
def _get_latest_snapshot_message_id(db, chat_id: int) -> int:
    """只读获取群内最后一条已持久化消息 ID，不向群发送探针消息。"""
    try:
        row = db.conn.execute(
            "SELECT MAX(msg_id) FROM message_snapshots WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
        return int(row[0]) if row and row[0] else 0
    except Exception as e:
        _get_logger().warning(f"读取最后消息快照失败 chat_id={chat_id}: {e}")
        return 0


def _check_db_integrity(db, cfg):
    """启动时数据库完整性检查，异常时自动从备份恢复"""
    logger = _get_logger()
    try:
        result = db.conn.execute("PRAGMA integrity_check").fetchone()
        if result and result[0] == "ok":
            table_count = db.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            logger.info(f"✅ 数据库完整性检查通过（{table_count} 张表）")
        else:
            logger.error(f"⚠️ 数据库完整性异常：{result}")
            _restore_db_from_backup(db, cfg)
    except Exception as e:
        logger.error(f"⚠️ 数据库检查出错：{e}")


def _restore_db_from_backup(db, cfg):
    """从备份恢复数据库"""
    logger = _get_logger()
    import glob as _glob
    import shutil
    _backup_dir = os.path.join(base_dir, "backup")
    if os.path.isdir(_backup_dir):
        _backups = sorted(_glob.glob(os.path.join(_backup_dir, "mory_backup_*.db")))
        if _backups:
            _latest_backup = _backups[-1]
            logger.warning(f"   → 尝试从备份恢复：{_latest_backup}")
            try:
                db.close()
                shutil.copy2(_latest_backup, os.path.join(base_dir, "mory.db"))
                # 【P0-NEW-09 修复】close() 后必须重建连接，否则后续操作抛
                # ProgrammingError: Cannot operate on a closed database
                db.reconnect()
                _load_dynamic_states(cfg, db)
                logger.info("✅ 数据库从备份恢复成功！")
                try:
                    from modules.auto_tasks import report_fault
                    report_fault("数据库异常已自动恢复", f"从备份{_latest_backup}恢复成功", "⚠️")
                except Exception as e:
                    # 【v5.31.2 修复】数据库恢复后管理员通知失败应告警
                    logger.warning(f"数据库恢复后告警发送失败: {e}")
            except Exception as restore_err:
                logger.critical(f"❌ 数据库恢复失败：{restore_err}")
                logger.critical("   → 请手动从 backup/ 目录恢复")
                try:
                    from modules.auto_tasks import report_fault
                    report_fault("数据库损坏且恢复失败", str(restore_err), "🚨")
                except Exception as e:
                    # 【v5.31.2 修复】CRITICAL：数据库损坏+恢复失败+告警失败=三重故障，必须告警
                    logger.critical(f"数据库恢复失败且告警发送失败（三重故障）: {e}")
        else:
            logger.error("   → 无可用备份，请手动检查数据库")
    else:
        logger.error("   → backup/ 目录不存在，无法自动恢复")


def _test_db_write():
    """启动时数据库写入测试（验证track_reply功能正常，使用内存SQLite）"""
    logger = _get_logger()
    test_conn = None
    try:
        logger.info("🔍 开始阅后即焚数据库功能测试...")
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
        test_cursor.execute("INSERT INTO reply_tracking VALUES (?,?,?,?,0)",
                            (test_bot_id, test_chat_id, test_user_id, int(time.time())))
        test_cursor.execute("SELECT bot_msg_id FROM reply_tracking WHERE bot_msg_id=?", (test_bot_id,))
        found = test_cursor.fetchone() is not None

        if found:
            logger.info("✅ 阅后即焚数据库功能测试通过（内存测试，未写生产库）")
        else:
            logger.error("❌ 阅后即焚数据库结构测试失败！")
    except Exception as e:
        logger.error(f"❌ 阅后即焚数据库写入测试异常：{e}")
        import traceback
        logger.error(f"❌ 测试异常详情：{traceback.format_exc()}")
    finally:
        # 【v5.31.2 修复】SQL 失败时也要关闭 test_conn，避免连接泄漏
        if test_conn is not None:
            try:
                test_conn.close()
            except Exception:
                pass


def _init_keyword_triggers(db):
    """初始化默认关键词触发规则"""
    logger = _get_logger()
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
