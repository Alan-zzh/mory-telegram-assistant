# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/ab_test_router.py  ·  多模型路由 A/B 测试分流器（阶段2-C）        ║
║                                                                        ║
║  功能：                                                                ║
║    1. 按 uid % 10 分流：                                               ║
║       - Group A (uid%10==0): 全量走 qwen-max（对照组）                 ║
║       - Group B (uid%10==1): 全量走 deepseek-chat（实验组）            ║
║       - Group Base (uid%10 in 2-9): 走默认路由（基线组）               ║
║    2. record_ab_metric() 记录 latency/cost/converted                   ║
║    3. 内存累计指标，定时刷盘到 ab_test_metrics 表                      ║
║                                                                        ║
║  配置开关：config.get('AB_TEST_ENABLED', False)                        ║
║  被调用：core/ai_engine.py:ask()                                       ║
║  数据表：ab_test_metrics（建表见 core/database.py）                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import time
import math
import threading
from typing import Optional, Dict, Any

from core.logging_util import get_logger

logger = get_logger("ab_test_router")

# ── 分组常量 ──────────────────────────────────────────────
GROUP_A = "A"        # 对照组：全量走 qwen-max
GROUP_B = "B"        # 实验组：全量走 deepseek-chat
GROUP_BASE = "Base"  # 基线组：走默认路由


# ── 内存指标缓冲区 ────────────────────────────────────────
# 累积指标，达到阈值或定时后批量刷盘到 ab_test_metrics 表
_metrics_buffer = []
_buffer_lock = threading.Lock()
_last_flush_ts = 0.0
_FLUSH_INTERVAL = 60.0   # 60 秒刷盘一次
_FLUSH_BATCH_SIZE = 100  # 单次最多刷 100 条


def is_enabled(config: dict) -> bool:
    """检查 A/B 测试是否启用（默认关闭，向后兼容）"""
    return bool((config or {}).get("AB_TEST_ENABLED", False))


def get_ab_group(uid: int) -> str:
    """按 uid % 10 分流到 A/B/Base 三组

    分流策略：
        - uid%10 == 0 → Group A（对照组，全量走 qwen-max）
        - uid%10 == 1 → Group B（实验组，全量走 deepseek-chat）
        - uid%10 in 2-9 → Group Base（基线组，走默认路由）

    Args:
        uid: 用户 ID

    Returns:
        "A" / "B" / "Base"；uid 无效时返回 Base
    """
    try:
        uid = int(uid) if uid else 0
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        return GROUP_BASE
    bucket = uid % 10
    if bucket == 0:
        return GROUP_A
    elif bucket == 1:
        return GROUP_B
    else:
        return GROUP_BASE


def get_model_for_group(group: str, config: dict) -> Optional[str]:
    """根据分组返回对应模型名

    Args:
        group: A / B / Base
        config: 配置字典

    Returns:
        模型名；Base 组返回 None（走默认路由，不覆盖）
    """
    if group == GROUP_A:
        return config.get("AB_TEST_GROUP_A_MODEL", "qwen-max")
    elif group == GROUP_B:
        return config.get("AB_TEST_GROUP_B_MODEL", "deepseek-chat")
    return None  # Base 组走默认路由


def record_ab_metric(uid: int, group: str, model: str, latency_ms: float,
                     cost: float = 0.0, converted: bool = False):
    """记录 A/B 测试指标到内存缓冲区，定时刷盘

    指标记录失败不影响主流程（仅 debug 日志）。

    Args:
        uid: 用户 ID
        group: 分组（A/B/Base）
        model: 实际使用的模型名
        latency_ms: 延迟（毫秒）
        cost: 成本（元）
        converted: 是否转化
    """
    try:
        metric = {
            "uid": int(uid) if uid else 0,
            "group": str(group or GROUP_BASE),
            "model": str(model or ""),
            "latency_ms": float(latency_ms or 0),
            "cost": float(cost or 0),
            "converted": 1 if converted else 0,
            "ts": int(time.time()),
        }
        should_flush = False
        with _buffer_lock:
            _metrics_buffer.append(metric)
            should_flush = (
                len(_metrics_buffer) >= _FLUSH_BATCH_SIZE
                or (time.time() - _last_flush_ts) >= _FLUSH_INTERVAL
            )
        if should_flush:
            flush_metrics()
    except Exception as e:
        # 指标记录失败不影响主流程
        logger.debug(f"A/B 指标记录失败（不影响主流程）: {e}")


def _get_db():
    """获取数据库实例（延迟导入避免循环依赖）

    优先从 main.py 获取 DB 类实例（含 conn/lock），
    失败则返回 None。
    """
    try:
        from main import db
        if db and hasattr(db, "conn"):
            return db
    except Exception:
        pass
    return None


def flush_metrics():
    """将内存缓冲区的指标刷盘到 ab_test_metrics 表

    失败不抛异常，仅记录日志。线程安全由 _buffer_lock + db.lock 保证。
    """
    global _last_flush_ts
    try:
        with _buffer_lock:
            if not _metrics_buffer:
                return
            batch = _metrics_buffer[:_FLUSH_BATCH_SIZE]
            del _metrics_buffer[:len(batch)]
            _last_flush_ts = time.time()

        db = _get_db()
        if not db:
            logger.debug("A/B 指标刷盘跳过：db 不可用")
            return

        # 使用 db.lock 保证写入线程安全
        with getattr(db, "lock", threading.Lock()):
            c = db.conn.cursor()
            for m in batch:
                try:
                    c.execute(
                        "INSERT INTO ab_test_metrics "
                        "(uid, group_name, model, latency_ms, cost, converted, ts) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (m["uid"], m["group"], m["model"], m["latency_ms"],
                         m["cost"], m["converted"], m["ts"])
                    )
                except Exception as e:
                    logger.debug(f"A/B 指标写入失败: {e}")
                    break
            db.conn.commit()
            logger.info(f"✅ A/B 指标刷盘完成: {len(batch)} 条")
    except Exception as e:
        logger.debug(f"A/B 指标刷盘异常（不影响主流程）: {e}")


def get_report(days: int = 7) -> list:
    """聚合查询 A/B 测试报表（供 Dashboard API 调用）

    Args:
        days: 回溯天数（默认 7）

    Returns:
        [{group, model, sample_count, avg_latency, p95_latency,
          avg_cost, conversion_rate}, ...]
    """
    db = _get_db()
    if not db:
        return []
    try:
        cutoff = int(time.time()) - days * 86400
        c = db.conn.cursor()
        # 先按 group+model 聚合基础统计
        c.execute("""
            SELECT group_name, model,
                   COUNT(*) AS sample_count,
                   AVG(latency_ms) AS avg_latency,
                   AVG(cost) AS avg_cost,
                   SUM(converted) AS converted_count
            FROM ab_test_metrics
            WHERE ts >= ?
            GROUP BY group_name, model
            ORDER BY group_name
        """, (cutoff,))
        rows = c.fetchall()

        result = []
        for r in rows:
            group = r[0]
            model = r[1]
            sample_count = r[2] or 0
            avg_latency = round(r[3] or 0, 2)
            avg_cost = round(r[4] or 0, 6)
            converted_count = r[5] or 0
            conversion_rate = round(converted_count / sample_count * 100, 2) if sample_count > 0 else 0.0

            # P95 延迟：取该组所有延迟排序后的第 95 百分位
            p95_latency = _calc_p95_latency(c, group, model, cutoff)

            result.append({
                "group": group,
                "model": model,
                "sample_count": sample_count,
                "avg_latency": avg_latency,
                "p95_latency": p95_latency,
                "avg_cost": avg_cost,
                "conversion_rate": conversion_rate,
            })
        return result
    except Exception as e:
        logger.warning(f"A/B 报表查询失败: {e}")
        return []


def _calc_p95_latency(cursor, group: str, model: str, cutoff: int) -> float:
    """计算指定组+模型的 P95 延迟

    使用 OFFSET 跳过法近似计算 P95（SQLite 无原生 percentile 函数）。
    """
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM ab_test_metrics WHERE group_name=? AND model=? AND ts>=?",
            (group, model, cutoff)
        )
        total = cursor.fetchone()[0] or 0
        if total == 0:
            return 0.0
        # P95 位置索引（0-based）
        p95_idx = int(total * 0.95) - 1
        if p95_idx < 0:
            p95_idx = 0
        cursor.execute(
            "SELECT latency_ms FROM ab_test_metrics "
            "WHERE group_name=? AND model=? AND ts>=? "
            "ORDER BY latency_ms ASC LIMIT 1 OFFSET ?",
            (group, model, cutoff, p95_idx)
        )
        row = cursor.fetchone()
        return round(row[0] if row else 0.0, 2)
    except Exception as e:
        logger.debug(f"P95 计算失败: {e}")
        return 0.0


# ── 统计显著性检验（阶段2-D） ────────────────────────────────
# 使用 scipy 进行 A/B 测试统计显著性分析
# 卡方检验：比较转化率（分类数据）
# Z 检验：比较均值（连续数据，如延迟、成本）

def calculate_statistical_significance(
    group_a_stats: Dict[str, Any],
    group_b_stats: Dict[str, Any],
    alpha: float = 0.05
) -> Dict[str, Any]:
    """计算两组 A/B 测试的统计显著性

    Args:
        group_a_stats: A 组统计指标
            - sample_count: 样本数
            - converted_count: 转化数（用于卡方检验）
            - avg_latency: 平均延迟（用于 Z 检验）
            - latency_std: 延迟标准差（可选，默认用均值估算）
        group_b_stats: B 组统计指标（同 A 组结构）
        alpha: 显著性水平阈值（默认 0.05，即 95% 置信度）

    Returns:
        {
            "chi_square": {
                "statistic": 卡方值,
                "p_value": p 值,
                "significant": 是否显著（p < alpha）,
                "winner": 胜出组（"A"/"B"/"tie"）,
                "confidence": 置信度百分比
            },
            "z_test": {
                "statistic": Z 值,
                "p_value": p 值,
                "significant": 是否显著,
                "winner": 胜出组（延迟更低者）,
                "confidence_interval": (下界, 上界),
                "confidence": 置信度百分比
            },
            "recommendation": 推荐结论（字符串）
        }
    """
    try:
        from scipy import stats
        from scipy.stats import chi2_contingency, norm

        result = {
            "chi_square": None,
            "z_test": None,
            "recommendation": ""
        }

        # ── 1. 卡方检验（比较转化率） ─────────────────────
        n_a = int(group_a_stats.get("sample_count", 0))
        n_b = int(group_b_stats.get("sample_count", 0))
        conv_a = int(group_a_stats.get("converted_count", 0))
        conv_b = int(group_b_stats.get("converted_count", 0))

        # 样本量检查（至少需要 30 个样本才进行检验）
        if n_a >= 30 and n_b >= 30 and (conv_a > 0 or conv_b > 0):
            # 构建 2x2 列联表：[[A转化, A未转化], [B转化, B未转化]]
            contingency_table = [
                [conv_a, n_a - conv_a],
                [conv_b, n_b - conv_b]
            ]

            chi2, p_chi2, dof, expected = chi2_contingency(contingency_table)

            # 计算转化率
            rate_a = conv_a / n_a * 100 if n_a > 0 else 0
            rate_b = conv_b / n_b * 100 if n_b > 0 else 0

            # 判断胜出组
            if p_chi2 < alpha:
                winner = "A" if rate_a > rate_b else "B"
            else:
                winner = "tie"

            result["chi_square"] = {
                "statistic": round(float(chi2), 4),
                "p_value": round(float(p_chi2), 6),
                "significant": p_chi2 < alpha,
                "winner": winner,
                "conversion_rate_a": round(rate_a, 2),
                "conversion_rate_b": round(rate_b, 2),
                "confidence": round((1 - p_chi2) * 100, 2)
            }

        # ── 2. Z 检验（比较平均延迟） ─────────────────────
        mean_a = float(group_a_stats.get("avg_latency", 0))
        mean_b = float(group_b_stats.get("avg_latency", 0))
        std_a = float(group_a_stats.get("latency_std", mean_a * 0.3))  # 无标准差时用均值估算
        std_b = float(group_b_stats.get("latency_std", mean_b * 0.3))

        if n_a >= 30 and n_b >= 30 and (mean_a > 0 or mean_b > 0):
            # 计算 Z 统计量（双样本 Z 检验）
            # H0: μA = μB（两组均值无显著差异）
            # H1: μA ≠ μB（两组均值有显著差异）
            se = math.sqrt((std_a ** 2) / n_a + (std_b ** 2) / n_b)
            if se > 0:
                z_stat = (mean_a - mean_b) / se
                # 双尾检验 p 值
                p_z = 2 * (1 - norm.cdf(abs(z_stat)))

                # 计算 95% 置信区间
                z_critical = norm.ppf(1 - alpha / 2)
                ci_lower = (mean_a - mean_b) - z_critical * se
                ci_upper = (mean_a - mean_b) + z_critical * se

                # 判断胜出组（延迟更低者胜出）
                if p_z < alpha:
                    winner = "A" if mean_a < mean_b else "B"
                else:
                    winner = "tie"

                result["z_test"] = {
                    "statistic": round(float(z_stat), 4),
                    "p_value": round(float(p_z), 6),
                    "significant": p_z < alpha,
                    "winner": winner,
                    "mean_a": round(mean_a, 2),
                    "mean_b": round(mean_b, 2),
                    "confidence_interval": (round(ci_lower, 2), round(ci_upper, 2)),
                    "confidence": round((1 - p_z) * 100, 2)
                }

        # ── 3. 综合推荐结论 ───────────────────────────────
        recommendations = []
        if result["chi_square"] and result["chi_square"]["significant"]:
            winner = result["chi_square"]["winner"]
            rate = result["chi_square"][f"conversion_rate_{winner.lower()}"]
            recommendations.append(
                f"转化率：{winner} 组显著胜出（{rate}%，p={result['chi_square']['p_value']:.4f}）"
            )

        if result["z_test"] and result["z_test"]["significant"]:
            winner = result["z_test"]["winner"]
            mean = result["z_test"][f"mean_{winner.lower()}"]
            recommendations.append(
                f"延迟：{winner} 组显著更低（{mean}ms，p={result['z_test']['p_value']:.4f}）"
            )

        if not recommendations:
            result["recommendation"] = "样本量不足或差异不显著，建议继续收集数据"
        else:
            result["recommendation"] = "；".join(recommendations)

        return result

    except ImportError:
        logger.warning("scipy 未安装，无法进行统计显著性检验")
        return {
            "chi_square": None,
            "z_test": None,
            "recommendation": "scipy 未安装，请执行 pip install scipy>=1.11.0"
        }
    except Exception as e:
        logger.warning(f"统计显著性检验失败: {e}")
        return {
            "chi_square": None,
            "z_test": None,
            "recommendation": f"检验失败: {str(e)}"
        }


def get_significance_report(days: int = 7, alpha: float = 0.05) -> Dict[str, Any]:
    """生成 A/B 测试统计显著性报告（供 Dashboard API 调用）

    Args:
        days: 回溯天数（默认 7）
        alpha: 显著性水平阈值（默认 0.05）

    Returns:
        {
            "period_days": 回溯天数,
            "alpha": 显著性阈值,
            "groups": {
                "A": {...统计指标...},
                "B": {...统计指标...}
            },
            "significance": calculate_statistical_significance() 的返回值,
            "generated_at": 生成时间戳
        }
    """
    db = _get_db()
    if not db:
        return {
            "period_days": days,
            "alpha": alpha,
            "groups": {},
            "significance": None,
            "generated_at": int(time.time())
        }

    try:
        cutoff = int(time.time()) - days * 86400
        c = db.conn.cursor()

        # 查询 A/B 两组的详细统计指标
        c.execute("""
            SELECT group_name, model,
                   COUNT(*) AS sample_count,
                   SUM(converted) AS converted_count,
                   AVG(latency_ms) AS avg_latency,
                   AVG(cost) AS avg_cost,
                   MIN(latency_ms) AS min_latency,
                   MAX(latency_ms) AS max_latency
            FROM ab_test_metrics
            WHERE ts >= ? AND group_name IN ('A', 'B')
            GROUP BY group_name, model
            ORDER BY group_name
        """, (cutoff,))

        rows = c.fetchall()
        groups = {}
        for r in rows:
            group_name = r[0]
            # 估算标准差（SQLite 无原生 STDDEV，用范围/4 近似）
            min_lat = r[6] or 0
            max_lat = r[7] or 0
            latency_std = (max_lat - min_lat) / 4 if max_lat > min_lat else 0

            groups[group_name] = {
                "model": r[1],
                "sample_count": r[2] or 0,
                "converted_count": r[3] or 0,
                "avg_latency": round(r[4] or 0, 2),
                "avg_cost": round(r[5] or 0, 6),
                "latency_std": round(latency_std, 2)
            }

        # 计算统计显著性
        significance = None
        if "A" in groups and "B" in groups:
            significance = calculate_statistical_significance(
                groups["A"], groups["B"], alpha
            )

        return {
            "period_days": days,
            "alpha": alpha,
            "groups": groups,
            "significance": significance,
            "generated_at": int(time.time())
        }
    except Exception as e:
        logger.warning(f"统计显著性报告生成失败: {e}")
        return {
            "period_days": days,
            "alpha": alpha,
            "groups": {},
            "significance": None,
            "generated_at": int(time.time())
        }

