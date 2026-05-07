# -*- coding: utf-8 -*-
"""
Universal AI Router - 主入口文件

功能：
    - 展示系统使用方法
    - 提供命令行接口
    - 测试各模块功能
"""

import sys
import json
from universal_ai_router.core import (
    get_config_manager,
    get_account_manager,
    get_router,
    get_universal_ai,
    get_router_statistics
)


def demo_basic_usage():
    """基础使用示例"""
    print("=" * 60)
    print("Universal AI Router - 基础使用示例")
    print("=" * 60)

    # 获取各组件实例
    config = get_config_manager()
    router = get_router()
    account_mgr = get_account_manager()
    stats = get_router_statistics()

    print("✅ 配置加载成功")
    print("✅ 路由器初始化成功")
    print("✅ 账号管理器初始化成功")
    print("✅ 统计模块初始化成功")

    # 显示配置信息
    print("\n📋 配置信息：")
    global_config = config.get_global_config()
    print(f"   默认策略: {global_config.get('default_strategy', 'cost')}")
    print(f"   启用降级: {global_config.get('enable_fallback', True)}")

    # 显示模型池
    print("\n📦 模型池：")
    pools = config.get_model_pools()
    for pool_name, pool_info in pools.items():
        models = pool_info.get("models", [])
        print(f"   {pool_name}: {len(models)} 个模型")

    # 显示提供商
    print("\n☁️ API提供商：")
    providers = ["qwen", "openai", "anthropic", "gemini"]
    for provider in providers:
        accounts = config.get_enabled_accounts(provider)
        if accounts:
            print(f"   {provider}: {len(accounts)} 个账号")

    print()


def demo_chat():
    """聊天示例"""
    print("=" * 60)
    print("聊天功能测试")
    print("=" * 60)

    try:
        ai = get_universal_ai()
        print("✅ UniversalAI 实例创建成功")

        # 注意：这里只是展示调用方式，实际调用需要有效的API Key
        print("\n📝 chat() 接口使用方式：")
        print("   result = ai.chat('你好，请介绍一下自己')")
        print("   result = ai.chat('画一幅画', model='dall-e-3')")
        print("   result = ai.chat('分析这张图片', image_data=image_bytes)")

    except Exception as e:
        print(f"⚠️ 聊天功能演示（需要有效API Key）: {e}")
    print()


def demo_statistics():
    """统计功能示例"""
    print("=" * 60)
    print("统计报表功能测试")
    print("=" * 60)

    try:
        stats = get_router_statistics()

        # 获取今日统计
        daily = stats.get_daily_statistic()
        print(f"\n📊 今日统计: {daily}")

        # 获取本周统计
        weekly = stats.get_weekly_statistic()
        print(f"📊 本周统计: {weekly}")

        # 获取本月统计
        monthly = stats.get_monthly_statistic()
        print(f"📊 本月统计: {monthly}")

        # 获取汇总
        summary = stats.get_summary_statistics()
        print(f"📊 汇总统计: {summary}")

        # 导出报表
        print("\n📄 导出CSV报表：")
        csv = stats.export_report("daily")
        print(f"   daily: {csv[:100]}...")

    except Exception as e:
        print(f"❌ 统计功能演示失败: {e}")
    print()


def demo_router():
    """路由功能示例"""
    print("=" * 60)
    print("智能路由功能测试")
    print("=" * 60)

    try:
        router = get_router()

        # 测试文字任务
        print("\n📝 文字任务路由：")
        models = router.route("你好，Mory！")
        print(f"   路由结果: {[m['name'] for m in models[:3]]}...")

        # 测试图像任务
        print("\n🖼️ 图像任务路由：")
        image_data = b'\xff\xd8\xff\xe0\x00\x10JFIF'
        models = router.route(image_data)
        print(f"   路由结果: {[m['name'] for m in models[:3]]}...")

        # 测试音频任务
        print("\n🎤 音频任务路由：")
        audio_data = b'ID3\x04\x00\x00\x00\x00\x00\x00'
        models = router.route(audio_data)
        print(f"   路由结果: {[m['name'] for m in models[:3]]}...")

    except Exception as e:
        print(f"❌ 路由功能演示失败: {e}")
    print()


def main():
    """主函数"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "Universal AI Router 系统演示" + " " * 17 + "║")
    print("║" + " " * 15 + "通用AI模型路由系统" + " " * 24 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    # 基础使用示例
    demo_basic_usage()

    # 功能演示
    demo_router()
    demo_statistics()
    demo_chat()

    print("=" * 60)
    print("演示完成！")
    print("=" * 60)
    print()
    print("📚 使用文档：")
    print("   1. 配置API密钥: config/router_config.json")
    print("   2. 导入模块: from universal_ai_router.core import get_universal_ai")
    print("   3. 调用接口: ai = get_universal_ai(); result = ai.chat('你好')")
    print()


if __name__ == "__main__":
    main()