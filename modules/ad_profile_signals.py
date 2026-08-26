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

    personal_parts, personal_chat_id = _personal_channel_parts(
        bot,
        chat_info,
        int(uid or 0),
        personal_channel_messages=personal_channel_messages,
    )

    sticker_texts = _sticker_texts(bot, status_ids)

    status_text = " ".join(sticker_texts)

    # 普通字段证据保持隔离：姓名/username 只跑账号名规则，Bio 只跑 Bio 规则。
    # 唯一例外是高置信“广告化姓名 + Bot 拉新深链”组合，禁止用普通文字+裸链接定罪。
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

    personal_result = _detect_personal_channel_ad(personal_parts)
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
        }

    return {
        "is_ad": False,
        "score": 0,
        "reason": "",
        "status_ids": [],
        "status_text": "",
        "personal_chat_id": personal_chat_id,
        "personal_chat_anchors": personal_result["anchors"],
    }
