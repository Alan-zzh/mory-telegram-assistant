# 意图路由系统（v5.19.0）
"""
[TRAE SOLO CN] v5.19.0 两级意图分类：规则兜底 + 大模型精分类。
Level 1: 复用 ai_engine._classify_intent（零 TOKEN 规则引擎，6 类意图）。
Level 2: 仅低置信度消息触发 Function Calling 精分类（走 llm_light 池，省 TOKEN）。
默认关闭（INTENT_ROUTING_ENABLED=false）。
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 5 类标准意图（路由分发用，与 ai_engine 的 6 类对齐映射）
_STANDARD_INTENTS = {"chat", "purchase_intent", "flirt", "complaint", "consult"}


class IntentRouter:
    """[TRAE SOLO CN] v5.19.0 两级意图路由器。"""

    def __init__(self, ai_engine, config: dict):
        """初始化。

        Args:
            ai_engine: AIEngine 实例（提供 _classify_intent 和 ask 接口）
            config: 配置字典
        """
        self.ai = ai_engine
        self.config = config
        self._rule_threshold = float(config.get("INTENT_RULE_THRESHOLD", 2.0))

    def classify(self, text: str, conversation_history: list[dict] | None = None) -> Dict:
        """两级分类，返回 {intent, confidence, source}。

        Returns:
            intent: chat / purchase_intent / flirt / complaint / consult
            confidence: 0.0-1.0
            source: rule / llm / rule_fallback / disabled
        """
        if not self.config.get("INTENT_ROUTING_ENABLED", False):
            return {"intent": "chat", "confidence": 0.0, "source": "disabled"}

        if not text or not isinstance(text, str):
            return {"intent": "chat", "confidence": 0.0, "source": "rule"}

        try:
            from core.conversion_glue import is_contextual_purchase_intent
            from core.keyword_manager import is_convert_rejection_message
            if is_convert_rejection_message(text):
                return {
                    "intent": "consult",
                    "confidence": 0.9,
                    "source": "rejection_rule",
                }
            if is_contextual_purchase_intent(text, conversation_history):
                return {
                    "intent": "purchase_intent",
                    "confidence": 0.95,
                    "source": "context_rule",
                }
        except Exception as e:
            logger.debug(f"上下文购买意图判断失败，继续单句分类: {e}")

        # Level 1: 规则引擎（零 TOKEN）
        intent, score = self._rule_classify(text)
        if score >= self._rule_threshold:
            return {"intent": intent, "confidence": min(1.0, score / 5.0), "source": "rule"}

        # Level 2: 大模型精分类（仅低置信度触发，省 TOKEN）
        if self.config.get("INTENT_LLM_ENABLED", False) and score < self._rule_threshold:
            return self._llm_classify(text)

        return {"intent": intent, "confidence": min(1.0, score / 5.0), "source": "rule_fallback"}

    def _rule_classify(self, text: str) -> tuple:
        """[TRAE SOLO CN] v5.19.0 复用 ai_engine._classify_intent，扩展返回分数。

        ai_engine 6 类意图映射到 5 类标准：
            flirt → flirt
            business → purchase_intent
            complaint → complaint
            help → consult
            bored / chat → chat
        """
        if not self.ai or not hasattr(self.ai, "_classify_intent"):
            return ("chat", 0.0)
        msg_lower = text.lower()
        scores = {}
        intent_keywords = getattr(self.ai, "_INTENT_KEYWORDS", {})
        for intent, cfg in intent_keywords.items():
            kws = cfg.get("keywords", [])
            if not kws:
                continue
            hit = sum(1 for kw in kws if kw in msg_lower)
            if hit > 0:
                scores[intent] = hit * cfg.get("weight", 1.0)
        if not scores:
            return ("chat", 0.0)
        raw_intent = max(scores, key=scores.get)
        score = scores[raw_intent]
        # 映射到标准意图
        mapping = {
            "flirt": "flirt",
            "business": "purchase_intent",
            "complaint": "complaint",
            "help": "consult",
            "bored": "chat",
            "chat": "chat",
        }
        return (mapping.get(raw_intent, "chat"), score)

    def _llm_classify(self, text: str) -> Dict:
        """[TRAE SOLO CN] v5.19.0 Function Calling 精分类，走 llm_light 池。

        使用 mode='intent_classify' 触发轻量模型池，避免占用标准池资源。
        """
        tools = [{
            "type": "function",
            "function": {
                "name": "classify_intent",
                "description": "将用户消息分类为 5 类意图之一",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "enum": list(_STANDARD_INTENTS),
                        },
                        "confidence": {"type": "number"},
                    },
                    "required": ["intent"],
                },
            },
        }]
        try:
            result = self.ai.ask(
                text, mode="intent_classify", tools=tools, tool_choice="auto"
            )
            # 解析 tool_calls（ai_engine 返回格式：字符串或带 tool_calls 的对象）
            parsed = self._parse_tool_result(result)
            if parsed:
                return {
                    "intent": parsed.get("intent", "chat"),
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "source": "llm",
                }
        except Exception as e:
            logger.debug(f"LLM 意图分类失败，降级规则: {e}")
        # 降级到规则
        intent, score = self._rule_classify(text)
        return {"intent": intent, "confidence": min(1.0, score / 5.0), "source": "rule_fallback"}

    def _parse_tool_result(self, result) -> Optional[Dict]:
        """解析 ai_engine.ask 返回的 tool_calls 结果。"""
        if isinstance(result, dict):
            tool_calls = result.get("tool_calls") or []
            for tc in tool_calls:
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                args_str = func.get("arguments", "{}")
                try:
                    import json
                    return json.loads(args_str) if isinstance(args_str, str) else args_str
                except Exception as e:
                    # 畸形/截断的工具参数不可静默丢弃，否则用户只看到"没执行"无从排查
                    logger.debug(f"工具调用参数解析失败（非致命，跳过该次函数调用）：func={func.get('name')} err={e}")
                    continue
        return None
