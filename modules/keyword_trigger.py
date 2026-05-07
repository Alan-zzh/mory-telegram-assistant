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

import logging
import traceback
from core.logging_util import get_logger

logger = get_logger("keyword_trigger")


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
            if self.ai and rule.get("ai_polish", True):
                matched_keywords = rule.get("keywords", [])
                if isinstance(matched_keywords, list):
                    matched_keywords = "、".join(str(x) for x in matched_keywords if x)
                polish_prompt = (
                    "你是Mory的小助理，要把一段固定模板润色成更自然、更像真人聊天的话。\n"
                    "要求：\n"
                    "1. 保留原模板的核心意思，不要改成别的业务方向\n"
                    "2. 语气自然、亲近、有高情商，不要像客服，不要像公告\n"
                    "3. 可以略带一点撩人的感觉，但不要油腻\n"
                    "4. 如果模板里本来有转化引导，要保留这种引导，但要更自然\n"
                    "5. 不要写成太长，控制在2到4行内，适合Telegram直接回复\n"
                    f"6. 这次触发词大致是：{matched_keywords}\n\n"
                    f"用户刚说的话：{getattr(message, 'text', '') or ''}\n\n"
                    f"原模板：{base_reply}\n\n"
                    "请直接输出润色后的最终回复，不要解释。"
                )
                ai_reply = self.ai.ask(polish_prompt, mode=rule.get("ai_mode", "normal"))
                if ai_reply and len(ai_reply.strip()) >= 6:
                    final_reply = ai_reply.strip()

            if self.mory_bot:
                self.mory_bot.reply_and_track(message, final_reply)
            else:
                bot.reply_to(message, final_reply)
            logger.info(f"🔑 特定词自动回复成功: {rule.get('name', '未命名规则')}")
            return True
        except Exception as e:
            logger.error(f"🔑 特定词自动回复失败: {e}")
            return False
    
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
                    self.mory_bot.reply_without_track(message, "✅ 代码已更新，请在VPS执行 `bash start.sh restart` 重启Bot")
                else:
                    bot.reply_to(message, "🚀 部署已触发！")
                    bot.reply_to(message, "✅ 代码已更新，请在VPS执行 `bash start.sh restart` 重启Bot")
                return True
            else:
                logger.warning(f"🔑 未知的动作类型: {action_type}")
                return False
        except Exception as e:
            logger.error(f"🔑 动作执行失败: {e}")
            return False
