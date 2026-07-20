"""
╔══════════════════════════════════════════════════════════════════════════╗
║  main.py  ·  Mory 私域超级分身机器人  (v5.1.0 重构版)                   ║
║                                                                            ║
║  架构：模块化入口 | 核心对象由 bot_initializer 创建                       ║
║  分发：message_dispatcher 处理 P0-P10 优先级                            ║
║  Handler：core/handlers/ 按优先级组织                                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import signal
import logging
import traceback

# 【v5.31.2 审计暗病修复】统一代码版本号来源：启动横幅用 version.VERSION（代码版本），
# 不再读 config._CONFIG_VERSION（配置 schema 版本）。两者语义不同，混用会造成日志显示 v5.18.2
# 而 /api/health 返回 v5.31.2 的版本号不一致暗病。
from version import VERSION as CODE_VERSION

# ── 项目根目录（跨目录启动也正确）──
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)


def main():
    """主入口：初始化 → 注册 → 启动"""
    logger = logging.getLogger("main")

    # ════════════════════════════════════════════════════════════════════
    #  1. 初始化核心组件（环境变量/依赖/配置/DB/AI/Bot/中间件等）
    # ════════════════════════════════════════════════════════════════════
    from core.bot_initializer import initialize_bot, start_config_reload_watcher, preflight_check
    ctx = initialize_bot()
    bot = ctx.bot
    CONFIG = ctx.config
    DB = ctx.db if hasattr(ctx, 'db') else None
    AI = ctx.ai if hasattr(ctx, 'ai') else None

    # 初始化结构化日志（JSON 格式，与现有 logging_util 共存）
    from core.structured_logger import init_structlog
    init_structlog(json_output=True)

    # 【v5.11.0】启动 preflight 健康检查：5 项关键检查，任何致命问题阻断启动
    # 【v5.25.0】连续失败时指数退避，防止 systemd 重启轰炸
    preflight_result = preflight_check(CONFIG, db_instance=DB, ai_instance=AI)
    if not preflight_result["ok"]:
        # 致命问题：阻断启动（但先通知 admin 然后再退出）
        logger.critical("🚨 preflight 启动检查失败，阻断启动")

        # 指数退避：连续失败时等待更久再退出，防止 systemd 重启轰炸
        _backoff_file = os.path.join(base_dir, ".preflight_fail_count")
        try:
            if os.path.exists(_backoff_file):
                with open(_backoff_file, "r") as f:
                    fail_count = int(f.read().strip())
            else:
                fail_count = 0
            fail_count += 1
            # 退避时间：5s, 15s, 30s, 60s, 120s... 上限 300s
            backoff = min(5 * (2 ** min(fail_count - 1, 6)), 300)
            with open(_backoff_file, "w") as f:
                f.write(str(fail_count))
            logger.warning(f"⏳ preflight 连续失败 {fail_count} 次，退避 {backoff}s 后退出")
            time.sleep(backoff)
        except Exception as e:
            logger.debug(f"backoff 文件读取跳过: {e}")

        sys.exit(1)

    # preflight 通过，清除失败计数
    _backoff_file = os.path.join(base_dir, ".preflight_fail_count")
    if os.path.exists(_backoff_file):
        try:
            os.remove(_backoff_file)
        except Exception as e:
            logger.debug(f"清除 preflight 失败计数文件失败: {e}")

    start_config_reload_watcher(CONFIG)

    # ════════════════════════════════════════════════════════════════════
    #  1.2 启动 WriteQueue 单线程写入队列（v5.23.0 P0-1：消除 database is locked）
    # ════════════════════════════════════════════════════════════════════
    from core.write_queue import write_queue
    write_queue.start()

    # ════════════════════════════════════════════════════════════════════
    #  1.3 初始化 LLM 成本熔断器（v5.26.0 阶段1-A：防刷资金安全红线）
    # ════════════════════════════════════════════════════════════════════
    from core.llm_cost_guard import init_guard
    init_guard(CONFIG, getattr(DB, "db_file", None))

    # ════════════════════════════════════════════════════════════════════
    #  1.4 初始化多 Bot 路由器（v5.24.0 阶段3-C：多 Bot 任务分工编排）
    #  默认关闭，开启后按 bot_group_routing 表决定 Bot 是否响应某群组某模块
    # ════════════════════════════════════════════════════════════════════
    from core.bot_routing import init_router
    init_router(CONFIG)

    # ════════════════════════════════════════════════════════════════════
    #  1.5 初始化统一HTTP客户端（网络请求异常处理重构）
    # ════════════════════════════════════════════════════════════════════
    from core.http_client import init_http_client
    http_config = CONFIG.get("HTTP_CLIENT_CONFIG", {})
    init_http_client(http_config)

    # ════════════════════════════════════════════════════════════════════
    #  1.6 初始化分布式追踪（OpenTelemetry，默认关闭）
    # ════════════════════════════════════════════════════════════════════
    from core.tracing import init_tracing, shutdown_tracing
    init_tracing(CONFIG)

    # ════════════════════════════════════════════════════════════════════
    #  2. 注册专用处理器（优先级高于主分发器）
    # ════════════════════════════════════════════════════════════════════

    # P0：新人入群（独立handler，优先于主分发器拦截）
    from core.handlers.member_handlers import register_member_handlers
    register_member_handlers(bot, ctx)

    # 回调查询 + /settings + 编辑消息检测
    from core.handlers.callback_handlers import register_callback_handlers
    register_callback_handlers(bot, ctx)

    # 媒体处理器（图片/语音/退群/频道帖子）
    from core.handlers.media_handlers import register_media_handlers
    register_media_handlers(bot, ctx)

    # Telegram Business/Guest 新事件（连接状态、删除同步等）
    from core.handlers.business_handlers import register_business_handlers
    register_business_handlers(bot, ctx)

    # 管理员救援命令必须早于兜底分发器，避免私聊被 AI/反馈路由吞掉。
    @bot.message_handler(
        func=lambda m: bool(
            getattr(m, "text", "")
            and (
                m.text.strip().startswith("/unban")
                or m.text.strip().startswith("/解封")
                or m.text.strip() == "解封"
                or m.text.strip().startswith("解封 ")
                or m.text.strip().startswith("解除封禁")
            )
        ),
        content_types=["text"],
    )
    def on_unban_command(message):
        from modules.ad_enforcement import handle_unban_command

        handle_unban_command(
            bot,
            message,
            CONFIG,
            DB,
            ad_detector=getattr(ctx, "ad_detector", None),
        )

    # ════════════════════════════════════════════════════════════════════
    #  3. 注册主分发器（兜底 handler，必须最后注册）
    # ════════════════════════════════════════════════════════════════════
    from core.message_dispatcher import master_handler

    @bot.message_handler(func=lambda m: True,
                         content_types=["text", "new_chat_members"])
    def on_any_message(message):
        master_handler(message, ctx)

    # ════════════════════════════════════════════════════════════════════
    #  4. 信号处理（优雅停机）
    # ════════════════════════════════════════════════════════════════════
    import atexit

    _shutdown_done = False

    def _graceful_shutdown(signum=None, frame=None):
        """优雅停机：保存配置 → 关闭数据库 → 关闭追踪 → 退出"""
        nonlocal _shutdown_done
        if _shutdown_done:
            return
        _shutdown_done = True
        logging.getLogger("main").info("⏹️ 正在优雅停机...")
        try:
            ctx.save_config()
        except Exception as e:
            logging.getLogger("main").warning(f"停机时保存配置失败：{e}")
        try:
            from core.write_queue import write_queue
            write_queue.stop(timeout=10.0)
        except Exception as e:
            logging.getLogger("main").warning(f"停机时停止 WriteQueue 失败：{e}")
        try:
            ctx.db.close()
        except Exception as e:
            logging.getLogger("main").warning(f"停机时关闭数据库失败：{e}")
        try:
            shutdown_tracing()
        except Exception as e:
            logging.getLogger("main").warning(f"停机时关闭追踪失败：{e}")
        logging.getLogger("main").info("✅ 优雅停机完成")
        if signum is not None:
            sys.exit(0)

    atexit.register(_graceful_shutdown)
    try:
        signal.signal(signal.SIGTERM, _graceful_shutdown)
        signal.signal(signal.SIGINT, _graceful_shutdown)
    except (OSError, ValueError):
        pass  # Windows下可能不支持SIGTERM

    # ════════════════════════════════════════════════════════════════════
    #  5. 启动 Bot
    # ════════════════════════════════════════════════════════════════════
    bot_name = CONFIG.get("BOT_NAME", "Mory")
    _llm_pool = CONFIG.get("MODEL_POOLS", {}).get("llm", CONFIG.get("MODEL_POOL", []))
    _cur_idx = CONFIG.get("CURRENT_MODEL_INDEX", 0)
    if not isinstance(_cur_idx, int) or _cur_idx < 0 or _cur_idx >= len(_llm_pool):
        logger.warning(f"⚠️ 当前模型索引越界，已自动重置：idx={_cur_idx}, pool_size={len(_llm_pool)}")
        _cur_idx = 0
        CONFIG["CURRENT_MODEL_INDEX"] = 0
    cur_model = _llm_pool[_cur_idx].get("name", "N/A") if _llm_pool else "N/A"
    reply_chance = CONFIG.get("REPLY_CHANCE", 10)
    # 【v5.31.2 审计暗病修复】启动横幅优先用代码版本（version.VERSION），
    # 与 /api/health 返回的版本号保持一致；_CONFIG_VERSION 是配置 schema 版本，
    # 仅作为回退（兼容旧部署未导入 version 模块的场景）。
    # 注意：version.VERSION 已自带 "v" 前缀（如 "v5.31.2"），无需再拼 "v"。
    config_version = CODE_VERSION if CODE_VERSION else (CONFIG.get("_CONFIG_VERSION") or CONFIG.get("VERSION", "未知"))
    # 统一格式：保证 "v5.31.2"（带 v 前缀）
    if config_version and not config_version.startswith("v"):
        config_version = f"v{config_version}"

    logger.info("=" * 60)
    logger.info(f"🚀 {bot_name} 私域超级分身  {config_version}  启动！")
    logger.info(f"🤖 当前模型：{cur_model}")
    logger.info(f"👑 管理员ID：{CONFIG.get('ADMIN_ID', 0)}")
    logger.info(f"👥 主群ID：{CONFIG.get('GROUP_ID', 0)}")
    logger.info(f"🎲 随机回复概率：{reply_chance}%")
    logger.info(f"📁 数据库：mory.db（更新代码不影响此文件）")
    logger.info("=" * 60)

    try:
        from core.telebot_compat import get_allowed_updates
        bot.infinity_polling(timeout=60, long_polling_timeout=30,
                             allowed_updates=get_allowed_updates(CONFIG))
    except KeyboardInterrupt:
        logger.info("⏹️ 机器人已停止")
    except Exception as e:
        logger.critical(f"❌ 机器人崩溃：{e}\n{traceback.format_exc()}")
        try:
            from modules.auto_tasks import report_fault
            report_fault("Bot崩溃退出", f"{type(e).__name__}: {str(e)[:200]}", "🚨")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
