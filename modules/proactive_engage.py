# -*- coding: utf-8 -*-
"""
modules/proactive_engage.py  ·  商业问题主动搭讪模块（v5.14.0）

调用链路：dispatcher._dispatch_p7_5_proactive_engage() → should_engage() → engage()
"""
import time
import threading
import traceback
import random
import re
from typing import Tuple
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger
from core.helpers import format_user_mention

logger = get_logger("proactive_engage")

# 【v5.31.2 修复】VPS 运行在 UTC，每日搭讪限额按 CST 重置（原 UTC 导致 CST 0:00-8:00 仍算昨日）
_CST = timezone(timedelta(hours=8))

# A/B 群承接话术模板：了解阶段先预览，明确购买才进入自助。
# 【Agent F】走心化：先回应关切、再自然带唯一入口，不催单、不虚假承诺、无客服腔。
_FALLBACK_TEMPLATES = [
    "{uname}，你说的情况我懂，想先踏实看看的话，@moryselect 里有预览，看完心里就有数了。",
    "{uname}，我在听，别急。@moryselect 的预览可以先慢慢看，看完还想聊随时找我。",
    "嗯，我明白你问的是啥，具体内容 @moryselect 里都有预览，你先看看合不合眼缘。",
]

_FALLBACK_BY_INTENT = {
    "price": [
        "{uname}，价格的事我懂你在意，先看 @moryselect 的预览把内容弄清楚，心里有数了再聊也不迟。",
        "钱的事不急着定，先看看 @moryselect 里的预览值不值，你看完我们再慢慢说。",
    ],
    "rights": [
        "{uname}，内容区别一两句说不清，@moryselect 里的预览会更直观，你看了就知道差别在哪。",
        "你在意的点我记下了，@moryselect 有实际内容预览，你对比着看会更安心。",
    ],
    "trial": [
        "{uname}，想先看看当然可以，@moryselect 就是给你看预览的地方，看完有什么想细问的再来找我。",
        "预览看完再决定就好，@moryselect 里都有，我不催你。",
    ],
    "payment": [
        "{uname}，想继续的话，@MorychannelBot 里有当前可选的内容和档位，按提示自助完成就行。",
        "入口给你放这啦，@MorychannelBot 看看当前选项，按提示操作，有问题随时来找我。",
    ],
    "repeat": [
        "{uname}，你说的我记着呢，不用重复发入口，继续说你在意的细节就好。",
        "接着刚才的话聊就行，我在这听着，不催你。",
    ],
}

_DEFAULT_BUSINESS_ENGAGE_PROMPT = (
    "【商业搭讪模式 · Mory 人设】：你是温情清冷、有点俏皮的 Mory 小助理。\n"
    "1. 先承接用户刚才说的商品、定制或购买需求，回应他的原话和关切；\n"
    "2. 再按本轮唯一目标自然带一个入口：了解/价格/内容阶段只给 @moryselect 预览，"
    "明确下单才给 @MorychannelBot，每轮只出现一个入口；\n"
    "3. 不要引导私聊，不催促、不虚假承诺、不称对方“老板”，不讽刺、不挖苦、不责怪；\n"
    "4. 不写动作、场景、镜头或内心旁白，只用可直接发送的聊天正文说话。"
)


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

            from core.growth_optimizer import resolve_conversion_target
            target, _ = resolve_conversion_target(msg, mode="convert")
            if target == "none":
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
        """执行搭讪：生成单目标话术 + 发群 + 入库 + 通知管理员

        Returns:
            True 表示搭讪成功执行，False 表示执行失败（但已静默处理）
        """
        try:
            from core.growth_optimizer import resolve_conversion_target
            conversion_target, conversion_reason = resolve_conversion_target(
                msg,
                mode="convert",
            )
            if conversion_target == "none":
                return False
            reply_text = self._generate_reply(
                msg,
                matched_keyword,
                uname,
                uid,
                conversion_target=conversion_target,
                conversion_reason=conversion_reason,
            )
            sent_msg = self._send_group_reply(m, reply_text, uid)
            if sent_msg is None:
                logger.warning(
                    "proactive_engage 未实际发送，取消成功回执并交还主链 uid=%s",
                    uid,
                )
                return False
            self._notify_admin_if_needed(uname, uid, msg, matched_keyword)
            self._persist_engage(uid, chat_id, uname, msg, matched_keyword, reply_text)
            self._set_cooldown(uid)
            self._add_conversion_button(sent_msg, conversion_target)
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

    def _add_conversion_button(self, sent_msg, conversion_target: str):
        """群内商业承接只挂一个与正文目标一致的按钮。"""
        if not (sent_msg and hasattr(sent_msg, "chat") and hasattr(sent_msg, "message_id")):
            return
        try:
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            bot = self.mory_bot.bot if hasattr(self.mory_bot, "bot") else None
            if not bot:
                return
            fb_markup = InlineKeyboardMarkup(row_width=1)
            if conversion_target == "subscribe":
                fb_markup.row(InlineKeyboardButton(
                    "🛒 自助下单",
                    url="https://t.me/MorychannelBot",
                ))
            elif conversion_target == "preview":
                fb_markup.row(InlineKeyboardButton(
                    "👀 查看预览",
                    url="https://t.me/moryselect",
                ))
            else:
                return
            bot.edit_message_reply_markup(
                chat_id=sent_msg.chat.id,
                message_id=sent_msg.message_id,
                reply_markup=fb_markup,
            )
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # ────────────────────────── 内部方法 ──────────────────────────

    def _generate_reply(
        self,
        msg: str,
        matched_keyword: str,
        uname: str,
        uid: int = 0,
        *,
        conversion_target: str | None = None,
        conversion_reason: str = "",
    ) -> str:
        """生成搭讪话术（AI 失败时 fallback 到模板）"""
        intent = self._classify_intent(msg, matched_keyword)
        consult_count = self._get_recent_consult_count_from_db(uid)
        if conversion_target is None:
            from core.growth_optimizer import resolve_conversion_target
            conversion_target, conversion_reason = resolve_conversion_target(
                msg,
                mode="convert",
            )
        if conversion_target == "none":
            return ""
        target_entry = "@MorychannelBot" if conversion_target == "subscribe" else "@moryselect"
        target_rule = (
            "用户已明确要继续，只给 @MorychannelBot 查看当前可选内容和档位并按提示自助完成。"
            if conversion_target == "subscribe"
            else "用户仍在了解阶段，只给 @moryselect 预览，不催下单。"
        )
        # 优先尝试 AI 生成
        try:
            from modules.group_mgr import _is_convert_message
            if self.ai and _is_convert_message(msg, self.keyword_manager):
                stage_hint = self._build_stage_hint(consult_count)
                sys_prompt = self.config.get("PROMPT_TEMPLATES", {}).get(
                    "business_engage",
                    _DEFAULT_BUSINESS_ENGAGE_PROMPT,
                )
                # 生产旧覆盖若仍要求私聊或固定下单，会压过本轮单目标决策。
                if "唯一目标" not in sys_prompt or "引导私聊" in sys_prompt:
                    sys_prompt = _DEFAULT_BUSINESS_ENGAGE_PROMPT
                ai_stage_hint = (
                    f"{sys_prompt}\n"
                    f"用户咨询阶段：{stage_hint}；问题类型：{intent}；命中关键词：{matched_keyword}。\n"
                    f"本轮唯一目标：{target_rule}\n"
                    f"先直接回应用户原话，再自然带一次 {target_entry}。"
                    "用30-50字自然短句，不称“老板”，不引导私聊，不同时出现两个入口，"
                    "不承诺未确认的定制能力、价格或交付。"
                    "语气延续 Mory 人设：温柔清冷、不端着、不营销腔。"
                )
                # 用户原话继续作为 user message；成交合同放 system stage_hint，
                # 避免让模型把“请回复某用户”的元提示当成聊天内容。
                ai_reply = self.ai.ask(
                    msg,
                    mode="convert",
                    is_priv=False,
                    stage_hint=ai_stage_hint,
                )
                if ai_reply and len(ai_reply.strip()) > 5:
                    text = ai_reply.strip()
                    from core.handlers.ai_reply_handler import _align_conversion_reply
                    text = _align_conversion_reply(
                        text,
                        conversion_target=conversion_target,
                        conversion_reason=conversion_reason,
                    )
                    if len(text) > 300:
                        text = text[:300]
                    return text
        except Exception as e:
            logger.debug(f"proactive_engage AI 生成失败，使用 fallback: {e}")

        # fallback
        if conversion_target == "subscribe":
            templates = _FALLBACK_BY_INTENT["payment"]
        else:
            templates = _FALLBACK_BY_INTENT.get(intent, _FALLBACK_TEMPLATES)
        return random.choice(templates).format(uname=uname)

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
                f"💡 Bot 已按单目标漏斗在群内承接",
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
        return "多次咨询，直接整理重点，但仍只给本轮对应的一个入口"

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
        except Exception as e:
            logger.debug(f"操作异常: {e}")
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
            today = datetime.now(_CST).strftime("%Y-%m-%d")
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
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            row = self.db.conn.execute(
                "SELECT COUNT(*) FROM proactive_engage_log WHERE uid=? AND date(ts, 'unixepoch', '+8 hours')=?",
                (uid, today),
            ).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0

    def _increment_daily_count(self, uid: int):
        """用户今日搭讪计数+1（需在 _cooldown_lock 内调用）"""
        try:
            from datetime import datetime
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            entry = self._daily_count_dict.get(uid)
            if not entry or entry[0] != today:
                self._daily_count_dict[uid] = (today, 1)
            else:
                self._daily_count_dict[uid] = (today, entry[1] + 1)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
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
                today = datetime.now(_CST).strftime("%Y-%m-%d")
                stale = [uid for uid, entry in self._daily_count_dict.items() if entry[0] != today]
                for uid in stale:
                    del self._daily_count_dict[uid]
        except Exception as e:
            logger.debug(f"操作异常: {e}")
