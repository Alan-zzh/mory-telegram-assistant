# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：核心模块测试用例
"""
核心模块测试用例 - 覆盖配置管理、适配器工厂、账号管理、智能路由、统计模块
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_manager():
    """测试配置加载和验证"""
    from universal_ai_router.core import get_config_manager, ConfigManager

    # 测试单例
    config1 = get_config_manager()
    config2 = get_config_manager()
    assert config1 is config2, "配置管理器单例失效"

    # 测试配置验证
    default_strategy = config1.get_default_strategy()
    assert default_strategy in ["performance", "cost", "balanced"], f"未知策略: {default_strategy}"

    print("✅ 配置管理测试通过")


def test_adapter_factory():
    """测试适配器工厂"""
    from universal_ai_router.core.api_adapter import AdapterFactory, BaseAdapter

    # 测试支持的类型
    supported = AdapterFactory.get_supported_types()
    assert "tongyi" in supported
    assert "openai" in supported
    assert "anthropic" in supported
    assert "gemini" in supported

    # 测试创建适配器（不调用真实API，只验证创建）
    tongyi = AdapterFactory.get_adapter("tongyi", "test_key", "https://test.com", model="qwen")
    openai = AdapterFactory.get_adapter("openai", "test_key", "https://test.com", model="gpt-4")
    anthropic = AdapterFactory.get_adapter("anthropic", "test_key", "https://test.com", model="claude")
    gemini = AdapterFactory.get_adapter("gemini", "test_key", "https://test.com", model="gemini-1")

    assert tongyi is not None
    assert isinstance(tongyi, BaseAdapter)
    assert openai is not None
    assert isinstance(openai, BaseAdapter)
    assert anthropic is not None
    assert isinstance(anthropic, BaseAdapter)
    assert gemini is not None
    assert isinstance(gemini, BaseAdapter)

    print("✅ 适配器工厂测试通过")


def test_account_manager():
    """测试账号管理器"""
    from universal_ai_router.core import get_account_manager, get_config_manager

    # 初始化账号管理器（需要先有配置管理器）
    config_mgr = get_config_manager()
    mgr = get_account_manager(config_mgr)

    # 获取所有provider
    providers = config_mgr.get_all_providers()
    assert len(providers) > 0, "没有找到任何provider"

    # 测试账号管理器功能
    for provider in providers:
        # 获取provider统计
        stats = mgr.get_provider_stats(provider)
        assert stats is not None, f"获取{provider}统计失败"

        # 检查provider是否有可用账号
        is_available = mgr.is_provider_available(provider)
        assert isinstance(is_available, bool)

    print("✅ 账号管理器测试通过")


def test_router():
    """测试智能路由"""
    from universal_ai_router.core import get_router
    from universal_ai_router.core.router import TaskType

    router = get_router()

    # 测试文字任务
    models = router.route("你好")
    assert models is not None
    assert len(models) > 0, "文字任务路由失败"

    # 测试图像任务（PNG魔数）
    image_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
    models = router.route(image_data)
    assert models is not None
    assert len(models) > 0, "图像任务路由失败"

    # 测试明确指定任务类型
    models = router.route("hello", task_type=TaskType.TEXT)
    assert models is not None
    assert len(models) > 0

    print("✅ 智能路由测试通过")


def test_task_type_detection():
    """测试任务类型自动检测"""
    from universal_ai_router.core import get_router
    from universal_ai_router.core.router import TaskType

    router = get_router()

    # 字符串应该是TEXT
    assert router.detect_input_type("hello") == TaskType.TEXT
    assert router.detect_input_type("你好，世界") == TaskType.TEXT

    # PNG图片
    assert router.detect_input_type(b'\x89PNG\r\n\x1a\n\x00\x00\x00') == TaskType.IMAGE

    # JPEG图片
    assert router.detect_input_type(b'\xff\xd8\xff\xe0\x00\x10JFIF') == TaskType.IMAGE

    # GIF图片
    assert router.detect_input_type(b'GIF87a\x00\x01\x00\x00') == TaskType.IMAGE
    assert router.detect_input_type(b'GIF89a\x00\x01\x00\x00') == TaskType.IMAGE

    # MP3音频
    assert router.detect_input_type(b'ID3\x04\x00\x00\x00\x00\x00\x00') == TaskType.AUDIO

    print("✅ 任务类型检测测试通过")


def test_cost_strategies():
    """测试成本策略"""
    from universal_ai_router.core import get_router
    from universal_ai_router.core.router import CostStrategy

    router = get_router()

    # 测试成本优先策略
    models_cost = router.route("你好", strategy_override="cost")
    assert models_cost is not None
    assert len(models_cost) > 0

    # 测试性能优先策略
    models_perf = router.route("你好", strategy_override="performance")
    assert models_perf is not None
    assert len(models_perf) > 0

    # 测试平衡策略
    models_balanced = router.route("你好", strategy_override="balanced")
    assert models_balanced is not None
    assert len(models_balanced) > 0

    # 测试策略切换
    router.set_strategy(CostStrategy.COST)
    assert router.current_strategy == CostStrategy.COST

    router.set_strategy(CostStrategy.PERFORMANCE, temporary=True)
    assert router.current_strategy == CostStrategy.PERFORMANCE

    router.reset_strategy()
    assert router.current_strategy == CostStrategy.COST

    print("✅ 成本策略测试通过")


def test_statistics():
    """测试统计模块"""
    from universal_ai_router.core import get_router_statistics

    stats = get_router_statistics()

    # 获取今日统计
    daily = stats.get_daily_statistic()
    assert daily is not None
    assert isinstance(daily, dict)

    # 获取本周统计
    weekly = stats.get_weekly_statistic()
    assert weekly is not None
    assert isinstance(weekly, dict)

    # 获取本月统计
    monthly = stats.get_monthly_statistic()
    assert monthly is not None
    assert isinstance(monthly, dict)

    # 获取汇总统计
    summary = stats.get_summary_statistics()
    assert summary is not None
    assert "today" in summary
    assert "this_week" in summary
    assert "this_month" in summary

    print("✅ 统计模块测试通过")


def test_unified_response():
    """测试统一响应格式"""
    from universal_ai_router.core.api_adapter import UnifiedResponse, create_unified_response

    # 测试创建响应
    response = create_unified_response(
        content="测试内容",
        model="gpt-4",
        input_tokens=100,
        output_tokens=200,
        cost=0.01,
        provider="openai",
        success=True
    )

    assert response.content == "测试内容"
    assert response.model == "gpt-4"
    assert response.input_tokens == 100
    assert response.output_tokens == 200
    assert response.cost == 0.01
    assert response.provider == "openai"
    assert response.success is True

    # 测试错误响应
    error_response = UnifiedResponse(
        success=False,
        error_message="请求失败",
        provider="openai"
    )
    assert error_response.success is False
    assert error_response.error_message == "请求失败"

    print("✅ 统一响应格式测试通过")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Universal AI Router - 核心模块测试用例")
    print("=" * 60)

    test_config_manager()
    test_adapter_factory()
    test_account_manager()
    test_router()
    test_task_type_detection()
    test_cost_strategies()
    test_statistics()
    test_unified_response()

    print("=" * 60)
    print("所有测试通过!")
    print("=" * 60)


if __name__ == "__main__":
    main()
