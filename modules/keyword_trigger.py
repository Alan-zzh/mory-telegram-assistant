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

_DEFAULT_SPECIAL_AUTO_REPLIES = (
    {
        "name": "VPN/梯子推荐",
        "topic": "VPN/梯子推荐",
        "enabled": True,
        "keywords": [
            "vpn", "梯子", "翻墙", "科学上网", "代理软件", "网络代理",
            "外网加速器", "机场推荐", "节点推荐",
        ],
        "contextual_followups": [
            "群友有没有", "还有没有", "还有吗", "有吗", "链接呢", "地址呢",
            "在哪里", "在哪", "怎么用", "怎么下载",
        ],
        "excluded_keywords": ["不用了", "不需要", "不想要", "不要推荐", "已经有", "有了"],
        "ai_polish": False,
        "ai_mode": "normal",
        "conversion_target": "none",
        "ignore_conversion_target": True,
        "card_enabled": False,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "remember_context": True,
        "base_reply": (
            "可以试试这个，免费用，不好用删掉就行。\n"
            '体验地址 ➡️ <a href="https://getsapp.net/tQtX3e">'
            "https://getsapp.net/tQtX3e</a>"
        ),
    },
    {
        "name": "助理唤醒",
        "topic": "助理唤醒",
        "enabled": True,
        "keywords": ["小助理出来", "助理出来", "小助理在吗", "助理在吗"],
        "ai_polish": True,
        "ai_mode": "normal",
        "conversion_target": "none",
        "polish_prompt": (
            "按当前人设自然应答，先让对方知道你在，再问对方当前想聊什么；"
            "不要主动带预览、下单、订阅或人工联系入口。"
        ),
        "required_terms": [],
        "forbidden_terms": ["亲", "客服", "限时", "优惠"],
        "base_reply": "在。怎么啦，直接说你想聊什么。",
    },
    {
        "name": "签到积分福利",
        "topic": "签到积分",
        "enabled": True,
        "keywords": [
            "签到积分有什么福利",
            "签到积分能换什么",
            "积分有什么福利",
            "积分能换什么",
            "签到有什么福利",
            "签到福利",
        ],
        "ai_polish": True,
        "ai_mode": "normal",
        "conversion_target": "preview",
        "polish_prompt": (
            "只说明当前可用内容和福利以预览实际展示为准；"
            "不承诺兑换物、库存、价格、权益或人工处理。"
        ),
        "required_terms": ["@moryselect"],
        "forbidden_terms": ["现金", "返现", "保证", "免费"],
        "base_reply": "当前可用内容和福利以 @moryselect 的预览为准，你先看一眼再判断。",
    },
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

    def handle_message(
        self,
        text: str,
        chat_id: int,
        message,
        bot,
        is_admin: bool = False,
        conversation_history=None,
    ) -> bool:
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

            if self._handle_private_mystic(text, chat_id, message, bot):
                return True

            special_rule = self._match_special_rule(
                text,
                conversation_history=conversation_history,
            )
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

    def _handle_private_mystic(self, text: str, chat_id: int, message, bot) -> bool:
        """私聊明确占卜请求走本地引擎，在进入 LLM 前直接承接。"""
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "") or "")
        is_private = chat_type == "private" or (not chat_type and int(chat_id or 0) > 0)
        cfg = self.config.get("MYSTIC_BROADCAST_CONFIG", {})
        if not is_private or not isinstance(cfg, dict):
            return False
        if not bool(cfg.get("private_reply_enabled", False)):
            return False
        try:
            from tasks.support.mystic_content import build_private_mystic_reply

            user = getattr(message, "from_user", None)
            user_id = int(getattr(user, "id", 0) or 0)
            reply = build_private_mystic_reply(text, user_id)
            if not reply:
                return False
            if self.mory_bot:
                self.mory_bot.reply_and_track(message, reply["text"])
            else:
                bot.reply_to(message, reply["text"])
            self._record_topic_reply(
                {
                    "name": "私聊本地占卜",
                    "topic": f"mystic_{reply['mode']}",
                    "ai_mode": "local_zero_token",
                },
                message,
                chat_id,
                reply["mode"],
                False,
            )
            logger.info(
                "🔮 私聊本地占卜回复成功: mode=%s token=0",
                reply["mode"],
            )
            return True
        except Exception as e:
            logger.error(f"🔮 私聊本地占卜回复失败: {e}")
            return False

    def _match_special_rule(self, text: str, conversation_history=None):
        """匹配特定词规则；配置可覆盖或关闭同名内置规则。"""
        rules = self._effective_special_rules()

        # 早路由绝不能抢走明确购买或泛定制的统一判定。只有规则声明的目标
        # 与 resolve_conversion_target 一致时才允许静态/润色回复。
        try:
            from core.growth_optimizer import resolve_conversion_target
            conversion_target, conversion_reason = resolve_conversion_target(text, mode="normal")
        except Exception as exc:
            logger.debug("关键词早路由转化判定跳过: %s", exc)
            conversion_target, conversion_reason = "none", ""
        # 泛定制/概念解释不能被静态规则截走；必须交给主链按上下文承接。
        if conversion_target == "subscribe" or conversion_reason == "custom_information_only":
            return None

        text_lower = text.lower()
        best_rule = None
        best_len = -1
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if not rule.get("enabled", True):
                continue
            excluded_keywords = rule.get("excluded_keywords", [])
            if isinstance(excluded_keywords, str):
                excluded_keywords = [excluded_keywords]
            if any(
                str(keyword).lower() in text_lower
                for keyword in excluded_keywords
                if keyword
            ):
                continue
            rule_target = str(rule.get("conversion_target", "none")).strip().lower()
            # 价格、内容、福利这类“了解型”静态问法可安全收敛到预览；
            # 但明确购买必须完整交给主成交链，其他 target 严格一致。
            allow_preview_from_none = (
                rule_target == "preview"
                and conversion_target == "none"
                and bool(rule.get("allow_preview_from_none", True))
            )
            if (
                not rule.get("ignore_conversion_target", False)
                and rule_target != conversion_target
                and not allow_preview_from_none
            ):
                continue

            keywords = rule.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]

            matched_len = -1
            for keyword in keywords:
                if not keyword:
                    continue
                keyword_lower = str(keyword).lower()
                if keyword_lower in text_lower:
                    matched_len = max(matched_len, len(keyword_lower))

            if matched_len < 0 and self._is_contextual_followup(
                rule,
                text_lower,
                conversation_history,
            ):
                matched_len = max(
                    len(str(marker))
                    for marker in rule.get("contextual_followups", [])
                    if marker and str(marker).lower() in text_lower
                )

            if matched_len > best_len:
                best_rule = rule
                best_len = matched_len
        return best_rule

    @staticmethod
    def _is_contextual_followup(rule, text_lower: str, conversation_history) -> bool:
        """仅在最近同一会话明确提过本规则关键词时承接短追问。"""
        followups = rule.get("contextual_followups", [])
        if isinstance(followups, str):
            followups = [followups]
        if not any(
            str(marker).lower() in text_lower
            for marker in followups
            if marker
        ):
            return False

        keywords = rule.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        recent = list(conversation_history or [])[-4:]
        for item in recent:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).lower()
            if any(str(keyword).lower() in content for keyword in keywords if keyword):
                return True
        return False

    def _effective_special_rules(self):
        """合并项目内置规则和配置规则，保留 Dashboard 的同名覆盖能力。"""
        configured = self.config.get("SPECIAL_AUTO_REPLIES", [])
        if not isinstance(configured, list):
            configured = []

        configured_names = {
            str(rule.get("name", "")).strip()
            for rule in configured
            if isinstance(rule, dict)
        }
        rules = list(configured)
        rules.extend(
            dict(rule)
            for rule in _DEFAULT_SPECIAL_AUTO_REPLIES
            if rule["name"] not in configured_names
        )
        return rules

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
                    "请按当前已加载的Mory人设，把下面的业务底稿润色成一次自然回复。\n"
                    "硬约束：\n"
                    "1. 底稿原文是唯一信息源，逐句顺着原文意思精修，只做语气和措辞的打磨；"
                    "禁止重写、扩写、增删信息点或另起一段新文案。\n"
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

            if not self._send_special_reply(message, chat_id, final_reply, rule, bot):
                return False
            self._record_topic_reply(
                rule,
                message,
                chat_id,
                matched_keyword,
                was_polished,
                final_reply,
            )
            logger.info(f"🔑 特定词自动回复成功: {rule.get('name', '未命名规则')}")
            return True
        except Exception as e:
            logger.error(f"🔑 特定词自动回复失败: {e}")
            return False

    def _send_special_reply(self, message, chat_id: int, final_reply: str, rule, bot) -> bool:
        """发送特定词自动回复；卡片开关开启时走 Rich→HTML→纯文本回退链。

        AUTO_REPLY_CARD_ENABLED=false 时保持旧行为（纯文本 reply），回归安全。
        卡片模式下私聊不挂按钮（红线），群聊挂单入口按钮。
        """
        from core.auto_reply_card import (
            build_auto_reply_card,
            is_auto_reply_card_enabled,
            is_rich_message_enabled,
        )

        direct_kwargs = self._direct_reply_kwargs(rule)
        if (
            not is_auto_reply_card_enabled(self.config)
            or not rule.get("card_enabled", True)
        ):
            if self.mory_bot:
                return bool(
                    self.mory_bot.reply_and_track(
                        message,
                        final_reply,
                        **direct_kwargs,
                    )
                )
            return bool(bot.reply_to(message, final_reply, **direct_kwargs))

        try:
            card = build_auto_reply_card(rule, final_reply, chat_id, self.config)
        except Exception as e:
            logger.warning(f"🔑 自动回复卡片构建失败，回退纯文本: {e}")
            card = None

        if not card:
            if self.mory_bot:
                return bool(self.mory_bot.reply_and_track(message, final_reply))
            return bool(bot.reply_to(message, final_reply))

        sent = None
        rich_html = card.get("rich_html", "")
        if rich_html and is_rich_message_enabled(self.config):
            raw_bot = getattr(self.mory_bot, "_bot", None) or bot
            try:
                from core.telebot_compat import send_rich_message_compat

                sent = send_rich_message_compat(
                    raw_bot,
                    chat_id,
                    rich_html,
                    reply_markup=card.get("markup"),
                )
                if sent and hasattr(sent, "message_id") and int(chat_id or 0) < 0:
                    try:
                        self.db.track_channel_message(chat_id, sent.message_id, "rich")
                    except Exception as e:
                        logger.debug(f"🔑 Rich 消息追踪入库失败: {e}")
                logger.info(f"🔑 特定词自动回复成功（Rich 卡片）: {rule.get('name', '未命名规则')}")
            except Exception as e:
                logger.warning(f"🔑 Rich 卡片发送失败，回退 HTML: {e}")
                sent = None

        if sent is None:
            html_text = card.get("html_text", "")
            send_kwargs = {}
            if html_text:
                send_kwargs = {"parse_mode": "HTML", "reply_markup": card.get("markup")}
            try:
                if self.mory_bot:
                    sent = self.mory_bot.reply_and_track(
                        message, html_text or final_reply, **send_kwargs
                    )
                else:
                    sent = bot.reply_to(message, html_text or final_reply, **send_kwargs)
            except Exception as e:
                logger.warning(f"🔑 HTML 卡片发送失败，回退纯文本: {e}")
                sent = None

        if sent is None:
            try:
                if self.mory_bot:
                    sent = self.mory_bot.reply_and_track(message, final_reply)
                else:
                    sent = bot.reply_to(message, final_reply)
            except Exception as e:
                logger.error(f"🔑 特定词自动回复发送失败: {e}")
                return False
        return bool(sent)

    @staticmethod
    def _direct_reply_kwargs(rule) -> dict:
        """只放行 Telegram 支持的确定性格式参数，避免配置注入任意发送参数。"""
        kwargs = {}
        parse_mode = str(rule.get("parse_mode", "") or "").strip()
        if parse_mode in {"HTML", "Markdown", "MarkdownV2"}:
            kwargs["parse_mode"] = parse_mode
        if rule.get("disable_web_page_preview", False):
            kwargs["disable_web_page_preview"] = True
        return kwargs

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
        reply_text: str = "",
    ):
        """用现有 telemetry_events 记录关键话题，不保存用户原文。"""
        user = getattr(message, "from_user", None)
        user_id = int(getattr(user, "id", 0) or 0)
        topic = str(
            rule.get("topic")
            or matched_keyword
            or rule.get("name")
            or "未分类"
        ).strip()[:64]
        try:
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

        if rule.get("remember_context", False):
            try:
                recorder = getattr(self.db, "record_business_context", None)
                if callable(recorder):
                    recorder(
                        user_id,
                        int(chat_id or 0),
                        str(getattr(message, "text", "") or "")[:500],
                        str(reply_text or "")[:500],
                        intent=topic,
                        conversion_target="none",
                        conversion_reason="special_rule",
                    )
            except Exception as e:
                logger.warning(f"🔑 特定词短期上下文写入失败: {e}")

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
