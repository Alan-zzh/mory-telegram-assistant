"""
tasks/support/common.py - 任务模块通用工具函数

将 auto_tasks.py 中可被多个任务复用的工具函数集中到这里。
"""

import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from core.broadcast_formatter import _parse_news_copy, build_rich_news_html
from core.helpers import can_delete_message, get_broadcast_auto_delete_config
from core.logging_util import get_logger
from core.resource_manager import ResourceManager
from core.task_transaction import TaskTransactionManager
from core.telebot_compat import send_message_compat
from tasks.support.fault_reporter import get_fault_reporter
from tasks.support.message_templates import MessageTemplates
from telebot import types

logger = get_logger("tasks.support.common")

_CST = timezone(timedelta(hours=8))

# 新闻去重缓存
_news_pushed_today: set = set()
_news_cache_lock = threading.Lock()

_AI_FALLBACK_MARKERS = (
    "脑子刚才短路",
    "刚才走神",
    "网络有点卡",
    "刚刚没反应过来",
)
_NEWS_INTERNAL_MARKERS = (
    "NewsNow",
    "TrendRadar",
    "多源汇总",
    "均衡筛选",
    "真实新闻源",
    "聚合源",
    "百度热搜",
    "微博热搜",
    "知乎热榜",
    "抖音热点",
    "36氪快讯",
)
_NEWS_SOURCE_LABEL_RE = re.compile(
    r"【(?:社会|综合|国际|生活|体育|文娱|财经|科技)[·|｜][^】]+】"
)


class TaskAbort(Exception):
    """任务中止（非异常，但不应确认完成，需释放数据库锁）。"""

    def __init__(self, message: str, expected: bool = False):
        super().__init__(message)
        self.expected = expected


def record_abort(task_name: str, reason: str):
    """记录任务 abort 原因，连续 3 次触发 P0 告警。"""
    from tasks.support.task_guard import get_task_guard
    get_task_guard().record_claim_fail(task_name, reason)
    logger.warning(f"⚠️ [{task_name}] abort: {reason}")


def send_and_track(rm: ResourceManager, chat_id: int, text: str, parse_mode=None,
                   disable_web_page_preview=None, reply_markup=None):
    """发送消息并追踪浏览量（主动消息也入库 channel_tracking）。"""
    try:
        with rm.locked('bot'):
            # [v5.32] 修复：link_preview_options 由 send_message_compat 统一处理
            # 避免传 dict 给 pyTelegramBotAPI 4.34.0 触发 'dict' object has no attribute 'is_disabled'
            sent = send_message_compat(
                rm.bot,
                chat_id,
                text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
        if sent and hasattr(sent, 'message_id'):
            schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
            if chat_id < 0:
                rm.db.track_channel_message(chat_id, sent.message_id, "text")
                rm.db.track_bot_message(chat_id, sent.message_id)
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


def build_mory_contact_markup(period: str = ""):
    """按播报场景生成语义一致的联系或自助服务按钮。

    历史函数名保留给现有调用方；@Moryfansbot 用于联系 Mory，
    @MorychannelBot 仅用于自助下单和自助订阅。
    """
    actions = {
        "morning": ("☀️ 和 Mory 说早安", "https://t.me/Moryfansbot"),
        "afternoon": ("🛒 自助下单 / 订阅", "https://t.me/MorychannelBot"),
        "evening": ("🌙 找 Mory 聊聊", "https://t.me/Moryfansbot"),
        "news": ("🛒 自助下单 / 订阅", "https://t.me/MorychannelBot"),
    }
    label, url = actions.get(
        period,
        ("🛒 自助下单 / 订阅", "https://t.me/MorychannelBot"),
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            label,
            url=url,
        )
    )
    return markup


def send_greeting(
    rm: ResourceManager,
    chat_id: int,
    text: str,
    category: str = "greeting",
    rich_text: str = "",
    reply_markup=None,
):
    """发送早安/午安/晚安问候，支持"发新删旧"链式互删。

    [v5.32] 新增 rich_text 参数：当 RICH_MESSAGE_ENABLED=true 且 BROADCAST_FORMAT_VERSION
    ∈ {"rich","auto"} 时优先用 rich_text 走 sendRichMessage，失败回退到 text + HTML。
    """
    auto_cfg = get_broadcast_auto_delete_config(rm.config)

    # 链式互删
    if auto_cfg["greeting_chain_delete"] and hasattr(rm, "db") and rm.db is not None:
        try:
            last = rm.db.get_last_broadcast(chat_id, "greeting")
            if last and last[0]:
                last_msg_id, last_ts = last
                try:
                    if can_delete_message(rm.config):
                        with rm.locked('bot'):
                            rm.bot.delete_message(chat_id, last_msg_id)
                        logger.info(f"🗑️ 链式互删：已删除上一条问候 [{category}] msg={last_msg_id} ts={last_ts}")
                except Exception as del_err:
                    logger.debug(f"链式互删失败（继续发新问候）: {del_err}")
                try:
                    rm.db.delete_broadcast(chat_id, "greeting")
                except Exception as e:
                    logger.debug(f"删除旧问候播报追踪失败: {e}")
        except Exception as e:
            logger.debug(f"链式互删查询失败（继续发新问候）: {e}")

    # [v5.32] 优先尝试 Rich Message 路径
    sent = None
    cfg = rm.config or {}
    rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))
    format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
    if rich_enabled and rich_text and format_version in ("rich", "auto"):
        try:
            with rm.locked('bot'):
                from core.telebot_compat import send_rich_message_compat
                sent = send_rich_message_compat(
                    rm.bot,
                    chat_id,
                    rich_text,
                    reply_markup=reply_markup,
                )
            if sent and hasattr(sent, 'message_id'):
                schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
                if chat_id < 0:
                    rm.db.track_channel_message(chat_id, sent.message_id, "text")
                    rm.db.track_bot_message(chat_id, sent.message_id)
        except Exception as e:
            logger.warning(f"问候 Rich Message 发送失败，回退 HTML: {e}")
            sent = None

    # 回退到 HTML parse_mode 路径
    if sent is None:
        sent = send_and_track(
            rm,
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    if sent and hasattr(sent, 'message_id') and hasattr(rm, "db") and rm.db is not None:
        try:
            rm.db.track_broadcast(chat_id, "greeting", sent.message_id)
            logger.info(f"📌 问候追踪入库：chat={chat_id} category={category} msg={sent.message_id}")
        except Exception as e:
            logger.debug(f"问候追踪入库失败: {e}")
    return sent


def schedule_auto_delete(rm: ResourceManager, chat_id: int, message_id: int, delay_seconds: int):
    """定时消息 24 小时无人理自动删除（使用 APScheduler 调度，避免线程泄漏）。"""
    try:
        from tasks.task_scheduler import get_scheduler_instance
        scheduler = get_scheduler_instance()
        if scheduler:
            run_at = datetime.now(_CST) + timedelta(seconds=delay_seconds)
            scheduler.add_job(
                _do_delete_message,
                trigger='date',
                run_date=run_at,
                args=[rm, chat_id, message_id],
                id=f"auto_del_{chat_id}_{message_id}",
                max_instances=1,
                misfire_grace_time=300,
                replace_existing=False,
            )
    except Exception as e:
        logger.error(f"定时删除调度失败: {e}")


def _do_delete_message(rm: ResourceManager, chat_id: int, message_id: int):
    """APScheduler 回调：删除指定消息。"""
    try:
        if can_delete_message(rm.config):
            with rm.locked('bot'):
                rm.bot.delete_message(chat_id, message_id)
            logger.info(f"🗑️ 定时消息已自动删除: chat={chat_id}, msg={message_id}")
        else:
            logger.info(f"消息删除已禁用，跳过删除: chat={chat_id}, msg={message_id}")
    except Exception as e:
        logger.debug(f"定时消息删除失败（可能已被手动删除）: {e}")


def _extract_news_key(line: str) -> str:
    """抽取新闻去重键，尽量忽略序号、来源和热度等包装字符。"""
    text = line.strip()
    if not text:
        return ""
    if ". " in text[:4]:
        text = text.split(". ", 1)[-1].strip()
    if text.startswith("【") and "】" in text:
        text = text.split("】", 1)[-1].strip()
    if " 🔥" in text:
        text = text.split(" 🔥", 1)[0].strip()
    return text


def _clear_news_cache_if_new_day():
    """新的一天开始时清空新闻缓存。"""
    global _news_pushed_today
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    with _news_cache_lock:
        # 用第一个元素记录日期，简单实现：如果缓存非空且不是今天则清空
        # 这里在 prepare 时直接按天清空
        if hasattr(_clear_news_cache_if_new_day, "_last_date") and _clear_news_cache_if_new_day._last_date != today:
            _news_pushed_today.clear()
        _clear_news_cache_if_new_day._last_date = today


def prepare_news_lines(raw_news: str, source_hint: str = "", limit: int = 10) -> List[str]:
    """整理新闻标题，过滤当天已发送内容，但只在真正发送成功后再写入缓存。"""
    _clear_news_cache_if_new_day()
    with _news_cache_lock:
        lines = [l.strip() for l in raw_news.split("\n") if l.strip()]
        unique_lines = []
        for line in lines:
            core = _extract_news_key(line)
            if core and core not in _news_pushed_today:
                unique_lines.append(line)
    if source_hint:
        logger.info(f"📰 {source_hint}: 过滤前{len(lines)}条 → 去重后{len(unique_lines)}条")
    return unique_lines[:limit]


def remember_news_lines(lines: List[str]):
    """新闻真正发送成功后，再把标题写入当天去重缓存。"""
    _clear_news_cache_if_new_day()
    with _news_cache_lock:
        for line in lines:
            core = _extract_news_key(line)
            if core:
                _news_pushed_today.add(core)


def build_news_ai_mode(time_desc: str, source_name: str) -> str:
    """根据时段和新闻源选择对应的 AI 播报模式。"""
    if source_name == "trendradar":
        mapping = {
            "早间": "trendradar_morning_news",
            "午间": "trendradar_noon_news",
            "晚间": "trendradar_evening_news",
        }
        return mapping.get(time_desc, "trendradar_morning_news")
    mapping = {
        "早间": "news",
        "午间": "afternoon_news",
        "晚间": "evening_news",
    }
    return mapping.get(time_desc, "news")


def looks_like_ai_fallback(text: str) -> bool:
    """识别 AIEngine 所有模型失败后的聊天兜底，避免当新闻播报发送。"""
    value = (text or "").strip()
    return bool(value) and any(marker in value for marker in _AI_FALLBACK_MARKERS)


def is_usable_news_output(text: str, expected_count: int = 10) -> bool:
    """新闻 AI 输出门禁：条数准确且绝不携带内部来源/聚合标签。"""
    value = (text or "").strip()
    if not value:
        return False
    if any(marker in value for marker in _NEWS_INTERNAL_MARKERS):
        return False
    if _NEWS_SOURCE_LABEL_RE.search(value):
        return False
    return len(_parse_news_copy(value, max_items=10)[0]) == expected_count


def build_news_without_ai(lines: List[str], time_desc: str) -> str:
    """[v5.32] LLM 不可用时，用真实标题生成有信息量的新闻文案。

    重构原则（用户反馈"记流水账一样没有实际"）：
    - 不再用"晚点再补一条更稳的消息"等无价值填充
    - 不足 10 条时，明确告知实际条数，不凑数
    - 用编号列表 + 时间段 + 简短观察，提供真实阅读价值
    """
    cleaned = []
    for line in lines[:10]:
        core = line.split("】", 1)[-1].split("🔥", 1)[0].strip()
        if core:
            cleaned.append(core[:40])

    if not cleaned:
        # 真无数据就明说，不假装有内容
        return f"📰 {time_desc}新闻源暂时拉不到数据，稍后会重试。"

    # 用编号列表呈现，每条独立一行
    numbered = [f"{i+1}. {title}" for i, title in enumerate(cleaned)]
    count = len(numbered)
    header = f"📰 {time_desc}新闻速览（共 {count} 条）"
    observation = f"\n\n💡 {time_desc}重点不只一条线，先看事实和后续变化。"
    return header + "\n\n" + "\n".join(numbered) + observation


def get_preferred_news_lines(time_desc: str, config: dict) -> Tuple[List[str], str]:
    """优先用真实新闻源，失败后再降级到聚合热点。"""
    from tasks.support.task_config import get_news_source_strategy
    from core.trendradar_news import fetch_trendradar_news, fetch_real_news

    strategy = get_news_source_strategy(config)
    if strategy == "trendradar_first":
        source_chain = [
            ("trendradar", fetch_trendradar_news, f"{time_desc}新闻-TrendRadar"),
            ("fallback", fetch_real_news, f"{time_desc}新闻-真实新闻源"),
        ]
    else:
        source_chain = [
            ("fallback", fetch_real_news, f"{time_desc}新闻-真实新闻源"),
            ("trendradar", fetch_trendradar_news, f"{time_desc}新闻-TrendRadar"),
        ]

    combined_lines = []
    combined_keys = set()
    for source_name, fetcher, source_hint in source_chain:
        raw_news = fetcher() or ""
        lines = prepare_news_lines(raw_news, source_hint)
        if len(lines) >= 10:
            return lines, source_name
        for line in lines:
            key = _extract_news_key(line)
            if key and key not in combined_keys:
                combined_keys.add(key)
                combined_lines.append(line)
        if lines:
            logger.warning(
                f"📰 {source_hint}: 仅{len(lines)}条，未达到10条，继续尝试下一来源"
            )
    if len(combined_lines) >= 10:
        return combined_lines[:10], "fallback"
    if combined_lines:
        logger.warning(
            f"📰 所有来源合并后仍只有{len(combined_lines)}条，"
            "不足10条，本轮不发送并进入既有重试链"
        )
    return [], "none"


def retry_task(rm: ResourceManager, task_func, task_name: str, delay_sec: int = 300):
    """5 分钟后重试失败的任务，仍失败则通知管理员。"""
    logger.info(f"🔄 [{task_name}] 调度重试，{delay_sec}秒后执行")

    def _do_retry(rm_inner: ResourceManager):
        from tasks.support.task_guard import get_task_guard
        try:
            logger.info(f"🔄 [{task_name}] 开始重试执行")
            task_func(rm_inner)
        except Exception as e:
            logger.error(f"❌ [{task_name}] 重试仍失败: {e}")
            get_fault_reporter().report("定时任务失败", f"任务: {task_name}，错误: {str(e)[:200]}", "⚠️")

    try:
        from tasks.task_scheduler import get_scheduler_instance
        scheduler = get_scheduler_instance()
        if scheduler:
            run_at = datetime.now(_CST) + timedelta(seconds=delay_sec)
            scheduler.add_job(
                _do_retry,
                trigger='date',
                run_date=run_at,
                args=[rm],
                id=f"retry_{task_name}",
                max_instances=1,
                misfire_grace_time=300,
                replace_existing=True,
            )
        else:
            import threading
            t = threading.Thread(target=_do_retry, args=(rm,), daemon=True, name=f"Retry-{task_name}")
            t.start()
    except Exception as e:
        logger.error(f"重试任务调度失败: {e}")
        import threading
        t = threading.Thread(target=_do_retry, args=(rm,), daemon=True, name=f"Retry-{task_name}")
        t.start()
    logger.info(f"⏰ 已安排{task_name}在{delay_sec}秒后重试")


def execute_news_task(rm: ResourceManager, task_name: str, time_desc: str):
    """[v5.32] 执行新闻播报任务（富文本排版 + Rich Message + 转化按钮）。"""
    try:
        with TaskTransactionManager(task_name, rm.db, resources=None, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            gid = rm.config.get("GROUP_ID", 0)
            if gid == 0:
                record_abort(task_name, "GROUP_ID为0")
                raise TaskAbort("GROUP_ID为0")

            logger.info(f"📰 触发{time_desc}新闻播报（统一主流程）")
            seed = random.randint(100000, 999999)

            lines, source_name = get_preferred_news_lines(time_desc, rm.config)
            if not lines:
                logger.warning(f"{time_desc}新闻：所有源均失败，跳过发送")
                get_fault_reporter().report("新闻源故障", f"类型: {time_desc}新闻，所有新闻源均无法获取", "⚠️")
                record_abort(task_name, "新闻源均失败")
                raise TaskAbort("新闻源均失败")
            news_input = "\n".join(lines)

            ai_mode = build_news_ai_mode(time_desc, source_name)
            news = rm.ai.ask(news_input, mode=ai_mode, seed=seed, news_content=news_input)
            if not news or looks_like_ai_fallback(news):
                logger.warning(f"{time_desc}新闻 AI 生成不可用，使用真实标题兜底排版")
                get_fault_reporter().report(
                    "新闻AI生成降级",
                    f"类型: {time_desc}新闻，模型不可用，已用真实标题兜底，避免重复重试",
                    "⚠️",
                )
                news = build_news_without_ai(lines, time_desc)
            else:
                expected_count = min(10, len(lines))
                if not is_usable_news_output(news, expected_count=expected_count):
                    actual_count = len(_parse_news_copy(news, max_items=10)[0])
                    logger.warning(
                        f"{time_desc}新闻 AI 输出未通过门禁："
                        f"期望{expected_count}条，解析{actual_count}条，"
                        "或包含内部来源字样；改用真实标题兜底"
                    )
                    news = build_news_without_ai(lines, time_desc)

            if news:
                # [v5.32] 同时构建 HTML 卡片和 Rich Message 卡片
                rich_news = build_rich_news_html(time_desc, news, source_name=source_name)
                from core.broadcast_formatter import build_rich_news_card_message
                rich_news_message = build_rich_news_card_message(time_desc, news, source_name=source_name)
                markup = build_mory_contact_markup("news")

                # [v5.32] 优先尝试 Rich Message 路径
                cfg = rm.config or {}
                rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))
                format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()

                if rich_enabled and format_version in ("rich", "auto"):
                    try:
                        from core.telebot_compat import send_rich_message_compat
                        with rm.locked('bot'):
                            sent = send_rich_message_compat(
                                rm.bot, gid, rich_news_message,
                                reply_markup=markup,
                            )
                        if sent and hasattr(sent, 'message_id'):
                            schedule_auto_delete(rm, gid, sent.message_id, 24 * 3600)
                            rm.db.track_channel_message(gid, sent.message_id, "text")
                            rm.db.track_bot_message(gid, sent.message_id)
                            remember_news_lines(lines)
                            logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}，Rich Message+按钮）")
                            return
                    except Exception as e:
                        logger.warning(f"{time_desc}新闻 Rich Message 发送失败，回退 HTML: {e}")

                # HTML parse_mode 路径（含 [v5.32] 修复的 link_preview_options dict 兼容）
                try:
                    with rm.locked('bot'):
                        sent = send_message_compat(
                            rm.bot, gid, rich_news,
                            parse_mode="HTML",
                            reply_markup=markup,
                            disable_web_page_preview=True,
                            link_preview_options={"is_disabled": True},
                        )
                    if sent and hasattr(sent, 'message_id'):
                        schedule_auto_delete(rm, gid, sent.message_id, 24 * 3600)
                        rm.db.track_channel_message(gid, sent.message_id, "text")
                        rm.db.track_bot_message(gid, sent.message_id)
                        remember_news_lines(lines)
                        logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}，富文本+按钮）")
                        return
                except Exception as e:
                    logger.warning(f"{time_desc}新闻富文本发送失败，降级纯文本: {e}")
                    sent = send_and_track(
                        rm,
                        gid,
                        news,
                        reply_markup=markup,
                    )
                    if sent:
                        remember_news_lines(lines)
                        logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}，纯文本降级+按钮）")
                        return

            record_abort(task_name, "新闻发送失败")
            raise TaskAbort("新闻发送失败")
    except TaskAbort:
        pass
    except Exception as e:
        logger.error(f"{time_desc}新闻播报失败：{e}")
        retry_task(rm, lambda rm_inner: execute_news_task(rm_inner, task_name, time_desc), task_name)
