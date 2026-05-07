# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：智能路由核心
"""
智能路由核心 - 根据输入类型和任务类型自动选择最合适的模型
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Union

from .config_manager import get_config_manager

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """任务类型枚举"""
    TEXT = "text"           # 文字任务
    IMAGE = "image"         # 图像任务
    AUDIO = "audio"         # 音频任务
    VIDEO = "video"         # 视频任务
    EMBEDDING = "embedding" # 向量任务


class CostStrategy(Enum):
    """成本策略枚举"""
    PERFORMANCE = "performance"  # 性能优先
    COST = "cost"                # 成本优先
    BALANCED = "balanced"        # 平衡策略


class RouterConfig:
    """路由配置类"""

    def __init__(self, cost_strategy: str = "cost", enable_fallback: bool = True,
                 max_cost_per_request: float = 1.0):
        """
        初始化路由配置
        :param cost_strategy: 成本策略（performance/cost/balanced）
        :param enable_fallback: 是否启用降级
        :param max_cost_per_request: 单次请求最大成本
        """
        self.cost_strategy = CostStrategy(cost_strategy) if isinstance(cost_strategy, str) else cost_strategy
        self.enable_fallback = enable_fallback
        self.max_cost_per_request = max_cost_per_request

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RouterConfig":
        """从配置字典创建RouterConfig"""
        strategy = config.get("default_strategy", "cost")
        enable_fallback = config.get("enable_fallback", True)
        max_cost = config.get("max_cost_per_request", 1.0)
        return cls(cost_strategy=strategy, enable_fallback=enable_fallback, max_cost_per_request=max_cost)


class Router:
    """智能路由类"""

    # 任务类型到模型池的映射
    TASK_POOL_MAPPING = {
        TaskType.TEXT: "llm",
        TaskType.IMAGE: "vision",
        TaskType.AUDIO: "voice_asr",
        TaskType.VIDEO: "vision",
        TaskType.EMBEDDING: "embedding",
    }

    # 图片格式魔数特征
    IMAGE_MAGIC_NUMBERS = {
        b"\xff\xd8\xff": "jpeg",
        b"\x89PNG\r\n\x1a\n": "png",
        b"GIF87a": "gif",
        b"GIF89a": "gif",
        b"RIFF": "webp",
        b"BM": "bmp",
    }

    # 音视频格式魔数
    AUDIO_MAGIC_NUMBERS = {
        b"ID3": "mp3",
        b"\xff\xfb": "mp3",
        b"\xff\xfa": "mp3",
        b"RIFF": "wav",
        b"OggS": "ogg",
        b"fLaC": "flac",
    }

    VIDEO_MAGIC_NUMBERS = {
        b"\x00\x00\x00": "mp4",  # 多种视频格式
        b"RIFF": "avi",
        b"FLV": "flv",
    }

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化路由实例
        :param config_path: 配置文件路径
        """
        self.config_manager = get_config_manager(config_path)
        self.config_manager.load_config()
        self.config_manager.validate_config()

        # 加载全局配置
        global_config = self.config_manager.get_global_config()
        self.router_config = RouterConfig.from_config(global_config)

        # 初始化模型池
        self.model_pools = self.config_manager.get_model_pools()

        # 当前策略（可临时覆盖）
        self._current_strategy_override: Optional[CostStrategy] = None

        logger.info(f"Router初始化完成，策略: {self.router_config.cost_strategy.value}, "
                    f"降级: {self.router_config.enable_fallback}")

    @property
    def current_strategy(self) -> CostStrategy:
        """获取当前策略（支持临时覆盖）"""
        if self._current_strategy_override is not None:
            return self._current_strategy_override
        return self.router_config.cost_strategy

    def set_strategy(self, strategy: Union[str, CostStrategy], temporary: bool = False) -> None:
        """
        设置成本策略
        :param strategy: 策略名称或枚举
        :param temporary: 是否临时生效（仅本次请求）
        """
        if isinstance(strategy, str):
            strategy = CostStrategy(strategy)

        if temporary:
            self._current_strategy_override = strategy
            logger.info(f"临时策略切换: {strategy.value}")
        else:
            self.router_config.cost_strategy = strategy
            logger.info(f"持久策略切换: {strategy.value}")

    def reset_strategy(self) -> None:
        """重置策略覆盖，恢复配置文件中的默认策略"""
        self._current_strategy_override = None
        logger.info("策略覆盖已重置")

    def detect_input_type(self, input_data: Any) -> TaskType:
        """
        检测输入数据类型
        :param input_data: 输入数据（str/bytes/其他）
        :return: 任务类型
        """
        if isinstance(input_data, str):
            return TaskType.TEXT

        if isinstance(input_data, bytes):
            return self._detect_binary_type(input_data)

        # 默认按文字处理
        logger.warning(f"未知输入类型 {type(input_data)}，默认按文字处理")
        return TaskType.TEXT

    def _detect_binary_type(self, data: bytes) -> TaskType:
        """检测二进制数据类型"""
        if len(data) < 8:
            return TaskType.TEXT

        # 检查图片格式
        for magic, fmt in self.IMAGE_MAGIC_NUMBERS.items():
            if data.startswith(magic):
                logger.info(f"检测到图片格式: {fmt}")
                return TaskType.IMAGE

        # 检查音频格式
        for magic, fmt in self.AUDIO_MAGIC_NUMBERS.items():
            if data.startswith(magic):
                logger.info(f"检测到音频格式: {fmt}")
                return TaskType.AUDIO

        # 检查视频格式
        for magic, fmt in self.VIDEO_MAGIC_NUMBERS.items():
            if data.startswith(magic):
                logger.info(f"检测到视频格式: {fmt}")
                return TaskType.VIDEO

        # 数据大小判断（大于10MB视为视频）
        if len(data) > 10 * 1024 * 1024:
            logger.info("数据大小超过10MB，判定为视频")
            return TaskType.VIDEO

        # 无法识别，默认按图片处理
        logger.warning("无法识别二进制数据类型，默认按图片处理")
        return TaskType.IMAGE

    def route(self, input_data: Any, task_type: Optional[TaskType] = None,
              strategy_override: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        主路由方法
        :param input_data: 输入数据
        :param task_type: 指定任务类型（可选，自动检测）
        :param strategy_override: 策略覆盖（可选）
        :return: 排序后的模型列表
        """
        # 策略覆盖
        if strategy_override:
            self.set_strategy(strategy_override, temporary=True)

        try:
            # 自动检测或使用指定的类型
            if task_type is None:
                task_type = self.detect_input_type(input_data)

            logger.info(f"路由决策: 输入类型={type(input_data).__name__}, 任务类型={task_type.value}")

            # 获取任务对应的模型池
            models = self.get_models_by_task(task_type)
            if not models:
                logger.warning(f"模型池为空，尝试降级: {task_type.value}")
                return self.fallback(task_type)

            # 应用成本策略排序
            sorted_models = self.apply_cost_strategy(models)

            logger.info(f"路由完成，候选模型数: {len(sorted_models)}")
            return sorted_models

        finally:
            # 重置临时策略覆盖
            if strategy_override:
                self.reset_strategy()

    def select_model(self, task_type: TaskType) -> Optional[Dict[str, Any]]:
        """
        根据任务类型选择单个最优模型
        :param task_type: 任务类型
        :return: 最优模型配置
        """
        models = self.get_models_by_task(task_type)
        if not models:
            if self.router_config.enable_fallback:
                models = self.fallback(task_type)
                if not models:
                    return None
            else:
                return None

        sorted_models = self.apply_cost_strategy(models)
        return sorted_models[0] if sorted_models else None

    def get_models_by_task(self, task_type: TaskType) -> List[Dict[str, Any]]:
        """
        获取任务对应的模型池
        :param task_type: 任务类型
        :return: 模型列表
        """
        pool_name = self.TASK_POOL_MAPPING.get(task_type)
        if not pool_name:
            logger.error(f"未配置任务类型映射: {task_type.value}")
            return []

        models = self.config_manager.get_models_by_pool(pool_name)
        if not models:
            logger.warning(f"模型池为空: {pool_name}")

        return models

    def apply_cost_strategy(self, models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        应用成本策略排序
        :param models: 模型列表
        :return: 排序后的模型列表
        """
        strategy = self.current_strategy

        if strategy == CostStrategy.PERFORMANCE:
            return self.sort_models_by_strategy(models, "performance")
        elif strategy == CostStrategy.COST:
            return self.sort_models_by_strategy(models, "cost")
        else:  # BALANCED
            return self.sort_models_by_strategy(models, "balanced")

    def sort_models_by_strategy(self, models: List[Dict[str, Any]],
                                  strategy: str) -> List[Dict[str, Any]]:
        """
        按策略排序模型
        :param models: 模型列表
        :param strategy: 策略名称
        :return: 排序后的模型列表
        """
        if strategy == "performance":
            # 性能优先：high > medium > low
            priority = {"high": 0, "medium": 1, "low": 2}
            return sorted(models, key=lambda m: priority.get(m.get("cost_level", "medium"), 1))

        elif strategy == "cost":
            # 成本优先：按input_price排序（升序）
            return sorted(models, key=lambda m: m.get("input_price", 0))

        else:  # balanced
            # 平衡策略：综合成本和性能
            def balanced_score(m: Dict[str, Any]) -> float:
                cost_level = m.get("cost_level", "medium")
                input_price = m.get("input_price", 0)

                # 性能分数（越高越好）
                perf_score = {"high": 3, "medium": 2, "low": 1}.get(cost_level, 2)
                # 成本分数（越低越好，取反）
                cost_score = 1 / (input_price + 0.000001)

                # 综合分数 = 0.4*性能 + 0.6*成本
                return 0.4 * perf_score + 0.6 * cost_score

            return sorted(models, key=balanced_score, reverse=True)

    def fallback(self, task_type: TaskType) -> List[Dict[str, Any]]:
        """
        降级处理：当主模型池不可用时的降级方案
        :param task_type: 任务类型
        :return: 降级后的模型列表
        """
        if not self.router_config.enable_fallback:
            logger.warning("降级已禁用")
            return []

        logger.info(f"执行降级策略，任务类型: {task_type.value}")

        # 不同任务的降级路径
        fallback_paths = {
            TaskType.TEXT: ["llm", "omni"],
            TaskType.IMAGE: ["vision", "llm"],
            TaskType.AUDIO: ["voice_asr", "llm"],
            TaskType.VIDEO: ["vision", "llm"],
            TaskType.EMBEDDING: ["embedding", "llm"],
        }

        pool_names = fallback_paths.get(task_type, ["llm"])

        for pool_name in pool_names:
            models = self.config_manager.get_models_by_pool(pool_name)
            if models:
                logger.info(f"降级到模型池: {pool_name}, 模型数: {len(models)}")
                return models

        logger.error("所有降级方案均失败")
        return []


# 全局路由器单例
_router_instance: Optional[Router] = None


def get_router(config_path: Optional[str] = None) -> Router:
    """
    获取路由器单例
    :param config_path: 配置文件路径（仅首次生效）
    :return: Router实例
    """
    global _router_instance
    if _router_instance is None:
        _router_instance = Router(config_path)
    return _router_instance


def reset_router() -> None:
    """重置路由器单例（用于测试或重新加载配置）"""
    global _router_instance
    _router_instance = None
    logger.info("路由器单例已重置")