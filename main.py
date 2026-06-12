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
import signal
import logging
import traceback

# ── 项目根目录（跨目录启动也正确）──
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)


def main():
    """主入口：初始化 → 注册 → 启动"""

    # ════════════════════════════════════════════════════════════════════
    #  1. 初始化核心组件（环境变量/依赖/配置/DB/AI/Bot/中间件等）
    # ════════════════════════════════════════════════════════════════════
    from core.bot_initializer import initialize_bot, start_config_reload_watcher, preflight_check
    ctx = initialize_bot()
    bot = ctx.bot
    CONFIG = ctx.config
    DB = ctx.db if hasattr(ctx, 'db') else None
    AI = ctx.ai if hasattr(ctx, 'ai') else None

    # 【v5.11.0】启动 preflight 健康检查：5 项关键检查，任何致命问题阻断启动
    preflight_result = preflight_check(CONFIG, db_instance=DB, ai_instance=AI)
    if not preflight_result["ok"]:
        # 致命问题：阻断启动（但先通知 admin 然后再退出）
        logger = __import__('logging').getLogger("main")
        logger.critical("🚨 preflight 启动检查失败，阻断启动")
        sys.exit(1)

    start_config_reload_watcher(CONFIG)

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
        """优雅停机：保存配置 → 关闭数据库 → 退出"""
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
            ctx.db.close()
        except Exception as e:
            logging.getLogger("main").warning(f"停机时关闭数据库失败：{e}")
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
    logger = logging.getLogger("main")

    bot_name = CONFIG.get("BOT_NAME", "Mory")
    _llm_pool = CONFIG.get("MODEL_POOLS", {}).get("llm", CONFIG.get("MODEL_POOL", []))
    _cur_idx = CONFIG.get("CURRENT_MODEL_INDEX", 0)
    if not isinstance(_cur_idx, int) or _cur_idx < 0 or _cur_idx >= len(_llm_pool):
        logger.warning(f"⚠️ 当前模型索引越界，已自动重置：idx={_cur_idx}, pool_size={len(_llm_pool)}")
        _cur_idx = 0
        CONFIG["CURRENT_MODEL_INDEX"] = 0
    cur_model = _llm_pool[_cur_idx].get("name", "N/A") if _llm_pool else "N/A"
    reply_chance = CONFIG.get("REPLY_CHANCE", 10)
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
        bot.infinity_polling(timeout=60, long_polling_timeout=30,
                             allowed_updates=["message", "chat_member", "my_chat_member"])
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


if __name__ == "__main__":
    main()
