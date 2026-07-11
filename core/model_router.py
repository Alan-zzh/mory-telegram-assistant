"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/model_router.py  ·  多模型协同路由网关（阶段3-A）                 ║
║                                                                        ║
║  功能：                                                                ║
║    1. 三层模型池定义（与 AGENTS.md 第4章对齐）：                       ║
║       - llm_premium：高端模型（Qwen-Max / GPT-4o），角色扮演对话       ║
║       - llm_standard：标准模型（DeepSeek-V3 / Qwen-Plus），审核/广告   ║
║       - llm_light：廉价模型（Qwen-Flash / DeepSeek-V3-lite），摘要     ║
║    2. route_model(task_type) → (api_url, api_key_env, model_name)      ║
║    3. 配置覆盖：MODEL_ROUTER_OVERRIDE 手动覆盖任务类型映射             ║
║    4. 故障转移：某层 API Key 未配置时降级到下一层                      ║
║           premium → standard → light                                   ║
║                                                                        ║
║  与 ai_engine.py 现有三层路由的关系：                                  ║
║    - ai_engine._tier_pools：同一 DashScope API 下，按 mode 切模型名    ║
║    - model_router：按 task_type 切换 API URL + API Key + 模型名        ║
║      （支持不同厂商：Qwen / DeepSeek / GPT / Gemini）                  ║
║    - MODEL_ROUTER_ENABLED=False 时，ai_engine 走原逻辑（向后兼容）     ║
║                                                                        ║
║  依赖：os, logging                                                     ║
║  配置：config.json → MODEL_ROUTER_ENABLED / MODEL_POOL_* / OVERRIDE    ║
║  被调用：core/ai_engine.py:ask()                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import logging
from typing import Optional, Tuple

from core.logging_util import get_logger

logger = get_logger("model_router")


# ── 三层模型池默认配置 ──────────────────────────────────────────────
# 每层包含：默认模型名、默认 API URL、对应的 .env 变量名
# 实际值优先从 config.json 读取（MODEL_POOL_PREMIUM/STANDARD/LIGHT），其次用默认值

_DEFAULT_TIER_CONFIG = {
    "llm_premium": {
        "model_name": "qwen3.6-flash-2026-04-16",
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "api_key_env": "PREMIUM_MODEL_API_KEY",
    },
    "llm_standard": {
        "model_name": "qwen3.6-flash-2026-04-16",
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "api_key_env": "STANDARD_MODEL_API_KEY",
    },
    "llm_light": {
        "model_name": "qwen3.6-flash-2026-04-16",
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "api_key_env": "LIGHT_MODEL_API_KEY",
    },
}


# ── 任务类型 → 模型池层级 映射 ──────────────────────────────────────
# 任务类型按职责分流，与 AGENTS.md 第4章三层模型池定义对齐
_DEFAULT_TASK_TYPE_MAP = {
    # 角色扮演对话类 → 高端池
    "chat": "llm_premium",
    "tarot": "llm_premium",
    "fortune": "llm_premium",
    "persona": "llm_premium",
    # 内容审核 / 广告检测类 → 标准池
    "moderate": "llm_standard",
    "ad_detect": "llm_standard",
    "guard": "llm_standard",
    # 记忆摘要 / 简单分类类 → 廉价池
    "summarize": "llm_light",
    "classify": "llm_light",
    "extract": "llm_light",
}


# ── 故障转移链：某层不可用时降级到下一层 ────────────────────────────
_TIER_FALLBACK_CHAIN = {
    "llm_premium": ["llm_standard", "llm_light"],
    "llm_standard": ["llm_light"],
    "llm_light": [],  # 廉价池是兜底，无降级
}


class ModelRouter:
    """
    多模型协同路由网关。

    按 task_type 将请求路由到对应层级的模型池，支持：
    - 配置覆盖：config['MODEL_ROUTER_OVERRIDE'] = {"summarize": "llm_standard"}
    - 故障转移：某层 API Key 未配置时降级到下一层（premium→standard→light）
    - 向后兼容：MODEL_ROUTER_ENABLED=False 时完全不启用
    """

    def __init__(self, config: dict):
        self.config = config or {}
        # 用户自定义覆盖（task_type → tier），允许手动指定某些任务走不同层级
        self.override = self.config.get("MODEL_ROUTER_OVERRIDE", {}) or {}
        # 各层模型配置（从 config 读取，缺省用默认值）
        # config 键名：MODEL_POOL_PREMIUM / MODEL_POOL_STANDARD / MODEL_POOL_LIGHT
        self.tier_config = {}
        for tier, default in _DEFAULT_TIER_CONFIG.items():
            # 从 tier 名提取后缀：llm_premium → PREMIUM
            suffix = tier.split("_", 1)[1].upper()
            config_key = f"MODEL_POOL_{suffix}"
            model_name = self.config.get(config_key, default["model_name"])
            self.tier_config[tier] = {
                "model_name": model_name,
                "api_url": default["api_url"],
                "api_key_env": default["api_key_env"],
            }

    def _resolve_tier(self, task_type: str) -> str:
        """根据 task_type 解析出对应的层级（含覆盖逻辑）"""
        # 1. 优先使用用户覆盖
        if task_type in self.override:
            tier = self.override[task_type]
            if tier in _DEFAULT_TIER_CONFIG:
                return tier
            logger.warning(f"⚠️ MODEL_ROUTER_OVERRIDE[{task_type}]={tier} 不是合法层级，忽略")
        # 2. 查默认映射表
        tier = _DEFAULT_TASK_TYPE_MAP.get(task_type)
        if tier:
            return tier
        # 3. 未知 task_type 兜底到 standard
        logger.warning(f"⚠️ 未知 task_type='{task_type}'，默认路由到 llm_standard")
        return "llm_standard"

    def _tier_available(self, tier: str) -> bool:
        """检查某层是否可用（API Key 已在环境变量中配置）"""
        cfg = self.tier_config.get(tier)
        if not cfg:
            return False
        api_key = os.environ.get(cfg["api_key_env"], "").strip()
        return bool(api_key)

    def route_model(self, task_type: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        根据任务类型路由到对应模型。

        Args:
            task_type: 任务类型，如 "chat"/"moderate"/"summarize" 等

        Returns:
            (api_url, api_key_env, model_name) 三元组：
            - api_url:    该层模型的 API 端点 URL
            - api_key_env: 持有 API Key 的环境变量名（调用方自行 os.environ.get 解析）
            - model_name: 模型名

            故障转移：若目标层 API Key 未配置，按 premium→standard→light 降级。
            所有层均不可用时返回 (None, None, None)。
        """
        target_tier = self._resolve_tier(task_type)

        # 尝试目标层 + 降级链
        candidates = [target_tier] + _TIER_FALLBACK_CHAIN.get(target_tier, [])
        for tier in candidates:
            if self._tier_available(tier):
                cfg = self.tier_config[tier]
                if tier != target_tier:
                    logger.warning(
                        f"⬇️ task_type='{task_type}' 目标层 {target_tier} 不可用，降级到 {tier}"
                    )
                logger.info(
                    f"🔀 路由: task_type='{task_type}' → tier={tier} → model={cfg['model_name']}"
                )
                return (cfg["api_url"], cfg["api_key_env"], cfg["model_name"])

        # 所有层都不可用（API Key 均未配置）
        logger.error(
            f"🚫 task_type='{task_type}' 所有层级均不可用（API Key 未配置），"
            f"请检查 .env 中 PREMIUM/STANDARD/LIGHT_MODEL_API_KEY"
        )
        return (None, None, None)

    def get_tier_for_task(self, task_type: str) -> str:
        """查询 task_type 对应的层级名（不触发降级，仅供监控/日志）"""
        return self._resolve_tier(task_type)


# ── 模块级单例 + 便捷函数 ────────────────────────────────────────────
# 让 ai_engine.py 可以直接调用 route_model(task_type) 而无需管理实例

_router_instance: Optional[ModelRouter] = None


def init_router(config: dict):
    """显式初始化路由器单例（在 main.py 启动时调用一次）"""
    global _router_instance
    try:
        _router_instance = ModelRouter(config)
        logger.info("✅ ModelRouter 已初始化")
    except Exception as e:
        logger.warning(f"⚡ ModelRouter 初始化失败（不影响主流程）：{e}")
        _router_instance = None


def _get_router(config: dict = None) -> Optional[ModelRouter]:
    """懒加载路由器单例（首次调用需传 config）"""
    global _router_instance
    if _router_instance is None:
        if config is None:
            return None
        try:
            _router_instance = ModelRouter(config)
        except Exception as e:
            logger.warning(f"⚡ ModelRouter 懒加载失败：{e}")
            return None
    return _router_instance


def route_model(task_type: str, config: dict = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    模块级便捷函数：根据 task_type 路由到对应模型。

    Args:
        task_type: 任务类型（chat / moderate / summarize / ad_detect 等）
        config:    可选配置字典（首次调用需提供以初始化单例）

    Returns:
        (api_url, api_key_env, model_name) 三元组；
        路由不可用时返回 (None, None, None)。
    """
    router = _get_router(config)
    if router is None:
        return (None, None, None)
    return router.route_model(task_type)


def is_enabled(config: dict) -> bool:
    """检查 ModelRouter 是否启用（默认关闭，向后兼容）"""
    return bool((config or {}).get("MODEL_ROUTER_ENABLED", False))
