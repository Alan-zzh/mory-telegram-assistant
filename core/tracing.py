"""
core/tracing.py  ·  OpenTelemetry 分布式追踪模块

提供端到端追踪能力，用于观测消息处理链路：
Webhook → 分发 → 广告检测 → AI → 回复

特性：
- 默认关闭（TRACING_ENABLED=false）
- 采样率可配置（默认 10%）
- 日志导出器（JSON 格式输出）
- 提供 get_tracer() 和 @traced 装饰器

资源约束：2C4G VPS，轻量级追踪
"""

import os
import json
import logging
from functools import wraps
from typing import Optional, Callable, Any
from datetime import datetime, timezone

# 全局追踪器提供者
_tracer_provider = None
_tracer = None
_is_initialized = False

logger = logging.getLogger("tracing")


class JSONLogRecordExporter:
    """JSON 日志导出器 - 将 Span 导出为 JSON 格式日志
    
    适用于资源受限环境，无需外部追踪系统（如 Jaeger）
    输出到标准日志系统，可通过日志收集工具聚合
    """
    
    def __init__(self, service_name: str = "mory_assistant"):
        self.service_name = service_name
        self._logger = logging.getLogger("otel.traces")
    
    def export(self, spans) -> bool:
        """导出 span 批次为 JSON 日志"""
        for span in spans:
            try:
                # 构建 span 数据
                span_data = {
                    "timestamp": datetime.fromtimestamp(
                        span.start_time / 1e9, tz=timezone.utc
                    ).isoformat() if span.start_time else None,
                    "end_timestamp": datetime.fromtimestamp(
                        span.end_time / 1e9, tz=timezone.utc
                    ).isoformat() if span.end_time else None,
                    "trace_id": format(span.context.trace_id, '032x'),
                    "span_id": format(span.context.span_id, '016x'),
                    "parent_span_id": format(span.parent.span_id, '016x') if span.parent else None,
                    "service": self.service_name,
                    "operation": span.name,
                    "duration_ms": round((span.end_time - span.start_time) / 1e6, 2) if span.end_time and span.start_time else None,
                    "status": span.status.status_code.name if span.status else "UNSET",
                    "attributes": dict(span.attributes) if span.attributes else {},
                    "events": [
                        {
                            "name": event.name,
                            "timestamp": datetime.fromtimestamp(
                                event.timestamp / 1e9, tz=timezone.utc
                            ).isoformat(),
                            "attributes": dict(event.attributes) if event.attributes else {}
                        }
                        for event in span.events
                    ]
                }
                # 输出为 JSON 日志
                self._logger.info(json.dumps(span_data, ensure_ascii=False))
            except Exception as e:
                logger.debug(f"Span 导出失败: {e}")
        return True
    
    def shutdown(self):
        """关闭导出器"""
        pass
    
    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """强制刷新"""
        return True


def init_tracing(config: dict) -> bool:
    """初始化 OpenTelemetry 追踪
    
    Args:
        config: 配置字典，包含以下键：
            - TRACING_ENABLED: 是否启用追踪（默认 False）
            - TRACING_SAMPLE_RATE: 采样率（默认 0.1，即 10%）
            - TRACING_SERVICE_NAME: 服务名称（默认 "mory_assistant"）
    
    Returns:
        bool: 是否成功初始化
    """
    global _tracer_provider, _tracer, _is_initialized
    
    # 检查是否启用
    if not config.get("TRACING_ENABLED", False):
        logger.debug("追踪功能未启用（TRACING_ENABLED=false）")
        return False
    
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor
        
        # 配置参数
        sample_rate = float(config.get("TRACING_SAMPLE_RATE", 0.1))
        service_name = config.get("TRACING_SERVICE_NAME", "mory_assistant")
        batch_mode = config.get("TRACING_BATCH_MODE", True)  # 批量模式减少开销
        
        # 创建 TracerProvider（带采样）
        sampler = TraceIdRatioBased(sample_rate)
        _tracer_provider = TracerProvider(sampler=sampler)
        
        # 添加资源属性
        from opentelemetry.sdk.resources import Resource
        resource = Resource.create({
            "service.name": service_name,
            "service.version": config.get("_CONFIG_VERSION", "unknown"),
            "deployment.environment": config.get("ENVIRONMENT", "production")
        })
        _tracer_provider.resource = resource
        
        # 配置导出器（JSON 日志）
        exporter = JSONLogRecordExporter(service_name=service_name)
        
        # 选择处理器：批量模式减少 VPS 开销
        if batch_mode:
            processor = BatchSpanProcessor(
                exporter,
                max_queue_size=2048,
                schedule_delay_millis=5000,
                max_export_batch_size=512
            )
        else:
            processor = SimpleSpanProcessor(exporter)
        
        _tracer_provider.add_span_processor(processor)
        
        # 设置为全局追踪器提供者
        trace.set_tracer_provider(_tracer_provider)
        
        # 创建追踪器
        _tracer = trace.get_tracer(__name__)
        
        _is_initialized = True
        logger.info(f"✅ OpenTelemetry 追踪已启用：采样率={sample_rate*100}%, 服务={service_name}")
        return True
        
    except ImportError as e:
        logger.warning(f"OpenTelemetry 依赖未安装，追踪功能禁用: {e}")
        return False
    except Exception as e:
        logger.error(f"OpenTelemetry 初始化失败: {e}")
        return False


def shutdown_tracing():
    """关闭追踪系统，刷新所有待处理的 span"""
    global _tracer_provider, _is_initialized
    
    if not _is_initialized or _tracer_provider is None:
        return
    
    try:
        _tracer_provider.shutdown()
        logger.info("✅ OpenTelemetry 追踪已关闭")
    except Exception as e:
        logger.debug(f"追踪关闭异常: {e}")
    finally:
        _is_initialized = False


def get_tracer(name: Optional[str] = None):
    """获取追踪器
    
    Args:
        name: 追踪器名称（默认使用模块名）
    
    Returns:
        Tracer 对象，如果未初始化则返回 NoOpTracer
    """
    if not _is_initialized:
        # 返回 NoOp 追踪器，避免业务代码需要判断
        from opentelemetry.trace import NoOpTracer
        return NoOpTracer()
    
    from opentelemetry import trace
    return trace.get_tracer(name or __name__)


def traced(operation_name: Optional[str] = None, attributes: Optional[dict] = None):
    """追踪装饰器 - 自动创建 Span
    
    用法：
        @traced("process_message")
        def process_message(msg):
            ...
        
        @traced()  # 使用函数名作为 operation_name
        def handle_request():
            ...
    
    Args:
        operation_name: 操作名称（默认使用函数名）
        attributes: 附加属性字典
    
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        op_name = operation_name or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 未初始化时直接执行，不追踪
            if not _is_initialized:
                return func(*args, **kwargs)
            
            tracer = get_tracer(func.__module__)
            
            with tracer.start_as_current_span(op_name) as span:
                # 添加自定义属性
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                # 添加函数参数信息（可选，敏感信息需过滤）
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("function.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("function.success", False)
                    span.set_attribute("function.error", str(e))
                    span.record_exception(e)
                    raise
        
        return wrapper
    
    return decorator


def start_span(name: str, attributes: Optional[dict] = None):
    """手动创建 Span（上下文管理器）
    
    用法：
        with start_span("ad_detection", {"user_id": uid}) as span:
            # 业务逻辑
            span.set_attribute("result", "blocked")
    
    Args:
        name: Span 名称
        attributes: 初始属性
    
    Returns:
        Span 上下文管理器
    """
    if not _is_initialized:
        # 返回空上下文管理器
        from contextlib import nullcontext
        return nullcontext()
    
    tracer = get_tracer()
    span = tracer.start_span(name)
    
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)
    
    from opentelemetry import trace
    return trace.use_span(span, end_on_exit=True)


def is_tracing_enabled() -> bool:
    """检查追踪是否已启用"""
    return _is_initialized


def get_current_span():
    """获取当前活动的 Span"""
    if not _is_initialized:
        return None
    
    from opentelemetry import trace
    return trace.get_current_span()


def add_span_event(name: str, attributes: Optional[dict] = None):
    """向当前 Span 添加事件
    
    Args:
        name: 事件名称
        attributes: 事件属性
    """
    span = get_current_span()
    if span and _is_initialized:
        span.add_event(name, attributes=attributes)
