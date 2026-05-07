# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：配置管理器
"""
配置管理器 - 负责加载和验证路由配置文件
"""

import json
import os
from typing import Dict, List, Optional, Any


class ConfigManager:
    """配置管理器类"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        :param config_path: 配置文件路径，默认使用config/router_config.json
        """
        if config_path is None:
            # 默认路径：项目根目录下的config/router_config.json
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "router_config.json")
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._load_env_file()

    def _load_env_file(self) -> None:
        """加载项目根目录.env，供路由配置引用环境变量。"""
        router_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_root = os.path.dirname(router_dir)
        env_file = os.path.join(project_root, ".env")
        if not os.path.exists(env_file):
            return
        with open(env_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self._resolve_env_placeholders()
        return self.config

    def _resolve_env_placeholders(self) -> None:
        """解析配置中的环境变量占位符，避免把API密钥写死在JSON里。"""
        providers = self.config.get("providers", {})
        for provider_config in providers.values():
            for account in provider_config.get("accounts", []):
                api_key = account.get("api_key", "")
                if isinstance(api_key, str) and api_key.startswith("${ENV:") and api_key.endswith("}"):
                    env_name = api_key[6:-1]
                    account["api_key"] = os.environ.get(env_name, "")

    def validate_config(self) -> bool:
        """验证配置格式"""
        required_sections = ["global", "providers", "model_pools"]
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"配置缺少必需章节: {section}")

        # 验证global配置
        global_config = self.config.get("global", {})
        if "default_strategy" not in global_config:
            raise ValueError("global配置缺少default_strategy")

        # 验证providers配置
        providers = self.config.get("providers", {})
        if not providers:
            raise ValueError("providers配置不能为空")

        for provider_name, provider_config in providers.items():
            if "api_type" not in provider_config:
                raise ValueError(f"provider {provider_name} 缺少api_type")
            if "base_url" not in provider_config:
                raise ValueError(f"provider {provider_name} 缺少base_url")
            if "accounts" not in provider_config:
                raise ValueError(f"provider {provider_name} 缺少accounts")

            accounts = provider_config.get("accounts", [])
            if not accounts:
                raise ValueError(f"provider {provider_name} 的accounts不能为空")

            for account in accounts:
                if "api_key" not in account:
                    raise ValueError(f"provider {provider_name} 的账号缺少api_key")
                if account.get("enabled", True) and not account.get("api_key"):
                    raise ValueError(f"provider {provider_name} 的启用账号缺少有效api_key")

        # 验证model_pools配置
        model_pools = self.config.get("model_pools", {})
        if not model_pools:
            raise ValueError("model_pools配置不能为空")

        for pool_name, pool_config in model_pools.items():
            if "models" not in pool_config:
                raise ValueError(f"model_pool {pool_name} 缺少models")

        return True

    def get_provider_config(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """获取指定provider配置"""
        providers = self.config.get("providers", {})
        return providers.get(provider_name)

    def get_enabled_accounts(self, provider_name: str) -> List[Dict[str, Any]]:
        """获取provider下所有启用的账号"""
        provider_config = self.get_provider_config(provider_name)
        if not provider_config:
            return []

        accounts = provider_config.get("accounts", [])
        enabled = [acc for acc in accounts if acc.get("enabled", False)]
        return enabled

    def get_all_providers(self) -> List[str]:
        """获取所有provider名称"""
        return list(self.config.get("providers", {}).keys())

    def get_model_pools(self) -> Dict[str, Any]:
        """获取所有模型池"""
        return self.config.get("model_pools", {})

    def get_models_by_pool(self, pool_name: str) -> List[Dict[str, Any]]:
        """获取指定池中的模型"""
        model_pools = self.get_model_pools()
        pool_config = model_pools.get(pool_name, {})
        models = pool_config.get("models", [])

        # 返回启用的模型
        enabled_models = [m for m in models if m.get("enabled", False)]
        return enabled_models

    def get_global_config(self) -> Dict[str, Any]:
        """获取全局配置"""
        return self.config.get("global", {})

    def get_default_strategy(self) -> str:
        """获取默认策略"""
        return self.config.get("global", {}).get("default_strategy", "cost")

    def is_fallback_enabled(self) -> bool:
        """检查是否启用降级"""
        return self.config.get("global", {}).get("enable_fallback", True)

    def get_log_level(self) -> str:
        """获取日志级别"""
        return self.config.get("global", {}).get("log_level", "INFO")


# 单例模式，便于全局调用
_instance: Optional[ConfigManager] = None


def get_config_manager(config_path: Optional[str] = None) -> ConfigManager:
    """获取配置管理器单例"""
    global _instance
    if _instance is None:
        _instance = ConfigManager(config_path)
        _instance.load_config()
    return _instance
