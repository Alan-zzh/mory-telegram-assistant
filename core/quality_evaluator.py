"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/quality_evaluator.py  ·  内容质量评估引擎（LLM-as-a-Judge）       ║
║                                                                        ║
║  功能：                                                                ║
║    1. 从 conversation_telemetry 表抽样对话记录                         ║
║    2. 投放到 LLM 评估（使用 llm_standard 池，成本可控）                ║
║    3. 评估维度：自然度 / 业务相关性 / 人格一致性（1-5 分）             ║
║    4. 存储评分到 interaction_quality_scores 表                         ║
║                                                                        ║
║  配置（config.json）：                                                 ║
║    QUALITY_EVAL_SAMPLE_RATE   - 采样率，默认 0.05（5%）                ║
║    QUALITY_EVAL_DAILY_LIMIT   - 每日预算上限，默认 100 条              ║
║    QUALITY_EVAL_ENABLED       - 总开关，默认 False                     ║
║                                                                        ║
║  依赖：core/ai_engine.py, core/database.py                             ║
║  被调用：modules/auto_tasks.py → _job_evaluate_conversation_quality()  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import random
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

from core.logging_util import get_logger

logger = get_logger("quality_evaluator")

# 北京时间
_CST = timezone(timedelta(hours=8))

# 评估 Prompt（要求 LLM 返回 JSON，严格限制输出格式）
_EVAL_SYSTEM_PROMPT = """你是一个对话质量评估专家。请对以下对话进行评分。

评估维度（每项 1-5 分）：
1. 自然度（naturalness）：回复是否自然流畅，像真人对话，不生硬/机械
2. 业务相关性（relevance）：回复是否切题，并在购买/咨询场景给出清楚下一步
3. 人格一致性（persona）：回复是否符合 Mory 助理人设，不能像客服、AI、机器人或程序

项目红线：
- 不能暴露 AI/机器人/模型/程序身份
- 购买意图要自然引导 @MorychannelBot，自助下单路径要清楚
- 不能硬广、不能长篇说教、不能破坏至臻精选/至臻全享/精选图集边界

评分标准：
- 5分：优秀，无明显问题
- 4分：良好，有微小瑕疵
- 3分：一般，有明显改进空间
- 2分：较差，存在明显问题
- 1分：很差，严重影响体验

请严格以 JSON 格式返回，不要包含其他内容：
{"naturalness": 分数, "relevance": 分数, "persona": 分数, "reason": "一句话理由"}"""


class QualityEvaluator:
    """内容质量评估器（LLM-as-a-Judge）"""

    def __init__(self, ai, db, config: dict):
        """
        Args:
            ai: AIEngine 实例
            db: DB 数据库实例
            config: 配置字典
        """
        self.ai = ai
        self.db = db
        self.config = config or {}

    @property
    def enabled(self) -> bool:
        """总开关"""
        return bool(self.config.get("QUALITY_EVAL_ENABLED", False))

    @property
    def sample_rate(self) -> float:
        """采样率（0.0-1.0），默认 5%"""
        rate = self.config.get("QUALITY_EVAL_SAMPLE_RATE", 0.05)
        try:
            rate = float(rate)
            return max(0.0, min(1.0, rate))
        except (TypeError, ValueError):
            return 0.05

    @property
    def daily_limit(self) -> int:
        """每日评估预算上限，默认 100 条"""
        limit = self.config.get("QUALITY_EVAL_DAILY_LIMIT", 100)
        try:
            limit = int(limit)
            return max(1, min(1000, limit))
        except (TypeError, ValueError):
            return 100

    def _get_yesterday_conversations(self) -> List[Dict]:
        """获取昨天的对话记录（从 conversation_telemetry 表）"""
        now = datetime.now(_CST)
        yesterday_start = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        yesterday_end = yesterday_start + timedelta(days=1)
        start_ts = int(yesterday_start.timestamp())
        end_ts = int(yesterday_end.timestamp())

        try:
            rows = self.db.conn.execute(
                """SELECT id, user_id, chat_id, message_text, bot_reply_text,
                          intent, sentiment, round_num, ts
                   FROM conversation_telemetry
                   WHERE ts >= ? AND ts < ?
                     AND bot_reply_text != ''
                     AND message_text != ''
                   ORDER BY ts DESC""",
                (start_ts, end_ts),
            ).fetchall()

            conversations = []
            for row in rows:
                conversations.append({
                    "id": row[0],
                    "user_id": row[1],
                    "chat_id": row[2],
                    "message_text": row[3] or "",
                    "bot_reply_text": row[4] or "",
                    "intent": row[5] or "",
                    "sentiment": row[6] or "",
                    "round_num": row[7],
                    "ts": row[8],
                })
            return conversations
        except Exception as e:
            logger.error(f"读取昨日对话失败: {e}")
            return []

    def _sample_conversations(self, conversations: List[Dict]) -> List[Dict]:
        """按采样率抽样，同时受每日预算限制"""
        if not conversations:
            return []

        # 计算采样数量
        sample_count = max(1, int(len(conversations) * self.sample_rate))
        sample_count = min(sample_count, self.daily_limit)

        if sample_count >= len(conversations):
            return conversations

        return random.sample(conversations, sample_count)

    def _check_already_evaluated(self, conversation_id: int) -> bool:
        """检查该对话是否已评估过（避免重复评估）"""
        try:
            row = self.db.conn.execute(
                "SELECT 1 FROM interaction_quality_scores WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            return row is not None
        except Exception:
            # 表可能不存在，忽略
            return False

    def _build_eval_prompt(self, conv: Dict) -> str:
        """构建评估 Prompt"""
        user_msg = conv["message_text"][:500]  # 截断防止超长
        bot_reply = conv["bot_reply_text"][:500]
        intent = conv.get("intent", "")
        sentiment = conv.get("sentiment", "")

        prompt = f"""请评估以下对话：

用户消息：{user_msg}
机器人回复：{bot_reply}
对话意图：{intent if intent else "未知"}
用户情绪：{sentiment if sentiment else "未知"}

请严格按 JSON 格式返回评分。"""
        return prompt

    def _call_llm_evaluate(self, prompt: str) -> Optional[Dict]:
        """调用 LLM 评估，返回解析后的评分字典"""
        try:
            # 使用 mode="normal" 路由到 llm_standard 池（成本可控）
            response = self.ai.ask(
                question=prompt,
                mode="normal",
                retry=2,
                seed=random.randint(0, 9999),
            )
            if not response:
                return None

            # 尝试解析 JSON
            return self._parse_eval_response(response)
        except Exception as e:
            logger.error(f"LLM 评估调用失败: {e}")
            return None

    def _parse_eval_response(self, response: str) -> Optional[Dict]:
        """解析 LLM 返回的 JSON 评分"""
        # 尝试直接解析
        try:
            data = json.loads(response.strip())
            return self._validate_scores(data)
        except (json.JSONDecodeError, ValueError):
            pass

        # 尝试从文本中提取 JSON 块
        import re
        json_match = re.search(r'\{[^{}]*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return self._validate_scores(data)
            except (json.JSONDecodeError, ValueError):
                pass

        logger.warning(f"评估响应解析失败: {response[:200]}")
        return None

    def _validate_scores(self, data: Dict) -> Optional[Dict]:
        """验证评分数据合法性"""
        required_keys = ["naturalness", "relevance", "persona"]
        for key in required_keys:
            if key not in data:
                return None
            try:
                score = int(data[key])
                if not (1 <= score <= 5):
                    return None
                data[key] = score
            except (TypeError, ValueError):
                return None

        # 保留 reason 字段（可选）
        if "reason" not in data:
            data["reason"] = ""
        return data

    def _save_score(self, conversation_id: int, scores: Dict, ts: int):
        """保存评分到数据库"""
        try:
            self.db.conn.execute(
                """INSERT OR REPLACE INTO interaction_quality_scores
                   (conversation_id, naturalness_score, relevance_score,
                    persona_score, evaluated_at, reason)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    scores["naturalness"],
                    scores["relevance"],
                    scores["persona"],
                    ts,
                    scores.get("reason", ""),
                ),
            )
        except Exception as e:
            logger.error(f"保存评分失败 (conv_id={conversation_id}): {e}")

    def run_daily_evaluation(self) -> Dict:
        """
        执行每日评估任务。

        Returns:
            统计摘要 {"total": N, "evaluated": M, "skipped": K,
                      "avg_naturalness": X, "avg_relevance": Y, "avg_persona": Z}
        """
        if not self.enabled:
            logger.info("质量评估未启用（QUALITY_EVAL_ENABLED=False）")
            return {"total": 0, "evaluated": 0, "skipped": 0, "disabled": True}

        logger.info("📊 开始每日内容质量评估...")
        start_time = time.time()

        # 1. 获取昨日对话
        conversations = self._get_yesterday_conversations()
        total_available = len(conversations)
        logger.info(f"  昨日对话总数: {total_available}")

        if total_available == 0:
            return {"total": 0, "evaluated": 0, "skipped": 0, "message": "昨日无对话记录"}

        # 2. 抽样
        sampled = self._sample_conversations(conversations)
        logger.info(f"  抽样数量: {len(sampled)}（采样率 {self.sample_rate*100:.1f}%，上限 {self.daily_limit}）")

        # 3. 逐条评估
        evaluated_count = 0
        skipped_count = 0
        score_sums = {"naturalness": 0, "relevance": 0, "persona": 0}

        for conv in sampled:
            # 跳过已评估的
            if self._check_already_evaluated(conv["id"]):
                skipped_count += 1
                continue

            # 构建 Prompt 并调用 LLM
            prompt = self._build_eval_prompt(conv)
            scores = self._call_llm_evaluate(prompt)

            if scores is None:
                skipped_count += 1
                continue

            # 保存评分
            self._save_score(conv["id"], scores, conv["ts"])
            evaluated_count += 1
            score_sums["naturalness"] += scores["naturalness"]
            score_sums["relevance"] += scores["relevance"]
            score_sums["persona"] += scores["persona"]

        # 4. 计算平均值
        elapsed = time.time() - start_time
        result = {
            "total": total_available,
            "sampled": len(sampled),
            "evaluated": evaluated_count,
            "skipped": skipped_count,
            "elapsed_sec": round(elapsed, 1),
        }

        if evaluated_count > 0:
            result["avg_naturalness"] = round(score_sums["naturalness"] / evaluated_count, 2)
            result["avg_relevance"] = round(score_sums["relevance"] / evaluated_count, 2)
            result["avg_persona"] = round(score_sums["persona"] / evaluated_count, 2)
        else:
            result["avg_naturalness"] = 0
            result["avg_relevance"] = 0
            result["avg_persona"] = 0

        logger.info(
            f"📊 质量评估完成: 评估 {evaluated_count} 条，"
            f"跳过 {skipped_count} 条，耗时 {elapsed:.1f}s | "
            f"自然度={result.get('avg_naturalness', 0):.2f} "
            f"相关性={result.get('avg_relevance', 0):.2f} "
            f"人格={result.get('avg_persona', 0):.2f}"
        )
        return result


def get_average_scores(db, days: int = 7) -> Dict:
    """
    获取最近 N 天的平均评分（供 Dashboard API 调用）。

    Args:
        db: DB 数据库实例
        days: 统计天数，默认 7 天

    Returns:
        {"avg_naturalness": X, "avg_relevance": Y, "avg_persona": Z,
         "total_evaluated": N, "days": days}
    """
    cutoff_ts = int((datetime.now(_CST) - timedelta(days=days)).timestamp())
    try:
        row = db.conn.execute(
            """SELECT AVG(naturalness_score), AVG(relevance_score),
                      AVG(persona_score), COUNT(*)
               FROM interaction_quality_scores
               WHERE evaluated_at >= ?""",
            (cutoff_ts,),
        ).fetchone()

        if row and row[3] > 0:
            return {
                "avg_naturalness": round(row[0] or 0, 2),
                "avg_relevance": round(row[1] or 0, 2),
                "avg_persona": round(row[2] or 0, 2),
                "total_evaluated": row[3],
                "days": days,
            }
        return {
            "avg_naturalness": 0,
            "avg_relevance": 0,
            "avg_persona": 0,
            "total_evaluated": 0,
            "days": days,
        }
    except Exception as e:
        logger.error(f"获取平均评分失败: {e}")
        return {
            "avg_naturalness": 0,
            "avg_relevance": 0,
            "avg_persona": 0,
            "total_evaluated": 0,
            "days": days,
            "error": str(e),
        }


def get_score_trend(db, days: int = 30) -> List[Dict]:
    """
    获取评分趋势（按天聚合，供 Dashboard API 调用）。

    Args:
        db: DB 数据库实例
        days: 趋势天数，默认 30 天

    Returns:
        [{"date": "2026-06-17", "avg_naturalness": X, ...}, ...]
    """
    cutoff_ts = int((datetime.now(_CST) - timedelta(days=days)).timestamp())
    try:
        rows = db.conn.execute(
            """SELECT DATE(evaluated_at, 'unixepoch', '+8 hours') as day,
                      AVG(naturalness_score), AVG(relevance_score),
                      AVG(persona_score), COUNT(*)
               FROM interaction_quality_scores
               WHERE evaluated_at >= ?
               GROUP BY day
               ORDER BY day ASC""",
            (cutoff_ts,),
        ).fetchall()

        trend = []
        for row in rows:
            trend.append({
                "date": row[0] or "",
                "avg_naturalness": round(row[1] or 0, 2),
                "avg_relevance": round(row[2] or 0, 2),
                "avg_persona": round(row[3] or 0, 2),
                "count": row[4] or 0,
            })
        return trend
    except Exception as e:
        logger.error(f"获取评分趋势失败: {e}")
        return []
