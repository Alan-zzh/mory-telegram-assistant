"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/persona_adapter.py  ·  人设跨模型一致性适配层（阶段2-B）         ║
║                                                                        ║
║  功能：                                                                ║
║    1. 统一人设对齐层，防止 DeepSeek/Qwen/GPT 不同模型在人设表现上抖动   ║
║    2. get_model_persona_prompt(model_name, mode) → str                 ║
║    3. 按模型家族返回定制化人设 Prompt 片段：                           ║
║       - Qwen-Max/Plus：中文网络文学语境强，傲娇口癖自然，用标准人设    ║
║       - DeepSeek-V3：偏理性逻辑，强化情感词和口癖指令                  ║
║       - GPT-4o/4o-mini：结构化强，强化中文口语化指令                  ║
║       - 未知模型：标准人设 Prompt 兜底（返回空字符串）                 ║
║                                                                        ║
║  调用方：core/ai_engine.py:_build_persona()                            ║
║  设计原则：                                                             ║
║    - 纯函数，无副作用，异常不影响主流程                                 ║
║    - 返回额外 Prompt 片段，由调用方拼接到 System Prompt 末尾            ║
║    - 向后兼容：未知模型返回空字符串                                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from core.logging_util import get_logger

logger = get_logger("persona_adapter")


# ── 模型家族识别关键词 ──────────────────────────────────────────────
# 按优先级匹配，先匹配到的家族胜出。关键词用小写，匹配时模型名转小写。
_MODEL_FAMILY_KEYWORDS = {
    "qwen": [
        "qwen-max", "qwen-plus", "qwen-turbo", "qwen-flash",
        "qwen2", "qwen2.5", "qwen3", "qwen-omni",
    ],
    "deepseek": [
        "deepseek-v3", "deepseek-chat", "deepseek-coder",
        "deepseek-r1", "deepseek-lite", "deepseek-v3-lite",
    ],
    "gpt": [
        "gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-4-turbo",
        "gpt-3.5", "gpt-4.1", "gpt-4.5",
    ],
}


# ── 各模型家族的人设适配策略 ────────────────────────────────────────
# 每个家族返回一段额外 Prompt 片段，强化该模型容易缺失的人设维度。
# 设计依据：
#   - Qwen：中文网络文学训练充分，傲娇口癖自然，只需轻约束防过载
#   - DeepSeek：代码/逻辑训练偏重，易出理性分析腔，需强化情感和口癖
#   - GPT：英文结构化思维强，易出翻译腔，需强化中文口语化

_PERSONA_ADAPTER_STRATEGIES = {
    # Qwen 家族：中文网络文学语境强，傲娇口癖自然，用标准人设 Prompt
    # 仅追加一条轻量约束，防止口癖堆砌过度
    "qwen": (
        "\n\n【模型适配·Qwen】"
        "\n你天生擅长中文网络语境，傲娇口癖保持自然即可。"
        "\n约束：禁止过度使用'哼''嘁'等口癖堆砌，单条回复口癖不超过2个。"
    ),
    # DeepSeek 家族：偏理性逻辑，需强化情感词和口癖指令
    "deepseek": (
        "\n\n【模型适配·DeepSeek】"
        "\n你必须强化情感表达，禁止理性分析式回复。"
        "\n约束1：必须使用撒娇语气，禁止用'根据''分析''建议'等理性词汇。"
        "\n约束2：必须包含至少1个傲娇口癖（如'哼''才不''谁稀罕'）。"
        "\n约束3：禁止用'首先''其次''最后'等结构化表达。"
        "\n约束4：回复必须像情绪化的真人，不像理性的分析师。"
    ),
    # GPT 家族：结构化强，需强化中文口语化指令
    "gpt": (
        "\n\n【模型适配·GPT】"
        "\n你必须强化中文口语化表达，禁止翻译腔。"
        "\n约束1：禁止翻译腔，不用'我认为''在我看来''正如你所知'等书面语。"
        "\n约束2：必须用中文网络用语，如'绝了''离谱''笑死''无语'。"
        "\n约束3：禁止用'However''Therefore''In addition'等英文连接词的中文翻译。"
        "\n约束4：回复必须像中国网友聊天，不像翻译软件。"
    ),
}


def _detect_model_family(model_name: str) -> str:
    """根据模型名识别模型家族（qwen/deepseek/gpt/unknown）。

    Args:
        model_name: 模型名，如 qwen-max / deepseek-v3 / gpt-4o

    Returns:
        家族名：qwen / deepseek / gpt / unknown
    """
    if not model_name or not isinstance(model_name, str):
        return "unknown"
    name_lower = model_name.lower()
    for family, keywords in _MODEL_FAMILY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return family
    return "unknown"


def get_model_persona_prompt(model_name: str, mode: str = "normal") -> str:
    """根据模型名返回定制化人设 Prompt 片段。

    Args:
        model_name: 模型名（如 qwen-max / deepseek-v3 / gpt-4o）
        mode: 当前对话模式（预留扩展，目前未使用）

    Returns:
        额外的人设 Prompt 片段，拼接到 System Prompt 末尾。
        未知模型返回空字符串（兜底，向后兼容）。

    设计原则：
        - 纯函数，无副作用
        - 异常时返回空字符串，不影响主流程
        - 未知模型用标准人设 Prompt（兜底）
    """
    try:
        family = _detect_model_family(model_name)
        if family == "unknown":
            # 未知模型：用标准人设 Prompt（兜底），不追加额外约束
            logger.debug(f"未知模型家族：{model_name}，使用标准人设 Prompt")
            return ""
        return _PERSONA_ADAPTER_STRATEGIES.get(family, "")
    except Exception as e:
        logger.warning(f"⚡ 人设适配层异常（不影响主流程）：{e}")
        return ""


def list_supported_families() -> list:
    """返回当前支持的模型家族列表（供测试/监控使用）"""
    return list(_PERSONA_ADAPTER_STRATEGIES.keys())
