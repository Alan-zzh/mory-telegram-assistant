# -*- coding: utf-8 -*-
"""
modules/proactive_engage.py  ·  商业问题主动搭讪模块（v5.14.0）

调用链路：dispatcher._dispatch_p7_5_proactive_engage() → should_engage() → engage()
"""
import time
import threading
import traceback
import random
from typing import Tuple

from core.logging_util import get_logger
from core.helpers import format_user_mention

logger = get_logger("proactive_engage")

# A/B 群搭讪话术模板（防重复感，30-50字+私聊引导）
_FALLBACK_TEMPLATES = [
    "{uname}~订阅的话不同档位权益不一样哦，想看具体的细节私聊我跟你慢慢说～",
    "嗯嗯，关于{uname}问的这个～群里不太方便细说，私聊我呀，把完整对比发你～",
    "{uname}～这个我看一眼~想知道详情可以私聊我，免得群里刷屏啦～",
    "关于{uname}问的这个~ 内容比较多，私聊我给你单独发一份清单好不好呀～",
]

_FALLBACK_BY_INTENT = {
    "price": [
        "{uname}～价格我可以给你按档位捋清楚，群里容易刷屏，私聊我发你完整对比～",
        "这个看你想要月/季/年哪种呀，{uname}私聊我，我按适合你的方式说清楚～",
    ],
    "rights": [
        "{uname}问到权益啦～不同档位差别不小，私聊我我给你列一版好懂的～",
        "权益这块一句话说不全，{uname}私聊我，我把适合你的那档单独讲～",
    ],
    "trial": [
        "{uname}想先看看感觉对不对吧～私聊我，我发你能公开说的预览和说明～",
        "可以先别急着下单，{uname}私聊我，我帮你判断哪种更合适～",
    ],
    "payment": [
        "{uname}下单不用在群里操作，私聊我我把自助入口和步骤发你～",
        "支付这块群里不展开啦，{uname}私聊我，我把自助下单路径给你～",
    ],
    "repeat": [
        "{uname}我记得你刚才也问过类似的，我这次直接给你整理重点，私聊我～",
        "你这个问题和前面有点连着，{uname}私聊我，我按你的情况接着说～",
    ],
}

# 私聊引导话术模板（含 @MorychannelBot 自助下单提示）
_PRIVATE_TEMPLATES = [
    "💌 嘿，{uname}～\n刚才群里你说的那个我看到了～\n想了解具体细节的话，私聊我聊就行～\n\n@MorychannelBot 那边有自助下单链接，按提示操作就OK～",
    "💌 {uname}～\n群里我没细说怕打扰别人\n想看具体权益对比的话，私聊我就行～\n\n@MorychannelBot 可以自助下单，价格透明",
]


class ProactiveEngage:
    """商业问题主动搭讪管理器

    设计原则：
    1. 严格静默失败（不抛未捕获异常）
    2. [Codex] 落库冷却优先，内存冷却兜底
    3. 跨群共享冷却（同一 uid 在所有群共享）
    4. 搭讪后调用方拦截 P10 AI（避免重复回复）
    """

    def __init__(self, db, mory_bot, ai, config: dict, keyword_manager=None):
        self.db = db
        self.mory_bot = mory_bot
        self.ai = ai
        self.config = config or {}
        self.keyword_manager = keyword_manager

        # 内存冷却字典：{uid: last_engage_ts}
        self._cooldown_dict: dict = {}
        # 每日计数字典：{uid: (date_str, count)}
        self._daily_count_dict: dict = {}
        self._cooldown_lock = threading.Lock()
        self._last_cleanup = 0.0

    # ────────────────────────── 公开 API ──────────────────────────

    def should_engage(self, uid: int, msg: str, is_admin: bool) -> Tuple[bool, str]:
        """判断是否应该搭讪该用户

        Args:
            uid: 用户ID
            msg: 消息文本
            is_admin: 是否管理员

        Returns:
            (should_engage, matched_keyword)
            - (True, "订阅") 表示应搭讪，命中"订阅"关键词
            - (False, "") 表示不搭讪
        """
        try:
            cfg = self.config.get("PROACTIVE_ENGAGE_CONFIG", {})
            if not cfg.get("enabled", False):
                return (False, "")

            if is_admin:
                return (False, "")

            # 群黑名单/全局黑名单已在 P1 拦截，这里不必再判

            # 消息含商业关键词检测
            from modules.group_mgr import _is_convert_message
            if not _is_convert_message(msg, self.keyword_manager):
                return (False, "")

            matched_kw = self._find_matched_keyword(msg)
            if not matched_kw:
                return (False, "")

            # [Codex] 冷却检查优先读 proactive_engage_log，重启后仍生效。
            if self._is_in_cooldown(uid, cfg.get("cooldown_minutes", 30)):
                return (False, "")

            # 每日上限检查
            max_per_day = cfg.get("max_per_user_per_day", 3)
            if max_per_day > 0 and self._get_daily_count(uid) >= max_per_day:
                return (False, "")

            return (True, matched_kw)
        except Exception as e:
            logger.warning(f"proactive_engage.should_engage 异常: {e}")
            return (False, "")

    def engage(self, uid: int, uname: str, chat_id: int, msg: str,
               matched_keyword: str, m) -> bool:
        """执行搭讪：生成话术 + 发群 + 发私聊 + 入库 + 通知管理员

        Returns:
            True 表示搭讪成功执行，False 表示执行失败（但已静默处理）
        """
        try:
            reply_text = self._generate_reply(msg, matched_keyword, uname, uid)
            sent_msg = self._send_group_reply(m, reply_text, uid)
            self._send_private_guidance(uid, uname)
            self._notify_admin_if_needed(uname, uid, msg, matched_keyword)
            self._persist_engage(uid, chat_id, uname, msg, matched_keyword, reply_text)
            self._set_cooldown(uid)
            self._add_feedback_button(sent_msg)
            logger.info(
                f"💬 商业搭讪成功 uid={uid} uname={uname} chat={chat_id} "
                f"keyword={matched_keyword} len={len(reply_text)}"
            )
            return True
        except Exception as e:
            logger.warning(f"proactive_engage.engage 异常 uid={uid}: {e}\n{traceback.format_exc()}")
            return False

    # ────────────────────────── 内部方法（engage 拆解） ──────────────────────────

    def _send_group_reply(self, m, reply_text: str, uid: int):
        """群内搭讪回复（失败静默）

        [v5.12.4] 改用 bot.send_message + track_bot_message
        原逻辑用 reply_and_track（track_reply）会把搭讪消息当作用户触发的回复，
        但搭讪场景下用户原消息（广告）已被立即删除，导致搭讪消息变成孤儿。
        现改为 Bot 主动消息入库（user_msg_id=0, replied=1），30分钟无人理时自动清理。
        """
        try:
            cid = m.chat.id
            bot = self.mory_bot.bot if hasattr(self.mory_bot, "bot") else None
            if not bot:
                logger.warning(f"proactive_engage 无法获取 bot 实例 uid={uid}")
                return None
            # [v5.12.4] 改为普通发送而非 reply_to，避免 track_reply 把搭讪误判为对已删广告的回复
            sent = bot.send_message(cid, reply_text)
            if sent and hasattr(sent, "message_id") and hasattr(self.db, "track_bot_message"):
                try:
                    self.db.track_bot_message(cid, sent.message_id)
                    logger.info(
                        f"📌 搭讪消息追踪入库：bot={sent.message_id} chat={cid}"
                    )
                except Exception as track_err:
                    logger.debug(f"搭讪消息 track_bot_message 失败（不影响发送）: {track_err}")
            return sent
        except Exception as e:
            logger.warning(f"proactive_engage 群回复失败 uid={uid}: {e}")
            return None

    def _send_private_guidance(self, uid: int, uname: str):
        """私聊发送详细引导（失败静默）"""
        try:
            private_text = random.choice(_PRIVATE_TEMPLATES).format(uname=uname)
            self._send_private(uid, private_text)
        except Exception as e:
            logger.debug(f"proactive_engage 私聊发送失败 uid={uid}: {e}")

    def _notify_admin_if_needed(self, uname: str, uid: int, msg: str, keyword: str):
        """视奸雷达通知管理员（与 P7 行为一致）"""
        try:
            admin_id = self.config.get("ADMIN_ID", 0)
            if admin_id:
                self._notify_admin(admin_id, uname, uid, msg, keyword)
        except Exception as e:
            logger.warning(f"proactive_engage 管理员通知失败: {e}")

    def _persist_engage(self, uid: int, chat_id: int, uname: str,
                       msg: str, matched_keyword: str, reply_text: str):
        """入库 + 转化事件（失败静默）"""
        try:
            if hasattr(self.db, "log_proactive_engage"):
                self.db.log_proactive_engage(
                    uid=uid, chat_id=chat_id, uname=uname, msg=msg,
                    matched_keyword=matched_keyword, reply_text=reply_text,
                )
        except Exception as e:
            logger.warning(f"proactive_engage 入库失败 uid={uid}: {e}")
        try:
            if hasattr(self.db, "log_conversion_event"):
                self.db.log_conversion_event(uid, "proactive_engaged")
        except Exception as e:
            logger.debug(f"proactive_engage 转化事件记录失败: {e}")

    def _add_feedback_button(self, sent_msg):
        """给搭讪消息加 👍/👎 反馈按钮（仅当 send_msg 成功时，失败静默）"""
        if not (sent_msg and hasattr(sent_msg, "chat") and hasattr(sent_msg, "message_id")):
            return
        try:
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            bot = self.mory_bot.bot if hasattr(self.mory_bot, "bot") else None
            if not bot:
                return
            fb_markup = InlineKeyboardMarkup()
            fb_markup.row(
                InlineKeyboardButton("👍", callback_data=f"fb_like_{sent_msg.message_id}"),
                InlineKeyboardButton("👎", callback_data=f"fb_dislike_{sent_msg.message_id}"),
            )
            bot.edit_message_reply_markup(
                chat_id=sent_msg.chat.id,
                message_id=sent_msg.message_id,
                reply_markup=fb_markup,
            )
        except Exception:
            pass

    # ────────────────────────── 内部方法 ──────────────────────────

    def _generate_reply(self, msg: str, matched_keyword: str, uname: str, uid: int = 0) -> str:
        """生成搭讪话术（AI 失败时 fallback 到模板）"""
        intent = self._classify_intent(msg, matched_keyword)
        consult_count = self._get_recent_consult_count_from_db(uid)
        # 优先尝试 AI 生成
        try:
            from modules.group_mgr import _is_convert_message
            if self.ai and _is_convert_message(msg, self.keyword_manager):
                stage_hint = self._build_stage_hint(consult_count)
                prompt = (
                    f"用户 {uname} 在群里说：\"{msg}\"\n"
                    f"他可能在问商业相关问题（命中关键词：{matched_keyword}）。\n"
                    f"用户咨询阶段：{stage_hint}；问题类型：{intent}。\n"
                    f"请用30-50字回复，先简短回应他，再自然引导他私聊。\n"
                    f"要求：温柔不直白营销、不称'老板'、不重复固定模板、\n"
                    f"末尾可加一句'私聊我呀～'或'详情私聊我说'，但不要每句都加。\n"
                    f"绝对不要使用'老板'称谓。\n"
                )
                sys_prompt = self.config.get("PROMPT_TEMPLATES", {}).get(
                    "business_engage",
                    _FALLBACK_TEMPLATES[0],
                )
                full_prompt = sys_prompt + "\n\n" + prompt

                # 使用 normal 模式 + 直送 prompt（避免被 ai_engine 改写）
                ai_reply = self.ai.ask(full_prompt, mode="normal")
                if ai_reply and len(ai_reply.strip()) > 5:
                    text = ai_reply.strip()
                    if len(text) > 300:
                        text = text[:300]
                    return text
        except Exception as e:
            logger.debug(f"proactive_engage AI 生成失败，使用 fallback: {e}")

        # fallback
        templates = _FALLBACK_BY_INTENT.get(intent, _FALLBACK_TEMPLATES)
        if consult_count >= 2:
            templates = _FALLBACK_BY_INTENT["repeat"] + templates
        return random.choice(templates).format(uname=uname)

    def _send_private(self, uid: int, text: str):
        """私聊发送引导消息（失败静默）"""
        try:
            bot = self.mory_bot.bot if hasattr(self.mory_bot, "bot") else None
            if bot:
                bot.send_message(uid, text)
        except Exception as e:
            logger.debug(f"proactive_engage 私聊发送失败 uid={uid}: {e}")

    def _notify_admin(self, admin_id: int, uname: str, uid: int, msg: str, keyword: str):
        """视奸雷达通知管理员"""
        try:
            bot = self.mory_bot.bot if hasattr(self.mory_bot, "bot") else None
            if not bot:
                return
            _safe_msg = msg.replace("<", "&lt;").replace(">", "&gt;")[:150]
            bot.send_message(
                admin_id,
                f"💬 商业搭讪雷达\n"
                f"👤 {format_user_mention(uid, uname)}\n"
                f"💬 消息：{_safe_msg}\n"
                f"🔑 关键词：{keyword}\n"
                f"💡 Bot 已主动搭讪引导私聊",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug(f"proactive_engage 管理员通知失败: {e}")

    def _classify_intent(self, msg: str, keyword: str) -> str:
        """[Codex] 将咨询拆成粗阶段，fallback 按意图换说法。"""
        text = f"{msg or ''} {keyword or ''}"
        if any(k in text for k in ("多少钱", "价格", "价位", "包月", "包季", "包年", "订阅")):
            return "price"
        if any(k in text for k in ("权益", "内容", "有什么", "区别", "档位", "全享", "精选")):
            return "rights"
        if any(k in text for k in ("看看", "预览", "试试", "样例", "图集")):
            return "trial"
        if any(k in text for k in ("下单", "支付", "付款", "怎么买", "入口", "链接")):
            return "payment"
        return "general"

    def _build_stage_hint(self, consult_count: int) -> str:
        """[Codex] 根据近期待咨询次数给 AI 一个轻量阶段提示。"""
        if consult_count <= 0:
            return "首次轻问，只需温柔承接，不要催单"
        if consult_count == 1:
            return "二次咨询，可以更具体一点，但仍然保持克制"
        return "多次咨询，直接整理重点并引导私聊承接"

    def _get_recent_consult_count_from_db(self, uid: int, hours: int = 24) -> int:
        """[Codex] 从搭讪日志读取近期待咨询次数，失败时回落内存计数。"""
        try:
            if not uid or not getattr(self.db, "conn", None):
                return self._get_daily_count(uid)
            since_ts = int(time.time()) - hours * 3600
            row = self.db.conn.execute(
                "SELECT COUNT(*) FROM proactive_engage_log WHERE uid=? AND ts>=?",
                (uid, since_ts),
            ).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return self._get_daily_count(uid)

    def _find_matched_keyword(self, msg: str) -> str:
        """找出命中的第一个商业关键词（用于日志和入库）"""
        try:
            # 优先使用 KeywordManager
            if self.keyword_manager:
                substr_kws = self.keyword_manager.get_convert_keywords_substr()
                word_kws = self.keyword_manager.get_convert_keywords_word()
            else:
                from modules.group_mgr import _CONVERT_KEYWORDS_SUBSTR, _CONVERT_KEYWORDS_WORD
                substr_kws = _CONVERT_KEYWORDS_SUBSTR
                word_kws = _CONVERT_KEYWORDS_WORD
            # 优先子串匹配
            for kw in substr_kws:
                if kw in msg:
                    return kw
            # 全词匹配
            import re
            words = re.split(r'[^\u4e00-\u9fff]+', msg)
            for w in words:
                if w in word_kws:
                    return w
        except Exception:
            pass
        return ""

    def _is_in_cooldown(self, uid: int, cooldown_minutes: int) -> bool:
        """检查用户是否在冷却期内"""
        try:
            if cooldown_minutes <= 0:
                return False
            if self._is_in_persisted_cooldown(uid, cooldown_minutes):
                return True
            self._maybe_cleanup_cooldowns()
            with self._cooldown_lock:
                last_ts = self._cooldown_dict.get(uid, 0)
                if last_ts <= 0:
                    return False
                elapsed = time.time() - last_ts
                return elapsed < cooldown_minutes * 60
        except Exception:
            return False

    def _is_in_persisted_cooldown(self, uid: int, cooldown_minutes: int) -> bool:
        """[Codex] 落库冷却：服务重启后仍避免重复搭讪。"""
        try:
            if not uid or not getattr(self.db, "conn", None):
                return False
            row = self.db.conn.execute(
                "SELECT MAX(ts) FROM proactive_engage_log WHERE uid=?",
                (uid,),
            ).fetchone()
            last_ts = int(row[0] or 0) if row else 0
            return last_ts > 0 and time.time() - last_ts < cooldown_minutes * 60
        except Exception:
            return False

    def _set_cooldown(self, uid: int):
        """设置用户冷却时间戳 + 每日计数+1"""
        try:
            with self._cooldown_lock:
                self._cooldown_dict[uid] = time.time()
                self._increment_daily_count(uid)
        except Exception as e:
            logger.debug(f"proactive_engage 设置冷却失败: {e}")

    def _get_daily_count(self, uid: int) -> int:
        """获取用户今日搭讪次数"""
        try:
            persisted = self._get_today_count_from_db(uid)
            if persisted > 0:
                return persisted
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            with self._cooldown_lock:
                entry = self._daily_count_dict.get(uid)
                if not entry or entry[0] != today:
                    return 0
                return entry[1]
        except Exception:
            return 0

    def _get_today_count_from_db(self, uid: int) -> int:
        """[Codex] 每日上限优先读库，避免重启后重复触达。"""
        try:
            if not uid or not getattr(self.db, "conn", None):
                return 0
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            row = self.db.conn.execute(
                "SELECT COUNT(*) FROM proactive_engage_log WHERE uid=? AND date(ts, 'unixepoch', 'localtime')=?",
                (uid, today),
            ).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0

    def _increment_daily_count(self, uid: int):
        """用户今日搭讪计数+1（需在 _cooldown_lock 内调用）"""
        try:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            entry = self._daily_count_dict.get(uid)
            if not entry or entry[0] != today:
                self._daily_count_dict[uid] = (today, 1)
            else:
                self._daily_count_dict[uid] = (today, entry[1] + 1)
        except Exception:
            pass

    def _maybe_cleanup_cooldowns(self):
        """每10分钟清理一次过期冷却和昨日计数（防内存膨胀）"""
        try:
            now = time.time()
            if now - self._last_cleanup < 600:
                return
            self._last_cleanup = now
            with self._cooldown_lock:
                # 清理过期冷却（2小时以上）
                expired = [uid for uid, ts in self._cooldown_dict.items() if now - ts > 7200]
                for uid in expired:
                    del self._cooldown_dict[uid]
                # 清理昨日计数
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                stale = [uid for uid, entry in self._daily_count_dict.items() if entry[0] != today]
                for uid in stale:
                    del self._daily_count_dict[uid]
        except Exception:
            pass
