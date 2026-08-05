# -*- coding: utf-8 -*-
"""回复风格样本蒸馏：从高质量评估对话中提取 pending 风格样本。

默认关闭：由 conversation_quality_task 在 REPLAY_EVOLUTION_DISTILL_ENABLED=True 时调用。
数据来源：interaction_quality_scores（LLM-as-a-Judge 评分）JOIN conversation_telemetry（对话原文）。
只生成 pending 样本，审核权始终在管理员；绝不自动启用或改写 Prompt。
"""
from __future__ import annotations

from typing import Any, Dict

from core.logging_util import get_logger

logger = get_logger("tasks.analytics.reply_evolution_distill")

_MIN_TEXT_LEN = 5  # 用户话术与 Mory 回复均不少于 5 字
_HIGH_SCORE_THRESHOLD = 4.0  # 三维评分均值下限
_MAX_DISTILL_PER_RUN = 50  # 单次蒸馏上限，避免一次灌入过多待审样本
_QUERY_LIMIT = 200  # 高分候选查询上限（供去重/校验后筛选）


def _fetch_high_quality_pairs(db: Any) -> list[Any]:
    """读取高分评估对话对，与对话遥测原文配对。"""
    rows = db.conn.execute(
        """SELECT t.message_text, t.bot_reply_text
           FROM interaction_quality_scores q
           JOIN conversation_telemetry t ON t.id = q.conversation_id
           WHERE (q.naturalness_score + q.relevance_score + q.persona_score) / 3.0 >= ?
             AND t.message_text != ''
             AND t.bot_reply_text != ''
           ORDER BY q.evaluated_at DESC
           LIMIT ?""",
        (_HIGH_SCORE_THRESHOLD, _QUERY_LIMIT),
    ).fetchall()
    return rows


def _already_exists(db: Any, style_text: str) -> bool:
    """避免重复蒸馏：相同拼接文本已在库中则跳过。"""
    row = db.conn.execute(
        "SELECT 1 FROM reply_style_samples WHERE style_text=? LIMIT 1",
        (style_text,),
    ).fetchone()
    return row is not None


def distill_reply_style_samples(db: Any, config: dict | None = None, limit: int = _MAX_DISTILL_PER_RUN) -> Dict:
    """从高分评估对话中蒸馏 pending 风格样本（scene='chat'）。返回统计摘要。"""
    if not (hasattr(db, "conn") and hasattr(db, "create_reply_style_sample")):
        logger.warning("风格样本蒸馏跳过：当前 db 不支持 reply_style_samples 写入")
        return {"ok": False, "error": "db 不支持"}

    from core.db_repos.reply_evolution_repo import validate_feed_sample_safety

    try:
        pairs = _fetch_high_quality_pairs(db)
    except Exception as exc:
        logger.error(f"风格样本蒸馏读取高分对话失败: {exc}")
        return {"ok": False, "error": f"读取失败: {exc}"}

    created = 0
    skipped = 0
    seen: set[tuple[str, str]] = set()
    for row in pairs:
        if created >= int(limit or _MAX_DISTILL_PER_RUN):
            break
        user_text = str(row[0] or "").strip()
        mory_text = str(row[1] or "").strip()
        if len(user_text) < _MIN_TEXT_LEN or len(mory_text) < _MIN_TEXT_LEN:
            skipped += 1
            continue
        key = (user_text, mory_text)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        ok, reason = validate_feed_sample_safety(user_text, mory_text)
        if not ok:
            skipped += 1
            continue
        combined = f"用户：{user_text}\nMory：{mory_text}"
        if _already_exists(db, combined):
            skipped += 1
            continue
        result = db.create_reply_style_sample(
            combined,
            label="蒸馏-高分",
            created_by="distill",
            scene="chat",
            user_text=user_text,
            mory_text=mory_text,
        )
        if result.get("ok"):
            created += 1
        else:
            skipped += 1

    logger.info(
        f"🍼 风格样本蒸馏完成：新增 {created} 条 pending（scene=chat），跳过 {skipped} 条"
    )
    return {"ok": True, "created": created, "skipped": skipped}
