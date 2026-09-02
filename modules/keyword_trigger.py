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


def is_external_feature_text(text: str) -> bool:
    """识别应交给群内其他功能机器人的签到/积分操作话题。

    该判断只在已审核预设没有命中后使用；因此“积分有什么用”等老板已配置
    的白名单仍先走确定性答案，未配置的变体才会停止进入 Mory AI 主链。
    """
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    if not normalized:
        return False
    if "断签" in normalized or "补签" in normalized:
        return True
    unrelated_points_anchors = (
        "数学", "微积分", "高数", "航空", "机票", "信用卡", "商场", "游戏",
    )
    points_operation_markers = (
        "我的积分", "查看积分", "积分多少", "多少积分", "积分排行", "积分排名",
        "积分抽奖", "积分商城", "积分记录", "积分日志", "积分余额", "签到积分",
        "积分有什么用", "积分有啥用", "积分干嘛", "积分怎么用", "积分怎么获得",
        "怎么获得积分", "积分兑换", "兑换积分", "积分换", "换会员", "提现",
        # v5.42.24 老板确认补齐“作用”问法族，与预设“积分咨询”keywords 保持一致
        "积分有什么作用", "积分有啥作用", "积分有什么用处", "积分作用是什么",
    )
    if (
        "积分" in normalized
        and not any(anchor in normalized for anchor in unrelated_points_anchors)
        and any(marker in normalized for marker in points_operation_markers)
    ):
        return True
    if re.fullmatch(r"/(?:checkin|points|shop)(?:@[a-z0-9_]+)?", normalized):
        return True
    if normalized in {
        "打卡", "商城", "积分商城", "qd", "/qd", "q.d", "q-d", "簽到", "/簽到",
    }:
        return True
    if re.fullmatch(r"(?:签到)+(?:[，,。.!！?？~～]+)?", normalized):
        return True
    if re.fullmatch(r"签到(?:排行|排名|日历|记录)", normalized):
        return True
    if normalized.startswith("连续签到"):
        return True
    return False


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

_EXTERNAL_FEATURE_BUILTIN_RULES = {
    "签到积分福利",
    "积分兑换说明",
    "签到九十天兑换",
    "会员兑换未进群",
}

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
        "name": "群聊冷场说明",
        "topic": "群聊定位",
        "enabled": True,
        "priority": 120,
        "keywords": [
            "群里好安静", "群里没人说话", "为什么群里不说话",
            "群里没人聊天", "这个群好冷清",
        ],
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:这个)?群里?(?:怎么|为什么)?(?:这么|那么|好)?(?:安静|冷清)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:(?:怎么|为什么)?(?:群里|大家|群友)|(?:群里|大家|群友)(?:怎么|为什么)?)(?:都)?(?:没|没有|没人)(?:说话|聊天)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:(?:怎么|为什么)?(?:群里|大家|群友)|(?:群里|大家|群友)(?:怎么|为什么)?)(?:都)?不(?:说话|聊天)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
        "contextual_followups": [
            "一直这样吗", "都不聊天吗", "为什么不活跃", "没人活跃吗",
            "还是很安静", "还是没人说话", "还是没人聊天", "还是很冷清",
            "对", "对啊", "是的", "确实", "确实是", "也是", "那倒也是",
            "说得对", "有道理", "没毛病", "明白了", "懂了", "这样挺好",
            "我就喜欢这样", "喜欢这样的", "这样也好",
        ],
        "contextual_followup_patterns": [
            r"(?:你说得?)?(?:也)?(?:对|没错|确实|有道理|没毛病)(?:啊|呀|呢|吧|哦|哈)?[？?。！!~～]*",
            r"(?:我)?(?:就)?喜欢(?:这样|这种)(?:群|方式|氛围)?(?:的)?(?:啊|呀|呢|吧)?[？?。！!~～]*",
            r"(?:这样|这么)(?:也|就)?(?:挺|蛮|很)?好(?:的)?(?:啊|呀|呢|吧)?[？?。！!~～]*",
            r"(?:我)?(?:明白|懂|知道)(?:了|啦)(?:啊|呀|呢|吧)?[？?。！!~～]*",
            r"(?:好像|确实)?(?:是)?(?:这么|这样)(?:回事|个道理)(?:啊|呀|呢|吧)?[？?。！!~～]*",
            r"(?:可是|但是|不过)?(?:群里)?(?:还是|依然)(?:这么|那么|很|好)?(?:安静|冷清|没人说话|没人聊天)(?:啊|呀|呢|吧|吗)?[？?。！!~～]*",
        ],
        "followup_replies": [
            {
                "default": True,
                "keywords": [
                    "一直这样吗", "都不聊天吗", "为什么不活跃", "没人活跃吗",
                    "还是很安静", "还是没人说话", "还是没人聊天", "还是很冷清",
                    "对", "对啊", "是的", "确实", "确实是", "也是", "那倒也是",
                    "说得对", "有道理", "没毛病", "明白了", "懂了", "这样挺好",
                    "我就喜欢这样", "喜欢这样的", "这样也好",
                ],
                "conversion_target": "preview",
                "card_enabled": True,
                "button_enabled": True,
                "polish_length_instruction": (
                    "写2到4句、60到110个汉字；直接承接上一轮，不要重新解释整段群定位。"
                ),
                "polish_prompt": (
                    "承接对方对上一轮群定位的继续追问或认同，直接反推转化："
                    "群里冷不冷清不重要，内容值不值得看才重要；"
                    "让对方先去 @moryselect 免费预览，喜欢再自助订阅。"
                    "只保留这一个预览目标，不给订阅机器人或人工联系入口。"
                ),
                "required_terms": ["安静", "内容", "@moryselect"],
                "forbidden_terms": ["@MorychannelBot", "@Moryfansbot", "保证", "限时"],
                "base_reply": (
                    "对，所以群里安静一点并不影响你看内容，冷不冷清也不是重点。"
                    "想知道 Mory 具体有什么，先去 @moryselect 免费预览；喜欢再自助订阅，"
                    "比在群里等人闲聊实际。"
                ),
            },
        ],
        "ai_polish": True,
        "ai_mode": "normal",
        "conversion_target": "none",
        "card_enabled": False,
        "remember_context": True,
        "polish_length_instruction": (
            "写5到7句、140到180个汉字；保留完整逻辑、原有话锋和反问，句式可随机，"
            "不要压缩成一句客服套话。"
        ),
        "polish_prompt": (
            "严格保留老板给定的立场和话锋，不得弱化成客服腔："
            "这是粉丝反馈群；Mory 不是做女菩萨来陪聊，也不是做门姐找人要门槛；"
            "有问题反馈，有通知发公告，订阅自助办理，联系入口群里已有；"
            "整天口嗨不能赚钱或涨粉，付费用户更看重内容和效率，大家都要忙、要务实；"
            "Mory 不做打嘴炮的事；结尾必须逐字保留："
            "‘我相信你也不是这样的人，喜欢这样的吧，对不对？’"
            "开头必须出现‘粉丝反馈群’，订阅句必须出现‘想订阅就自助’。"
            "只调整语序和措辞，不删除这些信息点，不增加具体账号、价格、优惠或承诺。"
        ),
        "required_terms": [
            "粉丝反馈群", "通知", "女菩萨", "门姐", "口嗨", "赚钱", "涨粉",
            "打嘴炮", "想订阅就自助", "喜欢这样的",
        ],
        "forbidden_terms": [
            "@moryselect", "@MorychannelBot", "@Moryfansbot", "不喜欢这样", "保证", "限时",
        ],
        "base_reply": (
            "这就是个粉丝反馈群，Mory 不是做女菩萨来陪聊的，也不是做门姐找你要门槛的。"
            "有问题反馈，有通知会发公告；想订阅就自助，要联系群里已经提供入口了。"
            "未必人家一天到晚闲着在群里口嗨，就能赚钱还是能涨粉？"
            "付费的用户就没有喜欢公开场合闲聊的，大家都是要忙的，都务实点。"
            "打嘴炮的事情 Mory 干不出来。我相信你也不是这样的人，喜欢这样的吧，对不对？"
        ),
    },
    {
        "name": "签到积分福利",
        "topic": "签到积分",
        "enabled": True,
        "keywords": [
            "签到积分有什么福利",
            "积分有什么福利",
            "签到有什么福利",
            "签到福利",
        ],
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:签到)?积分(?:有|有什么|有啥)(?:福利|奖励)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"签到(?:有|有什么|有啥)(?:福利|奖励)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
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
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:签到)?积分(?:要|该|可以|能)?怎么(?:使用|用|兑换|换)(?:会员|vip)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:积分兑换会员|兑换会员)(?:需要|要)?多少(?:积分|分)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我有)?\d+积分(?:怎么|如何)(?:换|兑换)(?:会员|vip)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"签到(?:多久|多少天)(?:能|可以)?(?:换|兑换)(?:会员|vip)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:连续)?签到(?:90|九十)天(?:能否|能|可以)?(?:换|兑换)(?:会员|vip)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:连续)?签到(?:3个?月|三个月)(?:能否|能|可以)?(?:换|兑换)(?:会员|vip)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我)?签(?:到|了|满)?(?:90|九十)天(?:能否|能|可以)?(?:换|兑换)(?:会员|vip)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:我)?(?:积分)?(?:兑换|换)(?:会员)?(?:成功|完|了|成功了)?(?:但|怎么|为什么|却|还){0,2}(?:没|没有|未)(?:进群|拉我进群|收到群链接)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:积分)?兑换成功(?:了)?(?:但|怎么|为什么|却|还)?(?:没|没有|未)(?:进群|收到群链接)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:至臻)?全享(?:都)?(?:包括|包含|有)(?:哪|什么)?(?:三个|3个)?群(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:至臻)?全享(?:都)?有哪些群(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:至臻)?全享(?:是哪|有哪)(?:三个|3个)群(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:vip|会员|订阅)(?:后)?(?:都)?(?:包括|包含|有)(?:什么|啥)(?:权益|内容)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:vip|会员)(?:能干嘛|有什么权益|有啥权益|具体权益)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"订阅后(?:可以|能)(?:得到|获得|看)什么(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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
        "name": "已购会员定制承接",
        "topic": "会员定制",
        "enabled": True,
        "priority": 130,
        "private_match_patterns": [
            r"(?:刚刚?)?(?:开|开了|买|买了|订阅|订阅了)(?:会员|vip)(?:后|了)?[，,。.!！?？~～]*(?:是)?(?:可以|能)(?:聊|做)?(?:定制|订制)(?:了)?(?:呢|呀|啊|吗|嘛|咩)?[？?。！!~～]*",
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "none",
        "allow_custom_information": True,
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "可以先聊具体需求，但开了会员不等于所有定制都会自动承接。把类型、想要的内容、预算和边界发来，我帮你整理；是否可接、价格和交付时间由 Mory 最终确认。",
    },
    {
        "name": "会员加入入口",
        "topic": "会员进群",
        "enabled": True,
        "priority": 125,
        # 这几句来自生产私聊，脱离私聊语境可能是在问任意工作群/游戏群，
        # 因此只允许私聊完整句命中；群聊仍要求带会员、订阅或至臻对象。
        "private_keywords": ["怎么进群", "怎么加群", "会员群"],
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:怎么|如何)(?:进|加|加入)(?:会员|vip|订阅|至臻)(?:群|群聊)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:会员|vip|订阅|至臻)(?:群|群聊)(?:怎么|如何)(?:进|加|加入)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:会员|vip|订阅|至臻)(?:群|群聊)(?:在哪|在哪里|入口在哪)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "private_match_patterns": [
            r"(?:我)?(?:怎么|如何)(?:进|加|加入)群(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"会员群(?:呢|呀|啊|吗|嘛|在哪|在哪里)?[？?。！!~～]*",
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "subscribe",
        "ignore_conversion_target": True,
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "如果还没开通，直接去 @MorychannelBot 看当前档位并按提示自助操作；如果已经购买或兑换成功却没收到群入口，把订单号文字和成功凭证截图发来，我帮你登记核对。不要发送密码或验证码。",
    },
    {
        "name": "预览入口",
        "topic": "内容预览",
        "enabled": True,
        "priority": 125,
        "private_keywords": ["预览", "看预览", "想看预览"],
        "keyword_match_mode": "full",
        "private_match_patterns": [
            r"(?:我)?(?:想|要|想要)?看(?:一下)?预览(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "preview",
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "想看预览就去 @moryselect，里面有照片和视频可以试看；先看风格合不合你心意，再决定要不要继续。",
    },
    {
        "name": "会员包年咨询",
        "topic": "会员包年",
        "enabled": True,
        "priority": 125,
        "private_keywords": ["包年可以", "包年可以吗", "可以包年吗", "有包年吗"],
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:会员|vip|订阅|至臻全享|精选图集)(?:可以|能|可不可以|能不能|有没有|有)?(?:包年|年付)(?:吗|呢|呀|啊|嘛)?[？?。！!~～]*",
        ],
        "private_match_patterns": [
            r"(?:会员|vip|订阅)?(?:可以|能|可不可以|能不能|有没有|有)?包年(?:吗|呢|呀|啊|嘛)?[？?。！!~～]*",
        ],
        "ai_polish": False,
        "ai_mode": "local_zero_token",
        "conversion_target": "subscribe",
        "ignore_conversion_target": True,
        "card_enabled": False,
        "remember_context": True,
        "base_reply": "可以，当前有年付档位；具体可选档位、价格和权益以 @MorychannelBot 自助菜单的实时展示为准，点进去看最准确。",
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
        "keyword_match_mode": "full",
        "match_patterns": [
            r"(?:原味|视频)(?:是)?怎么(?:定制|订制)(?:的)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:原味|视频)?(?:定制|订制)(?:能|可以)?(?:做|定制)?什么(?:内容)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:可以|能)(?:定制|订制)(?:什么|哪些)(?:内容)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:原味|视频)?(?:定制|订制)(?:要|需要)(?:准备|提供|说)什么(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:原味|视频)?(?:定制|订制)(?:流程|规则)(?:是)?什么(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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
        "keyword_match_mode": "full",
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
            r"(?:微信|telegram|电报)(?:怎么|如何)(?:加|联系)(?:你|mory)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:能|可以|能不能)(?:加|联系)(?:你|mory)(?:微信|telegram|电报)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:怎么|如何)(?:跟|和)?mory联系(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:会员)?怎么联系(?:你|mory)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
            r"(?:我想|想|我要)(?:找|联系)(?:mory本人|mory|你)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        ],
        "private_match_patterns": [
            r"约(?:吗|呢|呀|啊|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:可以|能|可不可以|能不能)约(?:吗|呢|呀|啊|嘛)?[？?。！!~～]*",
            r"(?:我)?(?:可以|能|可不可以|能不能)(?:线下)?见面(?:吗|呢|呀|啊|嘛)?[？?。！!~～]*",
            r"线下(?:吗|呢|呀|啊|嘛)?[？?。！!~～]*",
        ],
        "contextual_followup_match_mode": "full",
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


# 这些名称来自项目随附的 SPECIAL_AUTO_REPLIES。线上配置可能仍是旧版，只含
# keywords 且默认子串匹配；若任由“积分/福利/价格”等词在长句中命中，会把
# 航空积分、保险权益或无关商品价格串成 Mory 业务答案。安全匹配由代码统一
# 兜底，Dashboard 仍可改文案和开关，但不能把这些项目内置族降回宽泛子串。
_CONFIGURED_RULE_MATCH_CONTROLS = {
    "助理唤醒": [
        r"(?:mory)?小?助理(?:出来|在吗|在不在)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
    ],
    "价格咨询": [
        r"(?:(?:mory|你们)?(?:会员|vip|订阅|预览|定制|原味|视频|内容|这个|这些)(?:的)?)?(?:价格|价钱|费用|报价)(?:是)?(?:多少|怎样|怎么算)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:会员|vip|订阅|预览|定制|原味|视频|这个|这些)?(?:要)?多少钱(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:会员|vip|订阅|预览|定制|原味|视频|这个|这些)(?:是)?怎么收费(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
    ],
    "福利咨询": [
        r"(?:(?:mory|你们|会员|vip|订阅|预览)(?:的|里|都有|有)?)?(?:什么|哪些|啥|更多)?(?:福利|权益)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:会员|vip|订阅)(?:都)?(?:有|包含|包括)(?:什么|哪些|啥)(?:福利|权益)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:福利|权益)(?:在哪|在哪里|怎么领|怎么拿)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:有|有没有|还有没有|有啥|有什么)(?:福利|权益)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
    ],
    "内容咨询": [
        r"(?:会员|vip|订阅|预览|完整版|全套)?(?:里|都)?(?:有什么|有啥|能看什么)(?:内容)?(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:会员|vip|订阅|预览|完整版|全套)?(?:的)?内容介绍(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
    ],
    "积分咨询": [
        r"(?:我的|签到)?积分(?:可以|能)?(?:干嘛|做什么|有什么用|怎么用|怎么获得|有多少|是多少|排行|排名|抽奖)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
        r"(?:怎么获得|如何获得|查看|查)(?:我的)?积分(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
    ],
    "签到奖励咨询": [
        r"签到(?:是)?(?:有什么用|干嘛|干嘛用|有什么好处|有什么奖励|有啥奖励)(?:呢|呀|啊|吗|嘛)?[？?。！!~～]*",
    ],
}


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

            chat = getattr(message, "chat", None)
            chat_type = str(getattr(chat, "type", "") or "")
            is_private = chat_type == "private" or (
                not chat_type and int(chat_id or 0) > 0
            )

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
                is_private=is_private,
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
            reply = build_private_mystic_reply(text, user_id, config=self.config)
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

    def _match_special_rule(
        self,
        text: str,
        conversation_history=None,
        *,
        is_private: bool = False,
    ):
        """匹配特定词规则；配置可覆盖或关闭同名内置规则。"""
        rules = self._effective_special_rules()

        # 早路由绝不能抢走明确购买或泛定制的统一判定。只有规则声明的目标
        # 与 resolve_conversion_target 一致时才允许静态/润色回复。
        try:
            from core.conversion_glue import resolve_conversion_target
            conversion_target, conversion_reason = resolve_conversion_target(text, mode="normal")
        except Exception as exc:
            logger.debug("关键词早路由转化判定跳过: %s", exc)
            conversion_target, conversion_reason = "none", ""
        # 明确购买必须交给主成交链；概念咨询只有命中已审核的精确预设时
        # 才会在下方承接，未命中仍自然落回 P10。
        if conversion_target == "subscribe":
            return None

        text_lower = text.lower()
        text_normalized = self._normalize_match_phrase(text_lower)
        text_pattern = re.sub(r"\s+", "", text_lower.strip())
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
            else:
                keywords = list(keywords)
            if is_private:
                private_keywords = rule.get("private_keywords", [])
                if isinstance(private_keywords, str):
                    private_keywords = [private_keywords]
                keywords.extend(private_keywords)
            keyword_match_mode = str(
                rule.get("keyword_match_mode", "substring") or "substring"
            ).strip().lower()

            matched_len = -1
            matched_pattern_text = ""
            for keyword in keywords:
                if not keyword:
                    continue
                keyword_lower = str(keyword).lower()
                if keyword_match_mode == "full":
                    keyword_matched = (
                        self._normalize_match_phrase(keyword_lower) == text_normalized
                    )
                else:
                    keyword_matched = keyword_lower in text_lower
                if keyword_matched:
                    matched_len = max(matched_len, len(keyword_lower))

            resolved_rule = rule
            match_patterns = rule.get("match_patterns", [])
            if isinstance(match_patterns, str):
                match_patterns = [match_patterns]
            else:
                match_patterns = list(match_patterns)
            if is_private:
                private_patterns = rule.get("private_match_patterns", [])
                if isinstance(private_patterns, str):
                    private_patterns = [private_patterns]
                match_patterns.extend(private_patterns)
            for pattern in match_patterns:
                if not pattern:
                    continue
                try:
                    pattern_match = re.fullmatch(
                        str(pattern),
                        text_pattern,
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

    @staticmethod
    def _normalize_match_phrase(text: str) -> str:
        """供整句规则使用：忽略空白和句末语气标点，不改变词序与实词。"""
        compact = re.sub(r"\s+", "", str(text or "").strip().lower())
        return re.sub(r"[，,。.!！?？~～]+$", "", compact)

    @classmethod
    def _resolve_contextual_followup(cls, rule, text_lower: str, conversation_history):
        """把短追问绑定到最近同一问答族，并切换到对应子答案。"""
        followups = rule.get("contextual_followups", [])
        if isinstance(followups, str):
            followups = [followups]
        followup_match_mode = str(
            rule.get("contextual_followup_match_mode", "substring") or "substring"
        ).strip().lower()
        normalized_text = cls._normalize_match_phrase(text_lower)
        matched_followups = []
        for marker in followups:
            if not marker:
                continue
            marker_text = str(marker)
            if followup_match_mode == "full":
                matched = cls._normalize_match_phrase(marker_text) == normalized_text
            else:
                matched = marker_text.lower() in text_lower
            if matched:
                matched_followups.append(marker_text)
        if not matched_followups:
            followup_patterns = rule.get("contextual_followup_patterns", [])
            if isinstance(followup_patterns, str):
                followup_patterns = [followup_patterns]
            pattern_text = re.sub(r"\s+", "", str(text_lower or "").strip())
            for pattern in followup_patterns:
                if not pattern:
                    continue
                try:
                    pattern_match = re.fullmatch(
                        str(pattern),
                        pattern_text,
                        flags=re.IGNORECASE,
                    )
                except re.error as exc:
                    logger.warning(
                        "特定词追问正则无效 name=%s pattern=%r error=%s",
                        rule.get("name", "未命名规则"),
                        pattern,
                        exc,
                    )
                    continue
                if pattern_match:
                    matched_followups.append(pattern_match.group(0))
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
        selected_followup = None
        for item in rule.get("followup_replies", []) or []:
            if not isinstance(item, dict):
                continue
            markers = item.get("keywords", [])
            if isinstance(markers, str):
                markers = [markers]
            if followup_match_mode == "full":
                matched_item = any(
                    cls._normalize_match_phrase(marker) == normalized_text
                    for marker in markers
                    if marker
                )
            else:
                matched_item = any(
                    str(marker).lower() in text_lower for marker in markers if marker
                )
            if not matched_item:
                continue
            selected_followup = item
            break
        if selected_followup is None:
            selected_followup = next(
                (
                    item
                    for item in rule.get("followup_replies", []) or []
                    if isinstance(item, dict) and item.get("default", False)
                ),
                None,
            )
        if selected_followup:
            for key in (
                "base_reply", "conversion_target", "required_terms",
                "forbidden_terms", "parse_mode", "disable_web_page_preview",
                "ai_polish", "polish_prompt", "polish_length_instruction",
                "card_enabled", "button_enabled",
            ):
                if key in selected_followup:
                    resolved[key] = selected_followup[key]
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
        rules = []
        for configured_rule in configured:
            if not isinstance(configured_rule, dict):
                rules.append(configured_rule)
                continue
            rule = dict(configured_rule)
            rule_name = str(rule.get("name", "")).strip()
            controls = _CONFIGURED_RULE_MATCH_CONTROLS.get(rule_name)
            if controls:
                rule["keyword_match_mode"] = "full"
                if rule_name in {"积分咨询", "签到奖励咨询"}:
                    # “我的积分有多少”里的“多少”不代表询价；只有在完整积分/
                    # 签到句式已命中后，才允许越过通用转化分类。
                    rule["ignore_conversion_target"] = True
                    # 这两类功能由其他机器人执行；Mory 只使用老板在生产配置
                    # 中明确列出的问法，不用代码正则再扩写相似句。
                else:
                    existing_patterns = rule.get("match_patterns", [])
                    if isinstance(existing_patterns, str):
                        existing_patterns = [existing_patterns]
                    rule["match_patterns"] = [*existing_patterns, *controls]
            rules.append(rule)
        rules.extend(
            dict(rule)
            for rule in _DEFAULT_SPECIAL_AUTO_REPLIES
            if rule["name"] not in configured_names
            and rule["name"] not in _EXTERNAL_FEATURE_BUILTIN_RULES
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
                polish_length_instruction = str(
                    rule.get("polish_length_instruction", "") or ""
                ).strip() or "只写1到2句、25到70个汉字；不要标题、列表、解释或客服腔。"
                polish_prompt = (
                    "请按当前已加载的Mory人设，把下面的业务底稿润色成一次自然回复。\n"
                    "硬约束：\n"
                    "1. 底稿原文是唯一信息源，逐句顺着原文意思精修，只做语气和措辞的打磨；"
                    "禁止重写、扩写、增删信息点或另起一段新文案。\n"
                    f"2. {polish_length_instruction}\n"
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
                from core.telegram_send_utils import send_rich_message_compat

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
        """拒绝过短、过长、降级话术和内部说明，安全回退业务底稿。

        上限 200：冷场族要求"140到180个汉字"，标点/emoji 也计入 len()，
        旧上限 180 与之边界相切，AI 多写一个标点整段报废回退模板，
        同一问题随机出现两种画风。
        """
        if not isinstance(reply, str):
            return False
        text = reply.strip()
        if not 6 <= len(text) <= 200:
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
        """记录关键话题；审核预设另写问题来源，供后续升级复盘。"""
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

        # 只在回复真实送达后记录 SPECIAL 预设；本地占卜等非FAQ内容不混入
        # 问题蒸馏。一次 INSERT 同时写问题、回复和来源，避免半条记录。
        rule_name = str(rule.get("name", "") or "").strip()
        if (
            reply_text
            and rule_name != "私聊本地占卜"
            and self.config.get("FAQ_TRACKING_ENABLED", False)
        ):
            try:
                log_question = getattr(self.db, "log_question", None)
                if callable(log_question):
                    target = str(rule.get("conversion_target", "none") or "none")
                    category = (
                        "pricing" if target == "subscribe"
                        else "content" if target == "preview"
                        else "other"
                    )
                    question_id = log_question(
                        uid=user_id,
                        chat_id=int(chat_id or 0),
                        question_text=str(getattr(message, "text", "") or "")[:500],
                        mode="convert" if target == "subscribe" else "normal",
                        intent=topic,
                        keyword_tag=matched_keyword,
                        question_category=category,
                        is_convert=1 if target == "subscribe" else 0,
                        ai_reply_summary=str(reply_text)[:200],
                        faq_hit_id=0,
                        answer_source="preset",
                        answer_ref=rule_name,
                    )
                    if question_id:
                        logger.debug(
                            "📋 预设问答已记录 id=%s rule=%s",
                            question_id,
                            rule_name,
                        )
            except Exception as e:
                logger.warning(f"🔑 预设问题来源写入失败: {e}")

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
