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

import re
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
    {
        "name": "积分兑换说明",
        "topic": "积分兑换",
        "enabled": True,
        "priority": 100,
        "keywords": [
            "积分怎么使用", "积分怎么用", "积分能兑换什么", "积分可以兑换什么",
            "积分换什么", "积分兑换什么", "多少积分能兑换", "兑换会员要多少积分",
        ],
        "contextual_followups": [
            "门槛多少", "多少积分", "怎么兑换", "在哪里兑换", "换什么",
            "90天能换吗", "签到90天可以吗", "多久能换",
        ],
        "followup_replies": [
            {
                "keywords": ["门槛多少", "多少积分", "兑换会员要多少"],
                "base_reply": "当前门槛是 14900 积分，可兑换 1 个月至臻精选会员；活动有时效，以群内当期积分商城展示为准。",
            },
            {
                "keywords": ["90天能换吗", "签到90天可以吗", "多久能换"],
                "base_reply": "连续签到约 90 天通常能攒到兑换门槛；是否正好够 14900 积分，要以你当时的积分余额和当期活动为准。",
            },
            {
                "keywords": ["怎么兑换", "在哪里兑换", "换什么"],
                "base_reply": "在群里发送“积分商城”，进入商城后按提示用 14900 积分兑换 1 个月至臻精选会员。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "none",
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "积分可以兑换至臻精选会员：在群里发送“积分商城”按提示操作，当前门槛是 14900 积分，可兑换 1 个月；活动有时效，以当期商城展示为准。",
    },
    {
        "name": "签到九十天兑换",
        "topic": "签到兑换",
        "enabled": True,
        "priority": 110,
        "keywords": [
            "签到90天能否兑换会员", "签到90天能兑换会员吗", "签到90天可以兑换会员吗",
            "签到九十天能兑换会员吗", "连续签到90天能换会员吗",
        ],
        "contextual_followups": ["我已经90天了", "已经90天", "够90天了", "接下来怎么办"],
        "followup_replies": [
            {
                "keywords": ["我已经90天了", "已经90天", "够90天了", "接下来怎么办"],
                "base_reply": "你先看积分余额是否达到 14900；达到后在群里发送“积分商城”兑换。若商城没有对应商品，把余额和签到记录发来，我帮你登记给 Mory 确认。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "none",
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "可以兑换 1 个月至臻精选会员，但活动有时效。先确认积分达到 14900，再在群里发送“积分商城”操作；如果你已连续签到 90 天却无法兑换，把情况发来，我帮你登记给 Mory 确认。",
    },
    {
        "name": "会员兑换未进群",
        "topic": "兑换未到账",
        "enabled": True,
        "priority": 120,
        "keywords": [
            "兑换成功但没进群", "兑换成功没有进群", "积分兑换了没进群",
            "兑换会员后没进群", "兑换成功了怎么没进群",
        ],
        "contextual_followups": ["要发什么", "订单号在哪", "怎么复制订单号", "凭证怎么发", "然后呢"],
        "followup_replies": [
            {
                "keywords": ["要发什么", "凭证怎么发", "然后呢"],
                "base_reply": "请发两样：购买或兑换成功的凭证截图，以及订单号文字。涉及支付信息时只保留核验所需部分，别发密码、验证码或完整账户资料。",
            },
            {
                "keywords": ["订单号在哪", "怎么复制订单号"],
                "base_reply": "回到你完成购买或兑换的机器人里找到对应订单，点击订单号即可复制；把订单号文字和凭证截图一起发来。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "none",
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "先回到你完成购买或兑换的机器人，找到订单并点击订单号复制；再把订单号文字和成功凭证截图发来，我帮你登记给 Mory 核对。不要发送密码、验证码或完整账户资料。",
    },
    {
        "name": "至臻全享群说明",
        "topic": "至臻全享",
        "enabled": True,
        "priority": 100,
        "keywords": [
            "至臻全享三个群分别是什么", "至臻全享是哪三个群", "全享三个群是什么",
            "三个群分别是什么", "全享包含哪些群", "至臻全享包括什么群",
        ],
        "contextual_followups": ["都是一年吗", "有效期多久", "时间多久", "能下载吗", "有水印吗", "分别有什么"],
        "followup_replies": [
            {
                "keywords": ["都是一年吗", "有效期多久", "时间多久"],
                "base_reply": "至臻全享当前是年付，三个群的对应权益按 1 年计算；最终以当前档位页面说明为准。",
            },
            {
                "keywords": ["能下载吗", "有水印吗"],
                "base_reply": "可收藏、可下载及水印版本的具体范围，以当前档位说明和入群后的实际内容为准，我不替页面多承诺。",
            },
            {
                "keywords": ["分别有什么"],
                "base_reply": "三个群分别对应至臻精选、至臻全享和精选图集；内容差异先看 @moryselect 预览，当前完整权益以档位页面说明为准。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "preview",
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "至臻全享当前包含 3 个群：至臻精选、至臻全享、精选图集，按年计算。内容差异先看 @moryselect 预览，完整权益以当前档位页面说明为准。",
    },
    {
        "name": "VIP订阅权益说明",
        "topic": "VIP权益",
        "enabled": True,
        "priority": 100,
        "keywords": [
            "VIP订阅具体权益", "vip具体权益", "订阅具体权益", "会员具体权益",
            "VIP有什么权益", "订阅到底有什么", "会员包含什么",
        ],
        "contextual_followups": ["能聊天吗", "能加好友吗", "能线下吗", "哪个适合我", "看不明白"],
        "followup_replies": [
            {
                "keywords": ["能聊天吗", "能加好友吗"],
                "base_reply": "是否包含 Telegram 日常沟通、定制或其他权限，要看你选择的具体档位；先对照当前权益，仍不清楚就把想要的能力直接告诉我。",
            },
            {
                "keywords": ["能线下吗"],
                "base_reply": "线下类资格不能由小助理直接承诺，要以当前档位说明和 Mory 最终确认为准。你可以先说所在城市和想咨询的事项，我帮你整理。",
            },
            {
                "keywords": ["哪个适合我", "看不明白"],
                "base_reply": "你只要告诉我最想要哪一类：看完整版、下载图集、定制，还是沟通权限。我会按这个目标帮你对应档位，不让你自己猜。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "preview",
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "VIP/订阅分不同档位，完整版、图集下载、定制和沟通权限并不完全相同。先看 @moryselect 判断内容风格；你再告诉我最想要什么，我会按目标帮你对应，当前完整权益以档位页面为准。",
    },
    {
        "name": "定制规则说明",
        "topic": "定制规则",
        "enabled": True,
        "priority": 100,
        "keywords": [
            "原味视频定制规则", "原味和视频定制规则", "原味/视频定制规则",
            "视频定制有什么规则", "原味定制有什么规则", "定制流程是什么",
        ],
        "contextual_followups": ["怎么留言", "需要说什么", "多久能好", "会露脸吗", "能做什么"],
        "followup_replies": [
            {
                "keywords": ["怎么留言", "需要说什么"],
                "base_reply": "留言时写清类型、预算、期望内容和不能接受的边界；小助理只负责记录，是否可接、价格和交付时间都要由 Mory 最终确认。",
            },
            {
                "keywords": ["多久能好"],
                "base_reply": "交付时间要结合当前排期和具体要求，由 Mory 确认后才算数；小助理不会先替她承诺日期。",
            },
            {
                "keywords": ["会露脸吗", "能做什么"],
                "base_reply": "能否露脸、可做范围和边界都以当前说明及 Mory 最终确认为准；你先把具体需求发来，我帮你拆成可确认的项目。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "none",
        "allow_custom_information": True,
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "原味或视频定制先把类型、具体需求、预算和边界发给我。我会整理并转给 Mory；是否可接、价格和交付时间以她最终确认为准。",
    },
    {
        "name": "联系与社交解锁",
        "topic": "联系Mory",
        "enabled": True,
        "priority": 120,
        "keywords": [
            "官方联系方式", "如何添加好友", "怎么添加好友", "怎么加好友",
            "怎么约你", "如何约你", "想约你", "怎么约mory", "如何约mory",
            "想约mory", "怎么联系mory", "如何联系mory", "怎么联系你",
        ],
        # “怎么约你”在口语里常被说成“怎么和你约/怎么约到你”。这些
        # 完整句式不能只靠子串枚举，否则插入一个虚词就会漏进 P10 AI。
        # 使用整句匹配，同时避免误伤“怎么预约体检/怎么约朋友吃饭”。
        "match_patterns": [
            r"(?:我)?(?:想|想要)?(?:怎么|如何|怎样)(?:才能)?(?:和|跟)?(?:你|mory)(?:约|见面)(?:一下)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:怎么|如何|怎样)(?:才能)?约(?:到)?(?:你|mory)(?:一下)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:能|可以|可不可以|能不能)(?:和|跟)?(?:你|mory)(?:约|见面)(?:一下)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:能|可以|可不可以|能不能)(?:约|见)(?:到)?(?:你|mory)(?:一下)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:想|想要)(?:和|跟)?(?:你|mory)(?:约|见面)(?:一下)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:想|想要)(?:约|见)(?:到)?(?:你|mory)(?:一下)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followups": ["微信呢", "线下呢", "怎么约", "那怎么联系", "必须先订阅吗", "只是聊聊呢"],
        "followup_replies": [
            {
                "keywords": ["微信呢"],
                "base_reply": "私人联系方式不能由小助理直接发。相关资格以 @MorychannelBot 当前社交解锁说明和 Mory 最终确认为准。",
            },
            {
                "keywords": ["线下呢", "怎么约"],
                "base_reply": "如果你问的是线下相关，先看 @MorychannelBot 当前社交解锁说明，再把城市、事项和期望时间发来；小助理只负责整理转达，是否安排由 Mory 最终确认。",
            },
            {
                "keywords": ["必须先订阅吗"],
                "base_reply": "不同沟通或社交权限的前置条件不一样，以 @MorychannelBot 当前说明为准；你告诉我具体想解锁哪种方式，我帮你对应。",
            },
            {
                "keywords": ["只是聊聊呢", "那怎么联系"],
                "base_reply": "普通咨询直接在这里发就行，我能处理就直接答；需要 Mory 确认的，我会整理后转达。涉及私人联系方式或社交权限，再按 @MorychannelBot 当前说明操作。",
            },
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "subscribe",
        "ignore_conversion_target": True,
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "如果你问的是怎么联系或约 Mory：普通咨询直接在这里发；涉及私人联系方式、线上或线下社交权限，先看 @MorychannelBot 当前社交解锁说明，再把具体事项发来。我会整理转达，是否安排由 Mory 最终确认。",
    },
)


class KeywordTrigger:
    """
    关键词触发回复管理器
    """

    def __init__(
        self,
        db,
        mory_bot=None,
        ai=None,
        config=None,
        private_preset_media=None,
    ):
        self.db = db
        self.mory_bot = mory_bot
        self.ai = ai
        self.config = config or {}
        self.private_preset_media = private_preset_media
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

            explicit_media_scene = None
            if not is_admin:
                explicit_media_scene = self._detect_private_media_scene(
                    text,
                    chat_id,
                    message,
                )

            special_rule = self._match_special_rule(
                text,
                conversation_history=conversation_history,
            )
            if special_rule:
                handled = self._handle_special_rule(
                    special_rule,
                    chat_id,
                    message,
                    bot,
                )
                if handled and not is_admin:
                    self._append_private_media_after_text(
                        special_rule,
                        message,
                        explicit_scene=explicit_media_scene,
                    )
                return handled

            if explicit_media_scene:
                # 明确索图由本地素材直接承接，零 Token；即使外部发送失败，
                # 也不能掉进 AI 再生成一段突兀文字或重复触发照片。
                return self._send_private_media(
                    message,
                    scene=explicit_media_scene,
                    include_caption=True,
                ) in {"sent", "duplicate", "failed"}

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

    def _detect_private_media_scene(self, text: str, chat_id: int, message):
        service = self.private_preset_media
        if service is None:
            return None
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "") or "")
        is_private = chat_type == "private" or (not chat_type and int(chat_id or 0) > 0)
        if not is_private:
            return None
        return service.detect_scene(text)

    def _send_private_media(
        self,
        message,
        *,
        scene: str,
        include_caption: bool,
    ) -> str:
        if self.private_preset_media is None or self.mory_bot is None:
            return "not_applicable"
        try:
            return self.private_preset_media.send_for_request(
                message,
                self.mory_bot,
                scene=scene,
                include_caption=include_caption,
            )
        except Exception as exc:
            logger.error("🔑 私聊预设媒体发送异常 scene=%s: %s", scene, exc)
            return "failed"

    def _append_private_media_after_text(
        self,
        rule,
        message,
        *,
        explicit_scene: str | None,
    ) -> str:
        """预设文字送达后再发图；图片不带 caption，避免重复文案和双入口。"""
        if self.private_preset_media is None:
            return "not_applicable"
        scene = explicit_scene or self.private_preset_media.scene_for_rule(rule)
        if not scene:
            return "not_applicable"
        return self._send_private_media(
            message,
            scene=scene,
            include_caption=False,
        )

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
        # 明确购买必须交给主成交链；概念咨询只有命中已审核的精确预设时
        # 才会在下方承接，未命中仍自然落回 P10。
        if conversion_target == "subscribe":
            return None

        text_lower = text.lower()
        best_rule = None
        best_score = (-1, -1)
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if not rule.get("enabled", True):
                continue
            if (
                conversion_reason == "custom_information_only"
                and not rule.get("allow_custom_information", False)
            ):
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
            matched_pattern_text = ""
            for keyword in keywords:
                if not keyword:
                    continue
                keyword_lower = str(keyword).lower()
                if keyword_lower in text_lower:
                    matched_len = max(matched_len, len(keyword_lower))

            resolved_rule = rule
            match_patterns = rule.get("match_patterns", [])
            if isinstance(match_patterns, str):
                match_patterns = [match_patterns]
            for pattern in match_patterns:
                if not pattern:
                    continue
                try:
                    pattern_match = re.fullmatch(
                        str(pattern),
                        text_lower.strip(),
                        flags=re.IGNORECASE,
                    )
                except re.error as exc:
                    logger.warning(
                        "特定词规则正则无效 name=%s pattern=%r error=%s",
                        rule.get("name", "未命名规则"),
                        pattern,
                        exc,
                    )
                    continue
                if pattern_match and len(pattern_match.group(0)) > matched_len:
                    matched_pattern_text = pattern_match.group(0)
                    matched_len = len(matched_pattern_text)

            if matched_pattern_text:
                resolved_rule = dict(rule)
                resolved_rule["_matched_keyword"] = matched_pattern_text
            if matched_len < 0:
                followup = self._resolve_contextual_followup(
                    rule,
                    text_lower,
                    conversation_history,
                )
                if followup:
                    matched_len, resolved_rule = followup

            priority = int(rule.get("priority", 0) or 0)
            score = (matched_len, priority)
            if matched_len >= 0 and score > best_score:
                best_rule = resolved_rule
                best_score = score
        return best_rule

    @classmethod
    def _resolve_contextual_followup(cls, rule, text_lower: str, conversation_history):
        """把短追问绑定到最近同一问答族，并切换到对应子答案。"""
        followups = rule.get("contextual_followups", [])
        if isinstance(followups, str):
            followups = [followups]
        matched_followups = [
            str(marker)
            for marker in followups
            if marker and str(marker).lower() in text_lower
        ]
        if not matched_followups:
            return None

        keywords = rule.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        context_anchors = list(keywords)
        context_anchors.extend(rule.get("context_anchors", []) or [])
        context_anchors.append(str(rule.get("topic", "")))
        recent = list(conversation_history or [])[-4:]
        has_context = False
        for item in recent:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).lower()
            intent = str(item.get("intent", "")).lower()
            if any(
                str(anchor).lower() in content or str(anchor).lower() == intent
                for anchor in context_anchors
                if anchor
            ):
                has_context = True
                break
        if not has_context:
            return None

        resolved = dict(rule)
        followup_text = max(matched_followups, key=len)
        for item in rule.get("followup_replies", []) or []:
            if not isinstance(item, dict):
                continue
            markers = item.get("keywords", [])
            if isinstance(markers, str):
                markers = [markers]
            if not any(str(marker).lower() in text_lower for marker in markers if marker):
                continue
            for key in (
                "base_reply", "conversion_target", "required_terms",
                "forbidden_terms", "parse_mode", "disable_web_page_preview",
            ):
                if key in item:
                    resolved[key] = item[key]
            break
        resolved["_matched_keyword"] = followup_text
        return len(followup_text), resolved

    @classmethod
    def _is_contextual_followup(cls, rule, text_lower: str, conversation_history) -> bool:
        """兼容旧调用：仅返回是否命中上下文追问。"""
        return bool(cls._resolve_contextual_followup(rule, text_lower, conversation_history))

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
        if rule.get("_matched_keyword"):
            return str(rule["_matched_keyword"])
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
                        conversion_target=str(rule.get("conversion_target", "none")),
                        conversion_reason="preset_question_family",
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
