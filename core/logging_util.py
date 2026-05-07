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
        # 检查是否在后台运行（通过 nohup 或其他重定向）
        # 如果标准输出被重定向到文件，则不添加控制台处理器，避免重复日志
        if not sys.stdout.isatty():
            # 非终端环境（如 nohup 后台运行），不添加控制台处理器
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

def log_execution(logger_name: str = 'main', level: int = logging.DEBUG):
    """
    记录函数执行的装饰器（输入/输出/耗时）
    
    Usage:
        @log_execution('module_name')
        def some_function(arg):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            if logger.isEnabledFor(level):
                # 记录输入（敏感信息需过滤）
                logger.log(
                    level,
                    f"Enter {func.__module__}.{func.__name__} "
                    f"args={args} kwargs={kwargs}"
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

# time模块已在文件顶部导入

__all__ = [
    'configure_logging',
    'get_logger',
    'get_logging_context',
    'set_logging_context',
    'clear_logging_context',
    'exception_handler',
    'log_execution',
]