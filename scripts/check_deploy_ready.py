#!/usr/bin/env python3
"""部署前统一检查工作树、版本、配置、数据库委托和文档一致性。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_script(name: str) -> tuple[int, str]:
    """运行 scripts/ 下的校验脚本，返回退出码和末行摘要。"""
    script = ROOT / "scripts" / name
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"执行失败: {exc}"
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1][:120] if tail else "(无输出)"
    return proc.returncode, summary


def check_git_clean() -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return False, "git 不可用（非 git 仓库？）"
    entries = [line for line in proc.stdout.splitlines() if line.strip()]
    if entries:
        return False, f"工作树有 {len(entries)} 项未提交：{entries[0][:60]}…"
    return True, "工作树干净"


def check_version_alignment() -> tuple[bool, str]:
    version_py = ""
    match = re.search(
        r'^VERSION\s*=\s*["\']([^"\']+)["\']',
        (ROOT / "version.py").read_text(encoding="utf-8", errors="ignore"),
        re.M,
    )
    if match:
        version_py = match.group(1)
    version_md = ""
    match = re.search(
        r"当前版本：\*\*(v[^\*]+)\*\*",
        (ROOT / "VERSION.md").read_text(encoding="utf-8", errors="ignore"),
    )
    if match:
        version_md = match.group(1)
    if not version_py or not version_md:
        return False, "version.py / VERSION.md 未解析到版本号"
    if version_py != version_md:
        return False, f"版本不一致：version.py={version_py} ≠ VERSION.md={version_md}"
    return True, f"版本一致 {version_py}"


def main() -> int:
    checks = [
        ("Git 工作树干净", check_git_clean),
        ("版本一致（version.py == VERSION.md）", check_version_alignment),
        (
            "配置三处同步（check_config_sync）",
            lambda: (lambda rc, summary: (rc == 0, summary))(
                *_run_script("check_config_sync.py")
            ),
        ),
        (
            "DB 方法注册（verify_db_methods）",
            lambda: (lambda rc, summary: (rc == 0, summary))(
                *_run_script("verify_db_methods.py")
            ),
        ),
        (
            "文档一致性（doc_consistency）",
            lambda: (lambda rc, summary: (rc == 0, summary))(
                *_run_script("doc_consistency.py")
            ),
        ),
    ]
    results = []
    failed = 0
    for name, function in checks:
        ok, detail = function()
        if not ok:
            failed += 1
        results.append({"check": name, "ok": ok, "detail": detail})
        print(f"{'✅' if ok else '❌'} {name}: {detail}")

    if "--json" in sys.argv:
        print(
            json.dumps(
                {"ready": failed == 0, "checks": results},
                ensure_ascii=False,
                indent=2,
            )
        )
    if failed:
        print(f"\n❌ 部署就绪检查未通过（{failed}/{len(checks)} 项失败），禁止部署。")
        return 1
    print("\n✅ 部署就绪：工作树干净、版本一致、门禁脚本全过，可以部署。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
