# -*- coding: utf-8 -*-
"""
配置管理 Settings 类测试

测试覆盖：
- ConfigJsonModel 动态属性访问
- Settings 初始化与配置加载
- 环境变量优先级
- 配置校验逻辑
- 便捷方法（get_token, get_api_key 等）
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ──────────────────────────────────────────────────────
# ConfigJsonModel 测试
# ──────────────────────────────────────────────────────

def test_config_json_model_getattr():
    """ConfigJsonModel 支持动态属性访问"""
    from core.settings import ConfigJsonModel
    
    data = {"BOT_NAME": "测试Bot", "ADMIN_ID": 123}
    model = ConfigJsonModel(data)
    
    assert model.BOT_NAME == "测试Bot"
    assert model.ADMIN_ID == 123


def test_config_json_model_get_method():
    """ConfigJsonModel.get() 方法支持默认值"""
    from core.settings import ConfigJsonModel
    
    data = {"BOT_NAME": "测试Bot"}
    model = ConfigJsonModel(data)
    
    assert model.get("BOT_NAME") == "测试Bot"
    assert model.get("MISSING_KEY", "default") == "default"


def test_config_json_model_getitem():
    """ConfigJsonModel 支持 [] 访问"""
    from core.settings import ConfigJsonModel
    
    data = {"KEY": "value"}
    model = ConfigJsonModel(data)
    
    assert model["KEY"] == "value"


def test_config_json_model_contains():
    """ConfigJsonModel 支持 in 操作符"""
    from core.settings import ConfigJsonModel
    
    data = {"KEY": "value"}
    model = ConfigJsonModel(data)
    
    assert "KEY" in model
    assert "MISSING" not in model


def test_config_json_model_to_dict():
    """ConfigJsonModel.to_dict() 返回字典副本"""
    from core.settings import ConfigJsonModel
    
    data = {"KEY": "value"}
    model = ConfigJsonModel(data)
    
    result = model.to_dict()
    assert result == data
    assert result is not data  # 确保是副本


# ──────────────────────────────────────────────────────
# Settings 初始化测试
# ──────────────────────────────────────────────────────

def test_settings_loads_config_json(temp_env, tmp_path, monkeypatch):
    """Settings 从 config.json 加载业务配置"""
    # 创建临时 config.json
    config_data = {
        "TOKEN": "test_token",
        "API_KEY": "test_api_key",
        "BOT_NAME": "测试Bot",
        "ADMIN_ID": 999,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    # 临时修改 PROJECT_ROOT
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.config.BOT_NAME == "测试Bot"
    assert settings.config.ADMIN_ID == 999


def test_settings_fallback_to_example(temp_env, tmp_path, monkeypatch):
    """config.json 不存在时回退到 config.json.example"""
    # 只创建 config.json.example
    config_data = {
        "TOKEN": "example_token",
        "API_KEY": "example_api_key",
        "BOT_NAME": "示例Bot",
    }
    example_path = tmp_path / "config.json.example"
    example_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.config.BOT_NAME == "示例Bot"


def test_settings_missing_config_raises_error(temp_env, tmp_path, monkeypatch):
    """config.json 和 config.json.example 都不存在时抛出错误"""
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    
    with pytest.raises(ValueError, match="配置文件不存在"):
        Settings()


def test_settings_invalid_json_raises_error(temp_env, tmp_path, monkeypatch):
    """config.json 格式错误时抛出错误"""
    config_path = tmp_path / "config.json"
    config_path.write_text("{invalid json", encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    
    with pytest.raises(ValueError, match="格式错误"):
        Settings()


# ──────────────────────────────────────────────────────
# 配置校验测试
# ──────────────────────────────────────────────────────

def test_settings_validate_missing_token_raises_error(tmp_path, monkeypatch):
    """缺少 TG_TOKEN 时校验失败"""
    config_data = {
        "TOKEN": "",  # 空 Token
        "API_KEY": "valid_key",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("TG_TOKEN", raising=False)
    monkeypatch.delenv("DASHBOARD_SECRET", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    
    from core.settings import Settings
    
    with pytest.raises(ValueError, match="TG_TOKEN 未配置"):
        Settings()


def test_settings_validate_missing_api_key_raises_error(tmp_path, monkeypatch):
    """缺少 DASHSCOPE_KEY 时校验失败"""
    config_data = {
        "TOKEN": "valid_token",
        "API_KEY": "",  # 空 API Key
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
    monkeypatch.delenv("DASHBOARD_SECRET", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    
    from core.settings import Settings
    
    with pytest.raises(ValueError, match="DASHSCOPE_KEY 未配置"):
        Settings()


# ──────────────────────────────────────────────────────
# 便捷方法测试
# ──────────────────────────────────────────────────────

def test_settings_get_token_priority(temp_env, tmp_path, monkeypatch):
    """get_token() 优先返回环境变量"""
    config_data = {"TOKEN": "config_token", "API_KEY": "key"}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("TG_TOKEN", "env_token")
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.get_token() == "env_token"


def test_settings_get_api_key_priority(temp_env, tmp_path, monkeypatch):
    """get_api_key() 优先返回环境变量"""
    config_data = {"TOKEN": "token", "API_KEY": "config_key"}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DASHSCOPE_KEY", "env_key")
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.get_api_key() == "env_key"


def test_settings_get_admin_id_from_config(temp_env, tmp_path, monkeypatch):
    """get_admin_id() 从 config.json 读取"""
    config_data = {"TOKEN": "token", "API_KEY": "key", "ADMIN_ID": 888}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.get_admin_id() == 888


def test_settings_get_bot_name_default(temp_env, tmp_path, monkeypatch):
    """get_bot_name() 返回默认值"""
    config_data = {"TOKEN": "token", "API_KEY": "key"}  # 无 BOT_NAME
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.get_bot_name() == "Mory小助理"


def test_settings_is_feature_enabled(temp_env, tmp_path, monkeypatch):
    """is_feature_enabled() 检查功能开关"""
    config_data = {
        "TOKEN": "token",
        "API_KEY": "key",
        "FEATURE_A": True,
        "FEATURE_B": False,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.is_feature_enabled("FEATURE_A") is True
    assert settings.is_feature_enabled("FEATURE_B") is False
    assert settings.is_feature_enabled("FEATURE_C", default=False) is False


def test_settings_get_nested_config(temp_env, tmp_path, monkeypatch):
    """get_nested_config() 支持多级键访问"""
    config_data = {
        "TOKEN": "token",
        "API_KEY": "key",
        "MODEL_POOLS": {
            "premium": {"model": "gpt-4"},
            "standard": {"model": "deepseek-v3"},
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    monkeypatch.setattr("core.settings.PROJECT_ROOT", tmp_path)
    
    from core.settings import Settings
    settings = Settings()
    
    assert settings.get_nested_config("MODEL_POOLS", "premium", "model") == "gpt-4"
    assert settings.get_nested_config("MODEL_POOLS", "missing", default="default") == "default"
