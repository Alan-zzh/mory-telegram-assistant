# -*- coding: utf-8 -*-
"""
统一配置管理模块 - 基于 pydantic-settings

提供类型安全的配置读取，支持：
- 从 .env 读取敏感配置（Token、API Key、密码等）
- 从 config.json 读取业务配置
- 启动时校验关键配置，缺失则 Fail-Fast
- 全局单例 settings 对象

使用方式：
    from core.settings import settings

    # 访问配置
    token = settings.tg_token
    api_key = settings.dashscope_key
    admin_id = settings.admin_id

    # 访问业务配置（来自 config.json）
    bot_name = settings.config.BOT_NAME
    model_pools = settings.config.MODEL_POOLS
"""

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from core.config_compat import normalize_runtime_config


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


class ConfigJsonModel:
    """config.json 业务配置模型（动态属性访问）"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        return self._data.get(name)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持默认值回退。

        Args:
            key: 配置键名
            default: 键不存在时的默认返回值

        Returns:
            配置值，或 default
        """
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def to_dict(self) -> dict[str, Any]:
        """返回配置的浅拷贝字典，用于序列化或传递给外部模块。

        Returns:
            dict: 配置数据的副本，修改不会影响原始配置
        """
        return self._data.copy()


class Settings(BaseSettings):
    """
    统一配置类

    敏感配置从 .env 读取，业务配置从 config.json 读取。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============ 敏感配置（从 .env 读取）============

    # Telegram Bot Token
    tg_token: str = Field(default="", alias="TG_TOKEN")

    # AI API密钥（通义千问 DashScope）
    dashscope_key: str = Field(default="", alias="DASHSCOPE_KEY")

    # 多模型协同路由 API Key
    premium_model_api_key: str = Field(default="", alias="PREMIUM_MODEL_API_KEY")
    standard_model_api_key: str = Field(default="", alias="STANDARD_MODEL_API_KEY")
    light_model_api_key: str = Field(default="", alias="LIGHT_MODEL_API_KEY")

    # Dashboard 配置
    dashboard_secret: str = Field(default="", alias="DASHBOARD_SECRET")
    dashboard_password: str = Field(default="", alias="DASHBOARD_PASSWORD")
    dashboard_viewer_password: str = Field(default="", alias="DASHBOARD_VIEWER_PASSWORD")
    dashboard_port: int = Field(default=6616, alias="DASHBOARD_PORT")
    dashboard_https: bool = Field(default=False, alias="DASHBOARD_HTTPS")
    dashboard_mode: str = Field(default="main", alias="DASHBOARD_MODE")

    # VPS 连接配置
    vps_host: str = Field(default="", alias="VPS_HOST")
    vps_port: int = Field(default=22, alias="VPS_PORT")
    vps_user: str = Field(default="ubuntu", alias="VPS_USER")
    vps_ssh_pass: str = Field(default="", alias="VPS_SSH_PASS")
    vps_path: str = Field(default="/home/ubuntu/mory_assistant", alias="VPS_PATH")

    # 告警 Bot 配置
    alert_bot_token: str = Field(default="", alias="ALERT_BOT_TOKEN")
    alert_chat_id: str = Field(default="", alias="ALERT_CHAT_ID")

    # 可选：从环境变量覆盖的 ID 配置
    admin_id: Optional[int] = Field(default=None, alias="ADMIN_ID")
    group_id: Optional[int] = Field(default=None, alias="GROUP_ID")

    # ============ 业务配置（从 config.json 读取）============

    # config.json 原始数据（内部使用）
    _config_data: dict[str, Any] = {}
    _config_model: Optional[ConfigJsonModel] = None

    @model_validator(mode="after")
    def load_config_json(self) -> "Settings":
        """加载 config.json 业务配置"""
        config_path = PROJECT_ROOT / "config.json"

        if not config_path.exists():
            # 尝试使用 config.json.example 作为回退
            example_path = PROJECT_ROOT / "config.json.example"
            if example_path.exists():
                config_path = example_path
            else:
                raise ValueError(
                    f"配置文件不存在: {config_path}\n"
                    "请复制 config.json.example 为 config.json 并填入实际配置"
                )

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._config_data = normalize_runtime_config(json.load(f))
        except json.JSONDecodeError as e:
            raise ValueError(f"config.json 格式错误: {e}")
        except Exception as e:
            raise ValueError(f"读取 config.json 失败: {e}")

        self._config_model = ConfigJsonModel(self._config_data)
        self._apply_env_overrides()

        return self

    def _apply_env_overrides(self) -> None:
        """保持与 bot_initializer.load_config() 一致的密钥优先级。"""
        env_map = {
            "TOKEN": self.tg_token,
            "API_KEY": self.dashscope_key,
            "ADMIN_ID": self.admin_id,
            "GROUP_ID": self.group_id,
        }
        for key, value in env_map.items():
            if value not in (None, ""):
                self._config_data[key] = value

    @model_validator(mode="after")
    def validate_critical_config(self) -> "Settings":
        """校验关键配置，缺失则 Fail-Fast"""
        errors = []

        # 校验 Telegram Bot Token
        token = self.tg_token or self._config_data.get("TOKEN", "")
        if not token or token in ("YOUR_TELEGRAM_BOT_TOKEN", ""):
            errors.append("TG_TOKEN 未配置（.env 或 config.json 的 TOKEN 字段）")

        # 校验 AI API Key
        api_key = self.dashscope_key or self._config_data.get("API_KEY", "")
        if not api_key or api_key in ("YOUR_DASHSCOPE_API_KEY", ""):
            errors.append("DASHSCOPE_KEY 未配置（.env 或 config.json 的 API_KEY 字段）")

        # 校验 Dashboard 密钥（如果 Dashboard 启用）
        if self.dashboard_port > 0:
            if not self.dashboard_secret:
                errors.append("DASHBOARD_SECRET 未配置（Dashboard 需要密钥）")
            if not self.dashboard_password:
                errors.append("DASHBOARD_PASSWORD 未配置（Dashboard 需要登录密码）")

        if errors:
            error_msg = "配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)

        return self

    @property
    def config(self) -> ConfigJsonModel:
        """获取 config.json 业务配置模型"""
        if self._config_model is None:
            raise RuntimeError("Settings 未正确初始化")
        return self._config_model

    @property
    def config_dict(self) -> dict[str, Any]:
        """获取 config.json 原始字典（向后兼容）"""
        return self._config_data

    def get_token(self) -> str:
        """获取 Telegram Bot Token（优先环境变量）"""
        return self.tg_token or self._config_data.get("TOKEN", "")

    def get_api_key(self) -> str:
        """获取 DashScope API Key（优先环境变量）"""
        return self.dashscope_key or self._config_data.get("API_KEY", "")

    def get_admin_id(self) -> int:
        """获取管理员 ID（优先环境变量，回退 config.json）"""
        if self.admin_id is not None:
            return self.admin_id
        return self._config_data.get("ADMIN_ID", 0)

    def get_group_id(self) -> int:
        """获取主群 ID（优先环境变量，回退 config.json）"""
        if self.group_id is not None:
            return self.group_id
        return self._config_data.get("GROUP_ID", 0)

    def get_channel_ids(self) -> list[int]:
        """获取频道 ID 列表"""
        return self._config_data.get("CHANNEL_IDS", [])

    def get_bot_name(self) -> str:
        """获取 Bot 名称"""
        return self._config_data.get("BOT_NAME", "Mory小助理")

    def get_model_pools(self) -> dict[str, Any]:
        """获取模型池配置"""
        return self._config_data.get("MODEL_POOLS", {})

    def get_mode_routing(self) -> dict[str, str]:
        """获取模式路由配置"""
        return self._config_data.get("MODE_ROUTING", {})

    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        return self._config_data.get("SYSTEM_PROMPT", "")

    def get_base_url(self) -> str:
        """获取 API Base URL"""
        return self._config_data.get(
            "BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        )

    def is_feature_enabled(self, feature_key: str, default: bool = False) -> bool:
        """检查功能是否启用（统一入口）"""
        return bool(self._config_data.get(feature_key, default))

    def get_nested_config(self, *keys: str, default: Any = None) -> Any:
        """获取嵌套配置值，支持多级键路径。

        例如 get_nested_config('a', 'b', 'c') 等价于 data['a']['b']['c']。

        Args:
            *keys: 多级键路径
            default: 任意层级缺失时的默认返回值

        Returns:
            嵌套配置值，或 default
        """
        value = self._config_data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value


# ============ 全局单例 ============

_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局 settings 单例（懒加载）"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reload_settings() -> Settings:
    """重新加载配置（用于配置热重载场景）"""
    global _settings_instance
    _settings_instance = Settings()
    return _settings_instance


# 模块级单例（导入时不立即加载，首次访问时加载）
class _SettingsProxy:
    """settings 代理类，支持延迟初始化"""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)

    def __repr__(self) -> str:
        return f"<SettingsProxy: {get_settings().__class__.__name__}>"


# 全局单例（延迟加载）
settings = _SettingsProxy()


# ============ 便捷函数（向后兼容）============

def get_config() -> dict[str, Any]:
    """获取 config.json 字典（向后兼容）"""
    return get_settings().config_dict


def get_config_value(key: str, default: Any = None) -> Any:
    """获取配置值（向后兼容）"""
    return get_settings().config_dict.get(key, default)
