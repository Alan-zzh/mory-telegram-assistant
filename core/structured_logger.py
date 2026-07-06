"""
结构化日志模块（structlog 封装）

提供：
1. JSON 格式结构化日志输出到 stdout
2. 自动注入 timestamp / level / logger_name
3. 支持绑定上下文（request_id / user_id / chat_id / bot_id）
4. 开发环境自动彩色输出（isatty 检测）
5. 与现有 logging_util.py 完全兼容（不修改原模块）

Usage:
    from core.structured_logger import get_struct_logger, init_structlog

    # 启动时初始化一次
    init_structlog()

    # 业务代码中使用
    logger = get_struct_logger("my_module")
    logger = logger.bind(request_id="abc-123", user_id=42)
    logger.info("user_action", action="send_message", chat_id=12345)
"""

import logging
import sys
import structlog
from typing import Optional

# 全局初始化标记
_initialized = False


def init_structlog(
    json_output: bool = True,
    log_level: int = logging.INFO,
) -> None:
    """
    初始化 structlog 全局配置

    Args:
        json_output: True 输出 JSON，False 输出彩色文本（开发环境）
        log_level: 根日志级别
    """
    global _initialized
    if _initialized:
        return

    # 自动检测终端：isatty 时且非强制 JSON 则用彩色输出
    use_console = sys.stdout.isatty() and not json_output

    # 共享处理器链：注入上下文 + 时间戳 + 日志级别 + logger 名称
    shared_processors = [
        structlog.contextvars.merge_contextvars,  # 合并 contextvars 中的绑定字段
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),  # ISO 8601 时间戳
    ]

    if use_console:
        # 开发环境：彩色人类可读格式
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=26,
        )
    else:
        # 生产环境：JSON 格式（便于日志采集器解析）
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准 logging 的 Formatter，让 structlog 接管输出
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # 替换根 logger 的 handler 格式器（不破坏现有 handler 配置）
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 为所有现有 handler 替换 formatter
    for handler in root_logger.handlers[:]:
        handler.setFormatter(formatter)

    # 如果没有 handler，添加一个 stdout handler
    if not root_logger.handlers:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    _initialized = True


def bind_context(
    request_id: Optional[str] = None,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    **extra,
) -> None:
    """
    绑定上下文到当前协程/线程（structlog contextvars）

    绑定后该线程/协程内所有 structlog 日志自动携带这些字段。

    Args:
        request_id: 请求唯一 ID
        user_id: 用户 ID
        chat_id: 聊天 ID
        bot_id: Bot ID
        **extra: 其他自定义字段
    """
    ctx = {}
    if request_id is not None:
        ctx["request_id"] = request_id
    if user_id is not None:
        ctx["user_id"] = user_id
    if chat_id is not None:
        ctx["chat_id"] = chat_id
    if bot_id is not None:
        ctx["bot_id"] = bot_id
    ctx.update(extra)
    structlog.contextvars.bind_contextvars(**ctx)


__all__ = [
    "init_structlog",
    "bind_context",
]
