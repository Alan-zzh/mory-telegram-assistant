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

# ────────────────────────── 文档卫生校验（v5.38.25 新增） ──────────────────────────
# 触发式更新 + 膨胀熔断的机械断言：版本五源一致 / 行数上限 / CHANGELOG 条目长度 / snapshot 大事条数。

DOC_LINE_LIMITS = {
    "AGENTS.md": 300,
    "project_snapshot.md": 150,
    "VERSION.md": 30,
    "CHANGELOG.md": 400,
    "AI_DEBUG_HISTORY.md": 300,
    "README.md": 250,
}

CHANGELOG_ENTRY_MAX_LEN = 100  # "一句话"列上限（字）
SNAPSHOT_EVENTS_MAX = 3        # "最近大事"条数上限


def extract_version() -> str:
    """从 version.py 读取 VERSION（如 v5.38.25）。"""
    p = ROOT / "version.py"
    if not p.exists():
        return ""
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', p.read_text(encoding="utf-8", errors="ignore"), re.M)
    return m.group(1) if m else ""


def doc_version(doc_name: str, pattern: str) -> str:
    p = ROOT / doc_name
    if not p.exists():
        return ""
    m = re.search(pattern, p.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1) if m else ""


def changelog_top_version() -> str:
    p = ROOT / "CHANGELOG.md"
    if not p.exists():
        return ""
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if re.match(r"^\|\s*20\d\d-", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 3:
                m = re.search(r"(v\d+\.\d+\.\d+)", cells[2])
                if m:
                    return m.group(1)
    return ""


def check_version_consistency() -> tuple[list[str], int]:
    """版本五源一致：version.py / VERSION.md / CHANGELOG 顶部 / snapshot 当前版本 / README 顶部。"""
    version_py = extract_version()
    version_md = doc_version("VERSION.md", r"当前版本：\*\*(v[^\*]+)\*\*")
    changelog = changelog_top_version()
    snapshot = doc_version("project_snapshot.md", r"## 当前版本\n(v[\d.]+)")
    readme = doc_version("README.md", r"当前版本 \*\*(v\S+?)\*\*")
    sources = [
        ("version.py", version_py),
        ("VERSION.md", version_md),
        ("CHANGELOG 顶部条目", changelog),
        ("project_snapshot.md", snapshot),
        ("README.md", readme),
    ]
    problems = []
    for name, value in sources:
        if not value:
            problems.append(f"{name}: 未解析到版本号")
        elif value != version_py:
            problems.append(f"{name}: {value} ≠ version.py {version_py}")
    return problems, (0 if not problems else 1)


def check_doc_line_limits() -> tuple[list[str], int]:
    problems = []
    for name, limit in DOC_LINE_LIMITS.items():
        p = ROOT / name
        if not p.exists():
            problems.append(f"{name}: 文件不存在")
            continue
        n = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        if n > limit:
            problems.append(f"{name}: {n} 行 > 上限 {limit}，需归档压缩")
    return problems, (0 if not problems else 1)


def check_changelog_entry_length() -> tuple[list[str], int]:
    p = ROOT / "CHANGELOG.md"
    if not p.exists():
        return [], 0
    problems = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not re.match(r"^\|\s*20\d\d-", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 3 and len(cells[2]) > CHANGELOG_ENTRY_MAX_LEN:
            problems.append(f"{cells[2][:24]}… 条目 {len(cells[2])} 字 > 上限 {CHANGELOG_ENTRY_MAX_LEN}")
    return problems, (0 if not problems else 1)


def check_snapshot_events() -> tuple[list[str], int]:
    p = ROOT / "project_snapshot.md"
    if not p.exists():
        return [], 0
    text = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"## 最近 \d+ 条大事(.*?)(?=\n## |\Z)", text, re.S)
    if not m:
        return [], 0
    events = [line for line in m.group(1).splitlines() if re.match(r"^\s*\d+\. ", line)]
    if len(events) > SNAPSHOT_EVENTS_MAX:
        return [f"snapshot 最近大事 {len(events)} 条 > 上限 {SNAPSHOT_EVENTS_MAX}，需压缩"], 1
    return [], 0


def check_readme_metrics() -> tuple[list[str], int]:
    """README 客观指标段落数字与 METRICS 块一致。"""
    p = ROOT / "README.md"
    snap = ROOT / "project_snapshot.md"
    if not p.exists() or not snap.exists():
        return [], 0
    declared = parse_declared(snap.read_text(encoding="utf-8", errors="ignore"))
    text = p.read_text(encoding="utf-8", errors="ignore")
    problems = []
    patterns = {
        "modules_py": r"modules 业务 .*? = (\d+)",
        "core_py": r"core 业务 .*? = (\d+)",
        "job_count": r"_job_ = (\d+)",
        "db_tables": r"DB 表 = (\d+)",
        "dashboard_routes": r"Dashboard 路由 = (\d+)",
        "dispatch_funcs": r"消息分发函数 = (\d+)",
        "model_router_mappings": r"model_router 映射 = (\d+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m and int(m.group(1)) != declared.get(key):
            problems.append(f"README {key}: {m.group(1)} ≠ METRICS {declared.get(key)}")
    return problems, (0 if not problems else 1)


def run_hygiene_checks() -> tuple[list[tuple[str, str]], int]:
    """运行全部文档卫生校验，返回 [(名称, 状态/问题)], 退出码。"""
    results = []
    failed = 0
    for name, fn in [
        ("版本五源一致", check_version_consistency),
        ("文档行数上限", check_doc_line_limits),
        ("CHANGELOG 条目长度", check_changelog_entry_length),
        ("snapshot 最近大事条数", check_snapshot_events),
        ("README 指标一致性", check_readme_metrics),
    ]:
        problems, rc = fn()
        if problems:
            failed += rc
            results.append((name, "❌ " + "；".join(problems)))
        else:
            results.append((name, "OK"))
    return results, failed


def main() -> int:
    actual = compute_actual()
    snap = ROOT / "project_snapshot.md"
    declared = parse_declared(snap.read_text(encoding="utf-8", errors="ignore")) if snap.exists() else {}

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

    print("\n== 文档卫生（触发式更新/膨胀熔断断言） ==")
    hygiene_results, hygiene_failed = run_hygiene_checks()
    for name, status in hygiene_results:
        print(f"  {name}: {status}")

    if "--json" in sys.argv:
        print(json.dumps({
            "actual": actual,
            "declared": declared,
            "hygiene": {name: status for name, status in hygiene_results},
        }, ensure_ascii=False, indent=2))

    total_failed = mismatches + hygiene_failed
    if total_failed:
        print(f"\n发现 {total_failed} 项不一致：文档数字或卫生断言未通过，请更新对应文档。")
        return 1
    print("\n全部文档数字与卫生断言一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
