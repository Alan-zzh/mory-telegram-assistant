"""doc_consistency.py 扩展校验的单测（v5.38.25 新增：版本五源/行数/条目长度断言）。"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

spec = importlib.util.spec_from_file_location("doc_consistency", ROOT / "scripts" / "doc_consistency.py")
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)


def test_extract_version_matches_semver():
    v = dc.extract_version()
    assert re.match(r"^v\d+\.\d+\.\d+$", v), f"version.py VERSION 格式异常: {v}"


def test_changelog_top_version_matches():
    top = dc.changelog_top_version()
    assert re.match(r"^v\d+\.\d+\.\d+$", top), f"CHANGELOG 顶部条目未解析到版本号: {top}"
    assert top == dc.extract_version(), "CHANGELOG 顶部版本与 version.py 不一致"


def test_version_consistency_ok_on_current_docs():
    problems, rc = dc.check_version_consistency()
    assert rc == 0, f"版本五源不一致: {problems}"


def test_doc_line_limits_ok_on_current_docs():
    problems, rc = dc.check_doc_line_limits()
    assert rc == 0, f"文档行数超限: {problems}"


def test_changelog_entries_within_length_limit():
    problems, rc = dc.check_changelog_entry_length()
    assert rc == 0, f"CHANGELOG 存在超长条目: {problems}"


def test_snapshot_events_within_limit():
    problems, rc = dc.check_snapshot_events()
    assert rc == 0, f"snapshot 最近大事超限: {problems}"


def test_hygiene_runs_and_returns_structure():
    results, failed = dc.run_hygiene_checks()
    assert isinstance(results, list) and len(results) >= 5
    assert all(isinstance(r, tuple) and len(r) == 2 for r in results)
    assert failed == 0, "当前文档卫生断言应全部通过"
