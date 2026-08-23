# -*- coding: utf-8 -*-
"""
pytest 共享 fixtures - 提供测试所需的基础设施

包含：
- 内存数据库 fixture（避免污染生产数据）
- Mock Telegram Bot fixture
- Mock LLM API fixture
- 临时配置文件 fixture
"""

import os
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest


# 确保项目根目录在 sys.path（conftest 位于仓库根，parent 即仓库根；
# 修复：此前误写 parent.parent 把仓库父目录插进了搜索路径）
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_db():
    """
    内存 SQLite 数据库，用于测试数据库操作
    返回 sqlite3.Connection 对象
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # 创建基础表结构（按需扩展）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ad_suspicious_users (
            user_id INTEGER PRIMARY KEY,
            score INTEGER DEFAULT 0,
            first_seen TEXT,
            messages TEXT DEFAULT '[]',
            updated_at INTEGER
        )
    """)
    conn.commit()
    
    yield conn
    conn.close()


@pytest.fixture
def mock_bot():
    """
    Mock Telegram Bot 实例，避免真实 API 调用
    提供常用方法的 Mock 实现
    """
    bot = MagicMock()
    
    # 常用方法
    bot.send_message = Mock(return_value=MagicMock(message_id=100))
    bot.delete_message = Mock(return_value=True)
    bot.ban_chat_member = Mock(return_value=True)
    bot.restrict_chat_member = Mock(return_value=True)
    bot.get_chat_member = Mock(return_value=MagicMock(
        user=MagicMock(id=123, full_name="Test User")
    ))
    bot.forward_message = Mock(return_value=MagicMock(message_id=200))
    bot.get_me = Mock(return_value=MagicMock(id=999))
    
    return bot


@pytest.fixture
def mock_llm_api():
    """
    Mock LLM API 响应，避免真实 API 调用
    返回可配置的 Mock 响应
    """
    def _create_mock_response(text="测试响应", status_code=200):
        mock_resp = Mock()
        mock_resp.status_code = status_code
        mock_resp.text = text
        mock_resp.json = Mock(return_value={"response": text})
        return mock_resp
    
    return _create_mock_response


@pytest.fixture
def temp_config():
    """
    临时配置文件（config.json），测试完成后自动清理
    返回配置字典，可修改后写入临时文件
    """
    config = {
        "TOKEN": "test_token_123",
        "API_KEY": "test_api_key_456",
        "ADMIN_ID": 123456,
        "GROUP_ID": -100123456,
        "BOT_NAME": "测试Bot",
        "AD_RULES": {
            "builtin_enabled": True,
            "custom_rules": [],
            "stats": {"total_detected": 0, "false_positives": 0},
        },
    }
    
    # 创建临时文件
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8"
    ) as f:
        json.dump(config, f, ensure_ascii=False)
        temp_path = f.name
    
    yield config, temp_path
    
    # 清理
    if os.path.exists(temp_path):
        os.remove(temp_path)


@pytest.fixture
def temp_env(monkeypatch):
    """
    临时环境变量，测试完成后自动恢复
    使用 monkeypatch 设置环境变量
    """
    env_vars = {
        "TG_TOKEN": "test_token_env",
        "DASHSCOPE_KEY": "test_api_key_env",
        "DASHBOARD_SECRET": "test_secret_key_1234567890",
        "DASHBOARD_PASSWORD": "test_password",
        "DASHBOARD_PORT": "6616",
    }
    
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    
    return env_vars


@pytest.fixture
def ad_detector_config():
    """
    广告检测器测试配置
    返回 AdDetector 初始化所需的配置字典
    """
    return {
        "AD_RULES": {
            "builtin_enabled": True,
            "custom_rules": [],
            "score_threshold": 3,
            "stats": {"total_detected": 0, "false_positives": 0},
        }
    }


@pytest.fixture
def sample_ad_messages():
    """
    样本广告消息，用于测试广告检测
    返回 (username, message, expected_is_ad) 元组列表
    """
    return [
        ("看简介", "加我微信", True),
        ("正常用户", "今天天气不错", False),
        ("赚钱日入千元", "私信我了解详情", True),
        ("普通用户", "有人知道怎么做吗？", False),
    ]
