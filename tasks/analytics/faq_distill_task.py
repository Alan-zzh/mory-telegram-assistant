"""
tasks/analytics/faq_distill_task.py - FAQ 蒸馏任务

从最近 7 天的用户问题中提取高频问题，生成 FAQ 候选并通知管理员审核。
"""

import re

from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort
from tasks.support.fault_reporter import get_fault_reporter

logger = get_logger("tasks.analytics.faq_distill")


# 兜底文案特征：AI 模型调用全失败时的降级回复，不是话术可优化项
_FALLBACK_REPLY_MARKERS = (
    "这个我不乱说",
    "这条我不乱说",
    "这个需要 Mory 看一下",
    "这个需要 mory 看一下",
    "直接问 @moryfansbot",
    "直接问 @Moryfansbot",
)

# FAQ 日报只服务“以后应沉淀成稳定业务答案”的问题。明确的小闲聊即使由 AI
# 正常回答，也不是 FAQ 漏命中；整句匹配避免把“你在干嘛帮我查积分”等实际
# 诉求一起隐藏。群聊定位/业务类问题由关键词早路由承接，不在这里扩大过滤。
_CASUAL_CHAT_QUESTION_PATTERNS = (
    re.compile(
        r"(?:(?:你|mory|小助理)(?:现在)?(?:在)?)?"
        r"(?:干嘛|干什么|做什么|忙什么|忙啥|忙吗|忙不忙)"
        r"(?:呢|呀|啊|吗|嘛)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?:你|mory|小助理))?"
        r"(?:在吗|在不在|睡了吗|睡了没|吃了吗|吃了没)"
        r"(?:呢|呀|啊|吗|嘛)?",
        re.IGNORECASE,
    ),
    re.compile(r"(?:有点|好)?无聊(?:呢|呀|啊|吗|嘛)?", re.IGNORECASE),
    re.compile(r"(?:陪我|来)(?:聊聊|聊天)(?:吧|呢|呀|啊)?", re.IGNORECASE),
)


def _is_command_text(text: str) -> bool:
    """以 / 开头的命令类消息不进话术待优化统计。"""
    return str(text or "").strip().startswith("/")


def _is_fallback_reply(summary: str) -> bool:
    """模型故障兜底文案，不是话术待优化项。"""
    lowered = str(summary or "").lower()
    return any(marker in lowered for marker in _FALLBACK_REPLY_MARKERS)


def _is_casual_chat_question(text: str) -> bool:
    """只过滤没有附带实际事项的完整闲聊句，不按宽泛子串猜测。"""
    normalized = re.sub(r"\s+", "", str(text or "").strip())
    normalized = re.sub(r"[，,。.!！?？~～]+$", "", normalized)
    return any(pattern.fullmatch(normalized) for pattern in _CASUAL_CHAT_QUESTION_PATTERNS)


def _build_daily_question_summary(questions, sample_limit: int = 8) -> str:
    """把最近一天问题整理成老板可直接优化话术的简报。"""
    if not questions:
        return ""

    def _question_text(item) -> str:
        text = " ".join(str(item.get("question_text", "") or "").split())
        return text[:90]

    def _unique_samples(items, limit):
        samples = []
        seen = set()
        for item in items:
            text = _question_text(item)
            normalized = text.lower().strip("？?。！!，, ")
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            samples.append(text)
            if len(samples) >= limit:
                break
        return samples

    reportable = [
        item
        for item in questions
        if not _is_command_text(item.get("question_text", ""))
        and not _is_fallback_reply(item.get("ai_reply_summary", ""))
        and not _is_casual_chat_question(item.get("question_text", ""))
    ]
    unresolved = [
        item
        for item in reportable
        if (
            not str(item.get("ai_reply_summary", "") or "").strip()
            or str(item.get("ai_reply_summary", "")).startswith("[UNRESOLVED]")
        )
    ]
    faq_hits = sum(1 for item in questions if int(item.get("faq_hit_id", 0) or 0) > 0)
    faq_misses = [
        item
        for item in reportable
        if int(item.get("faq_hit_id", 0) or 0) <= 0
        and item not in unresolved
    ]

    lines = [
        "📋 今日问题汇总",
        f"共记录 {len(questions)} 条｜FAQ命中 {faq_hits} 条｜待优化 {len(unresolved)} 条",
    ]

    unresolved_samples = _unique_samples(unresolved, sample_limit)
    if unresolved_samples:
        lines.append("")
        lines.append("待老板优化：")
        lines.extend(
            f"{index}. {text}"
            for index, text in enumerate(unresolved_samples, 1)
        )

    miss_samples = _unique_samples(
        faq_misses,
        max(0, sample_limit - len(unresolved_samples)),
    )
    if miss_samples:
        lines.append("")
        lines.append("AI已答但FAQ未命中：")
        lines.extend(
            f"{index}. {text}"
            for index, text in enumerate(miss_samples, 1)
        )

    lines.append("")
    lines.append("可在 Dashboard 的 FAQ 页面补充或审核话术。")
    return "\n".join(lines)


class FaqDistillTask(BaseTask):
    """FAQ 蒸馏任务（每日一次，间隔从配置读取，默认 86400 秒）。"""

    @property
    def task_id(self) -> str:
        return "faq_distill"

    def schedule(self) -> List[Dict[str, Any]]:
        if not (self.rm.config or {}).get("FAQ_TRACKING_ENABLED", False):
            return []
        interval = self.rm.config.get("FAQ_DISTILL_INTERVAL", 86400)
        return [
            {
                "job_id": "faq_distill",
                "trigger": "interval",
                "seconds": interval,
                "params": {},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 3600,
                },
            },
            {
                "job_id": "faq_daily_question_summary",
                "trigger": "cron",
                "hour": 23,
                "minute": 50,
                "params": {"operation": "daily_summary"},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 3600,
                },
            },
        ]

    def execute(self, ctx: TaskContext) -> None:
        operation = ctx.params.get("operation", "")
        try:
            if not ctx.rm.config.get("FAQ_TRACKING_ENABLED", False):
                return

            if operation == "daily_summary":
                self._send_daily_summary(ctx)
                return

            min_frequency = ctx.rm.config.get("FAQ_MIN_FREQUENCY", 2)

            with TaskTransactionManager("faq_distill", ctx.rm.db, min_interval_sec=86400) as tx:
                if not tx.claimed:
                    return

                count = ctx.rm.db.distill_candidates(min_frequency=min_frequency, days=7)

                if count > 0:
                    logger.info(f"📋 FAQ蒸馏完成：发现 {count} 个新高频问题候选")
                    get_fault_reporter().report(
                        "FAQ蒸馏",
                        f"发现 {count} 个新高频问题候选，请到Dashboard审核",
                        "📋",
                    )
                else:
                    logger.info("📋 FAQ蒸馏完成：无新高频问题候选")
                    raise TaskAbort("无新高频问题候选", expected=True)
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            task_name = "FAQ每日问题汇总" if operation == "daily_summary" else "FAQ蒸馏"
            logger.error(f"{task_name}失败：{e}")
            get_fault_reporter().report(f"{task_name}失败", str(e)[:200], "⚠️")
            raise

    @staticmethod
    def _send_daily_summary(ctx: TaskContext) -> None:
        admin_id = int(ctx.rm.config.get("ADMIN_ID", 0) or 0)
        if not admin_id:
            logger.warning("FAQ每日问题汇总跳过：未配置 ADMIN_ID")
            return

        questions = ctx.rm.db.get_questions(limit=200, days=1)
        summary = _build_daily_question_summary(questions)
        if not summary:
            logger.info("📋 FAQ每日问题汇总：今日无问题，跳过发送")
            return

        ctx.rm.bot.send_message(admin_id, summary)
        logger.info(
            f"📋 FAQ每日问题汇总已发送：admin={admin_id} questions={len(questions)}"
        )
