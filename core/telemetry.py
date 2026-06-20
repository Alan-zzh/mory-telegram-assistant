# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/telemetry.py  ·  Telemetry 埋点系统（v1.0）                       ║
║                                                                        ║
║  功能：                                                                ║
║    1. 事件埋点 —— 曝光 / 点击 / 转化 / 退群 / 投诉等                   ║
║    2. 对话埋点 —— 记录用户消息与 Bot 回复，用于后续话术分析             ║
║    3. 轻量情感标记 —— 基于关键词规则的情感极性判断                      ║
║    4. 批量异步写入 —— 不阻塞主消息流程                                  ║
║                                                                        ║
║  被调用：core/handlers/ai_reply_handler.py, modules/scheduled_broadcast ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from core.logging_util import get_logger

logger = get_logger("telemetry")

# 异步写入线程池（避免埋点阻塞主流程）
_telemetry_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="telemetry")

# 情感关键词规则（轻量，无需 NLP 库）
_SENTIMENT_RULES = {
    "positive": [
        "喜欢", "爱", "可爱", "好看", "漂亮", "美", "心动", "开心", "满意", "谢谢",
        "真好", "不错", "棒", "赞", "期待", "想买", "下单", "付款", "订阅", "开通",
        "VIP", "至臻", "会员", "多少钱", "价格", "怎么买"
    ],
    "negative": [
        "垃圾", "骗子", "骗", "差", "恶心", "讨厌", "失望", "后悔", "举报", "投诉",
        "退款", "滚", "傻逼", "贱", "丑", "假", "装", "死", "胖", "黑料", "退群",
        "离开", "不要", "别发", "烦"
    ],
}


def _detect_sentiment(text: str) -> str:
    """基于关键词规则判断情感极性"""
    if not text:
        return "neutral"
    text_lower = text.lower()
    pos_score = sum(1 for w in _SENTIMENT_RULES["positive"] if w in text_lower)
    neg_score = sum(1 for w in _SENTIMENT_RULES["negative"] if w in text_lower)
    if neg_score > pos_score:
        return "negative"
    if pos_score > neg_score:
        return "positive"
    return "neutral"


class Telemetry:
    """Telemetry 埋点客户端"""

    def __init__(self, db, config: dict):
        self.db = db
        self.config = config
        self._enabled = bool(config.get("AB_TEST_CONFIG", {}).get("telemetry_enabled", False))

    def _async_log(self, method_name: str, *args, **kwargs):
        """异步调用 db 的埋点方法"""
        if not self.db or not hasattr(self.db, method_name):
            return
        try:
            _telemetry_pool.submit(lambda: getattr(self.db, method_name)(*args, **kwargs))
        except Exception as e:
            logger.debug(f"Telemetry 异步提交失败: {e}")

    def log_event(self, user_id: int, chat_id: int, experiment_id: str, variant: str,
                  event_type: str, event_value: float = 0.0, event_meta: dict = None):
        """
        记录通用事件。
        event_type 枚举：
            exposure, engage, button_click, button_impression,
            consult, add_cart, conversion, group_leave, complaint,
            cart_abandoned, cart_recovered
        """
        if not self._enabled:
            return
        self._async_log("log_telemetry", user_id, chat_id, experiment_id, variant,
                        event_type, event_value, event_meta or {})

    def log_conversation(self, user_id: int, chat_id: int, experiment_id: str, variant: str,
                         message_text: str, bot_reply_text: str, intent: str = "", round_num: int = 0):
        """记录对话遥测，自动分析情感"""
        if not self._enabled:
            return
        sentiment = _detect_sentiment(message_text)
        self._async_log("log_conversation_telemetry", user_id, chat_id, experiment_id, variant,
                        message_text, bot_reply_text, intent, sentiment, round_num)

    def log_button_click(self, user_id: int, chat_id: int, button_id: str, style: str = "default"):
        """记录按钮点击（兼容现有 button_click_stats）"""
        if not self.db:
            return
        try:
            if hasattr(self.db, "record_button_click"):
                _telemetry_pool.submit(lambda: self.db.record_button_click(button_id, style))
        except Exception as e:
            logger.debug(f"按钮点击埋点失败: {e}")

    def log_conversion(self, user_id: int, chat_id: int, experiment_id: str = "", variant: str = "",
                       value: float = 0.0, event_meta: dict = None):
        """记录付费转化事件"""
        if not self._enabled:
            return
        self.log_event(user_id, chat_id, experiment_id, variant, "conversion", value, event_meta)

    def log_group_leave(self, user_id: int, chat_id: int, experiment_id: str = "", variant: str = ""):
        """记录退群事件"""
        if not self._enabled:
            return
        self.log_event(user_id, chat_id, experiment_id, variant, "group_leave")

    def log_complaint(self, user_id: int, chat_id: int, experiment_id: str = "", variant: str = "",
                      reason: str = ""):
        """记录投诉事件"""
        if not self._enabled:
            return
        self.log_event(user_id, chat_id, experiment_id, variant, "complaint", 0.0,
                       {"reason": reason})

    def log_cart_recovery(self, user_id: int, chat_id: int, recovered: bool = False,
                          experiment_id: str = "", variant: str = ""):
        """记录购物车挽回事件"""
        if not self._enabled:
            return
        evt = "cart_recovered" if recovered else "cart_abandoned"
        self.log_event(user_id, chat_id, experiment_id, variant, evt)


class TelemetryContext:
    """Telemetry 上下文管理器：用于单次消息处理生命周期内的批量埋点"""

    def __init__(self, telemetry: Telemetry, user_id: int, chat_id: int,
                 experiment_id: str = "", variant: str = ""):
        self.telemetry = telemetry
        self.user_id = user_id
        self.chat_id = chat_id
        self.experiment_id = experiment_id
        self.variant = variant
        self.round_num = 0

    def set_experiment(self, experiment_id: str, variant: str):
        """设置当前会话关联的实验"""
        self.experiment_id = experiment_id
        self.variant = variant

    def on_user_message(self, message_text: str, intent: str = ""):
        """用户发来消息时调用"""
        self.round_num += 1
        self.telemetry.log_event(self.user_id, self.chat_id, self.experiment_id, self.variant,
                                 "engage")
        return self

    def on_bot_reply(self, bot_reply_text: str, intent: str = ""):
        """Bot 回复后调用"""
        if not self.telemetry._enabled:
            return self
        self.telemetry.log_conversation(
            self.user_id, self.chat_id, self.experiment_id, self.variant,
            "", bot_reply_text, intent, self.round_num
        )
        return self

    def on_button_click(self, button_id: str, style: str = "default"):
        """用户点击按钮时调用"""
        self.telemetry.log_button_click(self.user_id, self.chat_id, button_id, style)
        self.telemetry.log_event(self.user_id, self.chat_id, self.experiment_id, self.variant,
                                 "button_click")
        return self

    def on_conversion(self, value: float = 0.0, meta: dict = None):
        """用户完成转化时调用"""
        self.telemetry.log_conversion(self.user_id, self.chat_id, self.experiment_id,
                                      self.variant, value, meta)
        return self
