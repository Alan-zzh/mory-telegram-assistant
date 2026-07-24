#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║ modules/keyword_trigger.py  ·  关键词触发回复系统                        ║
║                                                                        ║
║ 功能：                                                                ║
║    根据用户输入的文本匹配关键词，然后执行相应的回复或动作。             ║
║    - static: 直接回复预设文本                                           ║
║    - ai: 调用AI生成回复                                                 ║
║    - action: 执行动作（如部署更新等）                                   ║
║                                                                        ║
║  被调用：main.py (消息处理流程中，在AI回复之前)                          ║
║══════════════════════════════════════════════════════════════════════════╝
║ v4.4.9 新增                                                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import traceback
from core.logging_util import get_logger

logger = get_logger("keyword_trigger")

_UNUSABLE_POLISH_MARKERS = (
    "原模板",
    "润色后",
    "提示词",
    "作为AI",
    "作为 AI",
    "脑子刚才短路",
    "刚才走神",
    "网络有点卡",
    "刚刚没反应过来",
    "轻食版",
)


class KeywordTrigger:
    """
    关键词触发回复管理器
    """
    
    def __init__(self, db, mory_bot=None, ai=None, config=None):
        self.db = db
        self.mory_bot = mory_bot
        self.ai = ai
        self.config = config or {}
        # 需要管理员权限才能触发的动作类型
        self._admin_actions = {"deploy", "restart", "backup", "restore", "sync"}
    
    def handle_message(self, text: str, chat_id: int, message, bot, is_admin: bool = False) -> bool:
        """
        处理消息，匹配关键词
        
        Args:
            text: 用户输入的文本
            chat_id: 聊天ID
            message: 消息对象
            bot: Telegram Bot实例
            is_admin: 是否为管理员
            
        Returns:
            True表示已处理（已回复/执行动作），False表示未匹配
        """
        try:
            if not text or len(text.strip()) == 0:
                return False

            special_rule = self._match_special_rule(text)
            if special_rule:
                return self._handle_special_rule(special_rule, chat_id, message, bot)
            
            matched_triggers = self.db.match_keyword_trigger(text)
            if not matched_triggers:
                return False
            
            logger.info(f"🔑 匹配到 {len(matched_triggers)} 个关键词触发")
            
            # 过滤掉非管理员不能触发的动作类型
            filtered_triggers = []
            for trigger in matched_triggers:
                if trigger["reply_type"] == "action":
                    action_type = trigger.get("action_type", "")
                    if action_type in self._admin_actions and not is_admin:
                        logger.info(f"🔑 跳过需要管理员权限的动作: {trigger['keyword']} (action={action_type})")
                        continue
                filtered_triggers.append(trigger)
            
            if not filtered_triggers:
                return False
            
            # 只处理第一个匹配的
            trigger = filtered_triggers[0]
            logger.info(f"🔑 使用触发: {trigger['keyword']}")
            
            if trigger["reply_type"] == "static":
                return self._handle_static(trigger, chat_id, message, bot)
            elif trigger["reply_type"] == "ai":
                return self._handle_ai(trigger, chat_id, message, bot)
            elif trigger["reply_type"] == "action":
                return self._handle_action(trigger, chat_id, message, bot)
            else:
                logger.warning(f"🔑 未知的触发类型: {trigger['reply_type']}")
                return False
                
        except Exception as e:
            logger.error(f"🔑 关键词触发处理异常: {e}")
            logger.error(traceback.format_exc())
            return False

    def _match_special_rule(self, text: str):
        """匹配配置中的特定词自动回复规则"""
        rules = self.config.get("SPECIAL_AUTO_REPLIES", [])
        if not isinstance(rules, list):
            return None

        text_lower = text.lower()
        best_rule = None
        best_len = -1
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if not rule.get("enabled", True):
                continue

            keywords = rule.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]

            for keyword in keywords:
                if not keyword:
                    continue
                keyword_lower = str(keyword).lower()
                if keyword_lower in text_lower and len(keyword_lower) > best_len:
                    best_rule = rule
                    best_len = len(keyword_lower)
        return best_rule

    def _handle_special_rule(self, rule, chat_id, message, bot):
        """处理配置里的特定词自动回复，并交给AI做润色"""
        try:
            base_reply = (rule.get("base_reply") or "").strip()
            if not base_reply:
                return False

            final_reply = base_reply
            was_polished = False
            user_text = (getattr(message, "text", "") or "").strip()
            matched_keyword = self._get_matched_keyword(rule, user_text)
            if self.ai and rule.get("ai_polish", True):
                rule_prompt = (rule.get("polish_prompt") or "").strip()
                polish_prompt = (
                    "请按当前已加载的Mory人设，把业务底稿改成一次自然回复。\n"
                    "硬约束：\n"
                    "1. 先正面回应用户这句话，再自然带出底稿里的有效信息。\n"
                    "2. 只写1到2句、25到70个汉字；不要标题、列表、解释或客服腔。\n"
                    "3. 不编造价格、优惠、库存、权益、交付能力；不确定就保守表达。\n"
                    "4. 底稿里的必要入口必须保留，其他措辞要换成当下对话的说法。\n"
                    "5. 禁止输出“原模板”“润色后”“提示词”等内部字样。\n"
                    f"本规则额外要求：{rule_prompt or '保持清冷自然，不硬推，不油腻。'}\n"
                    f"命中话题：{matched_keyword or rule.get('name', '业务咨询')}\n"
                    f"用户原话：{user_text[:180]}\n"
                    f"业务底稿：{base_reply[:300]}\n"
                    "直接输出最终回复。"
                )
                ai_reply = self.ai.ask(
                    polish_prompt,
                    mode=rule.get("ai_mode", "normal"),
                    is_priv=chat_id > 0,
                )
                if self._is_usable_polish(ai_reply, rule):
                    final_reply = ai_reply.strip().strip("\"'“”")
                    was_polished = True

            if self.mory_bot:
                self.mory_bot.reply_and_track(message, final_reply)
            else:
                bot.reply_to(message, final_reply)
            self._record_topic_reply(
                rule,
                message,
                chat_id,
                matched_keyword,
                was_polished,
            )
            logger.info(f"🔑 特定词自动回复成功: {rule.get('name', '未命名规则')}")
            return True
        except Exception as e:
            logger.error(f"🔑 特定词自动回复失败: {e}")
            return False

    @staticmethod
    def _get_matched_keyword(rule, user_text: str) -> str:
        """返回实际命中的最长关键词，供提示词与统计使用。"""
        keywords = rule.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        text_lower = user_text.lower()
        matched = [
            str(keyword).strip()
            for keyword in keywords
            if keyword and str(keyword).lower() in text_lower
        ]
        return max(matched, key=len) if matched else ""

    @staticmethod
    def _is_usable_polish(reply, rule=None) -> bool:
        """拒绝过短、过长、降级话术和内部说明，安全回退业务底稿。"""
        if not isinstance(reply, str):
            return False
        text = reply.strip()
        if not 6 <= len(text) <= 180:
            return False
        if any(marker in text for marker in _UNUSABLE_POLISH_MARKERS):
            return False
        rule = rule if isinstance(rule, dict) else {}
        required_terms = rule.get("required_terms", [])
        forbidden_terms = rule.get("forbidden_terms", [])
        if isinstance(required_terms, str):
            required_terms = [required_terms]
        if isinstance(forbidden_terms, str):
            forbidden_terms = [forbidden_terms]
        if any(str(term) not in text for term in required_terms if term):
            return False
        return not any(str(term) in text for term in forbidden_terms if term)

    def _record_topic_reply(
        self,
        rule,
        message,
        chat_id: int,
        matched_keyword: str,
        was_polished: bool,
    ):
        """用现有 telemetry_events 记录关键话题，不保存用户原文。"""
        try:
            user = getattr(message, "from_user", None)
            user_id = int(getattr(user, "id", 0) or 0)
            topic = str(
                rule.get("topic")
                or matched_keyword
                or rule.get("name")
                or "未分类"
            ).strip()[:64]
            self.db.log_telemetry(
                user_id,
                int(chat_id or 0),
                "topic_interest",
                topic,
                "reply_polished" if was_polished else "reply_template",
                1.0,
                {
                    "rule": str(rule.get("name", ""))[:64],
                    "matched_keyword": matched_keyword[:64],
                    "ai_mode": str(rule.get("ai_mode", "normal"))[:32],
                },
            )
        except Exception as e:
            logger.warning(f"🔑 关键话题统计写入失败: {e}")
    
    def _handle_static(self, trigger, chat_id, message, bot):
        reply_text = trigger["reply_text"]
        try:
            if self.mory_bot:
                self.mory_bot.reply_and_track(message, reply_text)
            else:
                bot.reply_to(message, reply_text)
            logger.info(f"🔑 静态回复成功: {trigger['keyword']}")
            return True
        except Exception as e:
            logger.error(f"🔑 静态回复失败: {e}")
            return False
    
    def _handle_ai(self, trigger, chat_id, message, bot):
        ai_prompt = trigger["reply_text"]
        try:
            if self.ai:
                ai_reply = self.ai.ask(ai_prompt, mode="normal")
                if ai_reply:
                    if self.mory_bot:
                        self.mory_bot.reply_and_track(message, ai_reply)
                    else:
                        bot.reply_to(message, ai_reply)
                    logger.info(f"🔑 AI回复成功: {trigger['keyword']}")
                    return True
            logger.warning("🔑 AI引擎不可用，无法执行AI回复")
            return False
        except Exception as e:
            logger.error(f"🔑 AI回复失败: {e}")
            return False
    
    def _handle_action(self, trigger, chat_id, message, bot):
        action_type = trigger.get("action_type", "")
        logger.info(f"🔑 执行动作: {action_type}")
        try:
            if action_type == "deploy":
                if self.mory_bot:
                    self.mory_bot.reply_without_track(message, "🚀 部署已触发！")
                    self.mory_bot.reply_without_track(message, "✅ 代码已更新，请在VPS执行 `sudo systemctl restart mory-assistant` 重启Bot")
                else:
                    bot.reply_to(message, "🚀 部署已触发！")
                    bot.reply_to(message, "✅ 代码已更新，请在VPS执行 `sudo systemctl restart mory-assistant` 重启Bot")
                return True
            else:
                logger.warning(f"🔑 未知的动作类型: {action_type}")
                return False
        except Exception as e:
            logger.error(f"🔑 动作执行失败: {e}")
            return False
