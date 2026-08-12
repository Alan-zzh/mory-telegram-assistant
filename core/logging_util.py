"""
标准化日志与错误处理工具

提供：
1. 增强的日志配置（JSON格式可选）
2. 上下文感知的LoggerAdapter
3. 异常处理装饰器，自动捕获并记录异常
4. 结构化错误日志记录
"""

import logging
import json
import sys
import time  # 【v4.3.2修复M-08】补充import time（log_execution需要）
import os
import traceback
from threading import local
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, Union

# 线程本地存储，用于保存当前请求的上下文
_thread_local = local()

def get_logging_context() -> Dict[str, Any]:
    """获取当前线程的日志上下文"""
    return getattr(_thread_local, 'context', {})

def set_logging_context(**kwargs):
    """设置当前线程的日志上下文"""
    context = getattr(_thread_local, 'context', {})
    context.update(kwargs)
    _thread_local.context = context

def clear_logging_context():
    """清除当前线程的日志上下文"""
    if hasattr(_thread_local, 'context'):
        delattr(_thread_local, 'context')

def bind_context(
    request_id: Optional[str] = None,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    **extra,
) -> None:
    """绑定上下文到当前线程（统一入口，替代 structured_logger.bind_context）

    绑定后该线程内所有 ContextLogger 日志自动携带这些字段。

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
    set_logging_context(**ctx)

class ContextLogger(logging.LoggerAdapter):
    """自动注入上下文的LoggerAdapter"""

    def process(self, msg, kwargs):
        # 获取当前上下文
        context = get_logging_context()
        if context:
            # 将上下文作为extra传递，供格式化器使用
            extra = kwargs.get('extra', {})
            extra.update(context)
            kwargs['extra'] = extra
            # 在消息末尾添加上下文摘要（便于阅读）
            ctx_str = ' '.join(f'{k}={v}' for k, v in context.items() if v)
            if ctx_str:
                msg = f"{msg} [{ctx_str}]"
        return msg, kwargs

def get_logger(name: str) -> ContextLogger:
    """获取带有上下文支持的logger"""
    logger = logging.getLogger(name)
    return ContextLogger(logger, {})

class JsonFormatter(logging.Formatter):
    """JSON格式的日志格式化器"""

    def format(self, record):
        log_record = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        # 添加额外字段
        if hasattr(record, 'extra'):
            log_record.update(record.extra)
        # 异常信息
        if record.exc_info:
            log_record['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': self.formatException(record.exc_info),
            }
        return json.dumps(log_record, ensure_ascii=False)

def configure_logging(
    level: Union[int, str] = logging.INFO,
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    json_format: bool = False,
    console_output: bool = True,
):
    """
    配置日志系统

    Args:
        level: 日志级别
        log_file: 日志文件路径，None则不输出到文件
        max_bytes: 单个日志文件最大大小
        backup_count: 备份文件数量
        json_format: 是否使用JSON格式
        console_output: 是否输出到控制台
    """
    # 清除现有handler（避免重复）
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # 设置级别
    root_logger.setLevel(level)

    # 创建格式化器
    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        )

    # 文件处理器
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 控制台处理器
    if console_output:
        # 【v5.31.2 修复】systemd 环境下强制输出到 stdout，让 journalctl 能捕获日志
        # 之前仅在 tty 时输出，导致 systemd 服务运行时 journalctl 完全无 Python 日志，
        # 服务挂死等问题无法从 journalctl 排查。
        # systemd 环境检测：INVOCATION_ID 是 systemd 给每个服务实例分配的唯一 ID
        is_systemd = bool(os.environ.get("INVOCATION_ID"))
        if is_systemd:
            # systemd 环境：强制输出 stdout，由 journalctl 捕获
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
        elif not sys.stdout.isatty():
            # 非 systemd 的非终端环境（如 nohup 后台运行），不添加控制台处理器，避免重复日志
            pass
        else:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

    # 屏蔽无关日志
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('telebot').setLevel(logging.WARNING)

def exception_handler(logger_name: str = 'main'):
    """
    异常处理装饰器：自动捕获异常，记录日志，并可选择重新抛出或返回默认值

    Usage:
        @exception_handler('module_name')
        def risky_function():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 记录异常详情
                exc_info = sys.exc_info()
                logger.error(
                    f"Unhandled exception in {func.__module__}.{func.__name__}: {str(e)}",
                    exc_info=exc_info,
                )
                # 重新抛出异常，保持原有行为
                raise
        return wrapper
    return decorator

def _filter_sensitive(kwargs: dict) -> dict:
    """过滤 kwargs 中的敏感参数（密码/密钥/令牌等），避免泄露到日志"""
    SENSITIVE_KEYS = {'password', 'passwd', 'secret', 'token', 'api_key', 'api_key_secret',
                      'access_token', 'refresh_token', 'private_key', 'key', 'auth'}
    return {k: ('******' if any(s in k.lower() for s in SENSITIVE_KEYS) else v)
            for k, v in kwargs.items()}


def log_execution(logger_name: str = 'main', level: int = logging.DEBUG,
                  sensitive_params: tuple = None):
    """
    记录函数执行的装饰器（输入/输出/耗时）

    Usage:
        @log_execution('module_name')
        def some_function(arg):
            ...

        @log_execution('api', sensitive_params=('password', 'token'))
        def login(user, password, token):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            if logger.isEnabledFor(level):
                # 记录输入（敏感信息需过滤）
                filtered_kwargs = _filter_sensitive(kwargs)
                if sensitive_params:
                    # 额外过滤用户指定的敏感参数名（位置参数按名过滤）
                    filtered_kwargs.update({
                        k: '******' for k in filtered_kwargs
                        if k in sensitive_params
                    })
                logger.log(
                    level,
                    f"Enter {func.__module__}.{func.__name__} "
                    f"args={args} kwargs={filtered_kwargs}"
                )
                start_time = time.time() if level <= logging.DEBUG else None
            try:
                result = func(*args, **kwargs)
                if logger.isEnabledFor(level) and start_time:
                    elapsed = time.time() - start_time
                    logger.log(
                        level,
                        f"Exit {func.__module__}.{func.__name__} "
                        f"result={result} elapsed={elapsed:.3f}s"
                    )
                return result
            except Exception:
                if logger.isEnabledFor(level) and start_time:
                    elapsed = time.time() - start_time
                    logger.log(
                        level,
                        f"Exception in {func.__module__}.{func.__name__} "
                        f"elapsed={elapsed:.3f}s",
                        exc_info=True,
                    )
                raise
        return wrapper
    return decorator

def cleanup_old_logs(log_dir: str, retention_days: int = 30) -> int:
    """
    清理超过指定天数的日志文件

    Args:
        log_dir: 日志目录路径
        retention_days: 保留天数，默认30天

    Returns:
        删除的文件数量
    """
    if not os.path.exists(log_dir):
        return 0

    cutoff_time = time.time() - (retention_days * 86400)
    removed_count = 0
    cleanup_logger = get_logger("logging_cleanup")

    try:
        for filename in os.listdir(log_dir):
            if not filename.endswith('.log'):
                continue

            filepath = os.path.join(log_dir, filename)
            if not os.path.isfile(filepath):
                continue

            try:
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    removed_count += 1
            except Exception as e:
                # 单个文件删除失败不影响其他文件
                cleanup_logger.debug(f"日志文件删除失败: {filepath} - {e}")

    except Exception as e:
        # 目录读取失败
        cleanup_logger.debug(f"日志目录读取失败: {log_dir} - {e}")

    return removed_count


# time模块已在文件顶部导入

__all__ = [
    'configure_logging',
    'get_logger',
    'get_logging_context',
    'set_logging_context',
    'clear_logging_context',
    'bind_context',
    'exception_handler',
    'log_execution',
    'cleanup_old_logs',
]
