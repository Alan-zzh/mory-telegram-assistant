# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  tests/load/analyze_results.py  ·  压测结果分析与黄金指标提取              ║
║                          （v5.26.0 阶段1-B）                              ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 解析 Locust CSV 结果文件                                             ║
║    2. 提取黄金指标（P95/P99 延迟、错误率、WriteQueueFullError 首次出现）   ║
║    3. 生成背压阈值调优建议                                                 ║
║    4. 输出 Markdown 报告到 logs/load_test_analysis_report.md               ║
║                                                                            ║
║  用法：                                                                    ║
║    python -m tests.load.analyze_results --tier 1                           ║
║    python -m tests.load.analyze_results --tier 2 --csv-dir logs            ║
║    python -m tests.load.analyze_results --all                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import csv
import json
import argparse
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════
# 黄金指标定义
# ═══════════════════════════════════════════════════════════════════════════

# 背压阈值建议基准（基于 2C4G VPS + SQLite WAL）
THRESHOLD_BASELINE = {
    "write_queue_max_size": {
        "current": 500,           # 当前配置（write_queue.py 默认）
        "tier1_safe": 100,        # 1 档安全值
        "tier2_recommended": 300, # 2 档推荐值
        "tier3_critical": 500,    # 3 档临界值
    },
    "optimistic_lock_retry": {
        "current": 3,             # 当前重试次数
        "recommended_min": 3,     # 最低推荐
        "recommended_max": 5,     # 最高推荐
    },
    "p95_latency_ms": {
        "good": 200,              # 良好
        "acceptable": 500,        # 可接受
        "critical": 1000,         # 临界
    },
    "error_rate": {
        "good": 0.01,             # 1% 以下良好
        "acceptable": 0.05,       # 5% 可接受
        "critical": 0.10,         # 10% 临界
    },
}


def load_csv_stats(csv_prefix: str) -> Optional[dict]:
    """加载 Locust CSV 统计文件

    Locust 生成两个文件：
    - {prefix}_stats.csv：按请求类型统计
    - {prefix}_stats_history.csv：时间序列统计
    """
    stats_file = f"{csv_prefix}_stats.csv"
    if not os.path.exists(stats_file):
        return None

    result = {
        "requests": [],
        "total": None,
        "history": [],
    }

    # 读取按请求类型统计
    try:
        with open(stats_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed = {
                    "name": row.get("Name", ""),
                    "num_requests": int(row.get("Request Count", 0)),
                    "num_failures": int(row.get("Failure Count", 0)),
                    "avg_response_time": float(row.get("Average Response Time", 0)),
                    "min_response_time": float(row.get("Min Response Time", 0)),
                    "max_response_time": float(row.get("Max Response Time", 0)),
                    "p95": float(row.get("95th", 0)),
                    "p99": float(row.get("99th", 0)),
                    "rps": float(row.get("Requests/s", 0)),
                }
                if row.get("Name") == "Aggregated":
                    result["total"] = parsed
                else:
                    result["requests"].append(parsed)
    except Exception as e:
        print(f"⚠️  读取 {stats_file} 失败: {e}")
        return None

    # 读取时间序列历史
    history_file = f"{csv_prefix}_stats_history.csv"
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    result["history"].append({
                        "timestamp": row.get("Timestamp", ""),
                        "user_count": int(row.get("User Count", 0)),
                        "rps": float(row.get("Total RPS", 0)),
                        "failures": int(row.get("Total Failure Count", 0)),
                    })
        except Exception:
            pass  # 历史数据非必需

    return result


def load_write_queue_full_event() -> Optional[dict]:
    """加载 WriteQueueFullError 首次出现记录"""
    wq_file = "logs/load_test_wq_full_first_seen.json"
    if not os.path.exists(wq_file):
        return None
    try:
        with open(wq_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def analyze_tier(tier: int, csv_dir: str = "logs") -> dict:
    """分析指定档位的压测结果"""
    csv_prefix = os.path.join(csv_dir, f"load_test_tier{tier}")
    stats = load_csv_stats(csv_prefix)

    analysis = {
        "tier": tier,
        "csv_prefix": csv_prefix,
        "stats_available": stats is not None,
        "golden_metrics": {},
        "threshold_recommendations": [],
        "issues": [],
    }

    if not stats:
        analysis["issues"].append(f"未找到 {csv_prefix}_stats.csv，请先运行 {tier} 档压测")
        return analysis

    total = stats.get("total")
    if total:
        # 黄金指标
        analysis["golden_metrics"] = {
            "total_requests": total["num_requests"],
            "total_failures": total["num_failures"],
            "error_rate": total["num_failures"] / max(total["num_requests"], 1),
            "avg_latency_ms": total["avg_response_time"],
            "p95_latency_ms": total["p95"],
            "p99_latency_ms": total["p99"],
            "achieved_rps": total["rps"],
        }

        # 评估 P95 延迟
        p95 = total["p95"]
        if p95 > THRESHOLD_BASELINE["p95_latency_ms"]["critical"]:
            analysis["issues"].append(
                f"P95 延迟 {p95:.0f}ms 超过临界值 {THRESHOLD_BASELINE['p95_latency_ms']['critical']}ms"
            )
        elif p95 > THRESHOLD_BASELINE["p95_latency_ms"]["acceptable"]:
            analysis["threshold_recommendations"].append(
                f"P95 延迟 {p95:.0f}ms 在可接受范围，建议优化慢查询"
            )

        # 评估错误率
        err_rate = analysis["golden_metrics"]["error_rate"]
        if err_rate > THRESHOLD_BASELINE["error_rate"]["critical"]:
            analysis["issues"].append(
                f"错误率 {err_rate*100:.1f}% 超过临界值 {THRESHOLD_BASELINE['error_rate']['critical']*100}%"
            )

    # WriteQueueFullError 分析
    wq_event = load_write_queue_full_event()
    if wq_event:
        analysis["golden_metrics"]["write_queue_full_first_seen"] = wq_event["first_seen_at"]
        analysis["threshold_recommendations"].append(
            f"WriteQueueFullError 首次出现于 {wq_event['first_seen_at']}，"
            f"建议将背压阈值从 {THRESHOLD_BASELINE['write_queue_max_size']['current']} "
            f"调整为 {THRESHOLD_BASELINE['write_queue_max_size'][f'tier{tier}_recommended' if tier <= 2 else 'tier3_critical']}"
        )
    else:
        analysis["golden_metrics"]["write_queue_full_first_seen"] = None
        if tier < 3:
            analysis["threshold_recommendations"].append(
                f"{tier} 档未触发 WriteQueueFullError，当前背压阈值 "
                f"{THRESHOLD_BASELINE['write_queue_max_size']['current']} 足够"
            )

    # 按请求类型分析
    analysis["per_request"] = []
    for req in stats.get("requests", []):
        req_analysis = {
            "name": req["name"],
            "rps": req["rps"],
            "p95": req["p95"],
            "error_rate": req["num_failures"] / max(req["num_requests"], 1),
        }
        if req["p95"] > THRESHOLD_BASELINE["p95_latency_ms"]["acceptable"]:
            req_analysis["issue"] = f"P95 {req['p95']:.0f}ms 偏高"
        analysis["per_request"].append(req_analysis)

    return analysis


def generate_report(all_analyses: list) -> str:
    """生成 Markdown 分析报告"""
    lines = []
    lines.append("# Mory 助理压测结果分析报告")
    lines.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    lines.append("## 黄金指标阈值基准\n")
    lines.append("| 指标 | 良好 | 可接受 | 临界 |")
    lines.append("|------|------|--------|------|")
    lines.append(f"| P95 延迟 (ms) | {THRESHOLD_BASELINE['p95_latency_ms']['good']} | "
                 f"{THRESHOLD_BASELINE['p95_latency_ms']['acceptable']} | "
                 f"{THRESHOLD_BASELINE['p95_latency_ms']['critical']} |")
    lines.append(f"| 错误率 | {THRESHOLD_BASELINE['error_rate']['good']*100}% | "
                 f"{THRESHOLD_BASELINE['error_rate']['acceptable']*100}% | "
                 f"{THRESHOLD_BASELINE['error_rate']['critical']*100}% |")
    lines.append(f"| WriteQueue 队列上限 | {THRESHOLD_BASELINE['write_queue_max_size']['tier1_safe']} | "
                 f"{THRESHOLD_BASELINE['write_queue_max_size']['tier2_recommended']} | "
                 f"{THRESHOLD_BASELINE['write_queue_max_size']['tier3_critical']} |")
    lines.append(f"| 乐观锁重试次数 | {THRESHOLD_BASELINE['optimistic_lock_retry']['recommended_min']} | "
                 f"{THRESHOLD_BASELINE['optimistic_lock_retry']['current']} | "
                 f"{THRESHOLD_BASELINE['optimistic_lock_retry']['recommended_max']} |\n")

    for analysis in all_analyses:
        tier = analysis["tier"]
        lines.append(f"## {tier} 档压测结果\n")

        if not analysis["stats_available"]:
            lines.append(f"⚠️ {analysis['issues'][0]}\n")
            continue

        gm = analysis["golden_metrics"]
        lines.append("### 黄金指标\n")
        lines.append("| 指标 | 数值 | 评估 |")
        lines.append("|------|------|------|")

        # 总请求数
        lines.append(f"| 总请求数 | {gm.get('total_requests', 'N/A')} | - |")
        lines.append(f"| 失败请求数 | {gm.get('total_failures', 'N/A')} | - |")

        # 错误率
        err_rate = gm.get("error_rate", 0)
        err_eval = "✅ 良好" if err_rate < 0.01 else ("⚠️ 可接受" if err_rate < 0.05 else "❌ 临界")
        lines.append(f"| 错误率 | {err_rate*100:.2f}% | {err_eval} |")

        # P95 延迟
        p95 = gm.get("p95_latency_ms", 0)
        p95_eval = "✅ 良好" if p95 < 200 else ("⚠️ 可接受" if p95 < 500 else "❌ 临界")
        lines.append(f"| P95 延迟 | {p95:.0f} ms | {p95_eval} |")

        # P99 延迟
        p99 = gm.get("p99_latency_ms", 0)
        lines.append(f"| P99 延迟 | {p99:.0f} ms | - |")

        # 实际 RPS
        lines.append(f"| 实际 RPS | {gm.get('achieved_rps', 0):.1f} | - |")

        # WriteQueueFullError
        wq = gm.get("write_queue_full_first_seen")
        lines.append(f"| WriteQueueFullError | {wq or '未触发'} | {'⚠️ 已触发' if wq else '✅ 未触发'} |")

        lines.append("")

        # 阈值建议
        if analysis["threshold_recommendations"]:
            lines.append("### 阈值调优建议\n")
            for rec in analysis["threshold_recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")

        # 问题
        if analysis["issues"]:
            lines.append("### ⚠️ 发现的问题\n")
            for issue in analysis["issues"]:
                lines.append(f"- {issue}")
            lines.append("")

        # 按请求类型
        if analysis.get("per_request"):
            lines.append("### 按请求类型分析\n")
            lines.append("| 接口 | RPS | P95 (ms) | 错误率 | 问题 |")
            lines.append("|------|-----|----------|--------|------|")
            for req in analysis["per_request"]:
                issue = req.get("issue", "-")
                lines.append(f"| {req['name']} | {req['rps']:.1f} | {req['p95']:.0f} | {req['error_rate']*100:.1f}% | {issue} |")
            lines.append("")

    # 总结
    lines.append("## 背压阈值调优总结\n")
    lines.append("基于三档压测结果，建议按以下步骤调整背压阈值：\n")
    lines.append("1. **WriteQueue 队列上限**：")
    lines.append(f"   - 当前值: {THRESHOLD_BASELINE['write_queue_max_size']['current']}")
    lines.append(f"   - 若 2 档（100 QPS）未触发 WriteQueueFullError，保持当前值")
    lines.append(f"   - 若 3 档（300 QPS）首次触发，记录当时的队列堆积长度，将上限设为该值的 80%\n")
    lines.append("2. **乐观锁重试次数**：")
    lines.append(f"   - 当前值: {THRESHOLD_BASELINE['optimistic_lock_retry']['current']}")
    lines.append(f"   - 若 2 档冲突率 > 10%，从 3 次调整为 {THRESHOLD_BASELINE['optimistic_lock_retry']['recommended_max']} 次")
    lines.append(f"   - 若 3 档冲突率 > 30%，考虑迁移到 Postgres（参考 docs/technical/db-migration-blueprint.md）\n")
    lines.append("3. **配置修改位置**：")
    lines.append("   - `core/write_queue.py` 的 `maxsize` 参数")
    lines.append("   - `core/shared_db.py` 的乐观锁重试次数")
    lines.append("   - 修改后必须 `python -m py_compile` 验证 + VPS 部署验证\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="压测结果分析与黄金指标提取")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="分析指定档位")
    parser.add_argument("--all", action="store_true", help="分析所有档位")
    parser.add_argument("--csv-dir", default="logs", help="CSV 文件目录（默认 logs）")
    parser.add_argument("--output", default="logs/load_test_analysis_report.md", help="报告输出路径")
    args = parser.parse_args()

    if not args.tier and not args.all:
        parser.print_help()
        sys.exit(1)

    tiers = [1, 2, 3] if args.all else [args.tier]
    all_analyses = []

    for tier in tiers:
        print(f"\n分析 {tier} 档压测结果...")
        analysis = analyze_tier(tier, args.csv_dir)
        all_analyses.append(analysis)

        if analysis["stats_available"]:
            gm = analysis["golden_metrics"]
            print(f"  总请求数: {gm.get('total_requests', 'N/A')}")
            print(f"  错误率: {gm.get('error_rate', 0)*100:.2f}%")
            print(f"  P95 延迟: {gm.get('p95_latency_ms', 0):.0f} ms")
            print(f"  WriteQueueFullError: {gm.get('write_queue_full_first_seen') or '未触发'}")
        else:
            print(f"  ⚠️ {analysis['issues'][0]}")

    # 生成报告
    report = generate_report(all_analyses)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n✅ 分析报告已生成: {args.output}")


if __name__ == "__main__":
    main()
