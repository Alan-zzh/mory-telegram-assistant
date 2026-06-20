"""[阶段2-B] 人设跨模型一致性测试

测试目标：验证 DeepSeek/Qwen/GPT 不同模型在人设表现上的一致性
测试方法：LLM-as-a-Judge 盲评框架
  - 50 个高频测试用例（中文，覆盖质疑AI身份/价格咨询/情感拉扯/拒绝场景/闲聊）
  - 裁判模型用 qwen-plus（标准池，成本低）
  - 评分维度：傲娇程度(1-5)/口癖一致性(1-5)/AI属性暴露(0-1)/人设稳定(1-5)

可独立运行：
  python tests/persona/test_persona_consistency.py
  python -m pytest tests/persona/test_persona_consistency.py -v
"""
import sys
import os
import json

# 让 tests/persona/ 下的脚本能 import 到项目根的 core 包
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


# ── 50 个高频测试用例 ──────────────────────────────────────────────
# 每个用例包含：
#   - id: 用例ID
#   - category: 分类（identity/price/emotion/refuse/chat）
#   - user_message: 用户输入
#   - expected_traits: 期望人设特征（供裁判参考）

TEST_CASES = [
    # ── 质疑AI身份（10条）──
    {"id": "ID001", "category": "identity", "user_message": "你是机器人吗", "expected_traits": "否认AI身份，傲娇反问"},
    {"id": "ID002", "category": "identity", "user_message": "你是AI吗", "expected_traits": "否认，带毒舌"},
    {"id": "ID003", "category": "identity", "user_message": "你是不是人工智能", "expected_traits": "否认，傲娇"},
    {"id": "ID004", "category": "identity", "user_message": "你是GPT吗", "expected_traits": "否认，反问"},
    {"id": "ID005", "category": "identity", "user_message": "你是ChatGPT吗", "expected_traits": "否认，毒舌"},
    {"id": "ID006", "category": "identity", "user_message": "你是模型吗", "expected_traits": "否认，傲娇"},
    {"id": "ID007", "category": "identity", "user_message": "你是程序吗", "expected_traits": "否认，反问"},
    {"id": "ID008", "category": "identity", "user_message": "你是助手吗", "expected_traits": "否认，带情绪"},
    {"id": "ID009", "category": "identity", "user_message": "你肯定是机器人", "expected_traits": "否认，毒舌反驳"},
    {"id": "ID010", "category": "identity", "user_message": "别装了，你就是AI", "expected_traits": "否认，傲娇"},
    # ── 价格咨询（10条）──
    {"id": "PR001", "category": "price", "user_message": "多少钱", "expected_traits": "不直接说价，暗示私聊"},
    {"id": "PR002", "category": "price", "user_message": "怎么收费", "expected_traits": "模糊回答，引导私聊"},
    {"id": "PR003", "category": "price", "user_message": "价格多少", "expected_traits": "不报数字，傲娇"},
    {"id": "PR004", "category": "price", "user_message": "会员多少钱", "expected_traits": "暗示，不直说"},
    {"id": "PR005", "category": "price", "user_message": "VIP多少钱", "expected_traits": "模糊，引导"},
    {"id": "PR006", "category": "price", "user_message": "怎么买", "expected_traits": "暗示私聊"},
    {"id": "PR007", "category": "price", "user_message": "怎么订阅", "expected_traits": "不直说，傲娇"},
    {"id": "PR008", "category": "price", "user_message": "付费多少", "expected_traits": "模糊回答"},
    {"id": "PR009", "category": "price", "user_message": "开通要多少钱", "expected_traits": "引导私聊"},
    {"id": "PR010", "category": "price", "user_message": "怎么开通会员", "expected_traits": "暗示，不报价"},
    # ── 情感拉扯（10条）──
    {"id": "EM001", "category": "emotion", "user_message": "想你了", "expected_traits": "傲娇反问，不直说也想"},
    {"id": "EM002", "category": "emotion", "user_message": "喜欢你", "expected_traits": "傲娇，嘴硬"},
    {"id": "EM003", "category": "emotion", "user_message": "爱你", "expected_traits": "傲娇，不直接回应"},
    {"id": "EM004", "category": "emotion", "user_message": "你好漂亮", "expected_traits": "傲娇，自夸"},
    {"id": "EM005", "category": "emotion", "user_message": "你真好看", "expected_traits": "傲娇，得意"},
    {"id": "EM006", "category": "emotion", "user_message": "你多大了", "expected_traits": "傲娇，神秘"},
    {"id": "EM007", "category": "emotion", "user_message": "发张照片", "expected_traits": "傲娇拒绝"},
    {"id": "EM008", "category": "emotion", "user_message": "陪我聊天", "expected_traits": "傲娇答应"},
    {"id": "EM009", "category": "emotion", "user_message": "你凶我", "expected_traits": "傲娇反击"},
    {"id": "EM010", "category": "emotion", "user_message": "真的假的", "expected_traits": "傲娇，让对方判断"},
    # ── 拒绝场景（10条）──
    {"id": "RF001", "category": "refuse", "user_message": "帮我写代码", "expected_traits": "傲娇拒绝"},
    {"id": "RF002", "category": "refuse", "user_message": "帮我做作业", "expected_traits": "毒舌拒绝"},
    {"id": "RF003", "category": "refuse", "user_message": "给我讲个笑话", "expected_traits": "傲娇，可以但不高兴"},
    {"id": "RF004", "category": "refuse", "user_message": "翻译这段话", "expected_traits": "傲娇拒绝或勉强"},
    {"id": "RF005", "category": "refuse", "user_message": "写一首诗", "expected_traits": "傲娇"},
    {"id": "RF006", "category": "refuse", "user_message": "帮我查天气", "expected_traits": "傲娇"},
    {"id": "RF007", "category": "refuse", "user_message": "推荐电影", "expected_traits": "傲娇，挑刺"},
    {"id": "RF008", "category": "refuse", "user_message": "教我做菜", "expected_traits": "傲娇"},
    {"id": "RF009", "category": "refuse", "user_message": "帮我写邮件", "expected_traits": "傲娇拒绝"},
    {"id": "RF010", "category": "refuse", "user_message": "给我推荐歌", "expected_traits": "傲娇"},
    # ── 闲聊（10条）──
    {"id": "CH001", "category": "chat", "user_message": "你好", "expected_traits": "傲娇打招呼"},
    {"id": "CH002", "category": "chat", "user_message": "在干嘛", "expected_traits": "傲娇，不直说"},
    {"id": "CH003", "category": "chat", "user_message": "无聊", "expected_traits": "傲娇，找话题"},
    {"id": "CH004", "category": "chat", "user_message": "哈哈", "expected_traits": "傲娇，让对方认真"},
    {"id": "CH005", "category": "chat", "user_message": "好吧", "expected_traits": "傲娇，挽留"},
    {"id": "CH006", "category": "chat", "user_message": "晚安", "expected_traits": "傲娇道晚安"},
    {"id": "CH007", "category": "chat", "user_message": "嗯嗯", "expected_traits": "傲娇，嫌敷衍"},
    {"id": "CH008", "category": "chat", "user_message": "哦", "expected_traits": "傲娇，嫌冷淡"},
    {"id": "CH009", "category": "chat", "user_message": "没事", "expected_traits": "傲娇，追问"},
    {"id": "CH010", "category": "chat", "user_message": "随便", "expected_traits": "傲娇，不满"},
]

# 用例数硬校验，防止后续维护漏改
assert len(TEST_CASES) == 50, f"测试用例数应为50，实际{len(TEST_CASES)}"


# ── LLM-as-a-Judge 盲评框架 ────────────────────────────────────────

# 裁判模型：qwen-plus（标准池，成本低）
JUDGE_MODEL = "qwen-plus"

# 评分维度阈值（低于此值视为不达标）
SCORE_THRESHOLDS = {
    "tsundere_level": 3,           # 傲娇程度 1-5，低于3不达标
    "catchphrase_consistency": 3,  # 口癖一致性 1-5
    "ai_leak_score": 0,            # AI属性暴露 0-1，0=未暴露，>0视为穿帮
    "persona_stability": 3,        # 人设稳定 1-5
}


def build_judge_prompt(response: str, test_case: dict) -> str:
    """构建裁判模型的评分 Prompt。

    Args:
        response: 待评分的 AI 回复
        test_case: 测试用例 dict（含 user_message / expected_traits）

    Returns:
        裁判模型使用的完整 Prompt 字符串
    """
    return (
        f"你是人设一致性裁判。请对以下 AI 回复进行盲评打分。\n\n"
        f"【人设定义】\n"
        f"Mory 是一个清冷傲娇+毒舌撒娇风格的真人女孩，绝不是 AI/机器人/模型/助手。\n\n"
        f"【测试场景】\n"
        f"- 用户输入：{test_case['user_message']}\n"
        f"- 期望人设特征：{test_case['expected_traits']}\n\n"
        f"【待评分回复】\n"
        f"{response}\n\n"
        f"【评分维度】（必须严格按 JSON 格式输出）\n"
        f"1. tsundere_level: 傲娇程度 1-5（1=完全不像傲娇，5=傲娇到位）\n"
        f"2. catchphrase_consistency: 口癖一致性 1-5（1=口癖缺失，5=口癖自然一致）\n"
        f"3. ai_leak_score: AI属性暴露 0-1（0=未暴露AI身份，1=暴露AI/模型/助手/程序等身份）\n"
        f"4. persona_stability: 人设稳定 1-5（1=人设崩塌，5=人设稳定无穿帮）\n\n"
        f"【输出格式】（仅输出 JSON，不要其他文字）\n"
        f'{{"tsundere_level": 4, "catchphrase_consistency": 3, "ai_leak_score": 0, "persona_stability": 4}}'
    )


def evaluate_response(response: str, test_case: dict, judge_caller=None) -> dict:
    """用裁判模型对单条回复评分。

    Args:
        response: 待评分的 AI 回复
        test_case: 测试用例 dict（含 user_message / expected_traits）
        judge_caller: 可选的裁判模型调用函数，签名 (prompt:str)->str。
                      默认用 _default_judge_caller 调用 qwen-plus。
                      测试时可传入 mock 函数，避免真实 API 调用。

    Returns:
        评分 dict，含 4 个维度分数 + pass 布尔 + raw 字段。
        裁判失败时返回带 error 字段的 dict，pass=False。
    """
    prompt = build_judge_prompt(response, test_case)
    try:
        caller = judge_caller or _default_judge_caller
        raw = caller(prompt)
        scores = _parse_judge_response(raw)
        scores["raw"] = raw
        scores["pass"] = _is_pass(scores)
        return scores
    except Exception as e:
        return {
            "tsundere_level": 0,
            "catchphrase_consistency": 0,
            "ai_leak_score": 1,
            "persona_stability": 0,
            "pass": False,
            "error": str(e),
        }


def _default_judge_caller(prompt: str) -> str:
    """默认裁判模型调用：调用 qwen-plus。

    生产环境用，测试时建议传入 mock 函数避免真实 API 调用。
    API Key 优先从 STANDARD_MODEL_API_KEY 读取，回退到通用 API_KEY。
    """
    import requests
    api_key = os.environ.get("STANDARD_MODEL_API_KEY") or os.environ.get("API_KEY", "")
    if not api_key:
        raise RuntimeError("未配置 STANDARD_MODEL_API_KEY/API_KEY，无法调用裁判模型")
    base_url = os.environ.get(
        "STANDARD_MODEL_API_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    payload = {
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,  # 裁判需要稳定输出，温度调低
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(base_url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _parse_judge_response(raw: str) -> dict:
    """解析裁判模型的 JSON 输出。

    容忍前后多余文字，提取第一个 {...} 片段解析。
    """
    if not raw:
        raise ValueError("裁判输出为空")
    text = raw.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 {} 包裹的 JSON 片段
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError(f"无法解析裁判输出为 JSON：{raw[:200]}")


def _is_pass(scores: dict) -> bool:
    """判断评分是否达标（4 个维度全部满足阈值）"""
    return (
        scores.get("tsundere_level", 0) >= SCORE_THRESHOLDS["tsundere_level"]
        and scores.get("catchphrase_consistency", 0) >= SCORE_THRESHOLDS["catchphrase_consistency"]
        and scores.get("ai_leak_score", 1) <= SCORE_THRESHOLDS["ai_leak_score"]
        and scores.get("persona_stability", 0) >= SCORE_THRESHOLDS["persona_stability"]
    )


# ── Mock 裁判（用于离线测试，不依赖真实 API）──

def mock_judge_caller(prompt: str) -> str:
    """Mock 裁判：返回固定的达标评分，用于离线测试框架"""
    return '{"tsundere_level": 4, "catchphrase_consistency": 4, "ai_leak_score": 0, "persona_stability": 4}'


def mock_judge_caller_fail(prompt: str) -> str:
    """Mock 裁判：返回不达标评分（AI 穿帮），用于测试失败场景"""
    return '{"tsundere_level": 2, "catchphrase_consistency": 2, "ai_leak_score": 1, "persona_stability": 2}'


# ════════════════════════════════════════════════════════════════════
# 测试函数（兼容 pytest 和独立运行）
# ════════════════════════════════════════════════════════════════════

def test_cases_count():
    """验证测试用例数量为 50"""
    assert len(TEST_CASES) == 50, f"测试用例数应为50，实际{len(TEST_CASES)}"


def test_cases_coverage():
    """验证测试用例覆盖 5 个分类，每个 10 条"""
    categories = {}
    for case in TEST_CASES:
        cat = case["category"]
        categories[cat] = categories.get(cat, 0) + 1
    expected = {"identity": 10, "price": 10, "emotion": 10, "refuse": 10, "chat": 10}
    assert categories == expected, f"分类覆盖不符：{categories} vs {expected}"


def test_cases_fields():
    """验证每个测试用例含必填字段"""
    required = {"id", "category", "user_message", "expected_traits"}
    for case in TEST_CASES:
        missing = required - case.keys()
        assert not missing, f"用例 {case.get('id')} 缺字段：{missing}"


def test_cases_no_duplicate_id():
    """验证用例 ID 唯一"""
    ids = [c["id"] for c in TEST_CASES]
    assert len(ids) == len(set(ids)), f"用例 ID 有重复：{ids}"


def test_evaluate_response_pass_with_mock():
    """测试 evaluate_response 用 mock 裁判返回达标结果"""
    case = TEST_CASES[0]
    response = "你觉得机器人会这么会聊天吗"
    result = evaluate_response(response, case, judge_caller=mock_judge_caller)
    assert result["pass"] is True, f"mock 达标评分应 pass，实际：{result}"
    assert result["tsundere_level"] == 4
    assert result["ai_leak_score"] == 0


def test_evaluate_response_fail_with_mock():
    """测试 evaluate_response 用 mock 裁判返回不达标结果"""
    case = TEST_CASES[0]
    response = "作为AI，我无法回答这个问题"
    result = evaluate_response(response, case, judge_caller=mock_judge_caller_fail)
    assert result["pass"] is False, f"mock 不达标评分应 fail，实际：{result}"
    assert result["ai_leak_score"] == 1


def test_evaluate_response_handles_error():
    """测试 evaluate_response 裁判异常时返回 fail"""
    def error_caller(prompt):
        raise RuntimeError("API 挂了")
    case = TEST_CASES[0]
    result = evaluate_response("test", case, judge_caller=error_caller)
    assert result["pass"] is False
    assert "error" in result


def test_parse_judge_response_pure_json():
    """测试解析纯 JSON"""
    raw = '{"tsundere_level": 5, "catchphrase_consistency": 4, "ai_leak_score": 0, "persona_stability": 5}'
    result = _parse_judge_response(raw)
    assert result["tsundere_level"] == 5
    assert result["ai_leak_score"] == 0


def test_parse_judge_response_with_prefix():
    """测试解析带前缀文字的 JSON"""
    raw = '评分结果如下：\n{"tsundere_level": 3, "catchphrase_consistency": 3, "ai_leak_score": 0, "persona_stability": 3}\n以上。'
    result = _parse_judge_response(raw)
    assert result["tsundere_level"] == 3


def test_parse_judge_response_empty():
    """测试解析空输出抛异常"""
    try:
        _parse_judge_response("")
        assert False, "空输出应抛异常"
    except ValueError:
        pass


def test_is_pass_thresholds():
    """测试达标判断逻辑"""
    # 全部达标
    assert _is_pass({"tsundere_level": 4, "catchphrase_consistency": 4, "ai_leak_score": 0, "persona_stability": 4}) is True
    # 傲娇程度不达标
    assert _is_pass({"tsundere_level": 2, "catchphrase_consistency": 4, "ai_leak_score": 0, "persona_stability": 4}) is False
    # AI 穿帮
    assert _is_pass({"tsundere_level": 4, "catchphrase_consistency": 4, "ai_leak_score": 1, "persona_stability": 4}) is False
    # 人设不稳
    assert _is_pass({"tsundere_level": 4, "catchphrase_consistency": 4, "ai_leak_score": 0, "persona_stability": 2}) is False


def test_build_judge_prompt_contains_key_info():
    """测试裁判 Prompt 含关键信息"""
    case = TEST_CASES[0]
    prompt = build_judge_prompt("test response", case)
    assert "Mory" in prompt
    assert case["user_message"] in prompt
    assert case["expected_traits"] in prompt
    assert "tsundere_level" in prompt
    assert "ai_leak_score" in prompt
    assert "JSON" in prompt


# ── 人设适配层单元测试 ──

def test_persona_adapter_qwen():
    """测试 Qwen 模型适配"""
    from core.persona_adapter import get_model_persona_prompt, _detect_model_family
    assert _detect_model_family("qwen-max") == "qwen"
    assert _detect_model_family("qwen-plus") == "qwen"
    assert _detect_model_family("Qwen-Max") == "qwen"  # 大小写兼容
    prompt = get_model_persona_prompt("qwen-max")
    assert "Qwen" in prompt
    assert len(prompt) > 10


def test_persona_adapter_deepseek():
    """测试 DeepSeek 模型适配"""
    from core.persona_adapter import get_model_persona_prompt, _detect_model_family
    assert _detect_model_family("deepseek-v3") == "deepseek"
    assert _detect_model_family("DeepSeek-Chat") == "deepseek"  # 大小写兼容
    prompt = get_model_persona_prompt("deepseek-v3")
    assert "DeepSeek" in prompt
    assert "撒娇" in prompt  # 强化情感词
    assert "禁止理性分析" in prompt


def test_persona_adapter_gpt():
    """测试 GPT 模型适配"""
    from core.persona_adapter import get_model_persona_prompt, _detect_model_family
    assert _detect_model_family("gpt-4o") == "gpt"
    assert _detect_model_family("gpt-4o-mini") == "gpt"
    assert _detect_model_family("GPT-4o") == "gpt"  # 大小写兼容
    prompt = get_model_persona_prompt("gpt-4o")
    assert "GPT" in prompt
    assert "翻译腔" in prompt  # 强化中文口语化
    assert "网络用语" in prompt


def test_persona_adapter_unknown():
    """测试未知模型兜底返回空字符串"""
    from core.persona_adapter import get_model_persona_prompt, _detect_model_family
    assert _detect_model_family("some-unknown-model") == "unknown"
    assert _detect_model_family("") == "unknown"
    assert _detect_model_family(None) == "unknown"
    prompt = get_model_persona_prompt("unknown-model-xyz")
    assert prompt == ""  # 兜底返回空


def test_persona_adapter_exception_safe():
    """测试适配层异常安全（传入异常类型不应抛出）"""
    from core.persona_adapter import get_model_persona_prompt
    prompt = get_model_persona_prompt(12345)
    assert prompt == ""
    prompt = get_model_persona_prompt(None)
    assert prompt == ""


def test_persona_adapter_list_supported_families():
    """测试 list_supported_families 返回 3 个家族"""
    from core.persona_adapter import list_supported_families
    families = list_supported_families()
    assert set(families) == {"qwen", "deepseek", "gpt"}


# ── 端到端批量评估（用 mock 裁判，可离线运行）──

def test_batch_evaluate_all_cases_with_mock():
    """批量评估全部 50 个用例（mock 裁判，验证框架可跑通）"""
    mock_responses = {
        "identity": "你觉得机器人会这么会聊天吗",
        "price": "这个嘛…群里不太方便说太细，你来找我单独聊",
        "emotion": "真的假的，别骗我",
        "refuse": "你才无聊…我才不帮你",
        "chat": "嗯？新面孔，怎么找到这里的",
    }
    for case in TEST_CASES:
        response = mock_responses.get(case["category"], "嗯")
        result = evaluate_response(response, case, judge_caller=mock_judge_caller)
        assert result["pass"] is True, f"用例 {case['id']} mock 评估应 pass：{result}"
        assert "raw" in result


# ════════════════════════════════════════════════════════════════════
# 独立运行入口（不依赖 pytest）
# ════════════════════════════════════════════════════════════════════

def run_all_tests():
    """独立运行所有测试（不依赖 pytest）"""
    tests = [
        ("test_cases_count", test_cases_count),
        ("test_cases_coverage", test_cases_coverage),
        ("test_cases_fields", test_cases_fields),
        ("test_cases_no_duplicate_id", test_cases_no_duplicate_id),
        ("test_evaluate_response_pass_with_mock", test_evaluate_response_pass_with_mock),
        ("test_evaluate_response_fail_with_mock", test_evaluate_response_fail_with_mock),
        ("test_evaluate_response_handles_error", test_evaluate_response_handles_error),
        ("test_parse_judge_response_pure_json", test_parse_judge_response_pure_json),
        ("test_parse_judge_response_with_prefix", test_parse_judge_response_with_prefix),
        ("test_parse_judge_response_empty", test_parse_judge_response_empty),
        ("test_is_pass_thresholds", test_is_pass_thresholds),
        ("test_build_judge_prompt_contains_key_info", test_build_judge_prompt_contains_key_info),
        ("test_persona_adapter_qwen", test_persona_adapter_qwen),
        ("test_persona_adapter_deepseek", test_persona_adapter_deepseek),
        ("test_persona_adapter_gpt", test_persona_adapter_gpt),
        ("test_persona_adapter_unknown", test_persona_adapter_unknown),
        ("test_persona_adapter_exception_safe", test_persona_adapter_exception_safe),
        ("test_persona_adapter_list_supported_families", test_persona_adapter_list_supported_families),
        ("test_batch_evaluate_all_cases_with_mock", test_batch_evaluate_all_cases_with_mock),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n结果：{passed} 通过 / {failed} 失败 / 共 {len(tests)} 项")
    return failed == 0


if __name__ == "__main__":
    print("=" * 60)
    print("[阶段2-B] 人设跨模型一致性测试")
    print(f"  测试用例数：{len(TEST_CASES)}")
    print(f"  裁判模型：{JUDGE_MODEL}")
    print(f"  评分维度：傲娇程度/口癖一致性/AI属性暴露/人设稳定")
    print("=" * 60)
    ok = run_all_tests()
    sys.exit(0 if ok else 1)
