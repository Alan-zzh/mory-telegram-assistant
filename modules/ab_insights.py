# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/ab_insights.py  ·  A/B 测试闭环分析与周度报告（v1.0）          ║
║                                                                        ║
║  功能：                                                                ║
║    1. 周度自动分析任务 —— 每个周日运行，对比 A/B 两版话术数据           ║
║    2. Top 5 话术特征提取 —— 高转化用户对话中的高频共现词                 ║
║    3. Top 5 毒点词汇提取 —— 流失用户对话中的负向触发词                   ║
║    4. 生成可读性报告 —— 供运营人员直接阅读并指导下一周期实验             ║
║                                                                        ║
║  被调用：modules/auto_tasks.py 定时任务                                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import time
from datetime import datetime, timedelta, timezone

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("ab_insights")


class ABInsights:
    """A/B 测试闭环洞察引擎"""

    def __init__(self, db, config: dict):
        self.db = db
        self.config = config
        self._ab_cfg = config.get("AB_TEST_CONFIG", {})
        self._enabled = bool(self._ab_cfg.get("weekly_report_enabled", False))

    def run_weekly_analysis(self, experiment_id: str = "") -> list:
        """
        执行周度全量分析，返回生成的报告列表。
        experiment_id 为空则分析所有实验。
        """
        reports = []
        if not self._enabled or not self.db:
            return reports

        engine = None
        try:
            from core.ab_testing import ABTestEngine
            engine = ABTestEngine(self.db, self.config)
        except Exception as e:
            logger.warning(f"ABTestEngine 加载失败: {e}")
            return reports

        experiments = engine.list_running_experiments()
        if experiment_id:
            experiments = [e for e in experiments if e.get("id") == experiment_id]

        week_start = self._current_week_start()
        week_start_ts = int(datetime.strptime(week_start, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        week_end_ts = week_start_ts + 86400 * 7

        for exp in experiments:
            eid = exp.get("id")
            try:
                report = self._analyze_single_experiment(eid, week_start, week_start_ts, week_end_ts)
                if report:
                    reports.append(report)
            except Exception as e:
                logger.warning(f"周度分析失败 {eid}: {e}")

        return reports

    def _current_week_start(self) -> str:
        """获取本周一日期"""
        now = datetime.now(_CST)
        monday = now - timedelta(days=now.weekday())
        return monday.strftime("%Y-%m-%d")

    def _analyze_single_experiment(self, experiment_id: str, week_start: str,
                                   start_ts: int, end_ts: int) -> dict | None:
        """对单个实验进行深度分析"""
        if not hasattr(self.db, "get_conversion_funnel"):
            return None

        funnel = self.db.get_conversion_funnel(experiment_id, start_ts, end_ts)
        a = funnel.get("A", {})
        b = funnel.get("B", {})

        # CTR 与转化率
        a_ctr = a.get("ctr", 0)
        b_ctr = b.get("ctr", 0)
        a_conv = a.get("conversion_rate", 0)
        b_conv = b.get("conversion_rate", 0)

        # 提取 Top 5 话术特征（正向）
        pos_a = self.db.get_top_features(experiment_id, "A", positive=True, limit=5)
        pos_b = self.db.get_top_features(experiment_id, "B", positive=True, limit=5)

        # 提取 Top 5 毒点（负向）
        neg_a = self.db.get_top_features(experiment_id, "A", positive=False, limit=5)
        neg_b = self.db.get_top_features(experiment_id, "B", positive=False, limit=5)

        # 合并去重取全局 Top 5
        top_positive = self._merge_rank_features(pos_a, pos_b)
        top_negative = self._merge_rank_features(neg_a, neg_b)

        # 生成运营建议
        recommendation = self._generate_recommendation(a, b, top_positive, top_negative)

        # 持久化报告
        if hasattr(self.db, "save_weekly_report"):
            self.db.save_weekly_report(
                week_start=week_start,
                experiment_id=experiment_id,
                variant_a_ctr=a_ctr,
                variant_b_ctr=b_ctr,
                variant_a_conversion=a_conv,
                variant_b_conversion=b_conv,
                top_positive_features=top_positive,
                top_negative_features=top_negative,
                recommendation=recommendation,
            )

        return {
            "week_start": week_start,
            "experiment_id": experiment_id,
            "funnel": funnel,
            "top_positive": top_positive,
            "top_negative": top_negative,
            "recommendation": recommendation,
        }

    def _merge_rank_features(self, list_a: list, list_b: list) -> list:
        """合并两组的特征词，按总频次排序取 Top 5"""
        merged = {}
        for item in list_a + list_b:
            word = item.get("word", "")
            count = item.get("count", 0)
            if word:
                merged[word] = merged.get(word, 0) + count
        sorted_items = sorted(merged.items(), key=lambda x: x[1], reverse=True)
        return [{"word": w, "count": c} for w, c in sorted_items[:5]]

    def _generate_recommendation(self, a: dict, b: dict,
                                  top_positive: list, top_negative: list) -> str:
        """生成运营建议文本"""
        parts = []
        a_conv = a.get("conversion_rate", 0)
        b_conv = b.get("conversion_rate", 0)
        a_churn = a.get("churn_rate", 0)
        b_churn = b.get("churn_rate", 0)

        # 胜负判断
        if b_conv > a_conv * 1.2 and b_churn <= a_churn * 1.2:
            parts.append(f"B组表现更优：转化率{b_conv:.2f}% > A组{a_conv:.2f}%，且退群率可控。建议将 B 组策略逐步全量推广。")
        elif a_conv > b_conv * 1.2 and a_churn <= b_churn * 1.2:
            parts.append(f"A组表现更优：转化率{a_conv:.2f}% > B组{b_conv:.2f}%，且退群率可控。建议维持 A 组策略。")
        elif b_churn > a_churn * 1.5:
            parts.append(f"⚠️ B组退群率({b_churn:.2f}%)显著高于 A组({a_churn:.2f}%)，需立即排查 B 组话术中的刺激性表达。")
        elif a_churn > b_churn * 1.5:
            parts.append(f"⚠️ A组退群率({a_churn:.2f}%)显著高于 B组({b_churn:.2f}%)，需立即排查 A 组话术中的刺激性表达。")
        else:
            parts.append(f"两组数据差异不显著（A转化率{a_conv:.2f}% vs B{b_conv:.2f}%），建议延长实验周期或扩大样本量。")

        if top_positive:
            words = "、".join([p["word"] for p in top_positive[:3]])
            parts.append(f"高转化话术特征：{words}。建议在下一轮 Prompt 中保留并强化这些表达。")

        if top_negative:
            words = "、".join([n["word"] for n in top_negative[:3]])
            parts.append(f"流失用户高频触发词：{words}。建议下一轮实验中剔除或替换这些词汇。")

        return "\n".join(parts)


def run_weekly_ab_report_job(db, config: dict):
    """供 auto_tasks.py 调用的周度分析任务入口"""
    insights = ABInsights(db, config)
    reports = insights.run_weekly_analysis()
    logger.info(f"[AB Insights] 周度分析完成，生成 {len(reports)} 份报告")
    return reports
