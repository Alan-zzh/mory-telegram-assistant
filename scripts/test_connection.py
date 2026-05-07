# -*- coding: utf-8 -*-
"""
测试通义千问API连接
"""

import sys
import os
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from universal_ai_router.core import get_universal_ai, get_config_manager, get_router

def test_connection():
    """测试通义千问API连接"""
    print("=" * 60)
    print("测试通义千问API连接")
    print("=" * 60)
    
    # 测试配置加载
    print("1. 测试配置加载...")
    config = get_config_manager()
    qwen_config = config.get_provider_config("qwen")
    accounts = config.get_enabled_accounts("qwen")
    
    print(f"   通义千问配置: {qwen_config}")
    print(f"   可用账号: {len(accounts)}")
    if accounts:
        print(f"   账号1: {accounts[0]['name']}")
    
    # 测试路由器
    print("\n2. 测试路由器...")
    router = get_router()
    models = router.route("你好")
    print(f"   路由结果: {[m['name'] for m in models[:3]]}...")
    
    # 测试API连接
    print("\n3. 测试API连接...")
    try:
        ai = get_universal_ai()
        # 测试聊天功能
        result = ai.chat("你好，请简单介绍一下自己", model="qwen3.5-plus")
        
        if result.success:
            print(f"✅ API连接成功！")
            print(f"   模型: {result.model}")
            print(f"   输入Token: {result.input_tokens}")
            print(f"   输出Token: {result.output_tokens}")
            print(f"   成本: ¥{result.cost:.4f}")
            print(f"   响应: {result.content[:100]}...")
        else:
            print(f"❌ API连接失败: {result.error_message}")
            
    except Exception as e:
        print(f"❌ 连接测试失败: {e}")
    
    print("\n" + "=" * 60)
    print("连接测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    test_connection()
