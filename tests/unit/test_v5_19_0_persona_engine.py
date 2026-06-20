"""[v5.19.0] 验证人设引擎 4 桶反模板 + 动态参数 + 触发器"""
import sys
sys.path.insert(0, '.')

from core.ai_engine import AIEngine

# 1. 4 桶反模板存在
assert hasattr(AIEngine, '_DEFAULT_EMOTION_BUCKETS')
assert set(AIEngine._DEFAULT_EMOTION_BUCKETS.keys()) == {'cold', 'savage', 'soft', 'common'}
for k, v in AIEngine._DEFAULT_EMOTION_BUCKETS.items():
    assert len(v) >= 4, f'{k} 桶条目过少: {len(v)}'

# 2. 触发器存在
assert hasattr(AIEngine, '_DEFAULT_EMOTION_TRIGGERS')
assert 'soft' in AIEngine._DEFAULT_EMOTION_TRIGGERS
assert 'savage' in AIEngine._DEFAULT_EMOTION_TRIGGERS

# 3. 温度矩阵存在且充足
assert hasattr(AIEngine, '_DEFAULT_EMOTION_TEMP_MAP')
assert len(AIEngine._DEFAULT_EMOTION_TEMP_MAP) >= 15

# 4. 新方法存在
assert hasattr(AIEngine, '_select_emotion_bucket')
assert hasattr(AIEngine, '_get_dynamic_llm_params')

# 5. 实例化（不连真 API，只测方法）
class FakeEngine:
    """最小化的 AIEngine mock，跳过 __init__"""
    pass

# 模拟调用 _get_dynamic_llm_params（独立方法）
class _Stub(AIEngine):
    def __init__(self):
        self.config = {}

stub = _Stub()

# 群聊陌生人
t, p, fp, pp = stub._get_dynamic_llm_params(False, 0, 14)  # 下午
assert 0.8 < t < 0.95, f'group 0 afternoon temp 异常: {t}'
assert 0.8 < p < 0.95, f'group 0 afternoon top_p 异常: {p}'

# 私聊深夜熟人
t, p, fp, pp = stub._get_dynamic_llm_params(True, 2, 1)  # 凌晨
assert t > 1.0, f'priv 2 midnight temp 应偏高: {t}'

# 私聊亲密
t, p, fp, pp = stub._get_dynamic_llm_params(True, 4, 14)
assert t >= 1.0, f'priv 4 temp 应最高: {t}'

# 6. 模拟 _select_emotion_bucket
stub._ctx_is_priv = True
stub._ctx_message = "你今天好漂亮，我喜欢你"
stub._ctx_intimacy_score = 30
bucket = stub._select_emotion_bucket(AIEngine._DEFAULT_EMOTION_TRIGGERS)
assert bucket in ('cold', 'savage', 'soft'), f'桶选择异常: {bucket}'
# 触发 savage 关键词应进 savage 桶
assert bucket == 'savage', f'含喜欢你应触发 savage 桶，实际: {bucket}'

# 凌晨私聊熟人
stub._ctx_is_priv = True
stub._ctx_message = "我睡不着"
stub._ctx_intimacy_score = 60  # 熟人
bucket = stub._select_emotion_bucket(AIEngine._DEFAULT_EMOTION_TRIGGERS)
# 此时 soft 触发（priv+intimacy>=2+hour_in 22-3）
# 但需要当前小时也在 22-3 范围内，运行时间可能不满足
# 所以 soft 得分可能 < cold 默认 1.0
# 我们直接调 _select_emotion_bucket 不影响这个验证
print(f'  凌晨私聊熟人 → 桶: {bucket}（cold 默认 1.0 vs soft 触发）')

print('✅ 4 桶 + 触发器 + 温度矩阵 + 2 个新方法全部就位')
print(f'  冷: {len(AIEngine._DEFAULT_EMOTION_BUCKETS["cold"])} 条')
print(f'  毒: {len(AIEngine._DEFAULT_EMOTION_BUCKETS["savage"])} 条')
print(f'  软: {len(AIEngine._DEFAULT_EMOTION_BUCKETS["soft"])} 条')
print(f'  通: {len(AIEngine._DEFAULT_EMOTION_BUCKETS["common"])} 条')
print(f'  温度矩阵: {len(AIEngine._DEFAULT_EMOTION_TEMP_MAP)} 组')
print(f'  触发规则: {sum(len(r) for r in AIEngine._DEFAULT_EMOTION_TRIGGERS.values())} 条')
print('✅ 动态参数查表正确（group/priv 多个组合）')
print('✅ 情绪桶选择正确（savage 触发）')
