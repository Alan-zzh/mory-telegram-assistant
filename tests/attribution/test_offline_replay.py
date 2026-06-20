# -*- coding: utf-8 -*-
"""
归因模型离线回放验证脚本
对比：时间衰减归因 vs 末次触达归因
用法：python -m tests.attribution.test_offline_replay --days 30

设计说明：
- 不依赖 pytest fixture，可独立运行
- 只读访问 conversion_events 表，不修改生产数据
- 报错写 logs/attribution_replay_error.log，不甩 stack trace
- 归因算法与 core/funnel_state_machine.py 保持一致：
  * last_touch: 取转化前 window_hours 内最后一次 interested/carted 事件
  * time_decay: 按 exp(-lambda*hours_ago) 加权分配，主归因=权重最大渠道
"""

import argparse
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# 添加项目根目录到 sys.path，便于独立运行
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 时间衰减系数（与 funnel_state_machine.TIME_DECAY_LAMBDA 保持一致，单位 1/小时）
# 半衰期 = ln(2)/0.1 ≈ 6.93 小时
TIME_DECAY_LAMBDA = 0.1
# 默认回溯窗口（小时），与 attribute_conversion 默认值一致
DEFAULT_WINDOW_HOURS = 48
# 北京时区
_CST = timezone(timedelta(hours=8))


def _get_db_path() -> str:
    """获取数据库路径：优先 SHARED_DB_PATH 环境变量，回退项目根目录 mory.db"""
    path = os.environ.get("SHARED_DB_PATH", "")
    if path and os.path.exists(path):
        return path
    return os.path.join(_PROJECT_ROOT, "mory.db")


def _connect_db(db_path: str):
    """连接数据库（只读模式，避免影响生产数据）"""
    if not os.path.exists(db_path):
        return None
    # 用 uri 只读模式打开，杜绝误写
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _log_error(msg: str):
    """错误日志写入 logs/attribution_replay_error.log（不甩 stack trace）"""
    try:
        logs_dir = os.path.join(_PROJECT_ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "attribution_replay_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(_CST).isoformat()}] {msg}\n")
    except Exception:
        pass  # 日志写入失败不影响主流程


def load_historical_events(days: int, db_path: str = None) -> list:
    """从 conversion_events 表加载过去 N 天的转化事件

    返回按 (uid, ts) 升序排列的事件列表，每个事件为 dict：
        {uid, event, ts, mode, source, campaign_id, is_memory_assisted}

    兼容旧表（无 source/campaign_id 等列时返回默认值）。
    只加载 interested/carted/converted 三类事件（归因分析所需）。
    """
    if db_path is None:
        db_path = _get_db_path()
    conn = _connect_db(db_path)
    if conn is None:
        return []

    try:
        # 检查表是否存在
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversion_events'"
        )
        if not cur.fetchone():
            return []

        # 检查可用列（兼容旧表，列可能不存在）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversion_events)").fetchall()]
        has_source = "source" in cols
        has_campaign = "campaign_id" in cols
        has_mem = "is_memory_assisted" in cols

        cutoff = int(time.time()) - days * 86400

        # 动态构造查询列（兼容旧表）
        select_cols = ["uid", "event", "ts", "mode"]
        if has_source:
            select_cols.append("source")
        if has_campaign:
            select_cols.append("campaign_id")
        if has_mem:
            select_cols.append("is_memory_assisted")

        sql = (
            f"SELECT {', '.join(select_cols)} FROM conversion_events "
            f"WHERE ts > ? AND event IN ('interested', 'carted', 'converted') "
            f"ORDER BY uid ASC, ts ASC"
        )
        rows = conn.execute(sql, (cutoff,)).fetchall()

        events = []
        for r in rows:
            ev = {
                "uid": r["uid"],
                "event": r["event"],
                "ts": r["ts"],
                "mode": r["mode"] or "",
                "source": r["source"] if has_source else "",
                "campaign_id": r["campaign_id"] if has_campaign else "",
                "is_memory_assisted": int(r["is_memory_assisted"]) if has_mem else 0,
            }
            events.append(ev)
        return events
    except Exception as e:
        _log_error(f"load_historical_events 失败: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _group_events_by_uid(events: list) -> dict:
    """按 uid 分组事件（保持时间升序）"""
    grouped = defaultdict(list)
    for ev in events:
        grouped[ev["uid"]].append(ev)
    return dict(grouped)


def _resolve_channel(event: dict) -> str:
    """解析事件对应的归因渠道：优先 campaign_id，其次 source，最后 unknown"""
    return event.get("campaign_id") or event.get("source") or "unknown"


def replay_last_touch(events: list, window_hours: int = DEFAULT_WINDOW_HOURS) -> dict:
    """末次触达归因回放

    每个转化只归因于最后一次触达渠道（interested/carted 事件）。
    算法与 funnel_state_machine.attribute_conversion(use_time_decay=False) 一致：
        1. 找到每次 converted 事件作为转化点
        2. 回溯 window_hours 内最后一次 interested/carted 事件
        3. 该事件的渠道作为归因结果

    Returns:
        {
            "model": "last_touch",
            "total_conversions": int,
            "channel_attributions": {channel: attributed_count, ...},
            "per_user": {uid: {channel, event, ts}, ...},
        }
    """
    grouped = _group_events_by_uid(events)
    channel_attributions = defaultdict(float)
    per_user = {}
    total_conversions = 0

    for uid, user_events in grouped.items():
        # 找到所有 converted 事件
        conversions = [e for e in user_events if e["event"] == "converted"]
        if not conversions:
            continue

        for conv in conversions:
            conversion_ts = conv["ts"]
            window_start = conversion_ts - window_hours * 3600
            # 回溯窗口内最后一次 interested/carted 事件
            touch_events = [
                e for e in user_events
                if e["event"] in ("interested", "carted")
                and window_start <= e["ts"] <= conversion_ts
            ]
            if not touch_events:
                # 无触达事件，归入 unknown
                channel = "unknown"
                per_user[uid] = {"channel": channel, "event": None, "ts": conversion_ts}
                channel_attributions[channel] += 1.0
                total_conversions += 1
                continue

            # 时间升序，最后一个为最近一次触达
            last_touch = touch_events[-1]
            channel = _resolve_channel(last_touch)
            per_user[uid] = {
                "channel": channel,
                "event": last_touch["event"],
                "ts": last_touch["ts"],
            }
            channel_attributions[channel] += 1.0
            total_conversions += 1

    return {
        "model": "last_touch",
        "total_conversions": total_conversions,
        "channel_attributions": dict(channel_attributions),
        "per_user": per_user,
    }


def replay_time_decay(events: list, half_life_days: float = 7.0,
                      window_hours: int = DEFAULT_WINDOW_HOURS) -> dict:
    """时间衰减归因回放

    按时间衰减权重分配贡献：weight = exp(-lambda * hours_ago)
    主归因渠道 = 权重最大的渠道（与生产 attribute_conversion_time_decay 一致）。

    half_life_days 参数说明：
        - 默认 7.0 天，对应 lambda = ln(2)/(7*24) ≈ 0.00413/小时
        - 若需与生产模型 TIME_DECAY_LAMBDA=0.1（半衰期约 7 小时）完全一致，
          传入 half_life_days=7/24≈0.292
        - 本参数以"天"为单位，便于业务理解与调参

    Returns:
        {
            "model": "time_decay",
            "total_conversions": int,
            "channel_attributions": {channel: attributed_count, ...},  # 主归因渠道计数
            "per_user": {uid: {primary_channel, weights, ts}, ...},
        }
    """
    # 由半衰期反推 lambda（单位：1/小时）
    lambda_per_hour = math.log(2) / (half_life_days * 24.0)

    grouped = _group_events_by_uid(events)
    channel_attributions = defaultdict(float)
    per_user = {}
    total_conversions = 0

    for uid, user_events in grouped.items():
        conversions = [e for e in user_events if e["event"] == "converted"]
        if not conversions:
            continue

        for conv in conversions:
            conversion_ts = conv["ts"]
            window_start = conversion_ts - window_hours * 3600
            touch_events = [
                e for e in user_events
                if e["event"] in ("interested", "carted")
                and window_start <= e["ts"] <= conversion_ts
            ]
            if not touch_events:
                channel = "unknown"
                per_user[uid] = {
                    "primary_channel": channel,
                    "weights": {channel: 1.0},
                    "ts": conversion_ts,
                }
                channel_attributions[channel] += 1.0
                total_conversions += 1
                continue

            # 计算各渠道权重（按 campaign_id/source 分组累加）
            channel_weights = defaultdict(float)
            for te in touch_events:
                hours_ago = (conversion_ts - te["ts"]) / 3600.0
                if hours_ago < 0:
                    hours_ago = 0
                w = math.exp(-lambda_per_hour * hours_ago)
                channel = _resolve_channel(te)
                channel_weights[channel] += w

            total_weight = sum(channel_weights.values())
            if total_weight <= 0:
                primary_channel = "unknown"
                ratios = {"unknown": 1.0}
            else:
                ratios = {c: w / total_weight for c, w in channel_weights.items()}
                # 主归因 = 权重最大的渠道（与生产逻辑一致）
                primary_channel = max(ratios, key=ratios.get)

            per_user[uid] = {
                "primary_channel": primary_channel,
                "weights": ratios,
                "ts": conversion_ts,
            }
            channel_attributions[primary_channel] += 1.0
            total_conversions += 1

    return {
        "model": "time_decay",
        "total_conversions": total_conversions,
        "channel_attributions": dict(channel_attributions),
        "per_user": per_user,
    }


def _js_divergence(p: dict, q: dict) -> float:
    """计算 JS 散度（Jensen-Shannon divergence）

    p, q: {channel: value} 字典，会自动归一化为概率分布
    返回 0-1 之间的浮点数（0=完全一致，1=完全不同）
    """
    all_keys = set(p.keys()) | set(q.keys())
    p_sum = sum(p.values()) or 1.0
    q_sum = sum(q.values()) or 1.0

    # 归一化为概率分布
    p_probs = [p.get(k, 0.0) / p_sum for k in all_keys]
    q_probs = [q.get(k, 0.0) / q_sum for k in all_keys]

    # M = (P + Q) / 2
    m_probs = [(pp + qq) / 2.0 for pp, qq in zip(p_probs, q_probs)]

    def _kl_div(a, b):
        """KL 散度（自然对数）"""
        s = 0.0
        for ai, bi in zip(a, b):
            if ai > 0 and bi > 0:
                s += ai * math.log(ai / bi)
        return s

    return 0.5 * _kl_div(p_probs, m_probs) + 0.5 * _kl_div(q_probs, m_probs)


def compare_models(last_touch_result: dict, time_decay_result: dict) -> dict:
    """对比两种归因模型

    对比指标：
        - 各渠道归因转化数差异（绝对值 + 百分比）
        - 渠道排名变化
        - 总转化分配偏移度（L1 距离 + JS 散度）
        - TOP 3 差异最大的渠道

    Returns:
        {
            "last_touch_total": int,
            "time_decay_total": int,
            "channels": {channel: {last_touch, time_decay, abs_diff, pct_diff}, ...},
            "ranking_change": {channel: {last_touch_rank, time_decay_rank, change}, ...},
            "l1_distance": float,
            "js_divergence": float,
            "top_diff_channels": [(channel, abs_diff), ...],
        }
    """
    lt_attr = last_touch_result["channel_attributions"]
    td_attr = time_decay_result["channel_attributions"]
    all_channels = set(lt_attr.keys()) | set(td_attr.keys())

    # 各渠道归因数对比
    channels = {}
    for ch in all_channels:
        lt_val = lt_attr.get(ch, 0.0)
        td_val = td_attr.get(ch, 0.0)
        abs_diff = td_val - lt_val
        if lt_val > 0:
            pct_diff = abs_diff / lt_val * 100.0
        elif td_val > 0:
            pct_diff = float("inf")
        else:
            pct_diff = 0.0
        channels[ch] = {
            "last_touch": lt_val,
            "time_decay": td_val,
            "abs_diff": abs_diff,
            "pct_diff": pct_diff,
        }

    # 渠道排名变化
    lt_ranked = sorted(lt_attr.items(), key=lambda x: x[1], reverse=True)
    td_ranked = sorted(td_attr.items(), key=lambda x: x[1], reverse=True)
    lt_rank = {ch: i + 1 for i, (ch, _) in enumerate(lt_ranked)}
    td_rank = {ch: i + 1 for i, (ch, _) in enumerate(td_ranked)}
    ranking_change = {}
    for ch in all_channels:
        lt_r = lt_rank.get(ch, len(lt_rank) + 1)
        td_r = td_rank.get(ch, len(td_rank) + 1)
        ranking_change[ch] = {
            "last_touch_rank": lt_r,
            "time_decay_rank": td_r,
            "change": lt_r - td_r,  # 正数=排名上升，负数=下降
        }

    # L1 距离（归一化后的绝对差之和）
    lt_total = sum(lt_attr.values()) or 1.0
    td_total = sum(td_attr.values()) or 1.0
    l1_distance = 0.0
    for ch in all_channels:
        lt_norm = lt_attr.get(ch, 0.0) / lt_total
        td_norm = td_attr.get(ch, 0.0) / td_total
        l1_distance += abs(lt_norm - td_norm)

    # JS 散度
    js_divergence = _js_divergence(lt_attr, td_attr)

    # TOP 3 差异最大的渠道（按绝对差排序）
    top_diff = sorted(
        [(ch, info["abs_diff"]) for ch, info in channels.items()],
        key=lambda x: abs(x[1]),
        reverse=True
    )[:3]

    return {
        "last_touch_total": last_touch_result["total_conversions"],
        "time_decay_total": time_decay_result["total_conversions"],
        "channels": channels,
        "ranking_change": ranking_change,
        "l1_distance": round(l1_distance, 6),
        "js_divergence": round(js_divergence, 6),
        "top_diff_channels": top_diff,
    }


def generate_report(comparison: dict) -> str:
    """生成 Markdown 格式对比报告"""
    lines = []
    lines.append("# 归因模型离线回放对比报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')} CST")
    lines.append("")

    # 概览
    lines.append("## 1. 概览")
    lines.append("")
    lines.append(f"- 末次触达归因总转化数：**{comparison['last_touch_total']}**")
    lines.append(f"- 时间衰减归因总转化数：**{comparison['time_decay_total']}**")
    lines.append(f"- L1 距离（归一化）：**{comparison['l1_distance']}**")
    lines.append(f"- JS 散度：**{comparison['js_divergence']}**")
    lines.append("")

    # 各渠道对比
    lines.append("## 2. 各渠道归因转化数对比")
    lines.append("")
    lines.append("| 渠道 | 末次触达 | 时间衰减 | 绝对差 | 百分比差 |")
    lines.append("|------|---------|---------|--------|---------|")
    # 按末次触达归因数降序
    sorted_channels = sorted(
        comparison["channels"].items(),
        key=lambda x: x[1]["last_touch"],
        reverse=True
    )
    for ch, info in sorted_channels:
        pct = info["pct_diff"]
        pct_str = f"{pct:+.2f}%" if pct != float("inf") else "+∞"
        lines.append(
            f"| {ch} | {info['last_touch']:.2f} | {info['time_decay']:.2f} | "
            f"{info['abs_diff']:+.2f} | {pct_str} |"
        )
    lines.append("")

    # 渠道排名变化
    lines.append("## 3. 渠道排名变化")
    lines.append("")
    lines.append("| 渠道 | 末次触达排名 | 时间衰减排名 | 变化 |")
    lines.append("|------|------------|------------|------|")
    sorted_ranking = sorted(
        comparison["ranking_change"].items(),
        key=lambda x: x[1]["last_touch_rank"]
    )
    for ch, info in sorted_ranking:
        change = info["change"]
        arrow = "↑" if change > 0 else ("↓" if change < 0 else "→")
        lines.append(
            f"| {ch} | #{info['last_touch_rank']} | #{info['time_decay_rank']} | "
            f"{arrow} {abs(change)} |"
        )
    lines.append("")

    # TOP 3 差异最大渠道
    lines.append("## 4. TOP 3 差异最大渠道")
    lines.append("")
    if not comparison["top_diff_channels"]:
        lines.append("无差异渠道。")
    else:
        lines.append("| 排名 | 渠道 | 绝对差 |")
        lines.append("|------|------|--------|")
        for i, (ch, diff) in enumerate(comparison["top_diff_channels"], 1):
            lines.append(f"| {i} | {ch} | {diff:+.2f} |")
    lines.append("")

    # 指标说明
    lines.append("## 5. 指标说明")
    lines.append("")
    lines.append("- **L1 距离**：两种模型归因分布（归一化后）的绝对差之和。0=完全一致，2=完全相反。")
    lines.append("- **JS 散度**：Jensen-Shannon 散度，衡量两个概率分布的相似度。0=完全一致，1=完全不同。")
    lines.append("- **绝对差**：时间衰减归因数 - 末次触达归因数。正数=时间衰减更倾向该渠道。")
    lines.append("- **百分比差**：绝对差 / 末次触达归因数 × 100%。")
    lines.append("- **排名变化**：正数=时间衰减模型中排名上升，负数=下降。")
    lines.append("")

    return "\n".join(lines)


def main():
    """CLI 入口，支持 --days / --half-life / --window / --db / --output 参数"""
    parser = argparse.ArgumentParser(
        description="归因模型离线回放验证：对比时间衰减归因 vs 末次触达归因",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m tests.attribution.test_offline_replay --days 30\n"
            "  python -m tests.attribution.test_offline_replay --days 7 --half-life 3.5\n"
            "  python -m tests.attribution.test_offline_replay --days 30 --window 24\n"
            "  python -m tests.attribution.test_offline_replay --db /path/to/mory.db --days 14\n"
        ),
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="回放过去 N 天的转化事件（默认 30）"
    )
    parser.add_argument(
        "--half-life", type=float, default=7.0,
        help="时间衰减半衰期（天，默认 7.0；与生产 lambda=0.1 一致时传 7/24≈0.292）"
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW_HOURS,
        help=f"归因回溯窗口（小时，默认 {DEFAULT_WINDOW_HOURS}）"
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="数据库路径（默认项目根目录 mory.db 或 SHARED_DB_PATH 环境变量）"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="报告输出文件路径（默认 logs/attribution_replay_report.md）"
    )

    args = parser.parse_args()

    # 加载历史事件
    print(f"[INFO] 加载过去 {args.days} 天的转化事件...")
    events = load_historical_events(args.days, db_path=args.db)

    if not events:
        print("[WARN] 无历史数据，请确认：")
        print("  1. 数据库文件存在（mory.db 或通过 --db 指定）")
        print("  2. conversion_events 表中有过去 N 天的转化事件")
        print("  3. 表中包含 event IN ('interested', 'carted', 'converted') 的记录")
        return 0

    # 统计加载的事件
    event_counts = defaultdict(int)
    for ev in events:
        event_counts[ev["event"]] += 1
    print(f"[INFO] 加载完成：共 {len(events)} 条事件")
    for ev_type, cnt in sorted(event_counts.items()):
        print(f"       - {ev_type}: {cnt} 条")

    # 回放末次触达归因
    print(f"\n[INFO] 回放末次触达归因（window={args.window}h）...")
    lt_result = replay_last_touch(events, window_hours=args.window)
    print(f"[INFO] 末次触达归因完成：{lt_result['total_conversions']} 次转化，"
          f"{len(lt_result['channel_attributions'])} 个渠道")

    # 回放时间衰减归因
    print(f"\n[INFO] 回放时间衰减归因（half_life={args.half_life}天, window={args.window}h）...")
    td_result = replay_time_decay(
        events, half_life_days=args.half_life, window_hours=args.window
    )
    print(f"[INFO] 时间衰减归因完成：{td_result['total_conversions']} 次转化，"
          f"{len(td_result['channel_attributions'])} 个渠道")

    # 对比
    print("\n[INFO] 对比两种归因模型...")
    comparison = compare_models(lt_result, td_result)

    # 生成报告
    report = generate_report(comparison)

    # 输出到 stdout
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    # 输出到文件
    output_path = args.output
    if output_path is None:
        logs_dir = os.path.join(_PROJECT_ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        output_path = os.path.join(logs_dir, "attribution_replay_report.md")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n[INFO] 报告已写入：{output_path}")
    except Exception as e:
        _log_error(f"报告写入失败: {e}")
        print(f"\n[ERROR] 报告写入失败: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
