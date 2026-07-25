#!/usr/bin/env python3
"""文档数字一致性自检脚本（ISSUE-001 / ISSUE-009）。

计算代码真实指标，与 project_snapshot.md 中 METRICS 块声明的值逐项比对。
不一致则退出码 1（供 CI / pre-commit 断言）；一致则退出码 0。

用法：
    python scripts/doc_consistency.py
    python scripts/doc_consistency.py --json   # 输出 JSON
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def count_py_non_init(rel_dir: str) -> int:
    d = ROOT / rel_dir
    if not d.exists():
        return 0
    return sum(
        1
        for p in d.rglob("*.py")
        if p.name != "__init__.py" and ".sync-conflict-" not in p.name
    )


def count_jobs() -> int:
    p = ROOT / "modules" / "auto_tasks.py"
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()
               if re.match(r"^\s*def _job_", line))


def count_db_tables() -> int:
    p = ROOT / "core" / "database.py"
    if not p.exists():
        return 0
    return p.read_text(encoding="utf-8", errors="ignore").count("CREATE TABLE IF NOT EXISTS")


def count_routes() -> int:
    api_dir = ROOT / "dashboard" / "api"
    if not api_dir.exists():
        return 0
    n = 0
    for p in api_dir.rglob("*.py"):
        n += len(re.findall(r"@\w+\.route\(", p.read_text(encoding="utf-8", errors="ignore")))
    return n


def count_dispatch_funcs() -> int:
    n = 0
    md = ROOT / "core" / "message_dispatcher.py"
    if md.exists():
        n += len(re.findall(r"def _dispatch_p\d", md.read_text(encoding="utf-8", errors="ignore")))
    for p in (ROOT / "core").rglob("*.py"):
        n += len(re.findall(r"def _dispatch_p10_ai", p.read_text(encoding="utf-8", errors="ignore")))
    return n


def count_model_router_mappings() -> int:
    p = ROOT / "core" / "model_router.py"
    if not p.exists():
        return 0
    return len(re.findall(
        r'^\s{4}"\w+":\s*"(llm_premium|llm_standard|llm_light)"',
        p.read_text(encoding="utf-8", errors="ignore"),
        re.M,
    ))


def parse_declared(snapshot_text: str) -> dict[str, int]:
    m = re.search(r"<!--\s*METRICS:BEGIN\s*-->(.*?)<!--\s*METRICS:END\s*-->", snapshot_text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        try:
            out[k.strip()] = int(v.strip())
        except ValueError:
            pass
    return out


def compute_actual() -> dict[str, int]:
    return {
        "modules_py": count_py_non_init("modules"),
        "core_py": count_py_non_init("core"),
        "job_count": count_jobs(),
        "db_tables": count_db_tables(),
        "dashboard_routes": count_routes(),
        "dispatch_funcs": count_dispatch_funcs(),
        "model_router_mappings": count_model_router_mappings(),
    }


KEY_LABELS = {
    "modules_py": "modules 业务 .py（不含 __init__）",
    "core_py": "core 业务 .py（不含 __init__）",
    "job_count": "auto_tasks.py 中 _job_ 函数",
    "db_tables": "database.py CREATE TABLE 数",
    "dashboard_routes": "dashboard/api 路由装饰器数",
    "dispatch_funcs": "消息分发函数（含导入的 p10）",
    "model_router_mappings": "model_router 任务类型映射数",
}


def main() -> int:
    actual = compute_actual()
    snap = ROOT / "project_snapshot.md"
    declared = parse_declared(snap.read_text(encoding="utf-8", errors="ignore")) if snap.exists() else {}

    if "--json" in sys.argv:
        print(json.dumps({"actual": actual, "declared": declared}, ensure_ascii=False, indent=2))

    print(f"{'指标':<32}{'实际':>8}{'声明':>8}  结果")
    print("-" * 60)
    mismatches = 0
    for key in KEY_LABELS:
        a = actual.get(key)
        d = declared.get(key)
        if d is None:
            mark = "未声明"
            mismatches += 1
        elif a == d:
            mark = "OK"
        else:
            mark = "不一致"
            mismatches += 1
        print(f"{KEY_LABELS[key]:<30}{a:>8}{str(d):>8}  {mark}")

    if mismatches:
        print(f"\n发现 {mismatches} 项文档数字与代码不一致，请更新 project_snapshot.md。")
        return 1
    print("\n全部文档数字与代码一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
