# -*- coding: utf-8 -*-
"""私聊预设照片路由。

只发送项目内已审核的静态素材，不调用 LLM、不生成图片。触发优先级为：
原味 > 本人/真实照片 > 普通索图；福利/内容类预设文字发送后追加普通照片。
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from core.logging_util import get_logger


logger = get_logger("private_preset_media")

MEDIA_ROOT = Path(__file__).resolve().parents[1] / "assets" / "preset_media"
ORIGINAL_TASTE_ASSET = "original_taste_menu.png"
SELF_PORTRAIT_ASSET = "mory_self_portrait.png"
PHOTO_POOL = (
    SELF_PORTRAIT_ASSET,
    "photo_pool_01.png",
    "photo_pool_02.png",
    "photo_pool_03.png",
    "photo_pool_04.png",
    "photo_pool_05.png",
    "photo_pool_06.png",
    "photo_pool_07.png",
)

_SELF_MARKER_RE = re.compile(
    r"(?:本人|真人|真实|你本人|妳本人|你自己|妳自己|你的|妳的)",
    re.I | re.S,
)
_PHOTO_REQUEST_RE = re.compile(
    r"(?:发|發|给|給|来|來|看|看看|想看|要看|瞧)"
    r".{0,8}(?:照片|图片|圖片|相片|自拍|写真|寫真|图|圖)|"
    r"(?:照片|图片|圖片|相片|自拍|写真|寫真)"
    r".{0,8}(?:发|發|给|給|来|來|看|看看|想看|要看)|"
    r"(?:有|有没有|有沒有).{0,4}(?:照片|图片|圖片|相片|自拍|写真|寫真)(?:吗|嗎|么|麼|嘛|？|\?)|"
    r"^(?:照片|图片|圖片|相片|自拍|写真|寫真)[呀啊吗嗎呢嘛么麼～~!！?？ ]*$",
    re.I | re.S,
)
_MEDIA_NEGATION_RE = re.compile(
    r"(?:不要|不用|无需|別|别|不想|停止|取消|别再|不要再).{0,12}"
    r"(?:发|發|看|照片|图片|圖片|相片|自拍|写真|寫真|原味)|"
    r"(?:照片|图片|圖片|相片|自拍|写真|寫真|原味).{0,12}"
    r"(?:不要|不用|无需|別发|别发|不想看|别再发|不要再发)",
    re.I | re.S,
)
_MEDIA_FEEDBACK_RE = re.compile(
    r"(?:照片|图片|圖片|相片|自拍|写真|寫真|图|圖).{0,12}"
    r"(?:好看|漂亮|不错|不錯|拍得|喜欢|喜歡|保存了|收到了)|"
    r"(?:好看|漂亮|不错|不錯|喜欢|喜歡).{0,12}"
    r"(?:照片|图片|圖片|相片|自拍|写真|寫真|图|圖)",
    re.I | re.S,
)

_APPEND_MEDIA_TOPICS = frozenset({"福利", "内容", "VIP权益", "至臻全享"})

# 触达频控：这是全链路唯一没有冷却的销售触达面，换措辞连发即可无限触发。
# 冷却 + 每日上限双闸；持久化到 system_state，重启不重置。
_RATE_COOLDOWN_SECONDS = 600
_RATE_DAILY_LIMIT = 10
_CST = timezone(timedelta(hours=8))


class PrivatePresetMediaService:
    """同步发送私聊审核照片，并提供持久幂等与随机不连发保护。"""

    def __init__(self, db, *, media_root: Path = MEDIA_ROOT, chooser=None,
                 cooldown_seconds: int = _RATE_COOLDOWN_SECONDS,
                 daily_limit: int = _RATE_DAILY_LIMIT):
        self.db = db
        self.media_root = Path(media_root)
        self._chooser = chooser or secrets.choice
        self._cooldown_seconds = max(0, int(cooldown_seconds))
        self._daily_limit = int(daily_limit)
        self._locks_guard = threading.Lock()
        self._user_locks: dict[int, threading.Lock] = {}

    @staticmethod
    def detect_scene(text: str) -> str | None:
        normalized = str(text or "").strip()
        if not normalized:
            return None
        if _MEDIA_NEGATION_RE.search(normalized):
            return None
        if _MEDIA_FEEDBACK_RE.search(normalized):
            return None
        if "原味" in normalized:
            return "original_taste"
        if _SELF_MARKER_RE.search(normalized) and _PHOTO_REQUEST_RE.search(normalized):
            return "self_portrait"
        if _PHOTO_REQUEST_RE.search(normalized):
            return "photo_random"
        return None

    @staticmethod
    def scene_for_rule(rule: dict | None) -> str | None:
        """福利/内容类预设文字送达后，追加一张无配文的随机照片。"""
        item = rule if isinstance(rule, dict) else {}
        topic = str(item.get("topic") or "").strip()
        name = str(item.get("name") or "").strip()
        if topic in _APPEND_MEDIA_TOPICS:
            return "photo_random"
        if any(marker in name for marker in ("福利咨询", "内容咨询", "订阅权益")):
            return "photo_random"
        return None

    @staticmethod
    def caption_for(scene: str) -> str:
        # 称呼与搭讪链口径统一：温柔但不使用“宝宝”类亲昵称呼。
        if scene == "original_taste":
            return (
                "原味定制的现有档位和说明在图里～需要哪一项可以去 "
                "@MorychannelBot 选择；特殊定制把具体需求留言给我。"
            )
        if scene == "self_portrait":
            return "是想看本人照片呀，先给你一张～"
        return "想看照片呀，先给你一张～更多照片和视频预览在 @moryselect。"

    def _lock_for(self, user_id: int) -> threading.Lock:
        with self._locks_guard:
            return self._user_locks.setdefault(int(user_id), threading.Lock())

    @staticmethod
    def _rate_ts_key(user_id: int) -> str:
        return f"private_preset_media:last_sent_ts:{int(user_id)}"

    @staticmethod
    def _rate_day_key(user_id: int) -> str:
        return f"private_preset_media:daily_count:{int(user_id)}"

    def _check_rate_limit(self, user_id: int) -> bool:
        """返回 True 表示放行；冷却中或超每日上限时返回 False。"""
        try:
            now = time.time()
            if self._cooldown_seconds > 0:
                last_ts = float(self.db.get_system_state(self._rate_ts_key(user_id), 0) or 0)
                if last_ts > 0 and now - last_ts < self._cooldown_seconds:
                    logger.info(
                        "私聊预设媒体冷却中 uid=%s 剩余=%ss",
                        user_id,
                        int(self._cooldown_seconds - (now - last_ts)),
                    )
                    return False
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            raw = self.db.get_system_state(self._rate_day_key(user_id), "")
            try:
                decoded = json.loads(str(raw or ""))
            except (TypeError, ValueError):
                decoded = {}
            if (
                self._daily_limit > 0
                and isinstance(decoded, dict)
                and decoded.get("date") == today
                and int(decoded.get("count") or 0) >= self._daily_limit
            ):
                logger.info("私聊预设媒体已达每日上限 uid=%s count=%s", user_id, decoded.get("count"))
                return False
            return True
        except Exception as exc:
            logger.warning("私聊预设媒体频控检查失败 uid=%s: %s", user_id, exc)
            return True

    def _record_send_for_rate(self, user_id: int):
        try:
            self.db.set_system_state(self._rate_ts_key(user_id), time.time())
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            raw = self.db.get_system_state(self._rate_day_key(user_id), "")
            try:
                decoded = json.loads(str(raw or ""))
            except (TypeError, ValueError):
                decoded = {}
            count = (
                int(decoded.get("count") or 0)
                if isinstance(decoded, dict) and decoded.get("date") == today
                else 0
            )
            self.db.set_system_state(
                self._rate_day_key(user_id),
                json.dumps({"date": today, "count": count + 1}, separators=(",", ":")),
            )
        except Exception as exc:
            logger.debug("私聊预设媒体频控计数失败 uid=%s: %s", user_id, exc)

    @staticmethod
    def _message_id_from_state(raw_state: Any) -> str:
        try:
            decoded = json.loads(str(raw_state or ""))
        except (TypeError, ValueError):
            return str(raw_state or "")
        if isinstance(decoded, dict):
            return str(decoded.get("message_id") or "")
        return str(decoded or "")

    @staticmethod
    def _last_message_key(user_id: int) -> str:
        return f"private_preset_media:last_message:{int(user_id)}"

    @staticmethod
    def _last_asset_key(user_id: int) -> str:
        return f"private_preset_media:last_asset:{int(user_id)}"

    def _choose_asset(self, scene: str, user_id: int) -> str:
        if scene == "original_taste":
            return ORIGINAL_TASTE_ASSET
        if scene == "self_portrait":
            return SELF_PORTRAIT_ASSET
        if scene != "photo_random":
            raise ValueError(f"unsupported private preset media scene: {scene}")
        last_asset = self.db.get_system_state(self._last_asset_key(user_id), "")
        candidates = [asset for asset in PHOTO_POOL if asset != last_asset]
        return self._chooser(candidates or list(PHOTO_POOL))

    def send_for_request(
        self,
        message,
        mory_bot,
        *,
        scene: str,
        include_caption: bool = True,
    ) -> str:
        """返回 sent/duplicate/failed；外部发送前先持久领取，避免重复实发。"""
        user = getattr(message, "from_user", None)
        user_id = int(getattr(user, "id", 0) or 0)
        message_id = int(getattr(message, "message_id", 0) or 0)
        chat = getattr(message, "chat", None)
        if str(getattr(chat, "type", "") or "") != "private":
            return "not_applicable"
        if not user_id or not message_id:
            logger.error("私聊预设媒体缺少 user_id/message_id，已拒绝发送")
            return "failed"

        with self._lock_for(user_id):
            state_key = self._last_message_key(user_id)
            last_state = self.db.get_system_state(state_key, "")
            if self._message_id_from_state(last_state) == str(message_id):
                logger.info(
                    "私聊预设媒体重复更新已跳过 uid=%s message_id=%s scene=%s",
                    user_id,
                    message_id,
                    scene,
                )
                return "duplicate"

            # 频控放在幂等重放之后：同一条消息的重试不算新触达。
            if not self._check_rate_limit(user_id):
                return "rate_limited"

            asset_name = self._choose_asset(scene, user_id)
            asset_path = self.media_root / asset_name
            if not asset_path.is_file() or asset_path.stat().st_size <= 0:
                logger.error("私聊预设媒体不存在或为空 scene=%s asset=%s", scene, asset_path)
                return "failed"

            pending_state = json.dumps(
                {"message_id": message_id, "status": "pending"},
                separators=(",", ":"),
            )
            try:
                self.db.set_system_state(state_key, pending_state)
            except Exception as exc:
                logger.error("私聊预设媒体持久领取失败 uid=%s: %s", user_id, exc)
                return "failed"

            try:
                send_kwargs = {}
                if include_caption:
                    send_kwargs["caption"] = self.caption_for(scene)
                with asset_path.open("rb") as source:
                    sent = mory_bot.reply_photo_and_track(message, source, **send_kwargs)
                if not sent:
                    raise RuntimeError("Telegram 未返回照片消息回执")
            except Exception as exc:
                logger.warning(
                    "私聊预设媒体发送失败 scene=%s uid=%s asset=%s: %s",
                    scene,
                    user_id,
                    asset_name,
                    exc,
                )
                return "failed"

            try:
                self.db.set_system_state(self._last_asset_key(user_id), asset_name)
                self.db.set_system_state(
                    state_key,
                    json.dumps(
                        {"message_id": message_id, "status": "sent"},
                        separators=(",", ":"),
                    ),
                )
            except Exception as exc:
                logger.error(
                    "私聊预设媒体已送达但回执持久化失败 uid=%s: %s",
                    user_id,
                    exc,
                )
            self._record_send_for_rate(user_id)
            logger.info(
                "私聊预设媒体发送成功 scene=%s uid=%s asset=%s bytes=%s token=0",
                scene,
                user_id,
                asset_name,
                asset_path.stat().st_size,
            )
            return "sent"
