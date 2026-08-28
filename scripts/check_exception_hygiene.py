# -*- coding: utf-8 -*-
"""异常卫生静态扫描（AI_DEBUG_HISTORY 6.9/6.15 防复发闸门，v5.41.0 新增）。

规则（对应病历本铁律"非致命不等于不需要观测"）：
  R1 裸 `except:`                          → ERROR（必须绑定异常）
  R2 `except Exception: pass` 宽捕获静默    → ERROR（补 logger.debug 或标 hygiene-allow）
  R3 窄类型捕获的 pass（KeyError/OSError 等）→ 放行（语义即"预期缺失"，计数报告）

豁免：行尾或上一行带 `# hygiene-allow: <理由>` 的宽捕获静默点。
用法：python scripts/check_exception_hygiene.py   （违例 >0 则退出码 3）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = ["core", "modules", "tasks", "dashboard", "scripts"]
SCAN_FILES = ["main.py", "conftest.py", "start_dashboard.py", "deploy_vps.py"]

_BARE_RE = re.compile(r"^except\s*:")
_EXC_LINE_RE = re.compile(r"^except\b[^:]*:\s*$")
_PASS_TAIL_RE = re.compile(r"^except\b[^:]*:\s*pass\s*(#.*)?$")
_ALLOW_RE = re.compile(r"#\s*hygiene-allow\b")


def _iter_targets():
    for d in SCAN_DIRS:
        yield from sorted((ROOT / d).rglob("*.py"))
    for f in SCAN_FILES:
        p = ROOT / f
        if p.exists():
            yield p


def scan() -> tuple[list[str], int]:
    """返回 (违例清单, 窄捕获放行数)。"""
    violations: list[str] = []
    narrow_allowed = 0
    for path in _iter_targets():
        if "__pycache__" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, raw in enumerate(lines):
            s = raw.strip()
            is_bare = bool(_BARE_RE.match(s))
            exc_header = None
            silent_pass = False
            if _PASS_TAIL_RE.match(s):
                # 单行形式：except XxxError: pass
                exc_header = s.split(":", 1)[0]
                silent_pass = True
            elif _EXC_LINE_RE.match(s) and i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if re.match(r"^pass\s*(#.*)?$", nxt):
                    exc_header = s
                    silent_pass = True

            if not silent_pass and not is_bare:
                continue

            context = raw + "\n" + (lines[i + 1] if i + 1 < len(lines) else "")
            allowed = bool(_ALLOW_RE.search(context))

            if is_bare:
                violations.append(f"{path.relative_to(ROOT)}:{i + 1} 裸 except:（必须绑定异常名）")
                continue

            header = exc_header or ""
            broad = bool(re.search(r"\b(?:BaseException|Exception)\b", header))
            if not broad:
                narrow_allowed += 1
                continue
            if allowed:
                continue
            rel = path.relative_to(ROOT)
            violations.append(
                f"{rel}:{i + 1} 宽捕获静默 pass：{header.strip()} → "
                f"补 as e + logger.debug 留痕，或行尾加 # hygiene-allow: <理由>"
            )
    return violations, narrow_allowed


def main() -> int:
    violations, narrow_allowed = scan()
    print(f"[check_exception_hygiene] 窄捕获放行（预期缺失语义）: {narrow_allowed} 处")
    if violations:
        print(f"[check_exception_hygiene] ❌ 违例 {len(violations)} 处：")
        for v in violations:
            print(f"  - {v}")
        return 3
    print("[check_exception_hygiene] ✅ 无裸 except、无未留痕的宽捕获静默 pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
