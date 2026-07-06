# -*- coding: utf-8 -*-
"""A/B 测试与 Telemetry 数据操作"""
import time
import json
from datetime import datetime, timedelta, timezone

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.ab_test")


class ABTestRepo:
    """A/B 测试与 Telemetry 相关数据库操作"""

    def __init__(self, db):
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    # ═══════════════════════════════════════════════════════════════════════════
    # 实验管理
    # ═══════════════════════════════════════════════════════════════════════════

    def create_experiment(self, experiment_id: str, name: str, description: str,
                          variant_a: dict, variant_b: dict,
                          traffic_split: int = 50, scope: str = "private") -> bool:
        """创建或更新实验定义"""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    INSERT INTO ab_experiments
                    (id, name, description, variant_a_name, variant_b_name,
                     variant_a_config, variant_b_config, traffic_split, scope, status, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        variant_a_name=excluded.variant_a_name,
                        variant_b_name=excluded.variant_b_name,
                        variant_a_config=excluded.variant_a_config,
                        variant_b_config=excluded.variant_b_config,
                        traffic_split=excluded.traffic_split,
                        scope=excluded.scope,
                        status=excluded.status
                """, (experiment_id, name, description,
                      variant_a.get("label", "A"), variant_b.get("label", "B"),
                      json.dumps(variant_a, ensure_ascii=False),
                      json.dumps(variant_b, ensure_ascii=False),
                      traffic_split, scope, "running", int(time.time())))
                self.conn.commit()
                return True
            except Exception as e:
                logger.warning(f"创建实验失败: {e}")
                return False

    def get_experiment(self, experiment_id: str) -> dict | None:
        """获取实验定义"""
        c = self.conn.cursor()
        c.execute("""
            SELECT id, name, description, variant_a_name, variant_b_name,
                   variant_a_config, variant_b_config, traffic_split, scope, status,
                   start_time, end_time, rolled_back_at
            FROM ab_experiments WHERE id=?
        """, (experiment_id,))
        row = c.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "description": row[2],
            "variant_a_name": row[3], "variant_b_name": row[4],
            "variant_a_config": json.loads(row[5]) if row[5] else {},
            "variant_b_config": json.loads(row[6]) if row[6] else {},
            "traffic_split": row[7], "scope": row[8], "status": row[9],
            "start_time": row[10], "end_time": row[11], "rolled_back_at": row[12],
        }

    def list_experiments(self, status: str = None) -> list:
        """列出所有实验"""
        c = self.conn.cursor()
        if status:
            c.execute("SELECT id, name, status, scope, traffic_split FROM ab_experiments WHERE status=? ORDER BY created_at DESC", (status,))
        else:
            c.execute("SELECT id, name, status, scope, traffic_split FROM ab_experiments ORDER BY created_at DESC")
        return [{"id": r[0], "name": r[1], "status": r[2], "scope": r[3], "traffic_split": r[4]} for r in c.fetchall()]

    def update_experiment_status(self, experiment_id: str, status: str) -> bool:
        """更新实验状态: running / paused / stopped / rolled_back"""
        with self.lock:
            try:
                c = self.conn.cursor()
                now_ts = int(time.time())
                if status == "rolled_back":
                    # 消除 f-string 拼接：使用字面量 SQL，全部参数化
                    c.execute(
                        "UPDATE ab_experiments SET status=?, end_time=?, rolled_back_at=? WHERE id=?",
                        (status, now_ts, now_ts, experiment_id)
                    )
                else:
                    c.execute(
                        "UPDATE ab_experiments SET status=?, end_time=? WHERE id=?",
                        (status, now_ts, experiment_id)
                    )
                self.conn.commit()
                return c.rowcount > 0
            except Exception as e:
                logger.warning(f"更新实验状态失败: {e}")
                return False

    # ═══════════════════════════════════════════════════════════════════════════
    # 用户分组分配
    # ═══════════════════════════════════════════════════════════════════════════

    def assign_user_variant(self, experiment_id: str, user_id: int, chat_id: int = 0,
                            variant: str = "A") -> str:
        """分配用户到实验组，返回分配的 variant（A/B）"""
        with self.lock:
            try:
                c = self.conn.cursor()
                # 幂等：已分配则直接返回
                c.execute("SELECT variant FROM ab_user_assignments WHERE experiment_id=? AND user_id=?",
                          (experiment_id, user_id))
                row = c.fetchone()
                if row:
                    return row[0]
                c.execute("""
                    INSERT INTO ab_user_assignments (experiment_id, user_id, chat_id, variant, assigned_at)
                    VALUES (?,?,?,?,?)
                """, (experiment_id, user_id, chat_id, variant, int(time.time())))
                self.conn.commit()
                return variant
            except Exception as e:
                logger.warning(f"分配用户实验组失败: {e}")
                return "A"

    def get_user_variant(self, experiment_id: str, user_id: int) -> str | None:
        """获取用户已分配的 variant，未分配返回 None"""
        c = self.conn.cursor()
        c.execute("SELECT variant FROM ab_user_assignments WHERE experiment_id=? AND user_id=?",
                  (experiment_id, user_id))
        row = c.fetchone()
        return row[0] if row else None

    def get_assignment_stats(self, experiment_id: str) -> dict:
        """获取实验分组统计"""
        c = self.conn.cursor()
        c.execute("SELECT variant, COUNT(*) FROM ab_user_assignments WHERE experiment_id=? GROUP BY variant",
                  (experiment_id,))
        rows = c.fetchall()
        return {r[0]: r[1] for r in rows}

    # ═══════════════════════════════════════════════════════════════════════════
    # Telemetry 事件
    # ═══════════════════════════════════════════════════════════════════════════

    def log_telemetry(self, user_id: int, chat_id: int, experiment_id: str, variant: str,
                      event_type: str, event_value: float = 0.0, event_meta: dict = None) -> int:
        """记录遥测事件"""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    INSERT INTO telemetry_events
                    (user_id, chat_id, experiment_id, variant, event_type, event_value, event_meta, ts)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (user_id, chat_id, experiment_id, variant, event_type, event_value,
                      json.dumps(event_meta or {}, ensure_ascii=False), int(time.time())))
                self.conn.commit()
                return c.lastrowid
            except Exception as e:
                logger.warning(f"Telemetry 记录失败: {e}")
                return 0

    def log_conversation_telemetry(self, user_id: int, chat_id: int, experiment_id: str, variant: str,
                                   message_text: str, bot_reply_text: str,
                                   intent: str = "", sentiment: str = "", round_num: int = 0) -> int:
        """记录对话遥测"""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    INSERT INTO conversation_telemetry
                    (user_id, chat_id, experiment_id, variant, message_text, bot_reply_text,
                     intent, sentiment, round_num, ts)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (user_id, chat_id, experiment_id, variant,
                      message_text[:500], bot_reply_text[:500],
                      intent, sentiment, round_num, int(time.time())))
                self.conn.commit()
                return c.lastrowid
            except Exception as e:
                logger.warning(f"对话 Telemetry 记录失败: {e}")
                return 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 指标统计 SQL 报表接口
    # ═══════════════════════════════════════════════════════════════════════════

    def get_conversion_funnel(self, experiment_id: str, start_ts: int = 0, end_ts: int = 0) -> dict:
        """获取转化漏斗统计"""
        if end_ts == 0:
            end_ts = int(time.time())
        if start_ts == 0:
            start_ts = end_ts - 86400 * 7

        c = self.conn.cursor()
        result = {}
        for variant in ("A", "B"):
            # 总曝光用户数
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM telemetry_events
                WHERE experiment_id=? AND variant=? AND event_type='exposure' AND ts>=? AND ts<=?
            """, (experiment_id, variant, start_ts, end_ts))
            exposed = c.fetchone()[0] or 0

            # 互动用户数（消息回复）
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM telemetry_events
                WHERE experiment_id=? AND variant=? AND event_type='engage' AND ts>=? AND ts<=?
            """, (experiment_id, variant, start_ts, end_ts))
            engaged = c.fetchone()[0] or 0

            # 点击按钮用户数
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM telemetry_events
                WHERE experiment_id=? AND variant=? AND event_type='button_click' AND ts>=? AND ts<=?
            """, (experiment_id, variant, start_ts, end_ts))
            clicked = c.fetchone()[0] or 0

            # 咨询/加购用户数
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM telemetry_events
                WHERE experiment_id=? AND variant=? AND event_type IN ('consult','add_cart') AND ts>=? AND ts<=?
            """, (experiment_id, variant, start_ts, end_ts))
            consulted = c.fetchone()[0] or 0

            # 付费转化用户数
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM telemetry_events
                WHERE experiment_id=? AND variant=? AND event_type='conversion' AND ts>=? AND ts<=?
            """, (experiment_id, variant, start_ts, end_ts))
            converted = c.fetchone()[0] or 0

            # 退群/流失用户数
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM telemetry_events
                WHERE experiment_id=? AND variant=? AND event_type='group_leave' AND ts>=? AND ts<=?
            """, (experiment_id, variant, start_ts, end_ts))
            left = c.fetchone()[0] or 0

            result[variant] = {
                "exposed": exposed, "engaged": engaged, "clicked": clicked,
                "consulted": consulted, "converted": converted, "left": left,
                "ctr": round(clicked / max(exposed, 1) * 100, 2),
                "conversion_rate": round(converted / max(exposed, 1) * 100, 2),
                "churn_rate": round(left / max(exposed, 1) * 100, 2),
            }
        return result

    def get_daily_kpi_series(self, experiment_id: str, days: int = 14) -> list:
        """获取每日 KPI 时序数据"""
        c = self.conn.cursor()
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        rows = []
        for i in range(days - 1, -1, -1):
            day = (datetime.now(_CST) - timedelta(days=i)).strftime("%Y-%m-%d")
            day_start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
            day_end = day_start + 86400
            for variant in ("A", "B"):
                c.execute("""
                    SELECT COUNT(DISTINCT user_id),
                           SUM(CASE WHEN event_type='button_click' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN event_type='conversion' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN event_type='group_leave' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN event_type='complaint' THEN 1 ELSE 0 END)
                    FROM telemetry_events
                    WHERE experiment_id=? AND variant=? AND ts>=? AND ts<=?
                """, (experiment_id, variant, day_start, day_end))
                r = c.fetchone()
                rows.append({
                    "date": day, "variant": variant,
                    "users": r[0] or 0, "clicks": r[1] or 0,
                    "conversions": r[2] or 0, "leaves": r[3] or 0, "complaints": r[4] or 0,
                })
        return rows

    def get_top_features(self, experiment_id: str, variant: str, positive: bool = True, limit: int = 5) -> list:
        """轻量词频分析：从 conversation_telemetry 提取高频词特征"""
        c = self.conn.cursor()
        # 取最近7天数据
        since = int(time.time()) - 86400 * 7
        if positive:
            # 高转化用户的对话（该用户有 conversion 事件）
            c.execute("""
                SELECT ct.bot_reply_text FROM conversation_telemetry ct
                WHERE ct.experiment_id=? AND ct.variant=? AND ct.ts>=?
                  AND EXISTS (
                      SELECT 1 FROM telemetry_events te
                      WHERE te.user_id=ct.user_id AND te.experiment_id=ct.experiment_id
                        AND te.variant=ct.variant AND te.event_type='conversion'
                  )
                ORDER BY ct.ts DESC LIMIT 200
            """, (experiment_id, variant, since))
        else:
            # 流失用户的对话（该用户有 group_leave 事件）
            c.execute("""
                SELECT ct.bot_reply_text FROM conversation_telemetry ct
                WHERE ct.experiment_id=? AND ct.variant=? AND ct.ts>=?
                  AND EXISTS (
                      SELECT 1 FROM telemetry_events te
                      WHERE te.user_id=ct.user_id AND te.experiment_id=ct.experiment_id
                        AND te.variant=ct.variant AND te.event_type='group_leave'
                  )
                ORDER BY ct.ts DESC LIMIT 200
            """, (experiment_id, variant, since))
        texts = [r[0] for r in c.fetchall() if r[0]]
        if not texts:
            return []

        # 轻量中文分词：按2-4字滑动窗口统计词频（无需额外NLP库）
        from collections import Counter
        word_counter = Counter()
        stopwords = {"的", "了", "是", "我", "你", "在", "和", "就", "不", "人", "有", "都", "一个", "上", "也", "很", "到", "说", "要", "去", "可以", "会", "这", "那", "没有", "吗", "吧", "呢", "啊", "嗯", "哦", "哈", "哈哈", "什么", "怎么", "还是", "但是", "因为", "所以", "如果", "还是", "就是", "不是", "这个", "那个", "我们", "你们", "他们", "自己", "现在", "今天", "明天", "时候", "一下", "一样", "一直", "一下", "有点", "可能", "觉得", "感觉", "知道", "看看", "想想", "问问", "聊聊", "说说", "玩玩", "用用"}
        for text in texts:
            text = text.strip()
            for length in (2, 3, 4):
                for i in range(len(text) - length + 1):
                    word = text[i:i + length]
                    if any(sw in word for sw in stopwords):
                        continue
                    if word_counter[word] < 1000:  # 防内存膨胀
                        word_counter[word] += 1
        return [{"word": w, "count": c} for w, c in word_counter.most_common(limit)]

    # ═══════════════════════════════════════════════════════════════════════════
    # 守护日志与报告
    # ═══════════════════════════════════════════════════════════════════════════

    def log_guardian_alert(self, experiment_id: str, alert_type: str, alert_reason: str,
                           threshold_value: float, actual_value: float, action_taken: str = "") -> int:
        """记录守护告警"""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    INSERT INTO ab_guardian_log
                    (experiment_id, alert_type, alert_reason, threshold_value, actual_value, action_taken, ts)
                    VALUES (?,?,?,?,?,?,?)
                """, (experiment_id, alert_type, alert_reason, threshold_value, actual_value,
                      action_taken, int(time.time())))
                self.conn.commit()
                return c.lastrowid
            except Exception as e:
                logger.warning(f"守护日志记录失败: {e}")
                return 0

    def get_recent_guardian_alerts(self, experiment_id: str = "", limit: int = 20) -> list:
        """获取最近告警"""
        c = self.conn.cursor()
        if experiment_id:
            c.execute("""
                SELECT experiment_id, alert_type, alert_reason, threshold_value, actual_value, action_taken, ts
                FROM ab_guardian_log WHERE experiment_id=? ORDER BY ts DESC LIMIT ?
            """, (experiment_id, limit))
        else:
            c.execute("""
                SELECT experiment_id, alert_type, alert_reason, threshold_value, actual_value, action_taken, ts
                FROM ab_guardian_log ORDER BY ts DESC LIMIT ?
            """, (limit,))
        return [
            {"experiment_id": r[0], "alert_type": r[1], "alert_reason": r[2],
             "threshold_value": r[3], "actual_value": r[4], "action_taken": r[5], "ts": r[6]}
            for r in c.fetchall()
        ]

    def save_weekly_report(self, week_start: str, experiment_id: str,
                           variant_a_ctr: float, variant_b_ctr: float,
                           variant_a_conversion: float, variant_b_conversion: float,
                           top_positive_features: list, top_negative_features: list,
                           recommendation: str) -> int:
        """保存周度分析报告"""
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("""
                    INSERT INTO weekly_ab_report
                    (week_start, experiment_id, variant_a_ctr, variant_b_ctr,
                     variant_a_conversion, variant_b_conversion,
                     top_positive_features, top_negative_features, recommendation, generated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(week_start, experiment_id) DO UPDATE SET
                        variant_a_ctr=excluded.variant_a_ctr,
                        variant_b_ctr=excluded.variant_b_ctr,
                        variant_a_conversion=excluded.variant_a_conversion,
                        variant_b_conversion=excluded.variant_b_conversion,
                        top_positive_features=excluded.top_positive_features,
                        top_negative_features=excluded.top_negative_features,
                        recommendation=excluded.recommendation,
                        generated_at=excluded.generated_at
                """, (week_start, experiment_id,
                      variant_a_ctr, variant_b_ctr,
                      variant_a_conversion, variant_b_conversion,
                      json.dumps(top_positive_features, ensure_ascii=False),
                      json.dumps(top_negative_features, ensure_ascii=False),
                      recommendation, int(time.time())))
                self.conn.commit()
                return c.lastrowid
            except Exception as e:
                logger.warning(f"保存周报失败: {e}")
                return 0

    def get_weekly_reports(self, experiment_id: str = "", limit: int = 10) -> list:
        """获取周度报告列表"""
        c = self.conn.cursor()
        if experiment_id:
            c.execute("""
                SELECT week_start, experiment_id, variant_a_ctr, variant_b_ctr,
                       variant_a_conversion, variant_b_conversion,
                       top_positive_features, top_negative_features, recommendation, generated_at
                FROM weekly_ab_report WHERE experiment_id=? ORDER BY week_start DESC LIMIT ?
            """, (experiment_id, limit))
        else:
            c.execute("""
                SELECT week_start, experiment_id, variant_a_ctr, variant_b_ctr,
                       variant_a_conversion, variant_b_conversion,
                       top_positive_features, top_negative_features, recommendation, generated_at
                FROM weekly_ab_report ORDER BY week_start DESC LIMIT ?
            """, (limit,))
        rows = c.fetchall()
        return [
            {"week_start": r[0], "experiment_id": r[1],
             "variant_a_ctr": r[2], "variant_b_ctr": r[3],
             "variant_a_conversion": r[4], "variant_b_conversion": r[5],
             "top_positive_features": json.loads(r[6]) if r[6] else [],
             "top_negative_features": json.loads(r[7]) if r[7] else [],
             "recommendation": r[8], "generated_at": r[9]}
            for r in rows
        ]
