# -*- coding: utf-8 -*-
"""
Universal AI Router - 核心模块

功能：
    - 配置管理 (ConfigManager)
    - API适配层 (各种Adapter)
    - 账号管理 (AccountManager)
    - 智能路由 (Router)
    - 统一AI接口 (UniversalAI)
    - 数据库 (RouterDatabase)
    - 统计报表 (RouterStatistics)
"""

__version__ = "1.0.0"
__author__ = "Mory Team"

# 配置管理器
from .config_manager import ConfigManager, get_config_manager

# API适配器
from .api_adapter import (
    BaseAdapter,
    TongyiAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    GeminiAdapter,
    AdapterFactory,
    UnifiedResponse,
    create_unified_response,
    calculate_cost
)

# 账号管理器
from .account_manager import AccountManager, get_account_manager

# 智能路由
from .router import Router, TaskType, CostStrategy, get_router

# 统一AI接口
from .uni_ai import UniversalAI, get_universal_ai

# 数据库
from .router_database import RouterDatabase, get_router_database

# 统计报表
from .router_statistics import RouterStatistics, get_router_statistics