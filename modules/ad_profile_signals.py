# -*- coding: utf-8 -*-
"""
[Codex] 用户资料广告信号检测。

Telegram Premium 的 emoji 状态有时会被广告号做成“看我简介”贴纸。
Bot API 通常只能拿到 custom_emoji_id 和贴纸元数据，不保证能读到图片里的字；
能拿到文字元数据时直接封，拿不到时只记可疑分，避免误封正常 Premium 用户。
"""

import re

from core.logging_util import get_logger
from core.ai_engine import analyze_image
from modules.ad_patterns_encoded import BIO_PATTERNS, USERNAME_PATTERNS

logger = get_logger("ad_profile_signals")


_TELEGRAM_INVITE_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|te\.me|tg\.me)/(?:\+|joinchat/)[A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)
_INVITE_TEASER_RE = re.compile(
    r"(?:给(?:自己|你)?多(?:一条|条)?路|多(?:一条|条)?路)(?:试试|看看|了解|选择)",
    re.IGNORECASE,
)
_INVITE_OPPORTUNITY_ANCHOR_RES = (
    re.compile(r"(?:小白|新人|新手).{0,5}(?:必做|可做|能做|也能做|可上手|入门必看)", re.IGNORECASE),
    re.compile(r"(?:勤快|肯干|努力|执行力|自律).{0,8}(?:来|加入|进群|联系|了解|做)", re.IGNORECASE),
    re.compile(r"(?:懒人|闲人|非诚).{0,2}勿扰", re.IGNORECASE),
)
_INVITE_IDLE_PROJECT_RE = re.compile(
    r"(?:电脑|手机|主机).{0,6}(?:挂机|自动).{0,6}(?:项目|赚钱|进账|印钞)",
    re.IGNORECASE,
)
_PROFILE_CTA_RE = re.compile(
    r"(?:都|来|先|可以|直接)?(?:tmd)?(?:看我|看头像|看简介|看主页|点我)",
    re.IGNORECASE,
)
_TELEGRAM_BOT_INVITE_DEEP_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|te\.me|tg\.me)/"
    r"[A-Za-z0-9_]{5,}bot\?(?:[^\s#&]+&)*start=invite[_-]?[A-Za-z0-9_-]{4,}",
    re.IGNORECASE,
)
_PROFILE_NAME_FREE_LISTING_RE = re.compile(
    r"(?:同城|同程|老师).{0,8}免费.{0,6}上榜|免费.{0,6}上榜.{0,8}(?:同城|同程|老师)",
    re.IGNORECASE,
)
_INVITE_GROUP_ACTION_RE = re.compile(r"(?:加群|进群|入群|群里|群内|加入)", re.IGNORECASE)
_INVITE_PROJECT_RE = re.compile(
    r"(?:项目|兼职|副业|赚钱|赚米|收益|佣金|招募|接单|合作)", re.IGNORECASE
)
_EXPLICIT_INCOME_AMOUNT_RE = re.compile(
    r"(?:一天|一日|每天|日入|日赚|赚|挣|收益|利润).{0,4}"
    r"[0-9零一二三四五六七八九十百千万wWkK]{1,8}",
    re.IGNORECASE,
)
_SMUGGLED_TRADE_RE = re.compile(
    r"(?:卖|出售|售卖|出货|供货|批发|拿货).{0,6}走私"
    r"|走私.{0,8}(?:出售|售卖|出货|供货|批发|拿货)",
    re.IGNORECASE,
)
_SMUGGLED_PRODUCT_RE = re.compile(
    r"(?:苹果|手机|香烟|烟酒|雪茄|奢侈品|名表|化妆品|货源)",
    re.IGNORECASE,
)
_SMUGGLED_BIO_TRADE_RE = re.compile(
    r"(?:进群|加群|预订|订购|下单|购买|拿货|批发|合作|找我|私聊)",
    re.IGNORECASE,
)
_SMUGGLED_FICTION_RE = re.compile(r"(?:小说|电影|游戏|纪录片|剧本)", re.IGNORECASE)
_SMUGGLED_REPORT_SOURCE_RE = re.compile(
    r"(?:反诈|海关|警方|法院|案件|新闻|报道|科普|宣传|调查|研究)",
    re.IGNORECASE,
)
_SMUGGLED_REPORT_RESULT_RE = re.compile(
    r"(?:查获|查处|打击|判刑|违法|犯罪|曝光|提醒|危害|被捕|判决)",
    re.IGNORECASE,
)
_SMUGGLED_MESSAGE_CONTINUATION_RE = re.compile(
    r"(?:便宜|特价|水果机|卖手机|买手机|手机店|预订|订购|拿货|批发|合作|找我|私聊)",
    re.IGNORECASE,
)
_CODED_PHONE_NAME_RE = re.compile(
    r"(?:正品)?(?:水果|果子)(?:(?:手机|机)?(?:1[4-9]|20)|(?:1[4-9]|20)(?:手机|机)?)"
    r"(?:全系|全系列)",
    re.IGNORECASE,
)
_DISTRIBUTION_TARGET_RE = re.compile(
    r"(?:代理商|经销商|渠道商|散户|手机店|同行|商家)", re.IGNORECASE
)
_DISTRIBUTION_TRADE_RE = re.compile(
    r"(?:出货|供货|拿货|批发|预定|预订|订货|合作|招代理)", re.IGNORECASE
)
_DISTRIBUTION_SCALE_RE = re.compile(
    r"(?:大量|全系|全系列|现货|一手|货源|稳定)", re.IGNORECASE
)
_CODED_PHONE_MESSAGE_CONTINUATION_RE = re.compile(
    r"(?:寻|寻找|找|联系).{0,4}(?:手机店|代理商|经销商|渠道商|同行|商家)"
    r".{0,4}(?:合作|拿货|出货|供货|预定|预订|订货)",
    re.IGNORECASE,
)


def _iter_status_ids(user) -> list:
    """兼容不同 pyTelegramBotAPI 版本的 emoji 状态字段。"""
    ids = []
    for attr in ("emoji_status_custom_emoji_id", "emoji_status_custom_emoji_ids"):
        val = getattr(user, attr, None)
        if not val:
            continue
        if isinstance(val, (list, tuple, set)):
            ids.extend([str(x) for x in val if x])
        else:
            ids.append(str(val))
    return list(dict.fromkeys(ids))


def _sticker_texts(bot, status_ids: list) -> list:
    """读取自定义 emoji 贴纸可见元数据，失败时返回空。"""
    if not bot or not status_ids or not hasattr(bot, "get_custom_emoji_stickers"):
        return []
    try:
        stickers = bot.get_custom_emoji_stickers(status_ids)
    except Exception as e:
        logger.debug(f"[Codex] 获取emoji状态贴纸失败: ids={status_ids[:3]} err={e}")
        return []

    texts = []
    for sticker in stickers or []:
        parts = []
        for attr in ("emoji", "set_name", "custom_emoji_id"):
            val = getattr(sticker, attr, "") or ""
            if val:
                parts.append(str(val))
        # file_id 是不透明凭据，不参与规则匹配，避免把随机串当内容。
        if parts:
            texts.append(" ".join(parts))
    return texts


def _download_sticker_image(bot, sticker) -> bytes:
    """优先下载缩略图；贴纸本体可能是动画/视频，不一定适合 OCR。"""
    file_id = ""
    thumb = getattr(sticker, "thumbnail", None)
    if thumb:
        file_id = getattr(thumb, "file_id", "") or ""
    if not file_id:
        file_id = getattr(sticker, "file_id", "") or ""
    if not file_id:
        return b""
    try:
        file_info = bot.get_file(file_id)
        file_path = getattr(file_info, "file_path", "") or ""
        if not file_path:
            return b""
        return bot.download_file(file_path) or b""
    except Exception as e:
        logger.debug(f"[Codex] 下载emoji状态贴纸失败: file_id={file_id} err={e}")
        return b""


def _local_ocr(image_data: bytes) -> str:
    """本地 OCR fallback，使用 RapidOCR 在 CPU 上识别图片文字。
    未安装 rapidocr-onnxruntime 时返回空，不影响正常运行。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ""
    try:
        ocr_engine = RapidOCR()
        result, _ = ocr_engine(image_data)
        if not result:
            return ""
        texts = [item[1] for item in result if item and len(item) > 1]
        return " ".join(texts)
    except Exception as e:
        logger.debug(f"[AD] 本地OCR失败: {e}")
        return ""


def _has_vision_model(config: dict | None = None) -> bool:
    """检查是否有可用的视觉模型（用于决定降级策略）。
    config 为 None 时返回 True（避免测试/未初始化时触发降级）。
    """
    if not config:
        return True
    pools = config.get("MODEL_POOLS", {})
    vision_pool = pools.get("vision", [])
    if vision_pool:
        return True
    llm_pool = pools.get("llm", [])
    vl_keywords = ["vl", "vision", "omni", "qwen-vl", "qwen2-vl", "glm-4v", "deepseek-vl"]
    for m in llm_pool:
        name = m.get("name", "").lower()
        if any(kw in name for kw in vl_keywords):
            return True
    return False


def _ocr_sticker_texts(bot, status_ids: list, config: dict | None = None) -> list:
    """对自定义 emoji 状态贴纸做 OCR，识别图片里的“看我简介”等文字。"""
    if not config or not bot or not status_ids or not hasattr(bot, "get_custom_emoji_stickers"):
        return []
    try:
        stickers = bot.get_custom_emoji_stickers(status_ids)
    except Exception as e:
        logger.debug(f"[Codex] OCR前获取emoji状态贴纸失败: ids={status_ids[:3]} err={e}")
        return []

    results = []
    prompt = "请识别这张贴纸图片中的所有中文和英文文字，只返回文字内容，不要解释。没有文字就返回'无文字'。"
    has_vl = _has_vision_model(config)
    for sticker in stickers or []:
        image_data = _download_sticker_image(bot, sticker)
        if not image_data:
            continue
        text = None
        # 优先用 API 视觉模型 OCR
        if has_vl:
            try:
                text = analyze_image(image_data, prompt, config)
                if text and text != "无文字":
                    results.append(str(text))
                    continue
            except Exception as e:
                logger.debug(f"[Codex] emoji状态贴纸API-OCR失败: err={e}")
        # API 不可用时用本地 OCR fallback
        if not text or text == "无文字":
            local_text = _local_ocr(image_data)
            if local_text:
                logger.info(f"[AD] 本地OCR识别到文字: {local_text[:80]}")
                results.append(local_text)
    return results


def _match_ad_patterns(text: str, patterns=None) -> str:
    """返回命中的广告规则片段，未命中返回空。"""
    if not text:
        return ""
    selected_patterns = USERNAME_PATTERNS + BIO_PATTERNS if patterns is None else patterns
    for pattern in selected_patterns:
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group()[:50]
        except re.error:
            logger.debug(f"[Codex] 资料信号跳过异常正则: {pattern[:30]}")
    return ""


def _compact_profile_text(text: str) -> str:
    """压平空格、标点和拆字，避免“飞 机 / 结 算”规避资料检测。"""
    return re.sub(r"[\W_]+", "", str(text or "").lower(), flags=re.UNICODE)


def _detect_invite_teaser_ad(bio: str) -> str:
    """识别群邀请链接与规避式引流话术的同字段组合。"""
    raw = str(bio or "")
    if not _TELEGRAM_INVITE_RE.search(raw):
        return ""
    compact = _compact_profile_text(raw)
    match = _INVITE_TEASER_RE.search(compact)
    if match:
        return match.group()
    novice_opportunity = all(
        pattern.search(compact) for pattern in _INVITE_OPPORTUNITY_ANCHOR_RES
    )
    idle_project = (
        _INVITE_IDLE_PROJECT_RE.search(compact)
        and _INVITE_OPPORTUNITY_ANCHOR_RES[1].search(compact)
        and _INVITE_OPPORTUNITY_ANCHOR_RES[2].search(compact)
    )
    if novice_opportunity or idle_project:
        return "小白必做+勤快来+懒人勿扰"
    if (
        _INVITE_GROUP_ACTION_RE.search(compact)
        and _INVITE_PROJECT_RE.search(compact)
        and _EXPLICIT_INCOME_AMOUNT_RE.search(compact)
    ):
        return "加群项目+明确收益"
    return ""


def _detect_smuggled_goods_profile_ad(display: str, username: str, bio: str) -> str:
    """识别资料名明确售卖走私货，或走私商品名与 Bio 订购群的组合。"""
    compact_name = _compact_profile_text(" ".join((display, username)))
    compact_bio = _compact_profile_text(bio)
    if "走私" not in compact_name:
        return ""
    if _SMUGGLED_FICTION_RE.search(compact_name):
        return ""
    if (
        _SMUGGLED_REPORT_SOURCE_RE.search(compact_name)
        and _SMUGGLED_REPORT_RESULT_RE.search(compact_name)
    ):
        return ""
    if _SMUGGLED_TRADE_RE.search(compact_name):
        return "姓名明确售卖走私货"
    if (
        _SMUGGLED_PRODUCT_RE.search(compact_name)
        and _TELEGRAM_INVITE_RE.search(str(bio or ""))
        and _SMUGGLED_BIO_TRADE_RE.search(compact_bio)
    ):
        return "走私商品姓名+Bio订购群"
    return ""


def has_smuggled_goods_message_bridge(
    message_text: str, display: str, username: str, bio: str
) -> bool:
    """资料已确认售卖走私货时，只把明确交易续句标为逐条广告。"""
    if not _detect_smuggled_goods_profile_ad(display, username, bio):
        return False
    return bool(_SMUGGLED_MESSAGE_CONTINUATION_RE.search(_compact_profile_text(message_text)))


def _detect_coded_phone_distribution_profile_ad(
    display: str,
    username: str,
    bio: str,
    personal_parts: list[str] | None = None,
) -> str:
    """识别“水果+型号+手机全系”暗语及资料/频道中的批发招揽组合。"""
    compact_name = _compact_profile_text(" ".join((display, username)))
    name_match = _CODED_PHONE_NAME_RE.search(compact_name)
    if name_match:
        return f"姓名命中水果机型号全系暗语:{name_match.group()}"

    raw_bio = str(bio or "")
    parts = [raw_bio, *(personal_parts or [])]
    compact_distribution = _compact_profile_text(" ".join(parts))
    if not compact_distribution:
        return ""

    target = _DISTRIBUTION_TARGET_RE.search(compact_distribution)
    trade = _DISTRIBUTION_TRADE_RE.search(compact_distribution)
    scale = _DISTRIBUTION_SCALE_RE.search(compact_distribution)
    has_contact_surface = bool(personal_parts) or bool(_TELEGRAM_INVITE_RE.search(raw_bio))
    if target and trade and scale and has_contact_surface:
        surface = "关联频道" if personal_parts else "Bio邀请链接"
        return f"{surface}命中规模招代理出货组合:{target.group()}+{trade.group()}+{scale.group()}"
    return ""


def has_coded_phone_distribution_message_bridge(
    message_text: str,
    display: str = "",
    username: str = "",
    bio: str = "",
    profile_source: str = "",
) -> bool:
    """资料已确认手机分销广告时，只标记明确寻店合作等交易续句。"""
    confirmed = profile_source == "profile_coded_phone_distribution"
    if not confirmed:
        confirmed = bool(
            _detect_coded_phone_distribution_profile_ad(display, username, bio)
        )
    if not confirmed:
        return False
    return bool(
        _CODED_PHONE_MESSAGE_CONTINUATION_RE.search(
            _compact_profile_text(message_text)
        )
    )


def has_avatar_profile_bridge(avatar_reason: str, avatar_meta: dict, bio: str) -> bool:
    """高置信营销头像与邀请收益 Bio 联合时授权处置，头像单信号仍不定罪。"""
    if not _detect_invite_teaser_ad(bio):
        return False
    avatar_type = str((avatar_meta or {}).get("type", "") or "").lower()
    compact_reason = _compact_profile_text(avatar_reason)
    cta_text = any(
        anchor in compact_reason
        for anchor in ("看我简介", "看简介", "看我主页", "看主页")
    )
    return cta_text or avatar_type in {"marketing", "qr"}


def has_avatar_personal_channel_bridge(
    avatar_reason: str, recruitment_anchors
) -> bool:
    """仅允许“看资料”头像与绑定频道的规避式群演招募三锚点联合定罪。"""
    compact_reason = _compact_profile_text(avatar_reason)
    explicit_profile_cta = any(
        anchor in compact_reason
        for anchor in ("看我简介", "看简介", "看我主页", "看主页", "点我简介", "点我主页")
    )
    required = {"招聘动作", "群演岗位", "应召引导"}
    return explicit_profile_cta and required.issubset(set(recruitment_anchors or []))


def _detect_profile_name_bot_invite_ad(display: str, username: str, bio: str) -> str:
    """识别广告化姓名与 Bot 拉新深链的高置信跨字段组合。

    普通姓名、普通 t.me 链接和普通群邀请仍保持字段隔离；只有姓名含“老师/同城/同程
    + 免费上榜”招揽语义，且 Bio 同时给出 ``bot?start=invite_*`` 拉新深链时才定罪。
    """
    if not _TELEGRAM_BOT_INVITE_DEEP_LINK_RE.search(str(bio or "")):
        return ""
    compact_name = _compact_profile_text(" ".join((display, username)))
    match = _PROFILE_NAME_FREE_LISTING_RE.search(compact_name)
    return match.group() if match else ""


def has_profile_message_bridge(message_text: str, bio: str) -> bool:
    """正文明确让人查看资料，且资料含确证邀请引流时，正文属于广告桥接消息。"""
    if not _detect_invite_teaser_ad(bio):
        return False
    return bool(_PROFILE_CTA_RE.search(_compact_profile_text(message_text)))


def _detect_personal_channel_ad(parts: list[str]) -> dict:
    """识别个人资料关联频道中的组合广告语义。

    单个“飞机”“频道”“赚钱”都不定罪；必须同时出现三个独立语义锚点，
    从而覆盖同义改写、拆字和长段扩写，同时放过正常航班群、工作通知频道。
    """
    text = _compact_profile_text(" ".join(str(part or "") for part in parts))
    if not text:
        return {"is_ad": False, "anchors": []}

    groups = {
        "平台暗语": ("飞机", "飛機", "纸飞机", "紙飛機", "电报", "電報", "telegram", "tg群"),
        "拉群动作": ("进群", "進群", "加群", "入群", "私聊", "联系", "聯繫", "找我", "点我", "點我"),
        "商业招揽": (
            "结算", "結算", "赚钱", "賺錢", "赚米", "賺米", "佣金", "日结", "日結",
            "返利", "接单", "接單", "做单", "做單", "兼职", "兼職", "招募", "演员",
            "演員", "项目", "項目", "利润", "利潤", "收益",
        ),
        "频道载体": ("频道", "頻道", "channel", "群组", "群組"),
        "资金码盘": (
            "微信支付宝", "收款码", "付款码", "有码", "有码就要", "码商", "换资",
            "換資", "资金盘", "資金盤",
        ),
        "灰产组织": (
            "车队", "車隊", "老盘", "老盤", "开工", "開工", "做单", "做單",
            "结算记录", "結算記錄", "担保公群", "擔保公群", "双向私信", "雙向私信",
        ),
        "收益承诺": (
            "日赚", "日賺", "无风险", "無風險", "稳定开工", "穩定開工",
            "首单", "首單", "高效率", "安全有保障",
        ),
        "资料导流": ("客服", "私信", "机器人", "機器人", "公群", "tme", "认准id", "認準id"),
    }
    anchors = [name for name, words in groups.items() if any(word in text for word in words)]
    anchor_set = set(anchors)
    strong = (
        {"平台暗语", "拉群动作", "商业招揽"}.issubset(anchor_set)
        or {"拉群动作", "商业招揽", "频道载体"}.issubset(anchor_set)
        or (
            {"资金码盘", "灰产组织"}.issubset(anchor_set)
            and bool({"收益承诺", "资料导流"} & anchor_set)
        )
        or {"灰产组织", "收益承诺", "资料导流"}.issubset(anchor_set)
        # “换资车队 + 有码”是高度特异的灰产频道标题；即使频道帖子 API
        # 暂时不可用，也不能让入群审核退化为放行。
        or ("换资" in text and "车队" in text and ("有码" in text or "码商" in text))
    )
    return {"is_ad": strong, "anchors": anchors}


def _detect_personal_channel_avatar_bridge_candidate(parts: list[str]) -> dict:
    """识别需与“看我简介”头像联合的规避式群演招募频道。

    频道单独不处置；必须同时具备招聘动作、群演岗位和应召引导三个语义锚点，
    再由头像中的明确资料 CTA 完成跨字段证据闭环。
    """
    text = _compact_profile_text(" ".join(str(part or "") for part in parts))
    if not text:
        return {"is_candidate": False, "anchors": []}

    groups = {
        "招聘动作": (
            "招聘", "招募", "招人", "诚聘", "誠聘", "高聘", "急聘", "聘群演", "聘演员", "聘演員",
        ),
        "群演岗位": (
            "群演", "群众演员", "群眾演員", "演员", "演員",
        ),
        "应召引导": (
            "有时间来", "有時間來", "有空来", "有空來", "随时来", "隨時來",
            "想来的", "想來的", "来报名", "來報名",
            "来联系", "來聯繫", "来私聊", "來私聊",
        ),
    }
    anchors = [name for name, words in groups.items() if any(word in text for word in words)]
    return {
        "is_candidate": set(groups).issubset(set(anchors)),
        "anchors": anchors,
    }


def _personal_channel_parts(
    bot,
    chat_info,
    user_id: int = 0,
    personal_channel_messages=None,
) -> tuple[list[str], int]:
    """读取 personal_chat 的资料和最近帖子正文/图片 caption。"""
    personal_chat = getattr(chat_info, "personal_chat", None) if chat_info else None
    if not personal_chat:
        return [], 0

    channel_id = int(getattr(personal_chat, "id", 0) or 0)
    objects = [personal_chat]
    if channel_id and bot and hasattr(bot, "get_chat"):
        try:
            full_chat = bot.get_chat(channel_id)
            if full_chat is not None:
                objects.append(full_chat)
        except Exception as e:
            logger.debug(f"[AD] 获取个人资料关联频道详情失败: channel={channel_id} err={e}")

    parts = []
    for obj in objects:
        for attr in ("title", "username", "description"):
            value = str(getattr(obj, attr, "") or "").strip()
            if value and value not in parts:
                parts.append(value[:1000])

    # Telegram 资料卡展示的是个人频道最近帖子，而非频道 description。
    # 只读最近 3 条即可覆盖资料卡预览，失败时保留标题/简介证据降级判断。
    messages = list(personal_channel_messages or [])
    if not messages and user_id and bot and hasattr(bot, "get_user_personal_chat_messages"):
        try:
            messages = list(bot.get_user_personal_chat_messages(user_id, 3) or [])
        except Exception as e:
            logger.debug(f"[AD] 获取个人资料关联频道最近帖子失败: uid={user_id} err={e}")

    for message in messages[:3]:
        for attr in ("text", "caption"):
            value = str(getattr(message, attr, "") or "").strip()
            if value and value not in parts:
                parts.append(value[:1500])
    return parts, channel_id


def detect_profile_ad_signal(
    bot,
    user,
    bio: str = "",
    config: dict | None = None,
    chat_info=None,
    personal_channel_messages=None,
) -> dict:
    """
    检测用户资料层广告信号。

    返回:
    - is_ad=True：明确命中"看我简介"等强规则，可以直接广告处置
    - score=1：只有自定义 emoji 状态但没读到文字，只作为后续追踪信号

    注意：必须用 bot.get_chat(uid) 获取 Chat 对象来读取 emoji_status_custom_emoji_id，
    因为 m.from_user (User 对象) 在 pyTelegramBotAPI 4.34.0 中不保存该字段。
    """
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    username = getattr(user, "username", "") or ""
    uid = getattr(user, "id", None) or getattr(user, "uid", None)
    display = f"{first_name}{last_name}".strip()

    # 从 User 对象先尝试拿 emoji 状态
    status_ids = _iter_status_ids(user)

    # personal_chat、Bio 和 emoji 状态都只在 getChat 的 Chat 对象上稳定返回。
    # 调用方已经拉取时可传 chat_info，避免同一条消息重复请求 Telegram。
    if chat_info is None and uid and bot and hasattr(bot, "get_chat"):
        try:
            chat_info = bot.get_chat(uid)
        except Exception as e:
            logger.debug(f"[AD] get_chat获取用户完整资料失败: uid={uid} err={e}")
            chat_info = None
    if chat_info is not None:
        status_ids = list(dict.fromkeys(status_ids + _iter_status_ids(chat_info)))
        if not bio:
            bio = getattr(chat_info, "bio", "") or ""

    # 先完成只依赖姓名/username/Bio 的本地强证据判断。命中后继续读取
    # personal_chat 和最近帖子不会改变结论，只会放大每条群消息的 Bot API 调用。
    status_text = ""
    profile_hit = _match_ad_patterns(" ".join((display, username)), USERNAME_PATTERNS)
    if not profile_hit:
        profile_hit = _match_ad_patterns(bio or "", BIO_PATTERNS)
    if profile_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"资料文字命中广告规则: {profile_hit}",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    name_link_hit = _detect_profile_name_bot_invite_ad(display, username, bio)
    if name_link_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"广告化姓名与Bio Bot拉新链接组合命中: {name_link_hit}",
            "source": "profile_name_bot_invite",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    smuggled_trade_hit = _detect_smuggled_goods_profile_ad(display, username, bio)
    if smuggled_trade_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"资料命中走私商品交易组合: {smuggled_trade_hit}",
            "source": "profile_smuggled_goods_trade",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    coded_phone_name_hit = _detect_coded_phone_distribution_profile_ad(
        display, username, bio, []
    )
    if coded_phone_name_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"资料命中手机分销广告组合: {coded_phone_name_hit}",
            "source": "profile_coded_phone_distribution",
            "personal_chat_id": 0,
            "status_ids": status_ids,
            "status_text": status_text,
        }

    invite_teaser = _detect_invite_teaser_ad(bio)
    if invite_teaser:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"Bio群邀请链接命中规避式引流话术: {invite_teaser}",
            "source": "bio_invite_teaser",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    personal_parts, personal_chat_id = _personal_channel_parts(
        bot,
        chat_info,
        int(uid or 0),
        personal_channel_messages=personal_channel_messages,
    )

    sticker_texts = _sticker_texts(bot, status_ids)

    status_text = " ".join(sticker_texts)

    coded_phone_hit = _detect_coded_phone_distribution_profile_ad(
        display, username, bio, personal_parts
    )
    if coded_phone_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"资料命中手机分销广告组合: {coded_phone_hit}",
            "source": "profile_coded_phone_distribution",
            "personal_chat_id": personal_chat_id,
            "status_ids": status_ids,
            "status_text": status_text,
        }

    personal_result = _detect_personal_channel_ad(personal_parts)
    recruitment_result = _detect_personal_channel_avatar_bridge_candidate(personal_parts)
    if personal_result["is_ad"]:
        anchor_text = "+".join(personal_result["anchors"])
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"个人资料关联频道命中组合广告语义: {anchor_text}",
            "source": "personal_chat",
            "personal_chat_id": personal_chat_id,
            "personal_chat_anchors": personal_result["anchors"],
            "status_ids": status_ids,
            "status_text": status_text,
        }

    status_hit = _match_ad_patterns(status_text)
    if status_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"emoji状态命中广告规则: {status_hit}",
            "status_ids": status_ids,
            "status_text": status_text,
        }

    ocr_text = " ".join(_ocr_sticker_texts(bot, status_ids, config))
    ocr_hit = _match_ad_patterns(ocr_text)
    if ocr_hit:
        return {
            "is_ad": True,
            "score": 3,
            "reason": f"emoji状态图片OCR命中广告规则: {ocr_hit}",
            "status_ids": status_ids,
            "status_text": status_text,
            "ocr_text": ocr_text,
        }

    if status_ids:
        has_vl = _has_vision_model(config)
        if not has_vl and config is not None:
            base_score = 2
            reason = "存在自定义emoji状态，未读到明确广告文字（无视觉模型降级）"
            no_vl_flag = True
        else:
            base_score = 1
            reason = "存在自定义emoji状态，未读到明确广告文字"
            no_vl_flag = False
        return {
            "is_ad": False,
            "score": base_score,
            "reason": reason,
            "status_ids": status_ids,
            "status_text": status_text,
            "ocr_text": ocr_text,
            "no_vision_model": no_vl_flag,
            "personal_chat_id": personal_chat_id,
            "personal_chat_anchors": personal_result["anchors"],
            "avatar_bridge_candidate": recruitment_result["is_candidate"],
            "personal_chat_recruitment_anchors": recruitment_result["anchors"],
        }

    return {
        "is_ad": False,
        "score": 0,
        "reason": "",
        "status_ids": [],
        "status_text": "",
        "personal_chat_id": personal_chat_id,
        "personal_chat_anchors": personal_result["anchors"],
        "avatar_bridge_candidate": recruitment_result["is_candidate"],
        "personal_chat_recruitment_anchors": recruitment_result["anchors"],
    }
