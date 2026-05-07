# -*- coding: utf-8 -*-
import requests
import json

api_key = 'sk-6176519ce684477a86d830454c42eaa7'
url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}

models_to_test = [
    'qwen3.5-flash',
    'qwen3.5-plus',
    'glm-5.1',
    'kimi-k2.6',
    'qwen3.6-flash'
]

print(f'测试API密钥: {api_key[:10]}...')
print('='*50)

for model in models_to_test:
    data = {
        'model': model,
        'messages': [{'role': 'user', 'content': 'hi'}],
        'max_tokens': 20
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')[:50]
            print(f'✅ {model}: 成功 - {content}')
        else:
            error = resp.json().get('error', {})
            error_code = error.get('code', '未知')
            print(f'❌ {model}: {error_code}')
    except Exception as e:
        print(f'❌ {model}: {e}')

print('='*50)
print('测试完成')
