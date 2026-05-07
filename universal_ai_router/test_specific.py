# -*- coding: utf-8 -*-
import requests
import json

api_key = 'sk-6176519ce684477a86d830454c42eaa7'
url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}

# 测试截图里显示有额度的模型
models_to_test = [
    'tongyi-xiaomi-analysis-pro',      # 剩989,081
    'tongyi-xiaomi-analysis-flash',    # 剩999,986
    'glm-5.1',                         # 剩999,476
    'qwen3.6-plus-2026-04-02',         # 剩998,741
    'qwen3.5-plus-2026-04-20',         # 剩1,000,000
    'kimi-k2.6',                       # 剩999,979
    'qwen3.6-flash-2026-04-16',       # 剩1,000,000
]

print(f'测试API密钥: {api_key[:10]}...')
print('='*70)

for model in models_to_test:
    data = {
        'model': model,
        'messages': [{'role': 'user', 'content': 'hi'}],
        'max_tokens': 30
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            result = resp.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')[:60]
            print(f'✅ {model}: 成功 - {content}')
        else:
            error = resp.json().get('error', {})
            error_code = error.get('code', '未知')
            print(f'❌ {model}: {error_code}')
    except Exception as e:
        print(f'❌ {model}: {e}')

print('='*70)
print('测试完成')
