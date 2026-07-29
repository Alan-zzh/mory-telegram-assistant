# -*- coding: utf-8 -*-
"""
统一配置访问层（薄包装）

真相源：core.bot_initializer.load_config()（读取 config.json + 环境变量覆盖）
本模块：提供向后兼容的访问入口，不独立加载配置，避免双系统分裂。

使用方式：
    from core.settings import get_config, get_config_value

    # 获取完整配置字典（委托给 bot_initializer.load_config）
    config = get_config()

    # 获取单个配置值
    value = get_config_value("KEY", default)
"""

from typing import Any


def get_config() -> dict[str, Any]:
    """获取配置字典（委托给 bot_initializer.load_config，单一真相源）

    Returns:
        dict: 配置字典，包含 config.json + 环境变量覆盖
    """
    from core.bot_initializer import load_config
    return load_config()


def get_config_value(key: str, default: Any = None) -> Any:
    """获取单个配置值（委托给 bot_initializer.load_config）

    Args:
        key: 配置键名
        default: 键不存在时的默认返回值

    Returns:
        配置值，或 default
    """
    return get_config().get(key, default)


__all__ = [
    "get_config",
    "get_config_value",
]
